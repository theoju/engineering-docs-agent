# Setup Guide

## Prerequisites

- Claude Code installed.
- A host repo with a docs site (mkdocs or Docusaurus).
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

- `CLAUDE_CODE_OAUTH_TOKEN` (required) — OAuth token from `claude setup-token` (starts with `sk-ant-oat…`). Distinct from console API keys (`sk-ant-api…`); the Claude CLI reads the OAuth slot, not `ANTHROPIC_API_KEY`.
- `GITHUB_TOKEN` (provided automatically)
- `JIRA_API_TOKEN` (if Jira opt-in)
- `SLACK_WEBHOOK_URL` (if Slack notifications enabled)
- `SMTP_SERVER`, `SMTP_USER`, `SMTP_PASSWORD` (if email enabled)

## First run

The nightly cron fires at the time configured in `config.yml`. To trigger a run manually:

```
gh workflow run docs-agent-run.yml
```

## Troubleshooting

- **No PR opens after a run**: check the Actions log; usually a missing secret.
- **Lint failures dropping pages silently**: check the PR body's "Partial run" section.
- **Verify workflow can't find the build run**: confirm `publishing.build_workflow` matches your deploy workflow's filename.
