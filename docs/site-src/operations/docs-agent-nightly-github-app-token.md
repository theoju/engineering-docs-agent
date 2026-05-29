---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/65
synthesized_into: []
---

# Nightly Workflow: GitHub App Token

The `docs-agent-nightly` workflow authenticates as the `docs-agent-bot` GitHub App rather than using the default `GITHUB_TOKEN`. This page explains why that matters and what you need to configure.

## Why not GITHUB_TOKEN?

GitHub's default `GITHUB_TOKEN` has a documented loop-prevention rule: any commit or PR it creates will not trigger `pull_request` or `push` event workflows. This means every docs-agent PR opens silently — pytest and the diagram-gate never run without a manual empty-commit push to retrigger CI.

GitHub App installation tokens are explicitly exempt from this suppression rule. Switching to one guarantees CI fires automatically on every docs-agent-opened PR.

## Required secrets

Add two secrets to your repo before the nightly workflow will authenticate correctly:

| Secret | Value |
|--------|-------|
| `DOCS_AGENT_BOT_APP_ID` | The numeric App ID from the `docs-agent-bot` GitHub App settings page |
| `DOCS_AGENT_BOT_PRIVATE_KEY` | The PEM-encoded private key generated for the app |

The workflow mints a short-lived installation token at the start of each run using these two secrets. That token drives the `git push` and `gh pr create` steps in `.github/workflows/docs-agent-nightly.yml`.

You cannot substitute `GITHUB_TOKEN` here. The loop-prevention suppression is unconditional for the built-in token — no workflow setting overrides it.

## Why not a PAT?

A personal access token (PAT) bypasses the loop-prevention rule, but it binds authentication to a human identity. If that person leaves your org, the token stops working. A GitHub App credential is org-scoped and survives personnel changes.

## Creating the docs-agent-bot app

If you are self-hosting this plugin, create the GitHub App under your org's Settings → Developer Settings → GitHub Apps:

1. Set the app name to `docs-agent-bot` (or any name — update the workflow's app lookup to match).
2. Grant **Contents: Read & Write** and **Pull requests: Read & Write** repository permissions.
3. Install the app on the target repository.
4. Generate a private key and store it as `DOCS_AGENT_BOT_PRIVATE_KEY`.
5. Copy the App ID and store it as `DOCS_AGENT_BOT_APP_ID`.

Once both secrets are in place, the nightly workflow authenticates as the app and CI triggers automatically on every PR it opens.
