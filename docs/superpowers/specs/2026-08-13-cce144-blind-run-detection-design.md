# CCE-144 — Blind-run detection

**Status:** approved
**Date:** 2026-08-13
**Ticket:** CCE-144
**Distinct from CCE-128** (pre-checkout job death), which covers the opposite failure: the job dies before `actions/checkout`, so no repo tree exists for an `if: failure()` step to use. This spec covers a job in which _every step is green_ and the run is nonetheless useless.

## Problem

The docs-agent nightly cannot report failure.

`orchestrator_runner.run` returns `0` on every path. `main` returns whatever `run` returned, and the workflow's only signal is that exit code. A run in which every subagent was rejected by a rate limit is therefore a green check **by construction** — not by accident, and not by any recoverable condition.

### The incident

Runs `31472240064` (2026-08-11) and `31579090583` (2026-08-12) both report `conclusion: success`. Subagent forensics for the latter show `source-collector` rejected before it made a single tool call:

```json
"You've hit your weekly limit · resets 9am (UTC)"
{"type":"rate_limit_event","rate_limit_info":{"status":"rejected",
 "rateLimitType":"seven_day","overageStatus":"rejected",
 "overageDisabledReason":"org_level_disabled"}}
```

`returncode: 1`, `duration_ms: 344`, `total_calls: 0`. Both `source-collector` and `notifier` returned `None`. The watermark froze for three days. Nothing alarmed.

### Three independent layers of silence

1. **No non-zero exit exists.** Every `return` in `run` is `0`.
2. **The alarm shares the failure mode.** `notifier` is a Claude CLI subagent drawing on the same quota as the agents it reports on. A quota outage silences the work and its own alarm simultaneously — a correlated single point of failure that no scheduling change touches.
3. **The fallback diagnostic reads the wrong file.** The `Print partial-run reasons` workflow step greps `.engineering-docs-agent/state.json` for `.current_run.partial_reasons`. But `state_io.save_persistent_state` filters `_EPHEMERAL_KEYS = ("current_run",)` before writing; the reasons go to the sibling `current_run.json`, which the workflow never reads. Verified on disk: `state.json` contains exactly `last_successful_run` and `version`. The step prints nothing, always, and exits 0 either way — indistinguishable from a run with no reasons.

Layer 3 is a decomposition casualty. The step was added when `partial_reasons` lived in `state.json`; the later ephemeral split moved the key for good reasons (merge-as-promotion should commit only durable state) and the reader was never updated.

### The latent watermark hazard

`orchestrator_runner` coerces a dead source-collector into a valid empty result set:

```python
if sources is None:
    if not reasons:
        add_partial(state, "source_collector_invalid: returned None")
    sources = {"prs": [], "jira_issues": []}
```

"Prevented from judging" becomes "judged: nothing to do." Downstream cannot tell the difference.

The `last_successful_run` assignment is unconditional — its only enclosing block is the `try:` in `run`, not `if prs:` and not any success guard. Today this is not a live data-loss bug, but only because of **merge-as-promotion**: zero PRs means zero authored pages, no docs PR is opened, and the local state write is discarded when the runner is torn down. The guard is incidental. A blind run that authored even one page — a deterministic generator producing a diff, say — would open a PR carrying a watermark advanced past PRs nobody ever read. `last_successful_run` is a consume-once cursor; that loss is permanent.

## Design

### The distinction

`partial` currently conflates two conditions with opposite operational meanings. The blocking `add_partial` call sites split cleanly:

|          | **Blind**                                                                                                                             | **Degraded**                                                                  |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Meaning  | the pipeline was _prevented from judging_                                                                                             | the pipeline _judged, and rejected work_                                      |
| Examples | `source_collector_invalid: returned None`, `content_validator_invalid: returned None`, `page_author_invalid`, `app_token_unavailable` | `lint_block: …`, `unsafe_page_path`, `unknown_lens`, `lint_block_unsafe_path` |
| Inputs   | incomplete — the run cannot know what it missed                                                                                       | complete — the run saw everything and dropped some of it                      |
| Recovery | needs a human or a quota reset                                                                                                        | self-healing; the next run retries the same page                              |
| Signal   | red                                                                                                                                   | green                                                                         |

