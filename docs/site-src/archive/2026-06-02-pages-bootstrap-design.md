---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/103
synthesized_into: []
---

# Design Decision: GitHub Pages Bootstrap (2026-06-02)

**Jira:** CCE-82 | **Incident:** `theoju/claude-code-self-assessment` PR #121 (CCE-81)

## Problem

`actions/configure-pages@v6` exposes an `enablement: true` field that appears to bootstrap GitHub Pages on first deploy. It does not. The `GITHUB_TOKEN` available inside an Actions workflow carries only the scopes the workflow declares — and `permissions:` blocks can only *restrict* the default-token scopes, never expand them. The admin scope required to call `POST /repos/.../pages` is never available to a workflow token.

The result: every new host onboarded via the setup skill reached first deploy with Pages disabled and no error surfaced. The workflow would silently pass. The operator would find a broken `*.github.io` URL and need a manual `gh api` recovery to unblock.

The incident was exposed in `theoju/claude-code-self-assessment` PR #121, which hit the first-deploy failure during an mkdocs upgrade rollout. Recovery required manual `gh api -X POST repos/.../pages -f build_type=workflow` with admin credentials.

## Decision

Move Pages bootstrap to setup time, where operator credentials (admin `gh` auth) are always present. The `enablement: true` field was removed from both `templates/workflow-pages.yml` and the dogfood `.github/workflows/docs-pages.yml`.

Bootstrap is now performed by `scripts/enable_pages.py`, invoked at step 6c of the `engineering-docs-agent-setup` skill after the workflow file is written.

## Implementation

`scripts/enable_pages.py` wraps a single `gh api` call:

```
gh api -X POST repos/{owner}/{repo}/pages -f build_type=workflow
```

The script handles four failure modes and always returns exit 0 except for a missing `--owner` or `--repo` argument (exit 2):

| Condition | Behaviour |
|---|---|
| HTTP 201 | Pages bootstrapped successfully |
| HTTP 409 | Pages already enabled — idempotent, no-op |
| `gh` binary missing | Logs a warning; scaffolding continues |
| Any other error | Logs the error; scaffolding continues |

The 30-second subprocess timeout prevents a network hang from blocking the full setup run.

## Constraints

`permissions:` blocks in a workflow YAML can only restrict the default token — they cannot grant additional scopes. This is a GitHub platform constraint, not something configurable in the plugin. Any future version of `actions/configure-pages` that claims to bootstrap Pages from within a workflow would require GitHub to change this platform behaviour. Until then, setup-time bootstrap with operator credentials is the only reliable path.

## Test coverage

PR #103 added fourteen new CLI tests covering all four `enable_pages.py` exit paths and two updated template tests confirming the `enablement: true` block is absent from both workflow templates.
