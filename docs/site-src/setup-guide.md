---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/63
  - https://github.com/theoju/engineering-docs-agent/pull/60
synthesized_into: []
---

# Setup Guide

## Prerequisites

- Claude Code installed.
- A host repo with a docs site (MkDocs or Docusaurus).
- GitHub Actions enabled.

## One-time setup

Run from inside the host repo:

```
claude /engineering-docs-agent-setup
```

This will:

1. Auto-discover your docs framework, source directory, and lens IA.
2. Ask you about Slack/email, voice preferences, gap-detection allowlist, and Tier 2 lint rules.
3. Write `.engineering-docs-agent/config.yml`, `.engineering-docs-agent/state.json`, and the two workflow files.

## Configuring secrets

Set the following in your repo's Actions secrets:

- `CLAUDE_CODE_OAUTH_TOKEN` (required) — OAuth token from `claude setup-token` (starts with `sk-ant-oat…`). This is distinct from console API keys (`sk-ant-api…`); the Claude CLI reads the OAuth slot, not `ANTHROPIC_API_KEY`. Setting the wrong secret causes silent auth failures at dispatch time.
- `GITHUB_TOKEN` (provided automatically)
- `JIRA_API_TOKEN` (if Jira opt-in)
- `SLACK_WEBHOOK_URL` (if Slack notifications enabled)
- `SMTP_SERVER`, `SMTP_USER`, `SMTP_PASSWORD` (if email enabled)

## First run

The nightly cron fires at the time configured in `config.yml`. To trigger a run manually:

```
gh workflow run docs-agent-nightly.yml -f reason="<your reason>"
gh run watch
```

The `reason` input is a free-text label surfaced in the run summary. The actual workflow file is `.github/workflows/docs-agent-nightly.yml` — using any other filename (e.g., `docs-agent-run.yml`) will produce a "workflow not found" error.

## Troubleshooting

- **No PR opens after a run**: check the Actions log; usually a missing or misnamed secret. Confirm the repo secret is named `CLAUDE_CODE_OAUTH_TOKEN`, not `ANTHROPIC_API_KEY`.
- **Lint failures dropping pages silently**: check the PR body's "Partial run" section.
- **Verify workflow can't find the build run**: confirm `publishing.build_workflow` in `config.yml` matches your deploy workflow's filename.
- **`workflow not found` on manual trigger**: confirm you're referencing `docs-agent-nightly.yml`, not a stale alias.