This is the same idea the repo already reached twice, one level down. CCE-118 split advisory from blocking. CCE-125 went further and named the third state — `gap_detector_unjudged` — for a verdict that came back "I could not judge" rather than "I judged no." The run-level predicate is that concept promoted from one agent to the whole pipeline.

**"Produced nothing" is explicitly rejected as the predicate.** A run with no new PRs since the watermark legitimately produces nothing and must stay green; a blind run can still author pages. Output volume does not separate the cases — provenance of the emptiness does.

### Fail-safe by default

`state_io.add_partial` gains a `degraded` keyword:

```python
def add_partial(
    state: dict,
    reason: str,
    *,
    info_only: bool = False,
    degraded: bool = False,
) -> None:
```

Semantics, in precedence order:

- `info_only=True` — unchanged. Advisory; touches neither `partial` nor `blind`. `degraded` is ignored when `info_only` is set.
- `degraded=True` — flips `partial`, does **not** flip `blind`. Today's behavior for content rejection.
- **neither** — flips `partial` **and** `blind`. This is the default for a blocking reason.

The default is deliberately the loud one. A blocking failure mode that nobody classified turns the run red rather than passing silently. Failing open in the safe-looking direction is precisely what produced this incident, and what produced CCE-127's `conclusion`-vs-`outcome` trap: a diagnostic that reports healthy because it looked in the wrong place is worse than no diagnostic, because it actively suppresses inquiry.

`state_io.add_partial` remains the single writer of `current_run.partial_reasons` and becomes the single writer of the two new fields.

The highest-traffic path needs no change and is correct by default. `_record_dispatch_reasons(state, reasons, *, ok)` already calls `add_partial(state, r, info_only=ok)`; when `ok` is false — the dispatch produced no usable output — the reason now lands as blind, which is exactly the intended semantics. The `ok` boolean has always been the blind discriminator; it was simply collapsed into `partial` by the time it reached the exit code.

### New state fields

On `current_run`:

- `blind` (boolean) — true when at least one blind reason was recorded. Absent by default; absent reads as false everywhere.
- `blind_reasons` (list of strings) — always a subset of `partial_reasons`. Redacted by the same `_redact_credentials` path, appended with the same idempotency rule.

`templates/state.schema.json` is **not** touched: these live on `current_run`, which `save_persistent_state` strips. They are written only to `current_run.json`.

### Exit code

`run` returns `1` when `current_run.blind` is true, `0` otherwise. `2` remains reserved for `ConfigError`. Every existing `return 0` path keeps returning `0` unless the run is blind.

The exit code is the channel because it is the only one requiring **zero provisioning**: GitHub's native failure email and a red run-history entry need no secret, no webhook, and no config. It is also the only channel that survives total quota exhaustion, since nothing in the path invokes the Claude CLI.

### Watermark interlock

The `last_successful_run` advance is skipped when the run is blind. The cursor stays where it was; the next run re-reads the same window. Re-processing a window is cheap and idempotent. Skipping one is not.

### Auto-merge interlock

No new code. Blind implies `partial`, and `_maybe_auto_merge` already returns `skip("partial_run")` on `partial`. Recorded here so a future reader does not add a redundant gate.

### Workflow repair

`Print partial-run reasons` is repointed at `.engineering-docs-agent/current_run.json` and reads `.current_run.partial_reasons[]?`, plus `.current_run.blind_reasons[]?` under a distinguishing label. Applied to **both** `.github/workflows/docs-agent-nightly.yml` and `templates/workflow-run.yml`.

CI does not lint `templates/` — `.github/workflows/actionlint.yml` runs bare `actionlint`, which searches `.github/workflows/` only. Template changes must be linted explicitly with `actionlint templates/workflow-run.yml`. That gap is how the template drifted from the dogfood during CCE-127.

## Out of scope

