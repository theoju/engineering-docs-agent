---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/65
synthesized_into: []
---

# GitHub App Token for `docs-agent-nightly`

The `docs-agent-nightly` workflow uses a GitHub App installation token instead of the default `GITHUB_TOKEN`. This page explains why, how it is wired, and how to validate it.

## The problem: GitHub CI suppression

GitHub suppresses `pull_request` and `push` CI triggers on any commit or PR authored with the default `GITHUB_TOKEN`. This is a loop-prevention rule built into GitHub Actions. It applies to **both** event types — adding a `push: branches: [docs-agent/**]` trigger does not escape it.

Every docs-agent PR opened with `GITHUB_TOKEN` arrived without pytest or diagram-gate CI firing automatically. PRs #57 and #59 both required a manual empty-commit push to retrigger. The issue is systemic, not a fluke.

## The fix: GitHub App installation token

GitHub App installation tokens are explicitly exempt from the loop-prevention rule. A PR opened by a workflow that authenticates as an App installation triggers CI normally.

PR #65 adds an `actions/create-github-app-token@v1` step at the top of `.github/workflows/docs-agent-nightly.yml`. The step reads two repo secrets:

- `DOCS_AGENT_APP_ID` — the numeric ID of the `docs-agent-bot` GitHub App.
- `DOCS_AGENT_APP_PRIVATE_KEY` — the PEM private key for that app.

Both `env.GH_TOKEN` and the `actions/checkout@v5` `token:` input now reference the minted app token. The diff is 24 lines added, 1 removed — workflow YAML only, no orchestrator code changes.

## Setting up the secrets

You need to add both secrets to your repo before the workflow will authenticate correctly.

1. Go to **Settings → Secrets and variables → Actions** in the host repo.
2. Create `DOCS_AGENT_APP_ID` with the numeric app ID (visible on the GitHub App's settings page under "App ID").
3. Create `DOCS_AGENT_APP_PRIVATE_KEY` with the full PEM content, including the `-----BEGIN RSA PRIVATE KEY-----` header and footer lines.

If either secret is missing, the `create-github-app-token` step fails immediately and the workflow does not proceed.

## Validating the change

After the secrets are set, trigger a manual run:

```bash
gh workflow run docs-agent-nightly.yml -f reason="app-token validation"
gh run watch
```

The resulting docs-agent PR should fire pytest and the diagram gate automatically — no manual push required. If CI does not fire, check that the `docs-agent-bot` app has been installed on the repository (not just created) and that the private key secret matches the currently active key on the app.

## Scope of the change

The token swap is confined to `.github/workflows/docs-agent-nightly.yml`. No orchestrator code, no agent contracts, and no state files were touched. The `CLAUDE_CODE_OAUTH_TOKEN` secret used by the Claude CLI subprocess is unchanged.
