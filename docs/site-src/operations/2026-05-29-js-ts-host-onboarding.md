---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
---

# Onboarding a JS/TypeScript (Docusaurus) Host

PR #83 (CCE-57) extends the plugin's setup path to support JS/TypeScript hosts running Docusaurus. Previously the setup assumed Python/MkDocs. This page covers what you need to do, what the plugin now handles automatically, and how to recover from every partial-mode failure.

## Prerequisites

Run `scripts/preflight_host.py` against your host repo before installing. It checks prerequisites and exits non-zero with a plain-English error if anything is missing.

```bash
python3 scripts/preflight_host.py --repo-root /path/to/your/host-repo
```

The script is read-only — it makes no changes. Fix any reported gaps before proceeding with install.

## What the plugin detects automatically

`scripts/setup_discover.py` now calls `detect_toolchain` early in setup. If it finds a `package.json` and a Docusaurus config (`docusaurus.config.js` or `docusaurus.config.ts`) at the repo root, it takes the JS/Docusaurus path. All subsequent setup steps — docs dir resolution, build command, publish target — are derived from that detection.

You don't configure the toolchain explicitly. Detection drives the path.

## CI workflow install (vendored sub-tree)

When you install the plugin as a Git sub-tree, `templates/workflow-run.yml` previously resolved the plugin's scripts relative to the repo root rather than the sub-tree anchor. PR #83 fixes this. If you installed before this fix, pull the updated template and re-commit your `.github/workflows/docs-agent-nightly.yml`.

## GITHUB_TOKEN limitations (CCE-45)

The nightly workflow runs with the default `GITHUB_TOKEN`. That token **cannot** open PRs that trigger other required-status workflows — a GitHub limitation, not a plugin bug. You have two options:

1. **Use a PAT.** Create a fine-grained Personal Access Token with `contents: write` and `pull-requests: write` on the host repo. Store it as `DOCS_AGENT_GH_TOKEN` and update the workflow `env` block to use it.
2. **Skip re-trigger.** If you don't need the docs PR to trigger your CI suite, the default `GITHUB_TOKEN` is fine. Mark the docs-agent PR branch as exempt from the required-status rule in branch protection.

The runbook at `docs/superpowers/specs/2026-05-29-cce57-onboard-runbook.md` has the exact branch-protection steps for each option.

## Partial-mode failure reference

Each failure below corresponds to a `partial_reasons` entry you'll see in `.engineering-docs-agent/state.json`.

### `toolchain_unknown`

`detect_toolchain` couldn't identify the repo as Python/MkDocs or JS/Docusaurus. Confirm `docusaurus.config.js` (or `.ts`) exists at the repo root and that `package.json` is present. Re-run preflight after adding the missing file.

### `docs_dir_not_found`

The Docusaurus docs directory wasn't found at the expected location (`docs/` by default). If your repo uses a non-standard path, set `site.docs_dir` explicitly in `.engineering-docs-agent/config.yml`.

### `workflow_template_missing`

The vendored workflow file wasn't found. Re-run the setup skill from your host repo root: `claude /engineering-docs-agent-setup`. It regenerates `.github/workflows/docs-agent-nightly.yml` from the current template.

### `jira_auth_missing`

Jira enrichment is enabled but `JIRA_EMAIL` / `JIRA_API_TOKEN` aren't set. The run continues without issue summaries and marks itself `partial: true`. Either set the env vars or disable Jira in config (`sources.jira.enabled: false`).

### `publish_verification_skipped`

The `deploy.yml` workflow target isn't configured or the workflow hasn't run yet. Set `publishing.verify_workflow` in config once your Docusaurus build workflow exists. Until then, the agent skips post-merge verification without failing the run.

## Testing the install

After setup, trigger a dry run locally to verify detection and path resolution:

```bash
python3 scripts/orchestrator_runner.py --repo-root /path/to/your/host-repo --no-pr
```

Check the output for `toolchain: js_docusaurus` in the logged detection block. If it shows `python_mkdocs`, preflight again — Docusaurus config files may be missing or misnamed.

## Unit test fixture

`tests/fixtures/setup_repos/js_docusaurus/` is the canonical minimal Docusaurus repo for plugin unit tests. If you're contributing changes to `setup_discover.py`, use this fixture rather than any live host repo.
