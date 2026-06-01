---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/87
synthesized_into: []
---

# content-validator

The content-validator subagent runs after the page-author and page-editor subagents finish. It lints every authored or edited page and returns a structured pass/fail result. The orchestrator reads that result and records `lint_block` in `partial_reasons` for any blocking failure.

## What it does

The validator runs `scripts/lint/lint_runner.py` with the host config and a list of file paths. It then optionally performs LLM-based voice-consistency checks if `tier2.voice_consistency` is enabled in the host config. Results are aggregated into two lists — `passed` and `failed` — each item tied to a specific file path and rule.

The agent contract is in `agents/content-validator.md`. The output schema is in `agents/schemas/content-validator.json`.

## The `plugin_root` parameter

The validator receives a `plugin_root` input — the absolute path to the engineering-docs-agent plugin checkout. It constructs the lint runner path as `<plugin_root>/scripts/lint/lint_runner.py`.

Before PR #87, the agent used a host-relative path to reach the lint runner. That worked when the plugin was checked out at the repo root (local development, the dogfood host), but broke silently in CI.

## Why the host-relative path broke in CI

The plugin is vendored at `.docs-agent-plugin/` in CI via `templates/workflow-run.yml:40,52`. A host-relative path like `scripts/lint/lint_runner.py` resolves against the host repo root, not the plugin checkout. In CI, no such path exists. Every Tier-1 lint rule crashed; the orchestrator recorded `lint_block` in `partial_reasons` and moved on. Validation was silently skipped on every nightly run.

## How the fix works

The orchestrator resolves `_PLUGIN_ROOT` at startup in `scripts/orchestrator_runner.py:64`:

```python
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
```

It forwards this value as `plugin_root` in every content-validator dispatch payload. The agent contract uses angle-bracket interpolation — `<plugin_root>` — matching the same convention already used for `<config_path>`. The validator substitutes the literal value when building the shell command.

This approach is deployment-agnostic. Whether the plugin lives at the repo root, at `.docs-agent-plugin/`, or at any other absolute path, the lint runner resolves correctly.

## Effect on linting

With `plugin_root` wired correctly, the full Tier-1 lint suite runs on every nightly authoring pass. The `framework=none` handling in `scripts/lint/framework_build.py:51` and mkdocs build validation on onboarded hosts (CCSA, ADIS) can now exercise the full lint path. This was a blocking gap for CCE-64 end-to-end production proof.

## Failure handling

If `lint_runner.py` exits non-zero and the output is unparseable, the validator returns a single `failed` entry with `path: "*"`, `rule: "lint_runner"`, `severity: "block"`, and the stderr in the message. The orchestrator treats this the same as a normal lint block — it records `lint_block` in `partial_reasons` and the run surfaces as `partial: true` in the docs-agent PR body.
