---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/195
synthesized_into: []
doc_kind: architecture
---

# The nightly workflow

Every onboarded host gets `templates/workflow-run.yml` scaffolded to
`.github/workflows/docs-agent-nightly.yml`. It fires on a per-host cron (a
deterministic off-minute in `[5, 55]` so onboarded hosts don't all pile up at
`:07 UTC`), on `workflow_dispatch`, and — if you keep the template's D4 block —
on `pull_request: closed` against `main` (guarded against looping on its own
`docs-agent/*` branches). This page walks the steps you inherit and the one
piece of wiring you need to get right at onboarding time: the GitHub App
token.

## What the job does, in order

1. **Generate GitHub App installation token** — optional, `if:
   vars.DOCS_AGENT_APP_CLIENT_ID != ''`. Covered below.
2. **Checkout host repo** — full history (`fetch-depth: 0`) so the
   orchestrator's window math can see every merge back to
   `last_successful_run.head_sha`.
3. **Check out engineering-docs-agent plugin** — vendors the plugin's
   `scripts/` into `.docs-agent-plugin` at a pinned release tag.
4. Python + `claude` CLI setup, then an **OAuth token assertion** step that
   fails fast with a specific error if `CLAUDE_CODE_OAUTH_TOKEN` is missing,
   looks like a console API key (`sk-ant-api*` instead of `sk-ant-oat*`), or
   is suspiciously short.
5. **Run docs-agent** — invokes `scripts/orchestrator_runner.py`, the actual
   nightly pipeline.
6. **Upload subagent forensics** and **run summary** — always run
   (`if: always()`), so you get per-dispatch prompt/stdout/stderr artifacts
   and a `state.json` dump in the step summary even on failure.

Steps 2–6 all depend on step 1 having produced *some* usable token, so it's
worth understanding exactly what step 1 can and can't do.

## The App-token step and its two non-success paths

`templates/workflow-run.yml` mints a short-lived installation token via
`actions/create-github-app-token@v3`, gated by `if:
vars.DOCS_AGENT_APP_CLIENT_ID != ''`. That step has two ways of *not*
succeeding, and they mean different things:

- **`skipped`** — you never set `vars.DOCS_AGENT_APP_CLIENT_ID`. This is the
  normal bare-host path: no App configured, nothing broken. The next step's
  fallback (`token: ${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN
  }}`) resolves to `secrets.GITHUB_TOKEN` and the run proceeds on that.
- **`failure`** — you *did* configure an App, but the mint call itself failed:
  the App was uninstalled, transferred to another account, or the repository
  fell out of its installation's repo selection.

Either way, the job falls back to `secrets.GITHUB_TOKEN` and keeps running —
the App-token step carries `continue-on-error: true` specifically so a
`failure` outcome doesn't abort the job before that fallback line is even
reached (GitHub only evaluates the `||` fallback for a step reported as
`skipped`; a step that fails without `continue-on-error` aborts the workflow
before the expression is reached at all).

But `skipped` and `failure` are not equivalent outcomes for you as the host
operator, and the workflow tells the orchestrator which one happened:

```yaml
env:
  DOCS_AGENT_APP_TOKEN_STATUS: ${{ steps.app-token.outcome }}
```

`orchestrator_runner.py:run` reads that variable at run start. Only the
literal value `"failure"` records a blocking `app_token_unavailable` reason
and flips the run to `partial`; `"skipped"`, `"success"`, and unset all stay
silent. A `partial` run skips the CCE-101 auto-merge gate (`_maybe_auto_merge`
in `scripts/orchestrator_runner.py`) and stays open for manual review instead.

That distinction matters because a `GITHUB_TOKEN`-authored PR **never fires
your host's own CI** — `push`/`pull_request` events don't trigger for
`GITHUB_TOKEN`-authored commits. On a bare host that's expected and harmless;
on a host whose App just broke, it means zero checks register, and without
the CCE-127 degrade-to-partial fix that would read as "nothing failed" and
the PR would auto-merge undocumented, unvalidated changes. Flipping `partial`
is what stops that.

## What this means for you at onboarding

If you don't configure a GitHub App at all, none of the above applies to
you beyond the "bare host" bullet: the nightly runs on `GITHUB_TOKEN`,
authors PRs, and simply never triggers your own CI on them. That's a
supported, permanent configuration, not a degraded one.

If you *do* register an App (recommended if you want docs-agent PRs to pass
through your host's normal CI before merge), set `vars.DOCS_AGENT_APP_CLIENT_ID`
and `secrets.DOCS_AGENT_APP_PRIVATE_KEY`, then **install the App on the
repository** — configuring the credentials alone is not enough without the
installation. If the App later stops working, the error you'll see in the
mint step distinguishes two different fixes:

- **404** on `/repos/{owner}/{repo}/installation` — the JWT authenticated
  fine, but no installation currently covers the repo. Re-install the App;
  credentials are fine.
- **401** — the App or its private key is actually bad. Rotate the key.

Either failure now produces a green workflow run, an open PR marked
`partial: true` with `app_token_unavailable` in its digest, and auto-merge
skipped — not a dead job with no signal at all. Wire
`notifications.slack.enabled: true` and `SLACK_WEBHOOK_URL` (a job-env secret
in the template) during onboarding so that signal actually reaches someone;
a `partial` run with no notification channel is silent in practice even
though the mechanism worked.
