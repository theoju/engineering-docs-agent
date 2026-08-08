---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/195
synthesized_into: []
doc_kind: decision
---

# CCE-127: A Failed App-Token Mint Degrades the Nightly to `partial`, It No Longer Kills the Job

## Problem

The dogfood nightly in `theoju/engineering-docs-agent` failed 15 nights running, from
2026-07-24 through 2026-08-07 (~30 runs, counting the same-shaped failure on
`theoju/claude-code-self-assessment`), without anyone noticing. Every run died at the
"Generate GitHub App installation token" step with the same error:

```
Failed to create token for "theoju/engineering-docs-agent" (attempt 1):
  Not Found - .../get-a-repository-installation-for-the-authenticated-app
  url: 'https://api.github.com/repos/theoju/engineering-docs-agent/installation'
```

A **404** on `/repos/{owner}/{repo}/installation` means the JWT authenticated fine and no
installation covers the repo — App uninstalled, transferred, or repo-selection narrowed. A
**401** would mean the App or key itself is bad. This incident's App
(`engineering-docs-agent-bot`) had been transferred from the personal account `theoju` to
the `Design-It-Right` org while the ADIS repo was being migrated there; a personal-account
App loses its installation on personal repos once the owning account changes. Credentials
needed no change — the App just needed to be re-installed.

That operational event exposed a code defect. `templates/workflow-run.yml` guarded the
App-token step with `if: vars.DOCS_AGENT_APP_CLIENT_ID != ''` and fell back via
`token: ${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}`. That `||` fallback
only resolves for a **skipped** step — GitHub aborts the job the moment a step **fails**,
before the fallback expression is ever reached. The degradation path covered "never
configured an App" but not "configured an App that broke". It had been unreachable for
this failure mode since CCE-80 wrote it: CCE-80 §9.3 states the reasoning verbatim for the
skipped-step case only — nobody had asked what happens when the step runs and fails.

`.github/workflows/docs-agent-nightly.yml` (the dogfood copy) was worse than the template:
it carried neither the `if:` guard nor either `||` fallback, and it didn't pass
`SLACK_WEBHOOK_URL` at all — so even the notifier had nothing to alert through.

## Decision

When the App token cannot be minted **and the host intended to have one**, the nightly now
degrades to `secrets.GITHUB_TOKEN`, completes the run, and records a blocking
`app_token_unavailable` reason that flips the run to `partial`.

Silent degradation was rejected: `_maybe_auto_merge` treats zero registered checks after
the grace window as "a no-App-token host, nothing to gate on" — so a PR built entirely on
`GITHUB_TOKEN`, whose host CI never fires because `GITHUB_TOKEN`-authored pushes suppress
`push`/`pull_request` events, would sail through the check-poll and auto-merge unvalidated
documentation. Keeping the failure fatal was also rejected: it costs a night of docs per
incident and, as this incident showed, produces a red job nobody looks at.

## Mechanism

Two changes carry the signal across the workflow/orchestrator boundary, and either one
alone is inert:

1. **`templates/workflow-run.yml`** adds `continue-on-error: true` to the `app-token` step
   and exports `DOCS_AGENT_APP_TOKEN_STATUS: ${{ steps.app-token.outcome }}` into the
   authoring step's env (step-scoped, because job-env cannot reference `steps.*`).
   `continue-on-error: true` is what makes `steps.app-token.outcome` diverge from
   `steps.app-token.conclusion` — `continue-on-error` rewrites `conclusion` to `success` so
   the job proceeds, but `outcome` retains the true `failure`. Reading `.outcome` (never
   `.conclusion`) is what makes the signal observable at all.
2. **`scripts/orchestrator_runner.py`** (`run()`) reads `DOCS_AGENT_APP_TOKEN_STATUS` at
   startup:

   ```python
   if os.environ.get("DOCS_AGENT_APP_TOKEN_STATUS", "") == "failure":
       _record_dispatch_reasons(
           state,
           ["app_token_unavailable: GitHub App installation token could not "
            "be minted; run degraded to GITHUB_TOKEN, so host CI will not "
            "fire on this PR. Verify the App is installed on this repo."],
           ok=False,
       )
   ```

   Only the literal string `"failure"` degrades the run. `"skipped"` is the documented
   bare-host path (no `DOCS_AGENT_APP_CLIENT_ID` configured) and stays silent, as do
   `"success"` and an unset variable — collapsing "never configured" and "configured and
   broken" into one signal would be wrong, because they need opposite handling.

   Placement is load-bearing: the read happens after `state["current_run"]` is constructed
   and before the auto-merge decision. Any earlier and the dict literal that initializes
   `current_run` would overwrite the stub `add_partial` creates, silently swallowing the
   reason.

