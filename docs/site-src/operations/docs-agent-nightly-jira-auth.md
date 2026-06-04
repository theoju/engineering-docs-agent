---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/68
  - https://github.com/theoju/engineering-docs-agent/pull/91
synthesized_into: []
---

# Nightly workflow: Jira authentication

The nightly docs-agent workflow authenticates to Jira using two repo credentials forwarded as job-level environment variables in `.github/workflows/docs-agent-nightly.yml`. Without them, every run operates in partial mode.

## Required credentials

Set the following in your repository's **Settings → Secrets and variables → Actions**. Use the correct tab for each — the API token is sensitive and belongs in Secrets; the email address is a basic-auth username, not a credential, and belongs in Variables.

### Secrets

| Name             | Value                                                                                                                                             |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `JIRA_API_TOKEN` | Atlassian Cloud API token from [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens) |

### Variables

| Name         | Value                                                    |
| ------------ | -------------------------------------------------------- |
| `JIRA_EMAIL` | The email address associated with your Atlassian account |

`JIRA_EMAIL` is a basic-auth username — it already appears in Jira comments and git commit author lines. Storing it as a Secret masks it unnecessarily in workflow logs and makes operator debugging harder. Use Variables (the Repository Variables tab, not Secrets) for this value.

The workflow exposes both to the runner process:

```yaml
env:
  JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
  JIRA_EMAIL: ${{ vars.JIRA_EMAIL }}
```

The orchestrator passes its full environment into each subagent subprocess, so both variables reach the source-collector without additional plumbing once they are in the job environment.

## Migrating JIRA_EMAIL from Secret to Variable

If you set up Jira auth before PR #91 (CCE-66), you stored `JIRA_EMAIL` as a Secret. Migrate it to the correct tier:

1. Go to **Settings → Secrets and variables → Actions → Variables tab**.
2. Create a new Repository Variable named `JIRA_EMAIL` with your Atlassian email address.
3. Delete the old `JIRA_EMAIL` entry from the **Secrets tab**.

The workflow already reads `JIRA_EMAIL` from `vars.JIRA_EMAIL`, so the updated reference is in place. Only the repo-side storage tier needs to change.

## What happens when the credentials are missing

When `JIRA_EMAIL` or `JIRA_API_TOKEN` is absent, the source-collector returns `jira_issues: []` and the run is marked `partial: true` with `error: "jira_auth_missing"` in `.engineering-docs-agent/state.json`. The `partial_reasons` list will include `jira_auth_missing` on every subsequent run until the credentials are configured.

Partial mode is an operational-visibility signal. It is intended for transient failures — a run that partially succeeded because a downstream service was briefly unavailable. If it fires on every run, the signal loses its value. A permanently missing Jira credential is exactly this failure mode: the docs-PR is opened with a `partial: true` banner that never clears.

## Verifying the fix

After adding the secrets, trigger a manual run:

```bash
gh workflow run docs-agent-nightly.yml -f reason="verify jira auth"
gh run watch
```

A successful Jira fetch produces a non-empty `jira_issues` list in the source-collector output. Check `.engineering-docs-agent/state.json` after the run merges — `partial_reasons` should be absent or empty.

## Local development

To reproduce Jira enrichment locally, export the two variables before invoking the orchestrator:

```bash
export JIRA_EMAIL="your.email@example.com"
export JIRA_API_TOKEN="..."
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

See `agents/source-collector.md` Step 5 and Forbidden outputs §6 for the agent-side contract on unauthenticated Jira calls.
