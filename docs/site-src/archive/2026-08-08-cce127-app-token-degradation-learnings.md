---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/196
synthesized_into: []
doc_kind: decision
---

# CCE-127 app-token degradation: learnings

PR #195 shipped the CCE-127 fix: a failed GitHub App-token mint now degrades
the nightly run to `partial` instead of silently letting it auto-merge
unvalidated docs. That fix closed a 15-night outage. PR #196 does not touch
code — it appends the operational learnings from shipping the fix to
`CLAUDE.md`, following the CCE-125 learnings-capture precedent. This page
archives those learnings for durable, discoverable reference.

## The incident

An org transfer deleted the GitHub App's installation. From 2026-07-23 to
2026-08-07, every nightly run on `theoju/engineering-docs-agent` and
`theoju/claude-code-self-assessment` failed — 15 consecutive nightlies on
each repo, roughly 30 runs total. The failures were invisible because
neither repo had `SLACK_WEBHOOK_URL` wired at the time. The dogfood repo now
carries that webhook.

The fix itself: the workflow runs `actions/create-github-app-token` under
`continue-on-error: true` and exports `steps.app-token.outcome` as
`DOCS_AGENT_APP_TOKEN_STATUS` at step scope (job-env cannot reference
`steps.*`). `orchestrator_runner.run` records a blocking
`app_token_unavailable` reason for the literal `"failure"` outcome only —
`"skipped"` (the bare-host path, no `DOCS_AGENT_APP_CLIENT_ID`), `"success"`,
and unset stay silent. Flipping `partial` reuses the existing
`_maybe_auto_merge` interlock (`if partial: return skip("partial_run")`) —
no new gate code. That reuse is the point: a PR built on the fallback
`GITHUB_TOKEN` never fires host CI, so zero registered checks would
otherwise read as "nothing failed" and auto-merge unvalidated docs. Where
the env read is placed matters: it must run after the `current_run` dict
literal is built (`add_partial` creates a stub the literal would otherwise
overwrite, silently swallowing the reason) and before the auto-merge
decision.

## Four traps

**1. `continue-on-error` is what makes the `||` fallback reachable at all.**
GitHub only evaluates `steps.app-token.outputs.token || secrets.GITHUB_TOKEN`
when the step is *skipped*. A *failed* step aborts the job before the
expression is ever reached — so CCE-80's fallback was dead code on the
failure path for two months. Two mechanisms are required here, and either
one alone is inert.

**2. Export `outcome`, never `conclusion`.** `continue-on-error` rewrites
`conclusion` to `success`, so a `conclusion`-keyed export (or test) passes
green while reporting a healthy mint for a run that had no token at all.
That's worse than not fixing it, because it auto-merges with a clean
signal.

**3. 404 is not 401 when a token mint fails.** A 404 on
`/repos/{owner}/{repo}/installation` means the JWT authenticated fine and no
installation covers the repo — scope was lost (App uninstalled,
transferred, or repo-selection narrowed) and the fix is to re-install; the
credentials themselves are fine. A 401 means the App or key is bad and needs
rotation. This incident was the 404 case: an org transfer, so
`vars.DOCS_AGENT_APP_CLIENT_ID` and `secrets.DOCS_AGENT_APP_PRIVATE_KEY`
needed no change.

**4. CI does not lint `templates/`.** `.github/workflows/actionlint.yml`
runs bare `actionlint -color`, which only searches `.github/workflows/` —
template changes need explicit linting, e.g.
`actionlint templates/workflow-run.yml`. That gap is plausibly how the
template drifted from the dogfood workflow in the first place.

## The meta-lesson

`_TEMPLATE_ONLY_DIVERGENCES` in
`tests/templates/test_workflow_run_parity.py` had recorded three entries
where the dogfood workflow lacked a template safety property, each
justified with reasoning like "dogfood requires the App" or "dogfood uses
only the App token." Both justifications were true, and both were
irrelevant — the step fails on *state*, not intent. Owning the credentials
is not the same as those credentials staying valid.

Documenting a divergence is not the same as accepting the risk it
represents. Writing it down converted an unexamined gap into an accepted
one, and stopped anyone from re-examining it. That divergence list is
documentation-only, and no test detects when it goes stale — so it needs
auditing whenever a safety property lands on one side but not the other.

## Related work

The death alarm for pre-checkout failures is tracked separately as CCE-128,
deliberately split out because the draft version of that alarm assumed the
tree is already checked out when an `if: failure()` step runs — which is
false before `actions/checkout` executes.

Spec:
`docs/superpowers/specs/2026-08-07-cce127-app-token-degrade-partial-design.md`.
Reference: CCE-127 (2026-08-07); learnings captured in CCE-127 follow-up PR
#196 (2026-08-08).
