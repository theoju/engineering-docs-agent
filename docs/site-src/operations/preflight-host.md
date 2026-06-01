---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
---

# Preflight Host Check

`scripts/preflight_host.py` is a read-only CLI that validates a host repo before you run the full setup skill. It runs setup discovery, prints the config the setup skill would write, lists the required secrets and variables, and surfaces any warnings. It does not modify the host repo.

Run it from the plugin root against any host:

```bash
python scripts/preflight_host.py --repo-root /path/to/host
```

For machine-readable output, pass `--format json`:

```bash
python scripts/preflight_host.py --repo-root /path/to/host --format json
```

## What the report contains

The text report has five sections.

**Discovery** shows what `setup_discover.discover()` found: framework, source dir, lens paths, CI system, Python package root, toolchain (Node/Python), and Jira hints.

**Proposed config** shows the `.engineering-docs-agent/config.yml` the setup skill would write, derived entirely from discovery. Notification and lint blocks are stubbed with safe defaults — the setup skill prompts you for the real values later. Review this to catch path or framework misdetections before they propagate.

**Secrets checklist** lists every `secrets.X` reference in `templates/workflow-run.yml`, deduplicated and sorted. Two secrets are required; the rest are optional:

| Secret | Required |
| ------ | -------- |
| `CLAUDE_CODE_OAUTH_TOKEN` | yes |
| `DOCS_AGENT_APP_PRIVATE_KEY` | yes |

Set these in **Settings → Secrets and variables → Actions** on the host repo before running the nightly workflow.

**Variables checklist** lists required repo Variables (separate from Secrets). Two are always required:

| Variable | Notes |
| -------- | ----- |
| `DOCS_AGENT_APP_CLIENT_ID` | OAuth Client ID for the GitHub App (`Iv1.xxx` or `Iv23li…` format) |
| `JIRA_EMAIL` | Basic-auth username for Atlassian — a public identifier, not a credential |

Set these in **Settings → Secrets and variables → Actions → Variables**.

**Warnings** are emitted when discovery detects a condition that needs operator attention. See the section below.

## Warning codes

### `framework_none`

No `mkdocs.yml` or `docusaurus.config.*` was found at the repo root. The config writes `framework: none`. The `framework_build` lint rule and the publish-verifier skip cleanly; PR summaries, page authoring, and what's-new updates run normally. If you want strict build-time link checking, scaffold mkdocs (`mkdocs init`) and re-run preflight.

Severity: `info`. Not a blocker.

### `pages_not_auto_scaffolded`

Detected `framework: docusaurus` but the host is not configured for GitHub Pages auto-scaffolding. Set `publishing.build_command` (e.g. `npm run build`) and `publishing.site_dir` (e.g. `build`) in `config.yml` to enable.

Severity: `warn`. The nightly run proceeds but publish verification is skipped until you wire up these fields.

### `node_only_host`

Node detected with no Python package. This is the expected shape for JS/TS hosts such as Docusaurus repos. The orchestrator runs Python from `.docs-agent-plugin/` — the plugin's bundled interpreter, not the host's. No action required.

Severity: `info`.

## JS/TS hosts

PR #83 (CCE-57) extended `setup_discover.detect_toolchain()` to detect Node/Docusaurus repos. Preflight is the recommended first step when onboarding any JS/TS host because the `node_only_host` warning confirms detection fired correctly and the proposed config path aligns with the Docusaurus `docs/` convention.

Run preflight, review the proposed config and warnings, provision the secrets and variables, then invoke the setup skill:

```bash
# 1. Check detection and proposed config
python scripts/preflight_host.py --repo-root /path/to/js-host

# 2. Provision secrets + variables in GitHub repo settings (see checklists above)

# 3. Run the setup skill
claude /engineering-docs-agent-setup
```

## Exit codes

| Code | Meaning |
| ---- | ------- |
| `0` | Report built successfully |
| `1` | `--repo-root` does not exist |

A non-zero exit from preflight means the path is wrong — fix it before running the setup skill.
