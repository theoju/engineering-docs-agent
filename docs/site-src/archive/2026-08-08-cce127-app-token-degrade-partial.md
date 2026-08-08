---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/195
synthesized_into: []
doc_kind: decision
---

# CCE-127 — a failed App-token mint degrades the run to partial instead of killing the job

A failed GitHub App installation-token mint no longer aborts the nightly job. It now falls back to `secrets.GITHUB_TOKEN`, finishes the run, and records a blocking `app_token_unavailable` reason that flips the run to `partial` — which disables auto-merge through the existing CCE-101 interlock.

## What broke

`theoju/engineering-docs-agent` and `theoju/claude-code-self-assessment` each failed 15 consecutive nightlies, 2026-07-24 through 2026-08-07, with no notification. Every run died at the same step: `Generate GitHub App installation token`, with a 404 on `/repos/{owner}/{repo}/installation`.

That 404 matters: it means the JWT authenticated fine and the App simply has no installation covering the repo — not a credentials problem. In this case an org transfer had moved the `engineering-docs-agent-bot` App and dropped its installation on the personal-account repo; a 401 would instead mean the App or its private key is bad. The two failure modes need opposite remediation (re-install vs. rotate), so conflating them is a trap in its own right.

The underlying code defect was two months old. `templates/workflow-run.yml` already had a fallback — `token: ${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}` — but GitHub only evaluates that `||` expression when the preceding step is *skipped*. A step that *fails* aborts the job before the expression is ever reached. CCE-80's original design reasoned correctly about the skipped path (no App configured) but never considered the configured-but-broken path, so the fallback had been unreachable for exactly the failure mode that hit production.

The dogfood workflow, `.github/workflows/docs-agent-nightly.yml`, was worse than the template: it carried neither the `if: vars.DOCS_AGENT_APP_CLIENT_ID != ''` guard nor any `||` fallback, and it never wired `SLACK_WEBHOOK_URL` — so there was no channel to alarm on the failures even if something had degraded gracefully. Three `_TEMPLATE_ONLY_DIVERGENCES` entries in `tests/templates/test_workflow_run_parity.py` had recorded these gaps as accepted, on the reasoning "the dogfood requires the App" / "the dogfood uses only the App token." Both statements were true and both were irrelevant — the step fails on *state* (installation dropped), not on *intent* (App configured). Writing the divergence down had converted an unexamined gap into an accepted one, and nobody re-examined it until this incident forced the question.

## The fix

Two mechanisms, and either alone is inert:

1. **`continue-on-error: true`** on the App-token step in both `templates/workflow-run.yml` and the dogfood workflow. This is what makes `steps.app-token.outcome` and `steps.app-token.conclusion` diverge — `continue-on-error` rewrites `conclusion` to `success` so the job proceeds, but `outcome` retains the true `failure`. Reading `.conclusion` anywhere in this design would always report a healthy mint, even for a run that had none — worse than not fixing it at all, because it would auto-merge on a clean-looking signal.
2. **`DOCS_AGENT_APP_TOKEN_STATUS: ${{ steps.app-token.outcome }}`**, exported at step-env scope into the `Run docs-agent` step (job-env cannot reference `steps.*`). `scripts/orchestrator_runner.py`'s `run()` reads it right after `state["current_run"]` is constructed and before the auto-merge decision — that placement is deliberate, since reading it any earlier would have `add_partial` build a stub `current_run` that the dict literal then silently overwrites.

Only the literal `"failure"` value degrades the run:

| `outcome` | Meaning | Behavior |
| --- | --- | --- |
| `skipped` | `DOCS_AGENT_APP_CLIENT_ID` unset — bare host, no App configured | Silent |
| `failure` | App configured but the token mint failed | Blocking `app_token_unavailable` reason → `partial` |
| `success` / unset | Normal | Silent |

This mirrors the CCE-125 "unjudged" rule: an *absent* signal and a *present-and-broken* signal carry different semantics, and only the latter degrades behavior. Flipping `partial` needed no new gate — it reuses `scripts/orchestrator_runner.py`'s existing `_maybe_auto_merge` short-circuit (`if partial: return skip("partial_run")`). That reuse is the point: a PR authored with `GITHUB_TOKEN` never fires the host's own CI (`GITHUB_TOKEN` suppresses `push`/`pull_request` events), so zero registered checks after the grace window would otherwise read as "nothing failed" and auto-merge undocumented, unvalidated content.

The dogfood workflow also absorbed the missing `if:` guard, both `GITHUB_TOKEN` fallbacks, and the `SLACK_WEBHOOK_URL` job-env line, closing the CCE-71/CCE-80 template-vs-dogfood divergence. The three `_TEMPLATE_ONLY_DIVERGENCES` entries that had recorded those gaps as accepted are removed from `tests/templates/test_workflow_run_parity.py`.

## What this does not cover

`run()` returns before `state["current_run"]` exists at three earlier points: no config, invalid config, invalid state. An App-token failure on a host whose config is *also* broken records nothing and the job still shows red — a host with an unparseable config has a louder problem than a missing App token, so this is accepted rather than special-cased.

A separate follow-up, CCE-128, is scoped to alarm on job deaths the orchestrator itself can't report — an expired OAuth token, an orchestrator crash, a runner OOM. It's split out deliberately: an earlier draft assumed the checkout step has already run by the time an `if: failure()` step fires, which is false for failures at or before the App-token step (checkout runs *after* it), so the same class of untested assumption that caused this incident nearly recurred inside its own fix.

## Reference

CCE-127 (2026-08-08). Design: `docs/superpowers/specs/2026-08-07-cce127-app-token-degrade-partial-design.md`. Extends CCE-80 (App-token opt-in, designed for the skipped path only); closes the CCE-71/CCE-80 template/dogfood divergence.