**The Slack `curl` alarm.** Originally scoped as the primary mechanism, dropped on evidence: `gh secret list` on the dogfood returns `CLAUDE_CODE_OAUTH_TOKEN`, `DOCS_AGENT_APP_PRIVATE_KEY`, and `JIRA_API_TOKEN` — no `SLACK_WEBHOOK_URL`. The host config sets `notifications.slack.enabled: false` and `notifications.email.enabled: false`. CLAUDE.md's claim that the dogfood "now carries" the webhook after CCE-127 is incorrect and should be amended. Provisioning a webhook is an operator action no code change can perform, so this spec ships nothing that depends on a secret. The design leaves the hook point: once `current_run.json` carries `blind`, a `curl` step is a self-contained follow-on.

**Moving the nightly cron.** Considered and rejected as the primary fix. A weekly limit resets once per week, so cron placement rescues at most one night in seven — 08-12 sat near the boundary, 08-11 did not. It is also not the cheap change it appears: hour `7` is hardcoded in `templates/workflow-run.yml`, the dogfood workflow, and `scripts/scaffold_workflow.py`, whose regex both anchors on the literal `7 7` and re-emits the hour in its substitution — only the _minute_ is hashed per host. Plus six test assertions, a published page stating the cron literally, and a re-scaffold of every provisioned host. And the 09:00 UTC boundary is a property of one Anthropic account's quota window, not of arbitrary host repos: encoding it in the fleet default would violate the generic-first mandate. Observed queue drift for the current cron is 48–159 minutes, so the start time is a two-hour-wide distribution that cannot be precisely targeted at a boundary anyway.

**Enabling notifications.** The dogfood sends no digest at all today, healthy or not. An operator decision, tracked separately.

## Generic-first

Nothing here is host-specific. No new config keys, no new secrets, no hardcoded paths or times. A bare host gets the same behavior as a rich one: the exit code and the state file. The classification of a reason as blind or degraded is a property of the pipeline, not of the host.

## Testing

TDD throughout; every test fails first.

**`state_io.add_partial`**

- blocking reason with no kwargs → `partial` true, `blind` true, reason in both lists
- `degraded=True` → `partial` true, `blind` absent or false, reason in `partial_reasons` only
- `info_only=True` → neither flag flips; `degraded=True` alongside `info_only=True` is ignored
- `blind_reasons` is always a subset of `partial_reasons`
- idempotency: the same reason recorded twice appends once to each list
- redaction applies to `blind_reasons` identically

**`run` exit code**

- blind run → `1`
- degraded-only run → `0`
- clean run → `0`
- `ConfigError` → `2` (unchanged)

**Watermark**

- blind run leaves `last_successful_run` untouched
- degraded run advances it
- clean run advances it

**Fixture dry-run integration**

- `source-collector` returns `None` → blind, exit `1`, watermark frozen
- `lint_block` only → degraded, exit `0`, watermark advances
- a run with zero new PRs and no failures → not blind, exit `0`, watermark advances

**Classification coverage**

A test that enumerates every blocking `add_partial` call site in `scripts/orchestrator_runner.py` and asserts each is explicitly classified. This is what keeps the fail-safe default honest as the file grows: without it, the audit performed in this change decays silently. The test must fail on an unclassified new call site, not merely warn.

**Workflow parity**

- the print step reads `current_run.json` in both the dogfood workflow and the template
- `actionlint templates/workflow-run.yml` passes
- the existing workflow-parity suite still passes, and its template-only divergence list is audited — CCE-127's meta-lesson is that documenting a divergence converts an unexamined gap into an accepted one and stops anyone re-examining it

## Risks

**Alarm fatigue.** If blind reasons fire more often than expected, a red nightly becomes background noise and the signal is lost within a week — the same way an unbroken wall of green lost it. Mitigation: the plan's first task is an explicit audit of every blocking call site to fix the `degraded=True` set; the classification is data, changeable without touching the mechanism. Measure over the first week of live runs and reclassify if needed.

**A reclassification is a behavior change, not a tweak.** Moving a reason from blind to degraded makes a previously-red condition green. Any such move should cite the run evidence that justified it.

## Success criteria

1. A run whose `source-collector` returns `None` exits non-zero and appears red in the run history.
2. A run whose only failure is a lint block stays green and behaves exactly as it does today.
3. `Print partial-run reasons` emits actual reasons on a partial run.
4. A blind run cannot advance `last_successful_run`.
5. An unclassified new blocking `add_partial` call site fails the classification-coverage test.
