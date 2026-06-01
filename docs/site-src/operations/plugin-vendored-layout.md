---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/87
synthesized_into: []
---

# Plugin vendored layout

When the engineering-docs-agent runs in CI, the plugin is not checked out at the host repo root. It is vendored at `.docs-agent-plugin/` inside the host repo's workspace. This page describes what that means in practice and what the orchestrator does to stay deployment-agnostic.

## How the plugin is placed in CI

The nightly workflow template (`templates/workflow-run.yml:40,52`) checks out the plugin into `.docs-agent-plugin/` as a separate step before invoking the orchestrator. This keeps the plugin's files physically separate from the host repo's own tree.

In local development — including the dogfood host — you typically run the orchestrator from the plugin's own checkout, so paths like `scripts/lint/lint_runner.py` resolve correctly by accident. In CI they do not: the host repo root contains no `scripts/` directory from the plugin.

## How the orchestrator resolves its own root

The orchestrator resolves its installation path at startup in `scripts/orchestrator_runner.py:64`:

```python
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
```

This value is the absolute path to the plugin checkout — whether that is `/path/to/host/.docs-agent-plugin/`, a local development clone, or any other location. The orchestrator then forwards `plugin_root` in every subagent dispatch payload that needs to reference plugin-owned files.

No hardcoded path assumptions survive into the subagent layer. Each agent uses angle-bracket interpolation (`<plugin_root>`) to construct file references, matching the same convention already used for `<config_path>`.

## What broke before this was wired up

Before PR #87, the content-validator subagent used a host-relative path to find `lint_runner.py`. In CI, that path resolved against the host repo root and found nothing. Every Tier-1 lint rule crashed. The orchestrator recorded `lint_block` in `partial_reasons` and the run surfaced as `partial: true` — but the underlying cause was invisible in the PR body. Validation was silently skipped on every nightly CI run.

The symptom was surfaced by CCE-41's forensics and partial-PR design. The fix is described in detail on the [content-validator architecture page](../architecture/content-validator.md).

## Implications for adding new plugin-owned scripts

If a subagent needs to invoke a script that lives inside the plugin (under `scripts/`, `agents/`, or similar), use `<plugin_root>` interpolation in the agent contract — not a relative path and not an assumption about `cwd`. The orchestrator forwards `plugin_root` in every content-validator dispatch; if you are adding a new subagent that needs the same, wire it the same way.

Do not use `os.getcwd()` or a path relative to the subprocess working directory to locate plugin files. The working directory in CI is the host repo root, not the plugin root.

## Deployment layouts at a glance

| Context | Plugin location | `_PLUGIN_ROOT` resolves to |
| --- | --- | --- |
| CI (vendored) | `<host-repo>/.docs-agent-plugin/` | Absolute path under `.docs-agent-plugin/` |
| Local dev (dogfood) | Repo root (the plugin _is_ the host) | Repo root |
| Local dev (external host) | Wherever you cloned the plugin | Clone path |

The orchestrator's `Path(__file__).resolve().parent.parent` derivation works correctly in all three cases because `orchestrator_runner.py` always lives at `scripts/orchestrator_runner.py` inside the plugin tree.

## Pending changes

CCE-66 (migrating from `actions/create-github-app-token@v3` to the client-id pattern in `templates/workflow-run.yml`) is still in progress. That change modifies the workflow steps around the plugin checkout. Once it lands, verify that the `.docs-agent-plugin/` checkout step and `plugin_root` forwarding still align correctly.
