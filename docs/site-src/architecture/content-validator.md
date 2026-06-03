---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/87
synthesized_into: []
---

# content-validator

The `content-validator` subagent runs the full lint suite on every page the orchestrator authors or edits in a given nightly run. It executes `scripts/lint/lint_runner.py`, aggregates results across all Tier-1 (and optionally Tier-2/Tier-3) rules, and returns a structured pass/fail report. If any rule fires at `severity: block`, the orchestrator reverts that page before opening the PR.

## Role in the pipeline

After `page-author` writes or edits pages, the orchestrator collects their paths into an `authored` list and dispatches a single `content-validator` call covering all of them. The validator runs synchronously in the pipeline; the orchestrator does not open a PR until validation completes or times out.

The agent's output schema (`agents/schemas/content-validator.json`) has two arrays: `passed` and `failed`. Each `failed` entry carries a `severity` of `"block"` or `"warn"`. Blocks cause the orchestrator to revert the file (`git checkout HEAD -- <path>` for edits, `unlink` for creates) and record a partial-reason. Warns are surfaced in the PR body but do not revert the file.

## `plugin_root` interpolation contract

The validator invokes `lint_runner.py` via a subshell Bash call. The path to that script is **not host-relative**: when the plugin is installed as a vendored subdirectory (e.g., `.docs-agent-plugin/` in CI), `scripts/lint/lint_runner.py` does not exist relative to the host repo root.

To resolve this, the orchestrator threads a `plugin_root` value into the dispatch payload (`orchestrator_runner.py:1201`):

```python
"plugin_root": str(_PLUGIN_ROOT),
```

`_PLUGIN_ROOT` is computed once at module load as the directory two levels above `orchestrator_runner.py` itself (`orchestrator_runner.py:65`):

```python
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
```

This is always the plugin's install directory, regardless of where the host repo lives.

Inside `agents/content-validator.md`, the lint runner invocation uses the interpolated value directly:

```
python <plugin_root>/scripts/lint/lint_runner.py --config <config_path> --paths <paths...> --json
```

The agent prompt instructs the validator to substitute `plugin_root` literally — not to assume the runner is on `$PATH` or at a relative path.

## What broke before this fix

Prior to PR #87, the `content-validator` agent omitted `plugin_root` from its inputs and invoked the runner as `python scripts/lint/lint_runner.py`. On freshly-onboarded host repos (CCE-57, CCE-58) where the plugin is vendored at `.docs-agent-plugin/`, the relative path resolves against the host repo root. No `scripts/lint/lint_runner.py` exists there. Every Tier-1 lint check crashed, causing `content_validator_invalid` partial-reasons on every CI run for those hosts.

The fix is in two places: `agents/content-validator.md` (adds `plugin_root` to the Inputs section and uses `<plugin_root>/...` in the Procedure step) and `orchestrator_runner.py` (adds `"plugin_root": str(_PLUGIN_ROOT)` to the dispatch payload). New integration tests in the vendored-layout fixture cover this code path.

## Failure handling

If `lint_runner.py` exits non-zero and its output is unparseable, the validator returns a single `failed` entry with `path: "*"`, `rule: "lint_runner"`, `severity: "block"`, and a message containing the stderr from the runner. The orchestrator treats this as a block on all authored paths for that run.

If the orchestrator itself receives `None` back from `dispatch_validated("content-validator", ...)`, it records `content_validator_invalid: returned None` as a partial-reason and continues without reverting any file (the conservative path: a broken validator does not suppress the PR).

## Lint tiers

The runner's default Tier-1 set is nine rules (`lint_runner.py:21`):

- `frontmatter_schema`
- `internal_links`
- `markdown_hygiene_lang`
- `markdown_hygiene_structure`
- `footnotes`
- `diagrams`
- `framework_build`
- `stub_redirect`
- `description_quality`

Tier-2 and Tier-3 rules are opt-in via the host's `.engineering-docs-agent/config.yml`. The `voice_consistency` check is the one Tier-2 rule that `lint_runner.py` does **not** handle — it is an LLM-based check performed directly by the `content-validator` agent when enabled in config (`agents/content-validator.md:Step 3`).
