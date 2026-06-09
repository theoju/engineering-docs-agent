---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/103
synthesized_into: []
---

# GitHub Pages Bootstrap

GitHub Pages must be bootstrapped once before the docs-pages workflow can publish to it. This page explains why the workflow itself cannot do this, how the setup skill handles it, what can go wrong, and how to recover.

## Why the workflow cannot bootstrap Pages

The docs-pages workflow runs under `GITHUB_TOKEN`. The `permissions:` block in a workflow file can only **restrict** the default token's scopes — it cannot grant scopes the token was not issued with. Creating a GitHub Pages site requires the admin scope, which Actions' `GITHUB_TOKEN` never carries.

The `actions/configure-pages@v6` action exposes an `enablement: true` field that appears to do this. It does not. The field is silently ignored on first deploy, leaving the Pages site un-created. The `templates/workflow-pages.yml` template does **not** include this field.

## How the setup skill bootstraps Pages

The setup skill's step 6c calls `scripts/enable_pages.py` after committing the pages workflow. The script runs under your interactive `gh` auth, which has the admin scope needed to call `POST /repos/{owner}/{repo}/pages`.

```
scripts/enable_pages.py --repo <owner>/<repo>
```

The script wraps `gh api -X POST repos/{owner}/{repo}/pages -f build_type=workflow`. It handles four outcomes and exits 0 in every case so scaffolding never blocks on Pages bootstrap:

| Outcome | HTTP status | Behavior |
|---|---|---|
| Pages created | 201 | Logs success, exits 0 |
| Pages already exists | 409 | Logs idempotent skip, exits 0 |
| `gh` not on PATH | — | Logs warning, exits 0 |
| Any other error | non-201/409 | Logs warning with response body, exits 0 |

The graceful-exit contract means a failed bootstrap is visible in scaffolding output but never blocks the rest of setup. You must check the output to confirm Pages was created.

## Confirming the bootstrap succeeded

After `engineering-docs-agent-setup` completes, verify Pages is live:

```bash
gh api repos/{owner}/{repo}/pages --jq '.status'
# should print: built
```

If it prints `null` or returns a 404, the bootstrap did not complete. Run the script directly:

```bash
python3 scripts/enable_pages.py --repo <owner>/<repo>
```

Check the output for the failure reason, then re-trigger the first docs-agent workflow run once Pages is confirmed active.

## Manual recovery

If the script cannot be run (for example, `gh` is not authenticated with admin scope), bootstrap Pages from the GitHub UI:

1. Navigate to **Settings → Pages** in your repository.
2. Under **Source**, select **GitHub Actions**.
3. Save. Pages is now enabled and the docs-pages workflow can publish on its next run.

Alternatively, if you have admin scope via `gh`:

```bash
gh api -X POST repos/{owner}/{repo}/pages -f build_type=workflow
```

A 201 response means success. A 409 means Pages already exists — no action needed.

## References

- `scripts/enable_pages.py` — the bootstrap helper
- `skills/engineering-docs-agent-setup` step 6c — where it is invoked during setup
- `templates/workflow-pages.yml` — the pages workflow template (no `enablement:` field)
- CCE-81: originating incident (`theoju/claude-code-self-assessment` PR #121)
- CCE-82: fix landed 2026-06-02
