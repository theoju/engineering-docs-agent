---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/87
synthesized_into: []
---

# Plugin Vendoring in CI

How the engineering-docs-agent plugin is deployed in external host CI environments, and the path-resolution contract that makes lint invocations portable.

## The vendored-plugin layout

When you install the plugin into a host repo, CI clones the plugin into a separate directory alongside the host repo — not inside it. The conventional install path is `.docs-agent-plugin/` relative to the CI workspace root.

The host repo and the plugin checkout are siblings on disk:

```
<workspace>/
  <host-repo>/          ← your repo, checked out by the workflow
  .docs-agent-plugin/   ← plugin checkout, vendored by the nightly workflow
```

Nothing in the host repo contains `scripts/lint/lint_runner.py`. That file lives inside the plugin checkout. Any reference to `scripts/lint/lint_runner.py` from the host repo root is a broken path.

## How `plugin_root` is injected

The orchestrator computes `_PLUGIN_ROOT` at startup from its own `__file__` location:

```python
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
```

Because `orchestrator_runner.py` lives at `<plugin_root>/scripts/orchestrator_runner.py`, `parent.parent` resolves to the plugin checkout root regardless of where that checkout lives on the CI worker.

The orchestrator then injects `plugin_root` as a field in every content-validator dispatch payload before calling the subagent. The subagent never needs to infer the plugin location from the host environment.

## The content-validator contract

The `content-validator` subagent receives `plugin_root` as an explicit input (documented in `agents/content-validator.md`). It constructs the lint runner path as:

```
<plugin_root>/scripts/lint/lint_runner.py
```

This is an absolute path derived from the injected value — not relative to the host repo root, not relative to `$CWD`. The subagent must not fall back to a host-relative path if `plugin_root` is absent; missing `plugin_root` is a dispatch bug that should surface as an error, not silently produce a wrong path.

## What breaks without this guarantee

Before PR #87, the orchestrator did not inject `plugin_root`. The content-validator resolved `scripts/lint/lint_runner.py` relative to the host repo root. This worked in the dogfood repo (where the plugin lives at the repo root) but failed on every external host where the plugin is vendored at `.docs-agent-plugin/`.

Onboarding `theoju/claude-code-self-assessment` (CCE-57) and `theoju/advanced-data-import-system` (CCE-58) exposed this: CI exited with a `FileNotFoundError` on the lint invocation because the host root had no `scripts/lint/` directory.

## Confirming the layout in a new host

After installing the plugin into a new host, verify the vendoring layout with:

```bash
ls .docs-agent-plugin/scripts/lint/lint_runner.py
```

If that path does not exist, the plugin install step in your CI workflow is not vendoring correctly. Check the `plugin-install` step in `.github/workflows/docs-agent-nightly.yml` and confirm it is checking out the plugin into `.docs-agent-plugin/`, not into the host repo root or a subdirectory of it.

The `plugin_root` field in `.engineering-docs-agent/current_run.json` (written at the start of every run) shows the value the orchestrator resolved. Use it to diagnose path-resolution problems without re-running the full pipeline.
