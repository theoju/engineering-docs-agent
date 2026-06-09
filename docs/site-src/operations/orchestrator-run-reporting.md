---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/98
synthesized_into: []
---

# Orchestrator Run Reporting

The orchestrator runner (`scripts/orchestrator_runner.py`) produces two complementary outputs at the end of every run: a guard on `state.json` that prevents noop runs from masquerading as forward progress, and a sentinel file that gives the calling GitHub Actions workflow a structured, parseable signal of what just happened.

## Noop guard on `state.json`

Before PR #98, every orchestrator run — even one where nothing had changed since the last successful run — would write back `last_successful_run.head_sha`. This blurred the line between genuine forward progress and idle cycles.

The runner now compares the current HEAD SHA against the SHA already recorded in `state.json`. If they match, `last_successful_run` is not advanced. The `state.json` mutation only occurs when the run actually processes new commits.

## Sentinel file

After every run — success or partial — the runner writes `.engineering-docs-agent/last_run_report.json`. The file contains three fields:

```json
{
  "status": "success",
  "head_sha": "abc1234...",
  "timestamp": "2026-06-09T07:03:11Z"
}
```

`status` is either `"success"` or `"partial"`. It is never absent; the file is written even when the run crashes after the sentinel-write point is reached.

## Why this matters for the GitHub Actions workflow

Previously the workflow had no lightweight, structured way to distinguish a silent orchestrator crash from a deliberate partial run. It had to infer outcome from log scraping or the absence of artifacts — both brittle.

The workflow now reads `.engineering-docs-agent/last_run_report.json` directly after the runner exits. A missing file means the runner crashed before the sentinel write. A present file with `"status": "partial"` means the run completed but with gaps — the PR body will carry `partial: true`. A present file with `"status": "success"` means a clean run.

## Test coverage

Four unit tests cover the new behaviors:

- Noop: verifies `state.json` is not mutated when HEAD SHA matches the recorded SHA.
- Noop with a dirty tree: same guard, with uncommitted changes present.
- Sentinel written on success: verifies the file exists and contains the expected fields.
- Sentinel written on partial: verifies `status` is `"partial"` when the run exits with gaps.

All tests live alongside the runner in `scripts/` and run under the standard `python3 -m pytest` suite.

## Cross-references

If you maintain an architecture page for the orchestrator, cross-reference the sentinel path (`.engineering-docs-agent/last_run_report.json`) and the SHA-guard logic there. Both behaviors are confined to `scripts/orchestrator_runner.py`.