No new gate code was needed. Flipping `partial` reuses the existing interlock at
`_maybe_auto_merge` (`if partial: return skip("partial_run")`) — the same mechanism that
already renders `partial_reasons` into the Slack/email digest and the PR body.

## Four traps this touched

- **`continue-on-error` is what makes the `||` fallback reachable at all.** Two mechanisms
  are required and either alone is inert: without `continue-on-error: true`, a failed
  App-token step aborts the job before `steps.app-token.outputs.token ||
  secrets.GITHUB_TOKEN` is ever evaluated.
- **Export `outcome`, never `conclusion`.** `continue-on-error` rewrites `conclusion` to
  `success`, so a `conclusion`-keyed export (or test) would report a healthy mint for a run
  that had none — worse than no fix, because it would auto-merge with a clean-looking
  signal.
- **404 ≠ 401 on a failed token mint.** A 404 on the installation lookup means the JWT is
  fine and the scope was lost (App uninstalled, transferred, or repo-selection narrowed) →
  re-install. A 401 means the App or key itself is bad → rotate. Conflating the two sends
  the operator down the wrong remediation path.
- **CI does not lint `templates/`.** `.github/workflows/actionlint.yml` runs bare
  `actionlint -color`, which searches `.github/workflows/` only — template changes need
  explicit linting (`actionlint templates/workflow-run.yml`). That gap is plausibly how the
  template drifted from the dogfood in the first place.

## Meta-lesson: documenting a divergence is not the same as accepting the risk

`tests/templates/test_workflow_run_parity.py` carried three `_TEMPLATE_ONLY_DIVERGENCES`
entries recording that the dogfood *lacked* the template's App-token safety properties —
justified by "dogfood requires the App" and "dogfood uses only the App token". Both
justifications were true and both were irrelevant, because the step fails on **state**, not
intent: owning the credentials is not the same as their staying valid. Writing the gap down
converted an unexamined risk into an accepted one and stopped anyone re-examining it. All
three entries were removed; the dogfood now carries the App-token `if:` guard, both `||`
fallbacks, and `SLACK_WEBHOOK_URL`, and `test_05`/`test_09` enforce all three in both files.
That divergence list is documentation-only — no test detects staleness on its own — so it
needs auditing whenever a safety property lands on only one side.

## Residual case not covered

`run()` returns 2 at three points before `state["current_run"]` exists: no config, invalid
config, invalid state. An App-token failure on a host whose config is *also* broken records
nothing and stays a red job, because the read cannot be hoisted above those early returns
without the swallowing bug described above. This is accepted: a host with an unparseable
config has a louder problem than a missing App token.

## Split out — CCE-128

An earlier draft of this fix included a stdlib `notify_run_death.py` step to alarm on
failures the orchestrator can't report itself (expired `CLAUDE_CODE_OAUTH_TOKEN`, an
orchestrator crash, a runner OOM). Adversarial review found six open design questions and
one factual error — the draft assumed the step could run *after* checkout ("the tree is
already checked out by that point"), which is false for the App-token step itself: it runs
*before* `actions/checkout`, so a death alarm script that doesn't exist on the runner yet
can't fire during the earliest failures. That's the same class of mistake this ticket
exists to fix: asserting a mechanism works without checking when its preconditions hold.
CCE-128 tracks the death-alarm design separately rather than blocking this fix.

## Test coverage map

| Test | What it pins |
| --- | --- |
| `tests/orchestrator/test_pipeline_integration.py` | `DOCS_AGENT_APP_TOKEN_STATUS=failure` flips `partial` with `app_token_unavailable` in `partial_reasons`; `=skipped` and unset stay non-partial (the bare-host regression lock); `partial=True` from this reason routes through `_maybe_auto_merge` to `skip("partial_run")` |
| `tests/templates/test_workflow_run_parity.py` (`test_05`, `test_09`) | App-token `if:` guard, both `||` fallbacks, and `continue-on-error: true` + the `outcome` (not `conclusion`) export are enforced identically in `templates/workflow-run.yml` and the dogfood workflow |

All orchestrator-side tests use the existing fixture-driven dry-run path with
`monkeypatch.setenv`; the production Claude CLI dispatch stays monkeypatched, per the
repo's testing convention.

## Reference

Design spec:
`docs/superpowers/specs/2026-08-07-cce127-app-token-degrade-partial-design.md`. Ticket:
CCE-127 (2026-08-07). Extends CCE-80 (App-token opt-in, designed for the skipped path
only); closes the CCE-71 / CCE-80 template-vs-dogfood divergence.
