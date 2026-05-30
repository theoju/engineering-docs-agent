---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
---

# Preflight Host

`scripts/preflight_host.py` is a read-only CLI that checks whether a host repo is ready for the engineering-docs-agent plugin before you commit to the full install. Run it against any repo — Python, JS/TS, or otherwise — and it prints everything you need to review in one pass.

## What the preflight CLI outputs

The CLI produces four sections in order:

1. **Discovery output** — what `setup_discover.py` found: repo root, detected toolchain (Python / Node / Bun / Deno), Docusaurus presence, existing config files.
2. **Proposed config** — a rendered `.engineering-docs-agent/config.yml` block based on the discovered layout. Review this before running setup.
3. **Rendered workflow** — the `templates/workflow-run.yml` expanded with the correct plugin checkout path and run command for this host. Confirm it matches your repo's CI conventions.
4. **Secrets checklist** — the exact secret names the workflow expects. Tick them off in your repo's Settings → Secrets before the first nightly run.

Nothing is written to disk. The preflight command is safe to run multiple times.

## Usage

Run from the host repo root:

```bash
python scripts/preflight_host.py --repo-root /path/to/host-repo
```

Omit `--repo-root` to use the current directory:

```bash
cd /path/to/host-repo
python /path/to/plugin/scripts/preflight_host.py
```

The script exits 0 on success. Non-zero exit means discovery failed hard enough that setup would also fail — check the error output before proceeding.

## Toolchain detection

The preflight CLI calls `detect_toolchain()` in `scripts/setup_discover.py`, which checks for:

- `package.json` presence → Node host candidate.
- `bun.lockb` or `bun` in `package.json` scripts → Bun.
- `deno.json` or `deno.jsonc` → Deno.
- `docusaurus.config.js` / `docusaurus.config.ts` in `package.json` dependencies → Docusaurus framework.
- `setup.py`, `pyproject.toml`, or `requirements.txt` → Python host.

Detection results flow into `discover()` and appear verbatim in the "Discovery output" section. If detection produces an unexpected toolchain or `unknown`, fix the host layout before running setup.

## Secrets checklist

The rendered checklist lists every secret the workflow reads. For most hosts, these are:

| Secret | Purpose |
|--------|---------|
| `CLAUDE_CODE_OAUTH_TOKEN` | Authenticates the Claude CLI inside the nightly workflow. |
| `GH_TOKEN` | Allows the workflow to open the docs-update PR. |
| `JIRA_EMAIL` | Optional. Required only if `sources.jira.enabled: true`. |
| `JIRA_API_TOKEN` | Optional. Paired with `JIRA_EMAIL` for Jira enrichment. |

Add each secret in the host repo's **Settings → Secrets and variables → Actions** before merging the workflow file.

## Relation to the setup guide

The preflight CLI is a diagnostic companion to the full install walkthrough in `docs/site-src/setup-guide.md`. Run preflight first to surface any detection or config issues; then follow the setup guide for the App install, branch protection, and smoke-test steps that require user interaction.

## Background

PR #83 (CCE-57) introduced `scripts/preflight_host.py` alongside toolchain detection and a JS/Docusaurus fixture suite. Before this tool existed, operators had to mentally trace `setup_discover.py` output and manually verify the workflow template — both error-prone steps that blocked every non-dogfood host onboarding. The preflight CLI makes the pre-install state explicit and auditable.
