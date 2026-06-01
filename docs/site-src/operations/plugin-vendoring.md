---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/87
synthesized_into: []
---

# Plugin Vendoring

The engineering-docs-agent plugin can be installed at an arbitrary prefix on any host repo — not just at the repo root. This page explains how vendoring works, what changed in PR #87 to make the plugin path-agnostic, and what you need to know if you install the plugin under a custom directory.

## What "vendoring" means here

When you install the plugin via `claude plugin install`, Claude Code resolves the plugin's scripts relative to the installation directory. On the dogfood host that directory is the repo root (`./`), so `scripts/lint/lint_runner.py` resolves correctly. On external host repos onboarded through CI, the plugin is typically vendored under `.docs-agent-plugin/`, making the effective path `.docs-agent-plugin/scripts/lint/lint_runner.py`.

The plugin itself is the same code in both cases. Only the prefix changes.

## The hardcoded-path bug (CCE-67)

Before PR #87, the content-validator subagent hardcoded `scripts/lint/lint_runner.py` as the lint runner path in its dispatch invocation. On any host where the plugin was vendored at a prefix other than the repo root, that path did not exist and every Tier-1 lint rule crashed with a `FileNotFoundError`.

This blocked CI on all onboarded external hosts (CCE-57, CCE-58) and prevented CCE-64 (framework=none first-class config) from reaching production proof.

## The fix: `plugin_root` in the dispatch payload

PR #87 adds a `plugin_root` field to the orchestrator's dispatch payload. The change is a single line in `scripts/orchestrator_runner.py`: the orchestrator now computes `plugin_root` from its own `__file__` location (or from an explicit `--plugin-root` CLI flag) and passes it to every subagent invocation.

The `agents/content-validator.md` contract is updated to interpolate `<plugin_root>` when constructing the lint runner invocation:

```
<plugin_root>/scripts/lint/lint_runner.py --config <config_path> --paths <paths> --json
```

The content-validator reads `plugin_root` from the dispatch payload and substitutes it before invoking the lint runner. If `plugin_root` is absent from the payload (backward-compatibility with older orchestrators), the agent falls back to the unqualified `scripts/lint/lint_runner.py` path.

## What you need to do

**Nothing**, if you're upgrading from a version that predates PR #87. The orchestrator sets `plugin_root` automatically. Existing `config.yml` files do not need a new field.

If you are writing a custom orchestrator wrapper that dispatches subagents directly, add `plugin_root` to your dispatch payload:

```json
{
  "plugin_root": "/absolute/path/to/plugin/installation",
  ...
}
```

The value must be an absolute path to the directory that contains the `scripts/` and `agents/` subdirectories.

## Verifying the fix

Run the orchestrator against your host repo with `DOCS_AGENT_DEBUG_DIR` set:

```bash
DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

In the debug output for the `content-validator` invocation, confirm that the `lint_runner` command references the correct absolute path to `scripts/lint/lint_runner.py`. A path starting with `.docs-agent-plugin/` or `/` (not a bare `scripts/`) confirms the fix is active.

## Integration tests

PR #87 adds integration tests covering the vendored-path scenario. The fixtures simulate a host repo where the plugin is installed at `.docs-agent-plugin/` and assert that the lint runner invocation uses the resolved absolute path. Run the full suite with:

```bash
python3 -m pytest
```

The vendored-path tests are in the standard non-live suite — no `-m live` flag or network access required.
