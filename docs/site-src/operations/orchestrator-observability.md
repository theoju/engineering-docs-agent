---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/93
synthesized_into: []
---

# Orchestrator Observability

`scripts/orchestrator_runner.py` emits structured log lines at startup, after each stage, and at the end of every run. This page covers the four signals and how to use them when debugging a nightly run.

## Secrets redaction

At startup, the runner logs which environment variables it found — with values replaced by `[REDACTED]`. You can confirm that `ANTHROPIC_API_KEY` and `JIRA_API_TOKEN` are wired correctly without any credential leaking into CI logs.

A line like the following appears before the first stage dispatches:

```
env check: ANTHROPIC_API_KEY=[REDACTED] JIRA_API_TOKEN=[REDACTED]
```

If a variable is missing the field is absent, not redacted — so you can distinguish "present but secret" from "not set".

## Per-stage elapsed time

After each stage completes, the runner logs the wall-clock duration in seconds:

```
stage pr_summarizer completed in 14.3s
```

Use this to isolate slow stages without external tracing. If a nightly run is taking longer than expected, compare elapsed values across stages to find the bottleneck.

## Per-stage compact JSON output

Immediately after each stage, the runner logs a compact JSON line containing the stage name, status, and a summary of what it produced:

```json
{"stage": "pr_summarizer", "status": "ok", "pr_count": 4}
```

This appears in order — one line per stage — so a partial failure is visible at the exact stage boundary. You can `grep` for `"status": "error"` across a CI log to find every failed stage without reading the full output.

## Final run-summary line

At the end of `run()`, the runner emits a single structured JSON line for machine consumption:

```json
{"run": "complete", "stages": {"pr_summarizer": "ok", "page_author": "ok"}, "elapsed_s": 87.4}
```

The `run` field is either `"complete"` or `"partial"`. A partial run means at least one stage failed but the runner continued; it still opens a PR with `partial: true` in the body.

To extract this line from a CI log:

```bash
grep '"run":' <log-file>
```

The nightly workflow reads this line to decide whether to annotate the PR body with partial-run metadata.

## Reading the signals together

Start with the final summary line to get the overall status and total elapsed time. If `run` is `"partial"`, scan per-stage JSON lines for the first `"status": "error"` to find the stage that failed. Use the elapsed-time lines to identify whether the failure followed an unusually slow stage (timeout, rate-limit) or appeared immediately (misconfiguration).

All four signals are additive — no existing code path changed behavior in PR #93.
