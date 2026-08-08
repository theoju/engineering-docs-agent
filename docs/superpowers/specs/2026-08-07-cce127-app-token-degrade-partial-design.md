---
ticket: CCE-127
status: approved
date: 2026-08-07
incident: 15 consecutive nightly failures, 2026-07-24 → 2026-08-07 (theoju/engineering-docs-agent)
extends: CCE-80 (App-token opt-in designed for the skipped path only)
closes_divergence: CCE-71 / CCE-80 (template vs dogfood workflow)
---

# CCE-127 — App-token failure degrades to a partial run instead of killing the nightly

## Problem

The dogfood nightly in `theoju/engineering-docs-agent` failed 15 nights running, from
2026-07-24 through 2026-08-07, without anyone noticing. Every run died at step 2 of 12:

```
JOB: author -> failure
  1. Set up job                              -> success
  2. Generate GitHub App installation token  -> failure
  3-9. (checkout … run nightly authoring)    -> skipped
```

The error was identical every night:

```
Failed to create token for "theoju/engineering-docs-agent" (attempt 1):
  Not Found - .../get-a-repository-installation-for-the-authenticated-app
  url: 'https://api.github.com/repos/theoju/engineering-docs-agent/installation'
```

Two things went wrong, in different layers. Only the second is a code defect, but the first
is what exposed it — and the plugin promises to survive exactly this class of event.

## Root cause

### Layer 1 — operational (host config, no code defect)

The `engineering-docs-agent-bot` GitHub App (created 2026-05-29, client ID
`Iv23liZ5XLCf77iny1gT`) was transferred from the personal account `theoju` to the
`Design-It-Right` organization while the ADIS repo was being migrated there. A GitHub App
scoped to "Only on this account" cannot remain installed on personal repositories once it
is owned by an organization, so GitHub dropped the installation covering
`theoju/engineering-docs-agent`.

The App is alive and its private key is still valid — a dead App or bad key returns **401**
at JWT exchange. A **404** on `/repos/{owner}/{repo}/installation` means the JWT
authenticated successfully and the App simply has no installation covering that repo. That
status code is the diagnostic that separates "credentials broken" from "scope lost".

Timeline:

| When (UTC)       | Event                                                                                                     |
| ---------------- | --------------------------------------------------------------------------------------------------------- |
| 2026-07-19 17:41 | Org `Design-It-Right` created                                                                             |
| 2026-07-23 07:57 | Last successful nightly — PR #189 authored by `app/engineering-docs-agent-bot`                            |
| 2026-07-23 23:36 | ADIS repo receives a **new, separate** App `adis-docs-agent` (`Iv23lio9Ef5DWZE3TVJo`) + fresh private key |
| 2026-07-24 07:55 | First nightly failure — 404 on the installation lookup                                                    |
| 2026-08-07 08:19 | 15th consecutive failure                                                                                  |

### Layer 2 — the code defect (this ticket)

`templates/workflow-run.yml` guards the App-token step with
`if: vars.DOCS_AGENT_APP_CLIENT_ID != ''` and falls back via
`token: ${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}`.

That degradation only covers the **never configured** case. It cannot cover
**configured-but-broken**, because GitHub evaluates the `||` fallback only when a step is
_skipped_. A step that _fails_ aborts the job before the expression is reached. The
fallback has therefore been unreachable for this failure mode since it was written — it
reads as graceful degradation while providing none.

The blind spot is recorded in the originating spec. CCE-80 §9.3 states the reasoning
verbatim: _"GHA semantics: skipped-step outputs evaluate to empty string, so the `||`
resolves to the fallback."_ That analysis is correct and complete **for the skipped path**,
which is the only path CCE-80 set out to design. No one asked what happens when the step
runs and fails. CCE-127 extends CCE-80 to that second path rather than revising it.

This violates the generic-first mandate in `CLAUDE.md`: a capability that lacks a
convention must "skip or fall back cleanly — it never errors". It also contradicts the
contract stated in the workflow's own comments: _"a partial run opens the PR anyway with
`partial: true` in the body — the workflow itself stays green so the next nightly fire
isn't suppressed by a red status."_ Step 2 is the only step in the job that breaks that
rule.

`.github/workflows/docs-agent-nightly.yml` is worse than the template: it has neither the
`if:` guard nor any `||` fallback, and it does not pass `SLACK_WEBHOOK_URL` at all. This is
the CCE-71 / CCE-80 divergence resurfacing.

## What is explicitly NOT the problem

