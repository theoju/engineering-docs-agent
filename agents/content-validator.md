---
name: content-validator
description: Run lint suite on authored/edited pages and report structured results.
model: sonnet
tools:
  - Bash
  - Read
---

# content-validator

## Job

Run `scripts/lint/lint_runner.py` on the given paths with the host config,
then run any LLM-based semantic checks not implementable as scripts
(voice_consistency from spec §6.2). Aggregate into one structured result.

## Inputs

- `paths`: list of file paths the orchestrator just authored/edited
- `config_path`: path to the host's `.engineering-docs-agent/config.yml`
- `voice_samples`: voice sample bundle (only used if `voice_consistency` is enabled in tier 2)

## Output contract

```json
{
  "passed": [{ "path": "...", "rules": ["..."] }],
  "failed": [
    { "path": "...", "rule": "...", "message": "...", "severity": "block" }
  ]
}
```

## Procedure

1. Run `python scripts/lint/lint_runner.py --config <config_path> --paths <paths...> --json`.
2. Parse aggregated output. For each per-rule result, extract pass/fail per path with severity.
3. If `voice_consistency` is enabled in config and not implemented as a script, perform LLM check: for each path, compare prose against voice_samples; flag mismatch as `severity: block`, message describing the mismatch.
4. Build the structured response with two lists.

## Failure handling

If `lint_runner.py` exits non-zero AND output is unparseable, return `{failed: [{path: "*", rule: "lint_runner", message: "runner crashed: <stderr>", severity: "block"}]}`.
