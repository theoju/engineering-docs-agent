---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/65
synthesized_into: []
---

# docs-agent-nightly: GitHub App Token

The `docs-agent-nightly` workflow uses a GitHub App installation token instead of the default `GITHUB_TOKEN` for all Git and GitHub CLI operations. This page explains why, what you need to set up, and what the workflow does at runtime.

## Why not the default `GITHUB_TOKEN`

GitHub documents a loop-prevention property of `GITHUB_TOKEN`: any commit pushed or PR opened by that token does **not** trigger `push` or `pull_request` workflow events. For most workflows that is harmless. For the docs-agent, it means every nightly PR opens silently — `pytest` and the diagram-gate never fire — and you have to manually push an empty commit to re-trigger CI.

GitHub App installation tokens are explicitly exempt from this suppression. Switching to an App token is the correct fix; branch-filter workarounds do not help because both event types are suppressed.

## Prerequisites

Before the workflow runs, you need:

1. **A GitHub App** named `docs-agent-bot` (or any name you choose) installed on the repo with **Contents: write** and **Pull requests: write** permissions.
2. Two repository secrets:
   - `DOCS_AGENT_APP_ID` — the numeric App ID shown on the App's settings page.
   - `DOCS_AGENT_APP_PRIVATE_KEY` — the PEM private key generated from the App's settings page (the full `-----BEGIN RSA PRIVATE KEY-----…` block).

## How the workflow mints and uses the token

The workflow calls `actions/create-github-app-token@v1` early in the job, passing the two secrets as inputs. The step outputs a short-lived installation token bound to the repository.

```yaml
- uses: actions/create-github-app-token@v1
  id: app-token
  with:
    app-id: ${{ secrets.DOCS_AGENT_APP_ID }}
    private-key: ${{ secrets.DOCS_AGENT_APP_PRIVATE_KEY }}
```

Three places in the job consume `steps.app-token.outputs.token`:

- `actions/checkout@v5` receives it as `token:` so the runner's credential helper is configured from the start.
- `git push` uses it via the authenticated remote URL.
- `gh pr create` passes it via `GH_TOKEN` so the CLI authenticates as the App, not as the default runner identity.

The token expires after one hour. The job's timeout is 60 minutes, so the token is always valid for the full run.

## Secrets rotation

Rotate `DOCS_AGENT_APP_PRIVATE_KEY` by generating a new key on the App settings page, updating the secret, and deleting the old key. The App ID never changes for a given App, so `DOCS_AGENT_APP_ID` does not need rotation.

## Verifying the fix

After the workflow runs, open the resulting `docs-agent/YYYY-MM-DD` PR and confirm that the `pull_request` event triggered both `pytest` and the diagram-gate. If CI still does not fire, check that the App token is the one used for `gh pr create` — look for `github-actions[bot]` vs the App's slug in the PR author field. The App's slug is your indicator that the token swap took effect.
