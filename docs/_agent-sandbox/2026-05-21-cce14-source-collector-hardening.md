---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/10
synthesized_into: []
---

# CCE-14: source-collector hardening — partial fix summary

**Ticket:** CCE-14 | **PR:** [#10](https://github.com/theoju/engineering-docs-agent/pull/10) | **Date:** 2026-05-21

## Background

The CCE-12 baseline showed the `source-collector` agent returning empty `prs: []` in 4 of 5 runs without ever invoking `gh pr list`. That makes the pipeline useless in the majority of dispatches.

Two root causes were identified: insufficient procedural gates in the agent prompt (allowing a single-turn short-circuit to an empty response) and a silent extraction failure in the orchestrator when the final assistant turn was pure tool-use with no text block.

## Changes shipped in PR #10

### Gated-checklist prompt restructure

The `source-collector` agent's Procedure section was rewritten as a mandatory ordered checklist. Each step requires visible tool-call evidence before the next may begin. The agent cannot produce output without completing the required tool invocations first.

Forbidden Outputs gained a new §5, explicitly naming the Category-A failure mode: returning `prs: []` without ever calling `gh pr list`. All five Forbidden-output sections are now numbered §1–§5 so the Procedure can cross-reference them directly.

### `_extract_final_assistant_text` fix

`scripts/orchestrator_runner.py:_extract_final_assistant_text` previously returned the unconditional last assistant turn. If that turn contained only tool-use, the function silently dropped the agent's actual JSON output from an earlier text-bearing turn.

The fix changes the function to prefer the **last text-bearing assistant turn**. Two new pytest tests cover both edge cases: last-turn-is-tool-only and last-turn-has-text.

## Acceptance measurement (5-run Mode B)

Results after PR #10:

| Metric | Before (CCE-12) | After (CCE-14) | Target |
|---|---|---|---|
| Category-A failures (empty `prs: []`) | 4/5 | 2/5 | ≤1/5 |
| Runs invoking `gh pr list` | 0/5 | 3/5 | ≥4/5 |

Both targets were missed by 1. PR #10 ships as a partial fix.

Measurement artifacts are committed under `docs/superpowers/measurements/`. The CCE-12 baseline is marked **SUPERSEDED** — a plugin manifest loader bug silently rejected the plugin in those runs, meaning the agent never executed during baseline collection.

## Residual failure modes — scoped to CCE-15

Two failure modes remain characterized but unresolved:

1. **Checklist bypass** — the agent acknowledges the checklist but skips steps and proceeds directly to output.
2. **Prose contamination** — the agent emits explanatory prose before the JSON block, which the extraction layer can mishandle.

CCE-15 targets both with an XML-tagged output wrapper (giving extraction a fixed anchor point) and stronger checklist-compliance language in the prompt. See the CCE-15 ticket for acceptance criteria and targets.
