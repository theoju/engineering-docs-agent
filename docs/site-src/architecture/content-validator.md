---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/87
synthesized_into: []
---

# content-validator

The `content-validator` subagent runs the plugin's lint suite on every page the `page-author` produces, then aggregates the results into a single structured pass/fail payload. The orchestrator blocks the docs-PR from opening if any `severity: block` failure is present.

## Inputs

The orchestrator dispatches content-validator with four fields:

| Field | Type | Description |
|---|---|---|
| `paths` | `string[]` | Absolute paths of the pages just authored or edited. |
| `config_path` | `string` | Path to the host's `.engineering-docs-agent/config.yml`. |
| `voice_samples` | bundle | Passed through only when `voice_consistency` is enabled (Tier 2). |
| `plugin_root` | `string` | Absolute path to the plugin checkout — not host-relative. See §Plugin root below. |

The full contract is in `agents/content-validator.md`.

## Plugin root

The lint runner lives at `<plugin_root>/scripts/lint/lint_runner.py`. The plugin is not guaranteed to sit at the host repo root — in CI on external host repos it is vendored at a separate path (e.g. `.docs-agent-plugin/`).

Before PR #87, the agent hardcoded `scripts/lint/lint_runner.py` as the path. That assumption is always wrong on vendored installs: the file does not exist at that relative path and every Tier-1 lint rule crashed. CCE-67 captured the root cause.

The fix is minimal: `scripts/orchestrator_runner.py` now appends `plugin_root` to every content-validator dispatch payload (line added in PR #87). The agent contract interpolates `<plugin_root>` when constructing the invocation:

```
python <plugin_root>/scripts/lint/lint_runner.py \
  --config <config_path> \
  --paths <paths...> \
  --json
```

The orchestrator derives `plugin_root` from `_PLUGIN_ROOT = Path(__file__).resolve().parent.parent` (`scripts/orchestrator_runner.py:64`). This value is correct whether the plugin lives at the host root or under any vendored prefix.

## Lint tiers

The host config at `.engineering-docs-agent/config.yml` controls which rules run.

- **Tier 1** (7 rules): enabled by default via `lint.tier1: default`. These are script-based checks that run without an LLM call.
- **Tier 2**: opt-in per rule. `voice_consistency` is the most common Tier-2 check; it requires the `voice_samples` bundle and uses an LLM comparison.
- **Tier 3**: opt-in per rule. Reserved for heavier semantic checks.

Each failing rule emits a `{path, rule, severity, message}` entry. Severity is either `block` (stops the PR) or `warn` (surfaced in PR body, does not block).

## Output

```json
{
  "passed": [{ "path": "docs/site-src/architecture/connectors.md", "rules": ["frontmatter_present", "h1_present"] }],
  "failed": [
    { "path": "docs/site-src/architecture/connectors.md", "rule": "no_todos", "severity": "warn", "message": "Found TODO at line 14." }
  ]
}
```

The full JSON schema is defined in `agents/schemas/content-validator.json`.

## Failure handling

If `lint_runner.py` exits non-zero and its output is unparseable, content-validator returns a single synthetic failure:

```json
{
  "failed": [{
    "path": "*",
    "rule": "lint_runner",
    "severity": "block",
    "message": "runner crashed at <plugin_root>/scripts/lint/lint_runner.py: <stderr>"
  }]
}
```

The orchestrator treats any `severity: block` entry as a hard stop and marks the run `partial: true` with a `lint_crash` partial reason in `.engineering-docs-agent/state.json`.

## Integration with the orchestrator

The orchestrator calls content-validator after every `page-author` dispatch, before building the PR body. The sequence inside `scripts/orchestrator_runner.py` is:

1. `page-author` writes or edits pages and returns their paths.
2. The orchestrator collects those paths and dispatches `content-validator` with `plugin_root` set.
3. If `failed` contains any `block`-severity entries, the orchestrator aborts the PR open step and adds the paths + messages to `partial_reasons`.
4. If all entries are `warn` or `passed`, the orchestrator continues and includes the warnings in the PR body.

Integration tests covering the vendored-path scenario were added alongside PR #87. They use a fixture host layout where the plugin is rooted at `.docs-agent-plugin/` rather than the repo root, confirming that the `plugin_root` substitution resolves correctly.
