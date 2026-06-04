---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/87
synthesized_into: []
---

# content-validator

The content-validator subagent runs the lint suite on pages the orchestrator has just authored or edited. It returns a structured pass/fail result that the orchestrator uses to decide whether to include a page in the docs PR or surface a `lint_block` partial reason.

## Contract

The agent's full contract lives in `agents/content-validator.md`. The canonical input fields are:

| Field | Type | Description |
|---|---|---|
| `paths` | `list[str]` | Paths the orchestrator just authored or edited. |
| `config_path` | `str` | Absolute path to the host's `.engineering-docs-agent/config.yml`. |
| `voice_samples` | `object` | Voice sample bundle; only used when `voice_consistency` is tier-2 enabled. |
| `plugin_root` | `str` | Absolute path to the plugin checkout. Injected by the orchestrator at startup. |

The agent returns a JSON object with two arrays: `passed` (path + rules that passed) and `failed` (path + rule + severity + message).

## The `plugin_root` field

The lint runner lives inside the plugin, not inside the host repo. When the plugin is vendored — for example at `.docs-agent-plugin/` in CI via `templates/workflow-run.yml` — the relative path `scripts/lint/lint_runner.py` resolves to the host root, not the plugin root. Every Tier-1 lint rule crashes silently in that case.

The orchestrator resolves `_PLUGIN_ROOT` at startup (`scripts/orchestrator_runner.py:65`) using `Path(__file__).resolve().parent.parent`. That value is injected into the content-validator dispatch payload as a plain `str` field named `plugin_root`.

```python
# scripts/orchestrator_runner.py:65
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
```

The agent contract uses `<plugin_root>` as an angle-bracket marker — the same style as the existing `<config_path>` convention — when constructing the invocation:

```
python <plugin_root>/scripts/lint/lint_runner.py --config <config_path> --paths <paths...> --json
```

The agent substitutes the literal runtime value. It never assumes the runner is on `$PATH` or at a path relative to the current working directory.

## Why startup-time resolution matters

Resolving `_PLUGIN_ROOT` from `__file__` at import time is intentional. The orchestrator process starts in the host repo's working directory; `os.getcwd()` would return the host root, not the plugin root. Only `Path(__file__)` reliably points into the plugin's own `scripts/` directory regardless of where the process was launched from.

Serializing `plugin_root` as `str` rather than `Path` is equally intentional — JSON has no `Path` type, and the agent receives a string payload. Two regression tests in `tests/orchestrator/test_pipeline_integration.py` pin both properties: that `plugin_root` is present in the dispatch payload and that its type is `str`.

## Output schema

```json
{
  "passed": [{ "path": "docs/site-src/core/example.md", "rules": ["heading_hierarchy", "no_orphan"] }],
  "failed": [
    { "path": "docs/site-src/core/other.md", "rule": "frontmatter_required", "severity": "block", "message": "missing 'status' key" }
  ]
}
```

Severity `block` means the orchestrator excludes the page from the PR and records the failure in `partial_reasons`. Severity `warn` is informational — the page is included but the warning appears in the PR body.

## Failure mode

If `lint_runner.py` exits non-zero and its output is unparseable, the agent returns a synthetic failure covering all paths:

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

This surfaces as `lint_block` in `partial_reasons` rather than an unhandled exception, keeping the run's partial-PR visible in the branch rather than silently absent.
