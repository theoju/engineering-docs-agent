---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
---

# Workflow Run Template

`templates/workflow-run.yml` is the GitHub Actions workflow the setup skill copies to `.github/workflows/docs-agent-run.yml` on the host repo. It is the nightly trigger for the docs-agent orchestrator.

## What the template does

The workflow fires on two events: the daily cron at 07:00 UTC, and any PR merge to `main` that is not a `docs-agent/` branch itself. It runs on `ubuntu-latest` and vendors the plugin before invoking the orchestrator.

## P1 fix — generic host support (PR #83)

**If your host ran the old setup-skill output before PR #83, your workflow is broken for all non-dogfood hosts.** The original template hard-coded `scripts/orchestrator_runner.py` at the host repo root. That path only exists on the dogfood repo (`theoju/engineering-docs-agent`). Every other host got a `No such file or directory` error on the `Run orchestrator` step.

PR #83 fixed the template. The orchestrator step now runs from the vendored plugin checkout:

```yaml
- name: Check out engineering-docs-agent plugin
  uses: actions/checkout@v5
  with:
    repository: theoju/engineering-docs-agent
    ref: main
    path: .docs-agent-plugin
- name: Run orchestrator
  run: |
    python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .
```

The plugin is checked out into `.docs-agent-plugin/` on the runner workspace. The orchestrator is always invoked from there — never from the host repo root.

## If you installed before PR #83

Re-run the setup skill from your host repo's working directory:

```bash
claude /engineering-docs-agent-setup
```

The skill overwrites `.github/workflows/docs-agent-run.yml` with the fixed template. Commit and push the updated workflow. If the setup skill is not available, copy the current `templates/workflow-run.yml` from this repo manually and apply it.

Alternatively, edit your existing workflow directly: change the `Run orchestrator` step's `run:` command from:

```yaml
run: python scripts/orchestrator_runner.py --repo-root .
```

to:

```yaml
run: python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .
```

and add the plugin checkout step shown above before it.

## Full template reference

```yaml
name: docs-agent run

on:
  schedule:
    - cron: "0 7 * * *"
  pull_request:
    types: [closed]
    branches: [main]

concurrency:
  group: docs-agent-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: write
  pull-requests: write

jobs:
  run:
    if: github.event_name == 'schedule' || (github.event.pull_request.merged == true && !startsWith(github.head_ref, 'docs-agent/'))
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
      - name: Check out engineering-docs-agent plugin
        uses: actions/checkout@v5
        with:
          repository: theoju/engineering-docs-agent
          ref: main
          path: .docs-agent-plugin
      - name: Install plugin deps
        run: pip install pyyaml jsonschema
      - name: Install Claude Code CLI
        run: npm install -g @anthropic-ai/claude-code
      - name: Run orchestrator
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
        run: |
          python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .
```

The `ref: main` pin is intentional — versioned releases are not yet cut. Once a tag exists, pin to a tag or SHA here for reproducibility.

## Concurrency and triggers

The `concurrency` block serializes runs per `github.ref`. Concurrent invocations queue rather than race on the same `docs-agent/` branch. The `cancel-in-progress: true` setting cancels a queued run if a newer one arrives before the queued run starts.

The `pull_request` trigger fires on every merge to `main` except docs-agent merges. This gives near-real-time doc generation: when you merge a feature PR, the workflow fires within seconds and opens a `docs-agent/<date>` PR. If one already exists for today, the orchestrator appends a commit to it.

## Required secrets

| Secret | Required? |
|---|---|
| `ANTHROPIC_API_KEY` | Yes |
| `GITHUB_TOKEN` | Built-in; no action needed |
| `JIRA_API_TOKEN` | Only if Jira enrichment enabled |
| `SLACK_WEBHOOK_URL` | Only if Slack notifications enabled |

For the full secrets and variables checklist — including the GitHub App token wiring needed to trigger downstream CI on docs-agent PRs — see the [Setup Guide](../setup-guide.md).

## Pre-install diagnostics

Before running the setup skill, run `scripts/preflight_host.py` from the host repo root to see exactly what the setup skill would write:

```bash
python .docs-agent-plugin/scripts/preflight_host.py --repo-root .
```

The preflight CLI prints the discovery output, the config and workflow the setup skill would create, and a secrets checklist. It is read-only and makes no changes. See [preflight-host.md](preflight-host.md) for full usage.