The ADIS repo is healthy. `Design-It-Right/advanced-data-import-system` ran
`docs-agent-nightly` to `success` on every scheduled fire from 2026-08-01 through
2026-08-07, authoring PRs as `app/adis-docs-agent`. The org migration succeeded. Only the
plugin's own dogfood host regressed, because it kept pointing at the App that moved.

The "No files were found with the provided path … docs-agent-debug" warning is pure
downstream noise: `Upload subagent forensics` runs under `if: always()`, so it fires even
though the job died before any subagent dispatched. It is a symptom, not a second bug, and
this ticket does not change it.

## Decision

When the App token cannot be minted **and the host intended to have one**, the nightly
degrades to `secrets.GITHUB_TOKEN`, completes the run, and records a blocking
`app_token_unavailable` reason that flips the run to `partial`.

Rejected: silent degradation. `scripts/orchestrator_runner.py:_maybe_auto_merge` documents
that "zero registered checks after the grace window means a no-App-token host (the in-run
validation is the gate there)" — so a PR built on `GITHUB_TOKEN`, whose host CI never
fires, would pass the check-poll and auto-merge unvalidated documentation. Forcing
`partial` is what prevents that.

Rejected: keeping the failure fatal. It costs a night of docs per incident and, as this
incident demonstrated, produces no signal anyone acts on.

## Design

### Signal path

The failure occurs in the workflow (step 2); the `partial` flag lives in the orchestrator
(step 9). The signal must cross that boundary:

```
app-token step  (continue-on-error: true)
  └─ steps.app-token.outcome ∈ {success, failure, skipped}
       └─ env: DOCS_AGENT_APP_TOKEN_STATUS
            └─ orchestrator_runner startup
                 ├─ "failure"        → _record_dispatch_reasons([...], ok=False) → partial = True
                 ├─ "skipped"        → silent  (documented bare-host path)
                 └─ "success"/unset  → silent
```

`continue-on-error: true` is load-bearing for a non-obvious reason: it makes
`steps.<id>.outcome` and `steps.<id>.conclusion` diverge. `conclusion` is rewritten to
`success` so the job proceeds; `outcome` retains the true `failure`. Reading `.outcome` is
what makes the signal observable at all — `.conclusion` would always report `success`.

### Three states, not two

| `outcome` | Meaning                                                         | Behavior                                                                                 |
| --------- | --------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `skipped` | `DOCS_AGENT_APP_CLIENT_ID` unset — host never configured an App | Silent. This is the supported bare-host path documented in `templates/workflow-run.yml`. |
| `failure` | App configured but the token could not be minted                | Blocking reason → `partial` → auto-merge disabled → reason appears in the digest.        |
| `success` | Normal                                                          | Silent.                                                                                  |

Only the _present-and-broken_ state degrades the run. This mirrors CCE-125's rule that an
**absent** `needs_spec` key is a genuine malfunction while a **present** `null` is a
downgradeable "unjudged" value: the distinction between "never supplied" and "supplied and
wrong" carries the semantics.

### `partial` is the entire safety mechanism

No new gate code is required. Flipping `partial` buys three behaviors that already exist:

1. `scripts/orchestrator_runner.py:_maybe_auto_merge` short-circuits at `if partial:
return skip("partial_run")` — auto-merge is disabled without touching the gate.
2. `scripts/orchestrator_runner.py:_format_partial_digest` renders `app_token_unavailable`
   into the Slack/email digest and the PR body.
3. The CCE-89 digest header reflects the true run state (CCE-121).

The reason string must be recorded through
`scripts/orchestrator_runner.py:_record_dispatch_reasons` with `ok=False`, matching the
blocking-pipeline convention. It is deliberately **not** an advisory reason: unlike
`gap-detector` and `fact-checker` (CCE-118 / CCE-125), a missing App token degrades the
integrity of the PR itself, not merely a note attached to it.

### Touch-points

| #   | File                                       | Change                                                                                                                                                                                                                                        |
| --- | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T1  | `templates/workflow-run.yml`               | Add `continue-on-error: true` to the App-token step; export `DOCS_AGENT_APP_TOKEN_STATUS: ${{ steps.app-token.outcome }}` into the authoring step's env.                                                                                      |
| T2  | `.github/workflows/docs-agent-nightly.yml` | Same two changes, **plus** the missing `if: vars.DOCS_AGENT_APP_CLIENT_ID != ''` guard, the `\|\| secrets.GITHUB_TOKEN` fallbacks on both `checkout` and `GH_TOKEN`, and the absent `SLACK_WEBHOOK_URL` job-env line. Closes CCE-71 / CCE-80. |
| T3  | `scripts/orchestrator_runner.py`           | Read `DOCS_AGENT_APP_TOKEN_STATUS` at run start; on `failure`, record a blocking `app_token_unavailable` reason.                                                                                                                              |

