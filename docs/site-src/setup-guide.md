---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/60
  - https://github.com/theoju/engineering-docs-agent/pull/63
synthesized_into: []
---

# Setup Guide

This guide walks you through installing the engineering-docs-agent plugin into a host repo and running it for the first time.

## Prerequisites

- Claude Code CLI installed and authenticated.
- A GitHub repo you want to instrument (the "host repo").
- A `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`. Tokens start with `sk-ant-oat…`. This is an OAuth token, not a console API key (`sk-ant-api…`) — the Claude CLI reads the OAuth slot, not `ANTHROPIC_API_KEY`.

## Install

**Step 1 — Register the marketplace.**

```bash
claude marketplace add engineering-docs-agent <repo-url>
```

If you're working from a local clone:

```bash
claude plugin marketplace add /path/to/engineering-docs-agent
```

**Step 2 — Install the plugin.**

```bash
claude plugin install engineering-docs-agent
```

From a local clone:

```bash
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace
```

**Step 3 — Scaffold your host repo.**

Inside your host repo, run the setup skill:

```bash
claude /engineering-docs-agent-setup
```

This creates `.engineering-docs-agent/config.yml`, seeds `.engineering-docs-agent/state.json`, and wires the nightly GitHub Actions workflow.

## Configure GitHub secrets

Add the following secrets to your host repo under **Settings → Secrets and variables → Actions**:

| Secret | Required | Notes |
|--------|----------|-------|
| `CLAUDE_CODE_OAUTH_TOKEN` | Yes | OAuth token from `claude setup-token`. Starts with `sk-ant-oat…`. The Claude CLI reads this slot for agent dispatch — do not use `ANTHROPIC_API_KEY`. |
| `SLACK_WEBHOOK_URL` | No | Incoming webhook for Slack digest. |
| `JIRA_API_TOKEN` | No | Atlassian Cloud API token for Jira enrichment. |
| `SMTP_*` | No | SMTP credentials for email digest. |

## Trigger the nightly run

The agent runs automatically at 07:00 UTC via `.github/workflows/docs-agent-nightly.yml`. To trigger it manually:

```bash
gh workflow run docs-agent-nightly.yml -f reason="<your reason>"
gh run watch
```

The `reason` input is a free-text label surfaced in the run summary alongside the post-run `state.json` snapshot. One run at a time per repo — concurrent invocations queue rather than race on the same docs-agent branch.

## Run locally

To run the agent against your host repo without opening a PR:

```bash
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

For per-subagent raw-stdout diagnostics, set `DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug` before invoking.

## Jira enrichment (optional)

If your host config sets `sources.jira.enabled: true`, export two env vars before invoking the orchestrator:

```bash
export JIRA_EMAIL="your.email@example.com"
export JIRA_API_TOKEN="…"  # from https://id.atlassian.com/manage-profile/security/api-tokens
```

`JIRA_API_TOKEN` is an Atlassian Cloud API token, not your password. Without these vars, the orchestrator continues to run — `jira_issues` will be `[]` and the run is marked `partial: true` with `error: "jira_auth_missing"` so the gap is visible in `state.json` and in Slack/email notifications.

## What happens after setup

Each nightly run inspects merged PRs and commits since the last successful run, then opens or appends to a `docs-agent/YYYY-MM-DD` PR. That PR contains:

- A **What's New** entry summarizing changes.
- **Updated or new pages** authored by the `page-author` subagent with voice few-shot matching.
- **Gap flags** for non-trivial PRs that have no spec or plan.

After you merge the docs PR, the agent verifies the host's build pipeline succeeded and pages are live.
