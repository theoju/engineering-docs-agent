---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/68
  - https://github.com/theoju/engineering-docs-agent/pull/91
synthesized_into: []
---

# Nightly workflow: Jira authentication

The nightly docs-agent workflow authenticates to Jira using two repo credentials — one Secret, one Variable — forwarded as job-level environment variables in `.github/workflows/docs-agent-nightly.yml`. Without them, every run operates in partial mode.

## Required credentials

Set the following in your repository's **Settings → Secrets and variables → Actions**, using the correct tab for each tier.

### Repository Secrets

| Name             | Value                                                                                                                                             |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `JIRA_API_TOKEN` | Atlassian Cloud API token from [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens) |

### Repository Variables

| Name         | Value                                                    |
| ------------ | -------------------------------------------------------- |
| `JIRA_EMAIL` | The email address associated with your Atlassian account |

`JIRA_EMAIL` is a non-sensitive basic-auth username — it's already visible in Jira comments and git commit authors. Storing it as a Variable (not a Secret) makes it visible in workflow logs and avoids misleading operators about its sensitivity tier.

The workflow exposes them to the runner process:

```yaml
env:
  JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
  JIRA_EMAIL: ${{ vars.JIRA_EMAIL }}
```

The orchestrator passes its full environment into each subagent subprocess, so both variables reach the source-collector without additional plumbing once they are in the job environment.

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
