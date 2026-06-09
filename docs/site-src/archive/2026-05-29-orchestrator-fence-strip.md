---
status: draft
sources:
- https://github.com/theoju/engineering-docs-agent/pull/75
synthesized_into: []
doc_kind: decision
---

# Orchestrator: two-stage subagent output parse pipeline

PR #75 introduced a `_strip_code_fence` helper that sits in front of the existing `_rescue_json_object` path inside `dispatch_subagent`. Together they form a two-stage pipeline for turning raw subagent output into parsed JSON.

## Why the old single-stage rescue was not enough

Before PR #75, the orchestrator parsed subagent output with a single rescue path (`_rescue_json_object`). That helper correctly extracted JSON from a code-fence-wrapped response, but it also appended `prose_contamination_rescued` to `partial_reasons` regardless of whether real prose surrounded the JSON.

Subagents wrap their output in markdown fences roughly 19% of the time (observed in workflow run 26647051715 on PR #69), even though two places in every agent contract and the orchestrator's execution-framing prompt explicitly prohibit it. The result: almost every nightly run triggered a `WARNING — Partial run` banner. Operators stopped treating it as a signal.

## The two-stage pipeline

**Stage 1 — fence strip (`_strip_code_fence`).** Before attempting JSON parsing, the orchestrator checks whether the raw output is a bare code fence wrapping a JSON block (` ```json … ``` ` or ` ``` … ``` `). If the stripped content parses as valid JSON, the orchestrator returns that result immediately with no `partial_reasons` entry. No side-effects on the run status.

**Stage 2 — rescue (`_rescue_json_object`).** If stage 1 does not match — because the output contains genuine surrounding prose, a CCE-15-style SessionStart preamble, or other contamination — the rescue path runs as before and marks `prose_contamination_rescued`.

The ordering matters: stage 1 handles the common benign case silently; stage 2 handles the uncommon contamination case with an explicit flag.

## What changes for operators

You will see fewer `WARNING — Partial run` banners on docs-agent PRs. When the banner does appear, it means a subagent genuinely returned incomplete output or triggered the rescue path for real prose contamination — not a routine formatting quirk.

The `partial_reasons` field in `.engineering-docs-agent/state.json` remains the authoritative record. A run that reaches stage 2 still records `prose_contamination_rescued` there; a run that is handled entirely by stage 1 does not.

## Related context

- **CCE-55** — tracked the investigation that identified the 19% fence-wrap rate.
- **CCE-15** — documents the original prose-contamination rescue path that stage 2 preserves.
- `scripts/orchestrator_runner.py` — contains `_strip_code_fence` and `_rescue_json_object`.
- `docs/superpowers/plans/` and `docs/superpowers/specs/` — plan and spec documents shipped with PR #75.
