---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/68
synthesized_into: []
---

# Fix: Jira auth credentials missing from nightly runner environment (2026-05-29)

**Tracked by:** CCE-53  
**Merged in:** PR #68  
**Affected runs:** docs-agent PRs #54, #64, #67

## What broke

Every docs-agent PR since the workflow went live opened with `partial: true` and `partial_reasons: [jira_auth_missing]`. The `source-collector` subagent reached the Jira enrichment step, found no credentials, and skipped with `source_collector_error: jira_auth_missing`. Jira-enriched PR summaries were never produced.

The `JIRA_API_TOKEN` and `JIRA_EMAIL` secrets were already registered in the repository (added 15:32 UTC). The workflow never forwarded them into the runner environment.

## Root cause

`.github/workflows/docs-agent-nightly.yml` declared `CLAUDE_CODE_OAUTH_TOKEN` in the job-level `env:` block but omitted `JIRA_API_TOKEN` and `JIRA_EMAIL`. The `source-collector` agent runs as a subprocess via `dispatch_subagent`, which inherits the parent process environment — but there was nothing to inherit.

CCE-45 established the relevant constraint: `secrets.*` references are valid at job-env scope (resolved before any step runs) but not at step-env scope (where `steps.*` references from earlier steps are allowed). Jira credentials belong at job-env for the same reason `CLAUDE_CODE_OAUTH_TOKEN` does.

## Fix

PR #68 adds two entries to the `env:` block of the `author` job in `.github/workflows/docs-agent-nightly.yml:32`:

```yaml
JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
```

No further plumbing was required. `dispatch_subagent` already passes the full parent environment into every subprocess, so the credentials propagate to `source-collector` automatically.

## Verifying the fix

Trigger a manual run after the workflow change is on `main`:

```bash
gh workflow run docs-agent-nightly.yml -f reason="verify CCE-53 jira auth fix"
gh run watch
```

A healthy run produces a docs-agent PR with `partial: false` and a non-empty `jira_issues` list in the source-collector output. If `partial_reasons` still contains `jira_auth_missing`, confirm both secrets are set in **Settings → Secrets and variables → Actions** under the names `JIRA_API_TOKEN` and `JIRA_EMAIL`.

## If Jira secrets are not set in your repo

Without the secrets, the nightly run continues but marks itself partial. You will see this in `.engineering-docs-agent/state.json`:

```json
"partial": true,
"partial_reasons": ["jira_auth_missing"]
```

The docs-agent PR still opens; only Jira issue enrichment is skipped. To re-enable it, add the two secrets and re-trigger the workflow. See the README's "Jira enrichment (optional)" section for the token source.