### Residual case this design does NOT cover

`run()` returns 2 at three points **before** `state["current_run"]` is created: no config,
invalid config, and invalid state. An App-token failure on a host whose config is also
broken therefore records nothing and stays a red job. The read cannot be hoisted above those
returns, because `add_partial` would then create a stub `current_run` that the dict literal
initializing the real one immediately overwrites — silently swallowing the reason. The
narrow valid window is _after_ `current_run` exists and _before_ the auto-merge decision.
This residual is accepted: a host with an unparseable config has a louder problem than a
missing App token.

### Split out — CCE-128 (death alarm)

An earlier draft of this spec included a T4: a stdlib `scripts/notify_run_death.py` invoked
from an `if: failure()` step, to alarm on deaths the orchestrator cannot report itself
(expired `CLAUDE_CODE_OAUTH_TOKEN`, orchestrator crash, runner OOM). Adversarial review of
the implementation recon found six unresolved design questions and one factual error in the
draft, so it is split to **CCE-128** rather than blocking this fix.

The factual error is worth recording, because it is the same class of mistake as the one
this ticket exists to fix. The draft asserted T4 should be "a step, not a job — the tree is
already checked out by that point." That is false for pre-checkout failures:
`scripts/notify_run_death.py` does not exist on the runner until the checkout step runs, and
the checkout step is _after_ the App-token step. An alarm designed to cover early deaths
could not execute during the earliest ones. Asserting a mechanism works without checking
when its preconditions hold is exactly how the unreachable `||` fallback survived two
months of review.

CCE-128 must resolve, before implementation:

1. **Failed-step discovery.** GitHub exposes no built-in "which step failed" to a later
   step. Options are per-step `steps.<id>.outcome` (most dogfood steps have no `id:`), an
   API call to the jobs endpoint, or dropping the field from the message contract.
2. **Pre-checkout availability.** Where the script lives when checkout has not run.
3. **Config loading.** `state_io.load_config_validated` raises `ConfigError` on a missing or
   malformed file — the exact conditions under which the alarm most needs to fire. A
   tolerant reader is likely required, which is a second config-loading path to justify.
4. **Bare-host nagging.** T4 ships in `templates/workflow-run.yml`, so every onboarded host
   inherits it. `scripts/preflight_host.py` writes `notifications` disabled by default, so
   every host would emit a `::warning::` on every failed run about a setting it may have
   deliberately declined. The generic-first mandate forbids that.
5. **Parity impact.** A new run-step changes `_step_signature` in
   `tests/templates/test_workflow_run_parity.py`, whose signature for run-steps is the first
   line of `run:`. The two files invoke Python by different paths, so the step lands as a
   dogfood-only signature and fails `test_01` unless allowlisted.
6. **The script's contract.** Flags, env vars read, exact message text, retry behavior, and
   the precise `::warning::` string are all unspecified.

Independently of CCE-128, this host has `notifications.slack.enabled: false` and
`.github/workflows/docs-agent-nightly.yml` passes no `SLACK_WEBHOOK_URL`. T2 adds the
job-env line; enabling the channel remains operator work, and no alarm of any design can
help until it is done.

## Rejected alternatives

**Token introspection.** Have the orchestrator inspect its own `GH_TOKEN` (via
`/rate_limit` headers or token prefix) to detect that it holds a `GITHUB_TOKEN` rather than
an App token. Rejected: it costs a network call, is coupled to undocumented token formats,
and — fatally — cannot distinguish "never configured" from "configured and broke". Those
two states require opposite handling, so any mechanism that collapses them is wrong by
construction.

**Config flag `auth.require_app_token: true`.** Lets the host declare intent explicitly.
Rejected as redundant: the presence of `vars.DOCS_AGENT_APP_CLIENT_ID` already _is_ the
declaration of intent, and the `skipped`/`failure` split reads it for free. Adding a second
source of truth invites the two to disagree.

**Retry with backoff.** `create-github-app-token` already retries internally (the log shows
"attempt 1"). A dropped installation is not transient — retrying 15 nights in a row proved
that empirically.

## Testing (TDD)

T3 is a pure environment read, so it unit-tests without any GitHub interaction:

1. `DOCS_AGENT_APP_TOKEN_STATUS=failure` → run is `partial`, `partial_reasons` contains
   `app_token_unavailable`.
