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

- `CLAUDE_CODE_OAUTH_TOKEN` (required) — OAuth token from `claude setup-token` (starts with `sk-ant-oat…`). This is distinct from console API keys (`sk-ant-api…`); the Claude CLI reads the OAuth slot, not `ANTHROPIC_API_KEY`. Setting the wrong secret type causes silent auth failures.
- `GITHUB_TOKEN` (provided automatically by Actions)
- `JIRA_API_TOKEN` (if Jira opt-in is enabled)
- `SLACK_WEBHOOK_URL` (if Slack notifications are enabled)
- `SMTP_SERVER`, `SMTP_USER`, `SMTP_PASSWORD` (if email is enabled)

## First run

The nightly cron fires at the time configured in `config.yml`. To trigger a run manually:

```bash
gh workflow run docs-agent-nightly.yml
```

You can pass an optional `reason` label:

```bash
gh workflow run docs-agent-nightly.yml -f reason="initial test run"
gh run watch
```

The workflow is defined at `.github/workflows/docs-agent-nightly.yml`. The `reason` input surfaces in the run summary alongside the post-run `state.json` snapshot. One run at a time per repo — concurrent invocations queue rather than race on the same `docs-agent/YYYY-MM-DD` branch.

## Troubleshooting

- **No PR opens after a run**: check the Actions log; the most common cause is a missing or mis-named secret. Confirm you set `CLAUDE_CODE_OAUTH_TOKEN`, not `ANTHROPIC_API_KEY`.
- **Lint failures dropping pages silently**: check the PR body's "Partial run" section for which pages were dropped and why.
- **Verify workflow can't find the build run**: confirm `publishing.build_workflow` in your `config.yml` matches your deploy workflow's exact filename.
- **Jira issues not appearing**: set `JIRA_EMAIL` and `JIRA_API_TOKEN` env vars before invoking locally, or add them as repo secrets for CI runs. Missing Jira creds produce `partial: true` with `error: "jira_auth_missing"` in `state.json` — the run still completes.
