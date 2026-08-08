---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/196
synthesized_into: []
doc_kind: decision
---

# Postmortem: GitHub App-token failures silently killed 15 nightlies (CCE-127)

## What happened

From 2026-07-23 to 2026-08-07, the nightly docs-agent run failed 15 consecutive nights on both `theoju/engineering-docs-agent` and `theoju/claude-code-self-assessment` — roughly 30 failed runs total. Nobody noticed for two weeks because neither repo had `SLACK_WEBHOOK_URL` wired; the dogfood repo now carries it so this class of outage pages a human.

The root cause was an org transfer that deleted the GitHub App's installation on both repos. Every nightly run's `actions/create-github-app-token` step then failed to mint a token, and the failure took the whole job down with it — instead of falling back to `GITHUB_TOKEN` and completing a degraded run.

## Root cause

The workflow already had a fallback expression: `steps.app-token.outputs.token || secrets.GITHUB_TOKEN`. That fallback only works if the app-token step is marked `skipped`, not `failure` — GitHub evaluates the `||` only after a step you told it to continue past. Without `continue-on-error: true` on the mint step, a failed mint aborts the job before the fallback expression is ever reached. CCE-80 had shipped the fallback expression two months earlier, but it was dead code on the actual failure path the whole time.

## The fix

You address this the same way you address any external-dependency failure that shouldn't be fatal: degrade to `partial`, never kill the job.

- The workflow now runs `actions/create-github-app-token` under `continue-on-error: true` and exports `steps.app-token.outcome` (not `conclusion` — see traps below) as `DOCS_AGENT_APP_TOKEN_STATUS`, at **step** scope, since job-env can't reference `steps.*`.
- `orchestrator_runner.run` records a blocking `app_token_unavailable` reason for the literal value `"failure"` only. `"skipped"` (the bare-host path with no `DOCS_AGENT_APP_CLIENT_ID` configured), `"success"`, and unset all stay silent — this is not a new failure mode for hosts that never had the App installed.
- Flipping `partial` reuses the existing `_maybe_auto_merge` interlock (`if partial: return skip("partial_run")`). No new gate code was needed. That reuse is the point: a PR built on the fallback `GITHUB_TOKEN` never fires host CI, so zero registered checks would otherwise read as "nothing failed" and auto-merge unvalidated docs.
- Placement of the env read matters: it has to land after the `current_run` dict literal is constructed and before the auto-merge decision. `add_partial` creates a stub that the dict literal would silently overwrite if the read happened first.

## Four traps hit while shipping the fix

1. **`continue-on-error` is what makes the `||` fallback reachable at all.** Two mechanisms are required — the fallback expression and the continue-on-error flag — and either one alone is inert. This is the mechanism described above under root cause; it's worth repeating as its own checklist item because it's easy to ship one half and assume the pair is complete.
2. **Export `outcome`, never `conclusion`.** `continue-on-error: true` rewrites the step's `conclusion` to `success` even when the underlying action failed. A `conclusion`-keyed export or test would report a healthy mint for a run that had no token — passing green while hiding the exact condition you built the degrade-to-partial path to catch. That's worse than not fixing it at all, because it auto-merges with a clean-looking signal.
3. **404 and 401 on a token mint mean different remediations.** A 404 on `/repos/{owner}/{repo}/installation` means the JWT authenticated fine and no installation currently covers the repo — the App was uninstalled, transferred, or repo-selection was narrowed. The fix is to re-install; credentials are fine. A 401 means the App or its private key is bad, and the fix is to rotate. The org-transfer incident here was a 404: `vars.DOCS_AGENT_APP_CLIENT_ID` and `secrets.DOCS_AGENT_APP_PRIVATE_KEY` needed no change at all.
4. **CI does not lint `templates/`.** `.github/workflows/actionlint.yml` runs bare `actionlint -color`, which only searches `.github/workflows/`. Template changes — `templates/workflow-run.yml` and friends — need `actionlint` invoked on them explicitly. This gap is a plausible explanation for how the plugin's shipped template drifted from its own dogfood workflow in the first place.

## The meta-lesson: a documented gap is not an accepted risk

`tests/templates/test_workflow_run_parity.py` carries a `_TEMPLATE_ONLY_DIVERGENCES` list — entries where the dogfood workflow intentionally lacks a safety property that the shipped template has. Three of those entries were justified with "dogfood requires the App" or "dogfood uses only the App token." Both justifications were true, and both were irrelevant, because the step fails on *state* — whether the installation currently exists — not on *intent* — what token strategy the dogfood was designed around.

Owning the credentials is not the same as their staying valid. Writing "this doesn't apply to us" into a divergence list converts an unexamined gap into an apparently-accepted one, and nobody re-examines an accepted risk. That list is documentation-only; no test detects when an entry goes stale. Audit `_TEMPLATE_ONLY_DIVERGENCES` whenever a safety property lands on one side of the dogfood/template split, not just when you add the entry.

## Related work

The death alarm for failures *before* checkout — where an `if: failure()` step can't assume the tree is checked out — is deliberately split out as CCE-128, because the first draft of this fix assumed a checked-out tree that isn't guaranteed to exist that early in the job.

Design spec: `docs/superpowers/specs/2026-08-07-cce127-app-token-degrade-partial-design.md`. Reference: CCE-127 (2026-08-07). Closes out the advisory-agent partial-flip pattern established for gap-detector in CCE-125.
