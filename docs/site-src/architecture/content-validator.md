---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/87
synthesized_into: []
---

# Content Validator

The content-validator is the subagent responsible for running tiered lint rules against every page the agent authors or edits during a nightly run. It receives candidate file paths and returns a structured list of lint findings that the orchestrator uses to decide whether a docs-update PR is blocked, partially blocked, or clean.

## What the agent does

For each file in its input set, the content-validator invokes `lint_runner.py` and collects its JSON output. It maps rule severity to the three tiers — Tier-1 (blocking by default), Tier-2 (warning), Tier-3 (informational) — and emits a `lint_block` signal back to the orchestrator when any Tier-1 rule fires. The orchestrator surfaces `lint_block` in `partial_reasons` in `.engineering-docs-agent/state.json` so the operational gap is visible, not silent.

## Plugin-root path resolution (CCE-67)

Before PR #87, the agent constructed its lint invocation like this:

```
python scripts/lint/lint_runner.py --config <config_path> --paths <files> --json
```

This path is correct when the plugin lives at the host repo root — the default layout for local development and dogfood. It breaks as soon as you vendor the plugin at `.docs-agent-plugin/` in CI, which is the standard convention for host onboarding. In that layout, `scripts/lint/lint_runner.py` resolves against the host repo root and does not exist, so every Tier-1 rule crashed silently and the orchestrator marked the run `partial`.

The fix has two parts:

1. **Orchestrator side.** `orchestrator_runner.py` now includes `plugin_root` in every dispatch payload. The value is `_PLUGIN_ROOT`, which resolves to the directory containing the plugin's own `scripts/` tree regardless of where the plugin is vendored.

2. **Agent contract side.** The agent contract in `agents/content-validator.md` now specifies that the lint invocation must interpolate `<plugin_root>` before building the command:

   ```
   python <plugin_root>/scripts/lint/lint_runner.py --config <config_path> --paths <files> --json
   ```

The agent must not fall back to a bare `scripts/` path. If `plugin_root` is absent from the dispatch payload, the agent returns an error rather than guessing.

## Dispatch payload contract

The orchestrator sends:

| Field | Type | Required | Description |
|---|---|---|---|
| `files` | `string[]` | yes | Repo-relative paths of files to lint. |
| `config_path` | `string` | yes | Path to `.engineering-docs-agent/config.yml` for the host. |
| `plugin_root` | `string` | yes | Absolute path to the plugin's root directory. Interpolated into the lint runner invocation. |
| `lens` | `string` | yes | Active lens name, used to load tier settings from config. |

The agent's JSON output schema is in `agents/schemas/content-validator-output.json`. The `lint_block` boolean and `findings` array are the fields the orchestrator reads.

## Tier configuration

Tier-1 rules run by default on every host. Enable Tier-2 or Tier-3 rules per-rule in your host config:

```yaml
lint:
  tier1: default       # all 7 rules; cannot be disabled
  tier2:
    missing-summary: warn
  tier3:
    link-freshness: info
```

When `lint.tier1` is absent from the host config, the agent applies `default` — all 7 Tier-1 rules active. This matches the behavior before CCE-67 for hosts at root layout; the fix only affects the invocation path, not the rule set.

## Integration test coverage

A pipeline integration test (`tests/integration/test_content_validator_plugin_root.py`) covers the `plugin_root` field end-to-end: it sets up a fixture host with the plugin vendored at `.docs-agent-plugin/`, dispatches the agent with a known-bad markdown file, and asserts that `lint_block: true` appears in the output. Before the fix, this test failed because the lint runner was never reached.

## Related

- `agents/content-validator.md` — canonical input/output contract
- `agents/schemas/content-validator-output.json` — JSON schema for output
- `scripts/lint/lint_runner.py` — the lint runner the agent invokes
- `orchestrator_runner.py` — adds `plugin_root` to every dispatch payload (CCE-67)
- [Operations: Plugin Vendoring](../operations/plugin-vendoring.md) — how and where CI vendors the plugin on host repos
