---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/103
synthesized_into: []
---

# GitHub Pages Bootstrap

## The problem

`actions/configure-pages@v6 enablement: true` does **not** bootstrap GitHub Pages on a host's first deploy. The field name is misleading. The workflow's `GITHUB_TOKEN` lacks the admin scope required to call `POST /repos/.../pages`; `permissions:` blocks can only restrict default-token scopes, never expand them. The field is silently ignored.

This was exposed by `theoju/claude-code-self-assessment` PR #121 (CCE-81), where the mkdocs upgrade rollout hit a first-deploy failure and required manual `gh api` recovery.

Do not add `enablement: true` back to any workflow template. It does nothing and creates false confidence that Pages is bootstrapped.

## How bootstrap works now

The setup skill (`skills/engineering-docs-agent-setup`) performs Pages bootstrap at step 6c, immediately after writing the workflow file. It calls `scripts/enable_pages.py` using the operator's admin `gh` auth — credentials that are available at setup time but not inside a workflow run.

The script calls:

```bash
gh api -X POST repos/{owner}/{repo}/pages -f build_type=workflow
```

It handles four outcomes:

| Result | Behavior |
|--------|----------|
| HTTP 201 | Pages bootstrapped. Script exits 0. |
| HTTP 409 | Pages already enabled (idempotent). Script exits 0. |
| `gh` binary missing | Logs a warning. Script exits 0 (graceful fallback). |
| Any other error | Logs the error. Script exits 0 (graceful fallback). |

The only non-zero exit is exit 2, returned when `--owner` or `--repo` arguments are absent. That is a caller programming error, not a recoverable runtime condition.

The script enforces a 30-second subprocess timeout on the `gh api` call.

Graceful fallback — exit 0 on every runtime failure — means a missing or misconfigured `gh` credential never blocks the setup skill from completing. You can re-run Pages bootstrap manually (see below) after fixing credentials without re-running the full setup.

## What was removed

`templates/workflow-pages.yml` and the dogfood `.github/workflows/docs-pages.yml` both had the `enablement: true` block removed as part of CCE-82 (2026-06-02). Any host onboarded with an older plugin version may still have that field in its workflow file. It is harmless but inert; remove it to avoid confusion.

## Manual recovery

If you onboarded a host before this fix and Pages is not enabled, run:

```bash
gh api -X POST repos/{owner}/{repo}/pages -f build_type=workflow
```

A 201 response means Pages is now bootstrapped. A 409 means it was already enabled. Both are good states; the next deploy will succeed.

You need `gh` authenticated with an account that has admin access to the repo. The same credential the setup skill uses.

## Reference

- **CCE-82** — the fix (2026-06-02)
- **CCE-81** — the incident (`theoju/claude-code-self-assessment` PR #121)
- `scripts/enable_pages.py` — the bootstrap helper
- `skills/engineering-docs-agent-setup` step 6c — the invocation site
- `templates/workflow-pages.yml` — the workflow template (no `enablement: true`)
