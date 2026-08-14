# CCE-144 — Blind-run detection

**Status:** approved — **implemented and merged 2026-08-14.**
**Date:** 2026-08-13
**Ticket:** CCE-144
**Supersedes the CCE-150 archive.** PR #223 (merged 2026-08-14) stamped this document "NOT IMPLEMENTED — archived, branch deleted," on the premise that `feat/CCE-144-blind-run-detection` had been abandoned unpushed and its commits were unreachable. That premise was false: the branch was pushed at `5021f11` and landed under this ticket. Read every "the runner does X" statement below as **current behavior**, not as a proposal. CCE-150 is obsolete and its banner is removed here.
**Distinct from CCE-128** (pre-checkout job death), which covers the opposite failure: the job dies before `actions/checkout`, so no repo tree exists for an `if: failure()` step to use. This spec covers a job in which _every step is green_ and the run is nonetheless useless.

## Problem

The docs-agent nightly cannot report failure.

`orchestrator_runner.run` has no exit path for a run whose agents never answered. It returns `2` on a config error and `1` when the docs PR could not be opened; every other path returns `0`, including the `no_pr` path a fully rate-limited run takes. `main` returns whatever `run` returned, and the workflow's only signal is that exit code. A run in which every subagent was rejected by a rate limit is therefore a green check **by construction** — not by accident, and not by any recoverable condition.

### The incident

Runs `31472240064` (2026-08-11) and `31579090583` (2026-08-12) both report `conclusion: success`. Subagent forensics for the latter show `source-collector` rejected before it made a single tool call:

```json
"You've hit your weekly limit · resets 9am (UTC)"
{"type":"rate_limit_event","rate_limit_info":{"status":"rejected",
 "rateLimitType":"seven_day","overageStatus":"rejected",
 "overageDisabledReason":"org_level_disabled"}}
```

`returncode: 1`, `duration_ms: 344`, `total_calls: 0`. Both `source-collector` and `notifier` returned `None`. Nothing alarmed.

