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

Set both of the following in your repository's **Settings → Secrets and variables → Actions**. The API token is sensitive and goes in the Secrets tab; the email is non-sensitive (it's already visible in commit metadata anywhere it matters) and goes in the Variables tab so it shows up plainly in workflow logs.

| Name             | Tier     | Value                                                                                                                                             |
| ---------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `JIRA_API_TOKEN` | Secret   | Atlassian Cloud API token from [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens) |
| `JIRA_EMAIL`     | Variable | The email address associated with your Atlassian account                                                                                          |

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

## Migration: `JIRA_EMAIL` from Secrets to Variables

PR #91 re-classifies `JIRA_EMAIL` as a non-sensitive GitHub **Variable** (not a Secret). Non-sensitive configuration must not live in the encrypted Secrets store — it obscures the value in logs unnecessarily and makes debugging harder.

If you previously stored `JIRA_EMAIL` as a repository Secret, do the following:

1. **Delete** the `JIRA_EMAIL` entry under **Settings → Secrets and variables → Actions → Secrets**.
2. **Add** `JIRA_EMAIL` under **Settings → Secrets and variables → Actions → Variables** with the same email value.

The workflow snippet and table above already reflect the correct configuration. The preflight validator (`scripts/preflight_host.py`) checks for this shape on each nightly run and will surface a misconfiguration error if `JIRA_EMAIL` is still wired as a secret.
