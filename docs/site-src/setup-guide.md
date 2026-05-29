---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/63
  - https://github.com/theoju/engineering-docs-agent/pull/60
synthesized_into: []
---

# Setup Guide

This guide walks you through installing the engineering-docs-agent plugin into a host repo and wiring the required GitHub secrets so the nightly authoring run succeeds.

## Prerequisites

- The `claude` CLI installed and authenticated in your local environment.
- A GitHub repo where you want docs to be generated.
- A Claude OAuth token (see below for how to tell OAuth from API tokens).

## Install

1. Add this repo as a Claude Code marketplace:

   ```bash
   claude marketplace add engineering-docs-agent <repo-url>
   ```

2. Install the plugin:

   ```bash
   claude plugin install engineering-docs-agent
   ```

3. In your host repo, run the setup skill:

   ```bash
   claude /engineering-docs-agent-setup
   ```

   The setup skill scaffolds `.engineering-docs-agent/config.yml`, `state.json`, and the `docs/site-src/` tree. Review the generated config before proceeding.

## GitHub Secrets

Go to **Settings → Secrets and variables → Actions** in your host repo and add:

| Secret | Required | Notes |
|--------|----------|-------|
| `CLAUDE_CODE_OAUTH_TOKEN` | Yes | OAuth token from `claude setup-token`. Starts with `sk-ant-oat…`. **Not** the same as `ANTHROPIC_API_KEY` (API keys start with `sk-ant-api…`). The Claude CLI reads the OAuth slot. |
| `DOCS_AGENT_APP_ID` | Yes | GitHub App ID for the docs-agent-bot installation. |
| `DOCS_AGENT_APP_PRIVATE_KEY` | Yes | Private key for the same App. |
| `SLACK_WEBHOOK_URL` | No | Incoming webhook URL for Slack digest notifications. |
| `JIRA_API_TOKEN` | No | Atlassian Cloud API token for Jira enrichment. |
| `JIRA_EMAIL` | No | Email address tied to the `JIRA_API_TOKEN`. |
| `SMTP_*` | No | SMTP credentials for email digest. |

### OAuth token vs API key

The Claude CLI authenticates via OAuth, not the console API key. Use `claude setup-token` to generate the OAuth token. If you accidentally set `ANTHROPIC_API_KEY` here, the nightly workflow will fail the `Assert OAuth token is configured` step with a clear error message.

## Triggering the Nightly Workflow

The authoring pipeline runs automatically at 07:00 UTC via `.github/workflows/docs-agent-nightly.yml`. To fire it manually:

```bash
gh workflow run docs-agent-nightly.yml -f reason="<your reason>"
gh run watch
```

The `reason` label appears in the run summary alongside a snapshot of `state.json`. Only one run executes at a time per repo — concurrent invocations queue rather than race on the same `docs-agent/YYYY-MM-DD` branch.

## Local Dry-Run

You can run the agent locally against the host repo without opening a PR:

```bash
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

For per-subagent diagnostics, set `DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug` before invoking. Each dispatch writes its prompt, stdout, stderr, and stream events to that directory.

## Partial Runs

If a run completes with some subagents failing (e.g., Jira credentials missing), the orchestrator still opens the PR with `partial: true` in the body. The next nightly run picks up where the previous one left off. A silent gap is never the outcome — the PR body makes the failure visible.

Check `.engineering-docs-agent/state.json` for `partial_reasons` after a partial run.
