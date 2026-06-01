---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/87
synthesized_into: []
---

# content-validator

The content-validator subagent runs the plugin's lint suite against every page the orchestrator authors or edits in a given nightly run, then optionally applies an LLM-based voice-consistency check (Tier 2). It is the last mandatory stage before the orchestrator commits authored pages to the docs-agent branch.

## Inputs

The orchestrator dispatches content-validator with four fields:

| Field | Type | Description |
| --- | --- | --- |
| `paths` | `string[]` | Absolute paths to the pages just authored or edited. |
| `config_path` | `string` | Absolute path to the host's `.engineering-docs-agent/config.yml`. |
| `voice_samples` | `object` | Voice sample bundle passed through from the nightly run. Used only when `voice_consistency` is enabled in Tier 2. |
| `plugin_root` | `string` | Absolute path to the plugin checkout. The lint runner lives at `<plugin_root>/scripts/lint/lint_runner.py`. |

The `plugin_root` field is critical. It is resolved by the orchestrator from `_PLUGIN_ROOT` in `scripts/orchestrator_runner.py:64`, which uses `Path(__file__).resolve().parent.parent`. This gives the correct absolute path regardless of where the plugin is vendored on a given host.

## The plugin_root interpolation pattern

The plugin ships as a Claude Code plugin. Hosts install it in two layouts:

- **Development / dogfood**: `scripts/` is at the repo root. `plugin_root` resolves to the repo root, so `lint_runner.py` is at `<plugin_root>/scripts/lint/lint_runner.py`.
- **Vendored CI**: the plugin is installed at `.docs-agent-plugin/` inside the host repo. `plugin_root` resolves to `.docs-agent-plugin/`, so `lint_runner.py` is at `.docs-agent-plugin/scripts/lint/lint_runner.py`.

Prior to PR #87, the agent's prompt in `agents/content-validator.md` invoked `python scripts/lint/lint_runner.py` as a bare relative path. That worked in the development layout only. On every vendored host — including CCSA and ADIS, onboarded in CCE-57/CCE-58 — the invocation resolved against the host repo root, found no `scripts/` directory there, and crashed with `No such file or directory`. The crash produced `lint_block: lint_runner crashed: No such file or directory` in `partial_reasons` and silently skipped all Tier-1 lint rules.

The fix uses the angle-bracket marker convention already present in `agents/content-validator.md`: the prompt now says `python <plugin_root>/scripts/lint/lint_runner.py`, and the orchestrator injects the resolved `plugin_root` string into the dispatch payload at `scripts/orchestrator_runner.py:1200`. The agent substitutes the literal value at runtime. This is the same pattern used for other path interpolations in the agents directory.

## Output

The agent returns a JSON object with two arrays:

```json
{
  "passed": [{ "path": "...", "rules": ["..."] }],
  "failed": [
    { "path": "...", "rule": "...", "message": "...", "severity": "block" }
  ]
}
```

`severity` is either `"block"` or `"warn"`. The orchestrator acts on `"block"` failures: it reverts the authored page (via `git checkout HEAD -- <path>` for edits, or `unlink` for new creates) and records the block reason in `partial_reasons`.

The full JSON schema is in `agents/schemas/content-validator.json`.

## Procedure

1. Run `python <plugin_root>/scripts/lint/lint_runner.py --config <config_path> --paths <paths...> --json`. Do not assume the runner is on `$PATH` or at a relative path. Quote `plugin_root` if it contains spaces.
2. Parse the aggregated output. Extract pass/fail per path with severity.
3. If `voice_consistency` is enabled in config and not implemented as a script, perform the LLM check: compare each page's prose against `voice_samples`; flag mismatches as `severity: block`.
4. Return the structured response.

## Failure handling

If `lint_runner.py` exits non-zero and its output is unparseable, the agent returns:

```json
{
  "failed": [{
    "path": "*",
    "rule": "lint_runner",
    "message": "runner crashed at <plugin_root>/scripts/lint/lint_runner.py: <stderr>",
    "severity": "block"
  }]
}
```

The orchestrator treats a `None` return from `dispatch_validated` (dispatch-level failure) as equivalent to `{"failed": []}` — it records `content_validator_invalid: returned None` in `partial_reasons` and continues without reverting pages. This is intentional: a validator crash is a gap, not a reason to discard authored content.

## Tier-1 lint rules

Tier-1 rules are enabled by default for all hosts via `lint.tier1: default` in the host config. Seven rules are currently defined. All of them were unreachable on vendored hosts before PR #87. After the fix, they execute correctly on every layout.

See `scripts/lint/` for individual rule implementations and `scripts/lint/lint_runner.py` for the runner entrypoint.

## Relationship to the orchestrator

The orchestrator dispatches content-validator only after at least one page has been authored (`authored` list is non-empty). The dispatch site is `scripts/orchestrator_runner.py:1192`. The `plugin_root` value injected there is the same `_PLUGIN_ROOT` constant used throughout the orchestrator for resolving plugin-internal paths.
