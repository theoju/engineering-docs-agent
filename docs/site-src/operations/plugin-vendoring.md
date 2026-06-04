---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/87
synthesized_into: []
---

# Plugin vendoring

When the engineering-docs-agent runs in CI on a host repo, the plugin source is not on the host's `PATH` or at a well-known location. The setup skill copies the plugin into `.docs-agent-plugin/` at the host repo root. Every subagent that needs to invoke plugin scripts must use this path, not a path relative to CWD.

## Vendored layout

`templates/workflow-run.yml` provisions the nightly run workflow. It checks out the plugin at `.docs-agent-plugin/` before invoking the orchestrator:

```
.docs-agent-plugin/
  scripts/
    orchestrator_runner.py
    lint_runner.py
    ...
  agents/
  templates/
```

The host repo root (CWD during the workflow run) is the host's code and docs — not the plugin tree. Any subagent path that hardcodes `scripts/lint_runner.py` resolves against the wrong root and silently fails.

## Why `plugin_root` is resolved at startup

The orchestrator resolves `_PLUGIN_ROOT` once at startup in `scripts/orchestrator_runner.py:64` and injects it as a `plugin_root` string field in every dispatch payload. Two reasons this happens at startup rather than in each subagent:

1. **Single source of truth.** The orchestrator knows where it was invoked from; subagents receive a payload and have no reliable way to infer the plugin location from CWD.
2. **Serialization safety.** `plugin_root` is written as a `str`, not a `pathlib.Path`. Path objects do not round-trip cleanly through JSON; the regression tests in `tests/orchestrator/test_pipeline_integration.py` pin both the field's presence and its type.

## How subagents consume `plugin_root`

Subagent contracts use an angle-bracket marker convention: `<plugin_root>` expands to the injected value before the agent constructs any filesystem path. The content-validator contract (`agents/content-validator.md`) shows this for `lint_runner.py`:

```
<plugin_root>/scripts/lint_runner.py
```

This is the same style as the existing `<config_path>` marker in that contract. If you add a new subagent that shells out to a plugin script, follow this pattern — do not hardcode `scripts/` or `.docs-agent-plugin/scripts/` directly in the agent prompt.

## Failure mode: missing `plugin_root`

Before PR #87, every Tier-1 lint rule crashed silently in CI on onboarded hosts (CCSA and ADIS). The orchestrator surfaced `lint_block` in `partial_reasons` via the partial-PR design, but lint output was absent — not an error that blocked the PR, just a silent gap. If you see `lint_block` in `partial_reasons` with no accompanying lint results, check that `plugin_root` is present in the dispatch payload and resolves to the `.docs-agent-plugin/` subtree.

## Onboarding checklist for new hosts

When you onboard a new host repo:

1. Run `claude /engineering-docs-agent-setup` from the host root. The setup skill copies the plugin to `.docs-agent-plugin/` and writes the workflow files.
2. Confirm `.docs-agent-plugin/scripts/lint_runner.py` exists after setup completes.
3. Trigger a dry run (`python3 .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root . --no-pr`) and check that `plugin_root` appears in `.engineering-docs-agent/current_run.json`.
4. If lint results are absent from the first real run, inspect `partial_reasons` in `state.json`. A `lint_block` entry means the path resolution failed; re-run setup or check that the workflow checkout step is present in `.github/workflows/docs-agent-nightly.yml`.

The `current_run.json` file is gitignored and ephemeral — it is written on every state update and is the first place to look for diagnostics without waiting for a PR.