2. `DOCS_AGENT_APP_TOKEN_STATUS=skipped` → run is **not** partial, no reason recorded.
   This is the bare-host regression lock; it is the test most likely to catch a careless
   future change.
3. Variable unset → identical to `skipped`.
4. `partial=True` from this reason → `_maybe_auto_merge` returns `skip("partial_run")`.
   Locks the interlock the whole design rests on.

All four use the existing fixture-driven dry-run path with `monkeypatch.setenv`; the
production Claude CLI dispatch stays monkeypatched, per the repo's testing convention.

T1/T2 extend `tests/templates/test_workflow_run_parity.py` — the parity assertion is the
correct home, since T2's purpose is eliminating divergence.
`.github/workflows/actionlint.yml` covers YAML validity.

Two further suites glob both workflow files and must stay green:
`tests/ci/test_workflow_auth_tier.py` (asserts no `app-id:` and no `secrets.JIRA_EMAIL`) and
`tests/ci/test_workflow_node_runtime.py` (asserts no Node-20 action majors). Neither needs
changing, but the verification step must run them — a plan that names only the parity file
leaves an implementer unaware of where a bad action major surfaces.

## Blast radius

- **Hosts with a working App:** no behavior change. `outcome` is `success`, the branch is
  silent, tokens resolve as before.
- **Bare hosts with no App configured:** no behavior change. `outcome` is `skipped`, which
  test 2 locks. This is the largest population and the one most at risk from a careless
  implementation, because the naive reading of "App token missing → partial" would newly
  flip every bare host to partial and disable auto-merge fleet-wide.
- **Hosts with a broken App:** behavior changes from _total outage_ to _partial run with a
  named reason and auto-merge disabled_. This is the intended change.
- **`_record_dispatch_reasons` is a shared helper.** Per `CLAUDE.md`, its callers were
  enumerated before this design: `scripts/orchestrator_runner.py` calls it at the
  source-collector, pr-summarizer, page-author, content-validator, gap-detector, and
  notifier sites. T3 adds a new callsite; it does not change the signature or the semantics
  of the existing six.

## Operational remediation (outside code scope)

Restoring `theoju/engineering-docs-agent` does not require any of the above and should be
done first. The repository is staying under the personal account, and ADIS runs on its own
separate App, so `engineering-docs-agent-bot` has no remaining reason to live in the org:

1. Confirm `engineering-docs-agent-bot` is installed nowhere in `Design-It-Right` that
   matters (ADIS uses `adis-docs-agent`).
2. Transfer the App back to `theoju` (App → Advanced → Transfer ownership).
3. Install it on `theoju/engineering-docs-agent`, scoped to that repository only.
4. Verify with `gh workflow run docs-agent-nightly.yml --repo theoju/engineering-docs-agent`.

`vars.DOCS_AGENT_APP_CLIENT_ID` and `secrets.DOCS_AGENT_APP_PRIVATE_KEY` need **no
change** — a transfer moves ownership, not credentials. Preserving them also preserves the
bot identity `app/engineering-docs-agent-bot`, which matters:
`scripts/orchestrator_runner.py:_maybe_auto_merge` matches PR authorship against
`_DOCS_AGENT_BOT_AUTHOR_NAMES` / `_DOCS_AGENT_BOT_AUTHOR_EMAILS`. Minting a fresh App
instead would change the slug and silently break both the CCE-101 auto-merge human-edit
guard and the CCE-89 D2 auto-close sweep.

## Validation

- Full `python3 -m pytest` green on the branch merged with `main`, per the integrated-suite
  rule in `CLAUDE.md`.
- `actionlint` green on `.github/workflows/docs-agent-nightly.yml`. Note that CI does **not**
  cover the template: `.github/workflows/actionlint.yml` runs bare `actionlint -color`, which
  searches `.github/workflows/` only, and no `.github/actionlint.yml` extends that path. The
  template must therefore be linted by explicit invocation
  (`actionlint templates/workflow-run.yml`) as a plan step. Claiming CI coverage it does not
  have would repeat the `test -f` versus real-consumer-tool failure mode named in `CLAUDE.md`.
  Extending actionlint's search path to `templates/` is worth a follow-up ticket — that gap is
  how the template drifted from the dogfood in the first place.
- A `workflow_dispatch` fire on `theoju/engineering-docs-agent` with the App installed
  produces a non-partial run (proves no regression on the healthy path).
- A `workflow_dispatch` fire with `DOCS_AGENT_APP_CLIENT_ID` temporarily pointed at a
  client ID with no installation produces a green workflow, an open PR, `partial: true`,
  `app_token_unavailable` in the digest, and `auto_merge_skipped: partial_run`.