The 08-11 run's PR (#214) was closed unmerged by the D2 auto-close sweep, so its watermark write was discarded. The 08-12 run's PR (#215) merged — and carried its watermark advance with it. See "The watermark hazard already fired" below.

### Three independent layers of silence

1. **No exit path distinguishes a dead run.** `run` has seven returns: `2` on a config error (three sites), `1` when the docs PR could not be opened, and `0` on the remaining three. Exit `1` therefore already means "this run failed" — but only for that one narrow cause. A run whose agents never answered takes the `no_pr` path and returns `0`.
2. **The alarm shares the failure mode.** `notifier` is a Claude CLI subagent drawing on the same quota as the agents it reports on. A quota outage silences the work and its own alarm simultaneously — a correlated single point of failure that no scheduling change touches.
3. **The fallback diagnostic reads the wrong file.** The `Print partial-run reasons` workflow step greps `.engineering-docs-agent/state.json` for `.current_run.partial_reasons`. But `state_io.save_persistent_state` filters `_EPHEMERAL_KEYS = ("current_run",)` before writing; the reasons go to the sibling `current_run.json`, which the workflow never reads. Verified on disk: `state.json` contains exactly `last_successful_run` and `version`. The step prints nothing, always, and exits 0 either way — indistinguishable from a run with no reasons.

Layer 3 is a decomposition casualty. The step was added when `partial_reasons` lived in `state.json`; the later ephemeral split moved the key for good reasons (merge-as-promotion should commit only durable state) and the reader was never updated.

### The watermark hazard already fired

`orchestrator_runner` coerces a dead source-collector into a valid empty result set:

```python
if sources is None:
    if not reasons:
        add_partial(state, "source_collector_invalid: returned None")
    sources = {"prs": [], "jira_issues": []}
```

"Prevented from judging" becomes "judged: nothing to do." Downstream cannot tell the difference.

The `last_successful_run` assignment is unconditional — its only enclosing block is the `try:` in `run`, not `if prs:` and not any success guard. This is not a latent hazard. It has already caused permanent loss, on this repo, in the incident above.

Run `31579090583` produced PR #215, merged as `3140b9c`, which advanced `last_successful_run.head_sha` from `0c88411` to `08b27e2`. That window contains three feature PRs — #211 (CCE-138), #212 (CCE-139), #213 (CCE-140) — and `grep -rl 'CCE-138\|CCE-139\|CCE-140' docs/site-src/` returns nothing. The cursor now sits at `956144f`, far past `08b27e2`, so those three PRs are behind it for good. `last_successful_run` is a consume-once cursor: no future run will ever read that window again.

An earlier draft of this spec argued the hazard was latent, held off by **merge-as-promotion** — zero PRs means zero authored pages, no docs PR, and the local state write is discarded. Every step of that reasoning is wrong, for one reason it missed: `.engineering-docs-agent/state.json` is a **tracked** file on every host, and `_stage_docs_run_changes` runs `git add -A .` with no "nothing staged → skip PR" guard. `completed_at` is a fresh timestamp on every run, so state.json always diffs and a PR is always opened. Merge-as-promotion promotes the advance; it does not gate it.

PR #215 presented as a routine archive-index refresh — its only other files were deterministic-generator output (`.doc-source-map.json`, `archive/index.md`, `archive/plans.md`) — with the watermark advance buried in the diff. There was no signal that it carried three PRs' worth of skipped work.

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

### The criterion

"Prevented from judging" and "self-healing" usually agree. Where they diverge, the operational question decides:

> **Blind** — the run _consumed_ input it could not process.
> **Degraded** — the run _held back_ what it could not process.

The complement writer in `scripts/orchestrator_runner.py` is what determines which. Any batch that did not land folds its PR into `deferred_pages_by_pr`, holding that PR out of the advance cursor's prefix — but only on the time-truncated path; every advance-affecting read of `deferred_pages_by_pr` sits inside `if time_truncated:`. On a non-truncated run the `else` branch advances straight to window HEAD without reading it, and the sole protection for a degraded failure there is CCE-140's merge gate (`if partial and not advance_cursor_backed`, which fires because that branch also sets `advance_cursor_backed = False`) plus merge-as-promotion: the on-disk advance is real, but it reaches `main` only if an operator merges the PR by hand. It is written as a complement rather than an enumeration of failure sites on purpose, so a failure path added later is covered without anyone remembering to.

That is why `page_author_invalid` is degraded and `content_validator_invalid` is blind, though both are agent failures one pipeline step apart. On the time-truncated path a page that fails authoring never lands, so its PR is held back and re-authored next run; on a non-truncated run the advance goes to HEAD regardless, and the merge gate above is what stands between that failure and `main`. A page that fails validation is already in `landed_batches` either way — the run counts it as delivered and the cursor walks past it.

### Classification

Audited 2026-08-13 by AST enumeration of every `add_partial` call. Twenty-five direct blocking sites in `scripts/orchestrator_runner.py`, plus the seven dispatch paths through `_record_dispatch_reasons`. Ten `info_only=True` sites are advisory and unaffected.

**Blind** — no `degraded` kwarg, taking the fail-safe default:

| Reason                                                     | Loss mechanism                                                                        |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `source_collector_invalid` / `_error` / `_partial`         | PRs never seen; the cursor crosses them regardless                                    |
| `pr_summarizer_invalid` / `_error`                         | the PR yields no doc targets, never enters `deferred_pages_by_pr`, so is not held back |
| `content_validator_invalid`                                | pages stay in `landed_batches` — counted as delivered, never validated                |
| `notifier_invalid`                                         | no content loss; no alarm either                                                      |
| `app_token_unavailable`                                    | CCE-127: a PR on the fallback token fires no host CI, so zero checks reads as green   |

**Degraded** — `degraded=True`:

| Reason                                                    | Why it is safe                                                             |
| --------------------------------------------------------- | -------------------------------------------------------------------------- |
| `time_budget_exceeded` (4 sites)                          | CCE-109 truncation; deferred PRs are held back and retried                 |
| window-clip reasons                                       | the collector returned PRs outside the requested window; rejecting loses nothing |
| `unknown_lens`                                            | judged: the target names no configured lens                                |
| `unsafe_page_path`, `lint_block_unsafe_path`              | judged: a path guard doing its job                                         |
| `page_author_invalid`                                     | the batch does not land, so its PR is held back                            |
| `lint_block`                                              | the canonical judged-and-rejected case                                     |
| `gap_detector_invalid`                                    | advisory output only; excluded from the CCE-101 merge gate                 |
| cursor-resolution failures (4 sites)                      | these _prevent_ an advance; nothing is consumed                            |
| `deferral_skip`                                           | CCE-140's bounded forgiveness, already recorded append-only in `skipped_prs` |

The four `time_budget_exceeded` sites are the highest-stakes rows in this table. Classifying them blind would turn every truncated run red **and**, through the watermark interlock, freeze its advance — deleting the cursor-backed advance CCE-140 exists to produce, and reinstating the CCE-109 doom loop as a permanent state. They are degraded, and the auto-merge tests assert that a degraded cursor-backed run still merges.

`scripts/verify_runner.py` carries three further blocking sites — publish-verifier dispatch (blind), the CCE-63 CircleCI degrade (degraded), and notifier (degraded). They are classified so the coverage test is exhaustive, but `verify_runner` is a separate entry point and **this change does not alter its exit code.** Only `orchestrator_runner.run` returns `1` on blind.

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

`_record_dispatch_reasons(state, reasons, *, ok)` is the single path every agent dispatch failure takes. All seven dispatch sites route through it, and it calls `add_partial(state, r, info_only=ok)`. When `ok` is false the reason lands as blind by default. The `ok` boolean has always been the blind discriminator; it was simply collapsed into `partial` by the time it reached the exit code.

That default is right for five of the seven and wrong for two. `page-author` and `gap-detector` dispatch failures are **degraded** — see the classification below — so the helper gains a matching passthrough:

```python
def _record_dispatch_reasons(
    state: dict, reasons: list[str], *, ok: bool, degraded: bool = False
) -> None:
    for r in reasons:
        add_partial(state, r, info_only=ok, degraded=degraded)
```

and those two callsites pass `degraded=True`. This is a shared-helper signature change; per CLAUDE.md its callers are enumerated in the classification table and updated in the same change.

Each agent has **two** paths to a reason: the helper, carrying whatever the dispatch reported, and a direct `add_partial` fallback for when the dispatch returned nothing to report (`source_collector_invalid: returned None` and its siblings). Both must carry the same classification, or an agent's failure changes colour depending on whether it managed to explain itself.

### New state fields

On `current_run`:

- `blind` (boolean) — true when at least one blind reason was recorded. Absent by default; absent reads as false everywhere.
- `blind_reasons` (list of strings) — always a subset of `partial_reasons`. Redacted by the same `_redact_credentials` path, appended with the same idempotency rule.

`templates/state.schema.json` is **not** touched: these live on `current_run`, which `save_persistent_state` strips. They are written only to `current_run.json`.

### Exit code

`run` returns `1` when `current_run.blind` is true, `0` otherwise. Every existing `return 0` path keeps returning `0` unless the run is blind.

Exit `1` is not a new code. `run` already returns `1` when the docs PR could not be opened, which is the same class of signal — "this run failed, read the reasons." Blind joins that class rather than competing with it, and the operator action is identical for both, so the shared code carries no ambiguity worth a third value. `2` stays with the config-error paths.

The exit code is the channel because it is the only one requiring **zero provisioning**: GitHub's native failure email and a red run-history entry need no secret, no webhook, and no config. It is also the only channel that survives total quota exhaustion, since nothing in the path invokes the Claude CLI.

### Watermark interlock

The `last_successful_run` advance is skipped when the run is blind. The cursor stays where it was; the next run re-reads the same window. Re-processing a window is cheap and idempotent. Skipping one is not.

The interlock reads `blind` **at the moment of the advance**. Every blind reason except one is recorded upstream of that point, so this is normally the whole story. The exception is `notifier_invalid`, recorded near the end of `run`: it sets the exit code but cannot retroactively rewind a cursor already written. That is the correct behavior, not a gap — a failed digest means the operator was not told, while the authoring work itself completed and its watermark is honest. The alarm is what needs to fire, not the rollback.

### Auto-merge interlock

**This needs new code.** An earlier draft claimed it did not, on the premise that blind implies `partial` and `partial` blocks the merge. That premise held until CCE-140 (`08b27e2`, merged 2026-08-12) narrowed the gate to:

```python
if partial and not advance_cursor_backed:
    return skip("partial_run")
```

CCE-140's reasoning is sound for a _degraded_ run: a cursor-backed advance moves the baseline only past PRs whose pages all landed, so merging it promotes nothing unread. It does not transfer to a _blind_ run. The cursor proves the baseline is honest about what the run **saw**; a blind run did not see.

The gap is reachable, not theoretical. A run that truncates on the CCE-109 time budget sets `advance_cursor_backed = True`. If its `content-validator` dispatch then returns `None`, the run is blind, `partial`, and cursor-backed at once. `_MERGE_VETO_REASON_PREFIXES` is `("app_token_unavailable",)` — a hand-maintained allowlist that does not match `content_validator_invalid` — so no veto fires, `partial and not True` is false, and the merge proceeds. `merge_deadline` is also disabled on the cursor-backed path, removing the time-budget skip that might otherwise have caught it.

`_maybe_auto_merge` therefore gains a `blind: bool = False` keyword and skips unconditionally:

```python
if blind:
    return skip("blind_run")
```

placed **before** the CCE-140 `partial and not advance_cursor_backed` test, next to the existing veto check. `_MERGE_VETO_REASON_PREFIXES` is left alone: once `app_token_unavailable` classifies as blind that entry is redundant, but removing it is a separate behavior change carrying its own risk, and the redundancy costs nothing.

The veto list is the load-bearing lesson here. CCE-140 recognized that narrowing the `partial` gate reopened a hole for one blind reason, and patched it with a string-prefix allowlist — scar tissue from this exact mistake, made once already. An allowlist must be extended by hand for every new blind reason, which is the same classification decay the fail-safe default exists to prevent. Gating on the computed `blind` flag closes the class instead of one member of it.

CLAUDE.md's CCE-127 bullet still states the gate as `if partial: return skip("partial_run")`. That is where this spec inherited the error, and it is corrected in the same change.

### Workflow repair

`Print partial-run reasons` is repointed at `.engineering-docs-agent/current_run.json` and reads `.current_run.partial_reasons[]?`, plus `.current_run.blind_reasons[]?` under a distinguishing label. Applied to **both** `.github/workflows/docs-agent-nightly.yml` and `templates/workflow-run.yml`.

CI does not lint `templates/` — `.github/workflows/actionlint.yml` runs bare `actionlint`, which searches `.github/workflows/` only. Template changes must be linted explicitly with `actionlint templates/workflow-run.yml`. That gap is how the template drifted from the dogfood during CCE-127.

## Out of scope

**The Slack `curl` alarm.** Originally scoped as the primary mechanism, dropped on evidence: `gh secret list` on the dogfood returns `CLAUDE_CODE_OAUTH_TOKEN`, `DOCS_AGENT_APP_PRIVATE_KEY`, and `JIRA_API_TOKEN` — no `SLACK_WEBHOOK_URL`. The host config sets `notifications.slack.enabled: false` and `notifications.email.enabled: false`. CLAUDE.md's claim that the dogfood "now carries" the webhook after CCE-127 is incorrect and should be amended. Provisioning a webhook is an operator action no code change can perform, so this spec ships nothing that depends on a secret. The design leaves the hook point: once `current_run.json` carries `blind`, a `curl` step is a self-contained follow-on.

**Moving the nightly cron.** Considered and rejected as the primary fix. A weekly limit resets once per week, so cron placement rescues at most one night in seven — 08-12 sat near the boundary, 08-11 did not. It is also not the cheap change it appears: hour `7` is hardcoded in `templates/workflow-run.yml`, the dogfood workflow, and `scripts/scaffold_workflow.py`, whose regex both anchors on the literal `7 7` and re-emits the hour in its substitution — only the _minute_ is hashed per host. Plus six test assertions, a published page stating the cron literally, and a re-scaffold of every provisioned host. And the 09:00 UTC boundary is a property of one Anthropic account's quota window, not of arbitrary host repos: encoding it in the fleet default would violate the generic-first mandate. Observed queue drift for the current cron is 48–159 minutes, so the start time is a two-hour-wide distribution that cannot be precisely targeted at a boundary anyway.

**Enabling notifications.** The dogfood sends no digest at all today, healthy or not. An operator decision, tracked separately.

**Recovering the three lost PRs.** CCE-138, CCE-139, and CCE-140 sit behind the cursor and no future run will read them. This change prevents the next occurrence; it cannot replay the last one. Rewinding `last_successful_run.head_sha` to `0c88411` would put that window back in scope, at the cost of re-processing every PR merged since — a week's worth, in one docs PR. That is an operator decision about live host state, and it belongs in its own ticket. It is named here rather than omitted, because a fix that leaves the damage in place and says nothing reads as a fix that repaired it.

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

**Auto-merge interlock**

- blind **and** `advance_cursor_backed=True` → skipped. This is the case current code merges; it is the regression test for the whole section.
- blind and `advance_cursor_backed=False` → skipped, and the recorded reason is `auto_merge_skipped: blind_run`, not `partial_run`. Asserting the reason string is the point: without it the CCE-140 gate silently covers for a missing blind gate and the test passes against code that does not have one.
- degraded and `advance_cursor_backed=True` → still merges, exactly as CCE-140 intends. This is the alarm-fatigue guard: it fails if the blind classification over-reaches into the path CCE-140 exists to serve.

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
6. A blind run does not auto-merge its PR, including when its advance is cursor-backed, and records `auto_merge_skipped: blind_run`.
