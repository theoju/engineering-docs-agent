---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/196
synthesized_into: []
doc_kind: decision
---

# CCE-127: App-token degradation — operational learnings

This entry captures what shipping the CCE-127 fix actually took, beyond the mechanism itself. The mechanism (degrade to `partial` instead of failing the job) is documented in `CLAUDE.md` and in the spec at `docs/superpowers/specs/2026-08-07-cce127-app-token-degrade-partial-design.md`. What follows is the trap list every contributor should read before touching the GitHub App-token step or the workflow/orchestrator boundary again.

## The incident

Between 2026-07-23 and 2026-08-07, the nightly docs-agent run failed 15 consecutive times on both `theoju/engineering-docs-agent` and `theoju/claude-code-self-assessment` — roughly 30 failed runs total. The failures were invisible for two weeks because neither repo had `SLACK_WEBHOOK_URL` wired; the dogfood repo now carries it.

The root cause was an org transfer that silently dropped the docs-agent bot's GitHub App installation. Once the installation was gone, the `actions/create-github-app-token` step could no longer mint a token, and the job died before the fallback to `secrets.GITHUB_TOKEN` was ever reached.

## Why the fallback was dead code

CCE-80 had already wired a `||` fallback: `steps.app-token.outputs.token || secrets.GITHUB_TOKEN`. That fallback only fires if the token-mint step is *skipped* — a *failed* step aborts the job before GitHub Actions ever evaluates the expression. Without `continue-on-error: true` on the token-mint step, the `||` fallback was unreachable on the failure path. Two mechanisms are required here, and either alone is inert: `continue-on-error: true` to keep the job alive, and the `||` expression to substitute a working token. CCE-127 added the first; CCE-80 had already added the second.

## Four traps

1. **`continue-on-error` rewrites `conclusion`, not `outcome`.** A step that fails under `continue-on-error: true` reports `conclusion: success` but `outcome: failure`. Keying a downstream export or test on `conclusion` produces a green signal for a run that had no token at all — worse than no fix, because it clears the way for auto-merge on unvalidated docs. The workflow exports `steps.app-token.outcome` (not `conclusion`) as `DOCS_AGENT_APP_TOKEN_STATUS`, and it does so at **step** scope, because job-level `env:` blocks cannot reference `steps.*`.

2. **`orchestrator_runner.run` only treats the literal `"failure"` as blocking.** `"skipped"` (the bare-host path, when `DOCS_AGENT_APP_CLIENT_ID` isn't set), `"success"`, and an unset value all stay silent. When `DOCS_AGENT_APP_TOKEN_STATUS` reads `"failure"`, the runner records a blocking `app_token_unavailable` reason. That reuses the existing `_maybe_auto_merge` interlock (`if partial: return skip("partial_run")`) — no new gate code was needed. The reasoning: a PR built on the fallback `GITHUB_TOKEN` never fires host CI, so zero registered checks would otherwise look like "nothing failed," and the run would auto-merge undischecked docs. Placement of the env read matters too — it has to land after the `current_run` dict literal is built (that literal would otherwise overwrite the stub `add_partial` creates) and before the auto-merge decision.

3. **404 and 401 mean different things on a token-mint failure.** A 404 on `/repos/{owner}/{repo}/installation` means the JWT authenticated correctly but no installation covers the repo — the App was uninstalled, the repo transferred, or its repo-selection was narrowed. The fix is to re-install; credentials are fine. A 401 means the App ID or private key itself is bad, and the fix is to rotate. The CCE-127 incident was a 404: an org transfer had dropped the installation, so `vars.DOCS_AGENT_APP_CLIENT_ID` and `secrets.DOCS_AGENT_APP_PRIVATE_KEY` needed no change at all. Diagnosing by status code first avoids an unnecessary credential rotation.

4. **`.github/workflows/actionlint.yml` does not lint `templates/`.** It runs bare `actionlint -color`, which only searches `.github/workflows/`. Any change to a workflow template (`templates/workflow-run.yml`, etc.) has to be linted explicitly — `actionlint templates/workflow-run.yml` — or it slips through CI unchecked. This gap is plausibly how the template and the dogfood workflow drifted apart in the first place.

## The meta-lesson: a documented divergence is not a fixed one

`tests/templates/test_workflow_run_parity.py` carries a `_TEMPLATE_ONLY_DIVERGENCES` list — entries where the dogfood workflow *lacks* a safety property that the template has. Three of those entries were justified with "dogfood requires the App" or "dogfood uses only the App token." Both justifications are true, and both are irrelevant, because the degradation step fails on *state* (has the installation been dropped?), not on *intent* (does this repo rely on the App by design?).

Owning the credentials is not the same as their staying valid. Writing "this divergence is fine because X" into a test file converts an unexamined gap into an *accepted* one, and an accepted gap stops getting re-examined — which is exactly how a two-week, 30-run outage went unnoticed. `_TEMPLATE_ONLY_DIVERGENCES` is documentation-only; no test detects staleness in its justifications. Audit that list whenever a safety property lands on one side of the template/dogfood split, per the same precedent set by CCE-125's `ADVISORY_AGENTS` note — deferring a unification is fine, but the deferred item needs to stay visible, not get buried under a plausible-sounding comment.

## Scope note

CCE-127 deliberately did not attempt to alarm on pre-checkout failures — a draft version of this fix assumed the tree was already checked out when an `if: failure()` step runs, which is false before `actions/checkout` executes. That gap is tracked separately as CCE-128.

## References

- Fix: PR #195, spec `docs/superpowers/specs/2026-08-07-cce127-app-token-degrade-partial-design.md`
- Learnings capture: PR #196 (this entry)
- Precedent for the "advisory agent, info-only reason" pattern reused by CCE-127's gate: CCE-118 (fact-checker), CCE-125 (gap-detector)
- Follow-up: CCE-128 (pre-checkout failure alarm)
