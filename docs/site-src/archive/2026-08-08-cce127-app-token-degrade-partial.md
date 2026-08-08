---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/195
synthesized_into: []
---

# A failed GitHub App-token mint degrades the run to partial, it never kills the job

The nightly workflow's App-token step now runs under `continue-on-error`, and a mint failure is treated as a blocking-but-survivable signal that skips auto-merge instead of aborting the job outright.

## The incident

A GitHub App transfer during an org migration silently deleted the App's installations on two personal host repos. The next 15 consecutive nightlies failed on both repos (~30 runs total) with a 404 on the installation lookup — not a credentials problem, a lost installation. It stayed invisible for two weeks because neither repo had `SLACK_WEBHOOK_URL` wired up; the dogfood repo now carries it.

The root defect predated the incident. The token step's `token: ${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}` fallback in `templates/workflow-run.yml` only ever resolves for a *skipped* step — GitHub evaluates that expression for a skipped step, but a *failed* step aborts the job before the expression is ever reached. The fallback had been unreachable on the failure path since it was written; it only covered the bare-host case (no App configured at all), never the broken-host case (App configured but the mint fails).

## The mechanism

Two changes, and either one alone is inert:

1. **`continue-on-error: true` on the App-token step.** This is what makes the `||` fallback reachable at all. Without it, a failed mint aborts the job before the fallback expression is evaluated.
2. **Export `outcome`, never `conclusion`.** `continue-on-error` rewrites the step's `conclusion` to `success`, so a `conclusion`-keyed export would report a healthy mint for a run that had none — worse than doing nothing, because it would auto-merge on a clean-looking signal. The workflow exports `steps.app-token.outcome` as `DOCS_AGENT_APP_TOKEN_STATUS`, at step scope rather than job scope, because job-env cannot reference `steps.*`.

`orchestrator_runner.run` reads that env var and records a blocking `app_token_unavailable` reason for the literal value `"failure"` only. `"skipped"` — the documented bare-host path when `DOCS_AGENT_APP_CLIENT_ID` is unset, the largest host population — stays silent, as do `"success"` and an unset value. Flipping the run to `partial` reuses the existing `_maybe_auto_merge` interlock (`if partial: return skip("partial_run")`); no new gate code was needed. That's the point of the design: a PR built on the fallback `GITHUB_TOKEN` never fires host CI, so zero registered checks would otherwise read as "nothing failed" and the CCE-101 auto-merge gate would wave unvalidated docs through.

Placement of the env read in `run()` is load-bearing: it happens after the `current_run` dict literal is constructed and before the auto-merge decision. Reading it earlier would have the literal silently overwrite the reason `add_partial` had just recorded.

## Traps this touched

**404 is not 401.** A 404 on `/repos/{owner}/{repo}/installation` means the JWT authenticated fine and no installation covers the repo — the App was uninstalled, transferred, or its repo selection narrowed. The fix is re-installing the App, not rotating credentials. A 401 means the App or its private key is actually bad. The originating incident was an org transfer that deleted the installation, so the App's client ID and private key needed no change at all.

**CI does not lint `templates/`.** `.github/workflows/actionlint.yml` runs bare `actionlint -color`, which only searches `.github/workflows/` — template changes must be linted explicitly (`actionlint templates/workflow-run.yml`). That gap is plausibly how the template drifted from the dogfood workflow in the first place.

**Documenting a divergence is not the same as accepting the risk.** `tests/templates/test_workflow_run_parity.py` used to carry three `_TEMPLATE_ONLY_DIVERGENCES` entries recording that the dogfood workflow *lacked* a template safety property (the App-token `if:` guard, the `||` fallback, and `SLACK_WEBHOOK_URL`), justified by "dogfood requires the App" and "dogfood uses only the App token." Both justifications were true and both were irrelevant, because the step fails on *state* — an App installation that silently disappears — not on the intent the justification described. Writing the gap down converted an unexamined risk into an accepted one, and nothing re-examined it until the incident. This fix folds all three properties into the dogfood workflow itself and removes the divergence entries; `test_workflow_run_parity.py`'s test_05 and test_09 now enforce them in both files.

## Scope

The death-alarm case — the workflow failing before checkout, before any run/PR/notification is produced at all — is explicitly out of scope here and split to a follow-up (CCE-128), because this design's premise (an `if: failure()` step can read the checked-out tree) doesn't hold before `actions/checkout` runs.

## References

- `.github/workflows/docs-agent-nightly.yml`, `templates/workflow-run.yml` — the App-token step and its `continue-on-error` + `outcome` export
- `scripts/orchestrator_runner.py:run` — the `DOCS_AGENT_APP_TOKEN_STATUS` read and `app_token_unavailable` reason
- `tests/templates/test_workflow_run_parity.py` — parity enforcement between the template and the dogfood workflow
- Spec: `docs/superpowers/specs/2026-08-07-cce127-app-token-degrade-partial-design.md`
- Reference: CCE-127 (2026-08-07)
