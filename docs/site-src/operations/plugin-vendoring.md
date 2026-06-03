---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/87
synthesized_into: []
---

# Plugin vendoring

When you install engineering-docs-agent into a CI environment, the plugin's files land somewhere on disk — often a subdirectory of the host repo rather than a system-wide path. This page explains how to tell the orchestrator where the plugin lives so that subagents resolve internal scripts correctly.

## The vendored layout

A common CI install pattern places the plugin at `.docs-agent-plugin/` inside the host repo:

```
my-host-repo/
  .docs-agent-plugin/        ← plugin source
    scripts/
      lint/
        lint_runner.py
    agents/
    ...
  .engineering-docs-agent/
    config.yml
    state.json
```

Without explicit configuration, the `content-validator` subagent invokes `python scripts/lint/lint_runner.py` relative to the process working directory — the host repo root. That path does not exist in the host repo. Every Tier-1 lint rule crashes.

## Configuring `plugin_root`

Set `plugin_root` in your `.engineering-docs-agent/config.yml` to the absolute or repo-relative path of the plugin install:

```yaml
plugin_root: .docs-agent-plugin
```

The orchestrator reads this value at startup (`orchestrator_runner.py`) and injects it into every subagent dispatch payload. The `content-validator` subagent constructs the lint runner path as `{plugin_root}/scripts/lint/lint_runner.py` rather than assuming the script sits at the repo root.

If you omit `plugin_root`, the orchestrator defaults to the directory containing `orchestrator_runner.py` itself — correct for local development from a checkout, wrong for a vendored CI install.

## Onboarding a new CI host

1. Install the plugin into a stable path (e.g., `.docs-agent-plugin/`). Pin the commit SHA or release tag so runs are reproducible.
2. Add `plugin_root: .docs-agent-plugin` to `.engineering-docs-agent/config.yml`.
3. Run a dry-run pass to confirm the content-validator picks up lint rules without path errors:

   ```bash
   python3 .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root . --no-pr
   ```

4. Check the run output for `content-validator` results. A successful pass logs the absolute path resolved for `lint_runner.py`. A misconfigured path produces a `ModuleNotFoundError` or `FileNotFoundError` on the first linted file.

## How `plugin_root` flows through dispatch

The orchestrator populates `plugin_root` in the dispatch payload constructed in `orchestrator_runner.py`. Each subagent receives the payload as its input JSON. The `content-validator` agent reads `plugin_root` from that payload and interpolates it when building the `python <plugin_root>/scripts/lint/lint_runner.py` command line.

`plugin_root` is a runtime value, not a compile-time constant. You can point it at a local development checkout or a pinned vendored copy without touching the agent definition.

## Integration tests

PR #87 added integration tests covering the vendored-layout code path. The test fixtures place the plugin at a non-standard path and assert that the content-validator resolves `lint_runner.py` correctly. Run them with:

```bash
python3 -m pytest tests/ -k "vendored"
```

These tests use the fixture-driven dry-run path — no real Claude CLI dispatch, no cost.
