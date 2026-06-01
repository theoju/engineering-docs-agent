---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
---

# Onboarding a New Host Repo

This runbook walks you through installing the engineering-docs-agent plugin on any host repository. It covers Python hosts, JS/TS hosts, and anything else `detect_toolchain()` can identify. Follow the steps in order.

## Before you start: pre-flight inspection

Run the read-only pre-flight inspector against your target host root:

```bash
python3 scripts/preflight_host.py --repo-root /path/to/host-repo
```

`preflight_host.py` never writes. It runs `setup_discover.py`'s `discover()` function and prints what it finds: language, toolchain, package manager, docs framework, and anything missing. Fix every flagged item before continuing.

For JS/TS hosts, `detect_toolchain()` checks for Node, Bun, Deno, npm/Yarn, and Docusaurus presence. If the pre-flight output is missing toolchain fields, the host environment needs attention before install.

## Step 1: Register and install the plugin

Run these commands from your **plugin clone**, not the host repo:

```bash
claude plugin marketplace add /path/to/engineering-docs-agent
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace
```

This makes all seven agents resolvable. The marketplace registration reads `.claude-plugin/marketplace.json`; the plugin manifest is at `.claude-plugin/plugin.json`.

Switch to your host repo root for all remaining steps.

## Step 2: Run the setup skill

```bash
claude /engineering-docs-agent-setup
```

The setup skill calls `discover()`, which now includes `detect_toolchain()`. JS/TS hosts get Node version, package manager, and Docusaurus presence detected automatically — you don't configure them by hand. The skill writes the initial `.engineering-docs-agent/config.yml` and `state.json` based on what it finds.

## Step 3: Verify the workflow template

The nightly workflow is installed at `.github/workflows/docs-agent-nightly.yml`. Confirm it vendors the plugin via `actions/checkout`, not a hardcoded path:

```yaml
- uses: actions/checkout@v4
  with:
    repository: theoju/engineering-docs-agent
    path: .docs-agent-plugin
```

Pre-PR-83 installs had a defect: the orchestrator was invoked as `python3 scripts/orchestrator_runner.py`, which assumes the plugin lives at the host root. That fails for every non-dogfood host. If you see that pattern, patch the invocation to:

```bash
python3 .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .
```

Or regenerate the workflow by re-running `claude /engineering-docs-agent-setup`.

## Step 4: Configure secrets

Add these to your host repo under **Settings → Secrets → Actions**:

| Secret | Required | Value |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Yes | OAuth token for the `claude` CLI |
| `JIRA_EMAIL` | No | Your Atlassian account email |
| `JIRA_API_TOKEN` | No | Atlassian Cloud API token (from `id.atlassian.com`) |

Jira secrets are optional. Without them the agent runs in partial mode: `jira_issues` will be `[]` and `partial: true` is set in `state.json` with `error: "jira_auth_missing"`. That gap surfaces in Slack/email notifications — it's visible, not silent.

## Step 5: Commit config and state

The setup skill produces two files you must commit:

- `.engineering-docs-agent/config.yml` — host config including `lens_paths`, `agent_editable_paths`, and source settings.
- `.engineering-docs-agent/state.json` — initial run state. `last_successful_run.head_sha` is set to your current HEAD and acts as the starting window for the first nightly run.

Commit both on a feature branch. Do not commit `.engineering-docs-agent/current_run.json` — it is gitignored ephemeral state.

Every `lens_paths` entry in `config.yml` must be covered by at least one `agent_editable_paths` glob. The config loader enforces this at boot via `_validate_lens_paths_are_editable` in `scripts/state_io.py`. A mismatch causes a hard failure at startup, not a silent skip.

## Step 6: Validate locally

From your host repo root:

```bash
python3 .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root . --no-pr
```

A clean dry-run writes `.engineering-docs-agent/current_run.json` and exits without errors. Open that file and confirm `partial_reasons` is empty. If it is not, the reasons tell you what to fix before the first real run.

For per-subagent diagnostics, set `DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug` before invoking. Raw subagent stdout lands there.

## Step 7: Merge and enable the nightly workflow

Merge your feature branch. The nightly workflow fires at 07:00 UTC automatically. To validate immediately:

```bash
gh workflow run docs-agent-nightly.yml -f reason="initial onboarding validation"
gh run watch
```

One run at a time per repo — concurrent invocations queue, they don't race on the same docs-agent branch.

## Step 8: Verify pages are live

After the first docs-agent PR merges, confirm the publish pipeline succeeded. Check your host's deploy workflow for a green run, then spot-check one generated page at the published URL to make sure the live site reflects the update.

## Toolchain detection reference

`detect_toolchain()` in `scripts/setup_discover.py` returns the following keys, all wired into the `discover()` output:

| Key | What it detects |
|---|---|
| `node_version` | Output of `node --version`, or `null` if Node is absent |
| `package_manager` | `"npm"`, `"yarn"`, `"bun"`, or `null` |
| `bun` | `true` if `bun` is on `PATH` |
| `deno` | `true` if `deno` is on `PATH` |
| `docusaurus` | `true` if `docusaurus.config.js` or `docusaurus.config.ts` is present |

The orchestrator uses these values to select the correct build command and docs-source path. You never set them manually; `discover()` computes them at setup time and at every run.
