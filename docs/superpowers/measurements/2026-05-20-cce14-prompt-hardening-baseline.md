# CCE-14: Source-Collector Prompt-Hardening Baseline — 5-Run Mode B Ceremony

> **⚠ SUPERSEDED — see [CCE-16 real baseline](2026-05-21-cce16-real-baseline.md).**
>
> This measurement is invalid for source-collector prompt-compliance conclusions. The plugin manifest (`.claude-plugin/plugin.json`) had an invalid `author` field that caused the Claude CLI loader to silently reject the entire plugin, so every dispatch in this baseline ran as default Claude Code responding to an injected user prompt — the source-collector agent never executed. The prompt-hardening intervention described below is a sound design but was untested by this baseline; see CCE-16 for the first real measurement.
>
> The diagnostic infrastructure (stream-json capture, forensic artifacts) and the prompt-restructure intervention itself are retained — only the conclusions about agent behavior in §Headline, §Acceptance check, and §Delta are invalidated.

**Jira:** [CCE-14](https://designitright.atlassian.net/browse/CCE-14)
**Branch:** `feat/CCE-14-source-collector-prompt-hardening`
**Date:** 2026-05-20
**Dispatch window:** `a2a9dba273bf5ef82ef6d450d3eb44ee27e04681..b2cd07af5cdcf0482515fc757a6ee6def3af278d` on theoju/engineering-docs-agent (IDENTICAL to CCE-12's window)
**PR filter:** `docs-agent/*`
**Intervention:** `agents/source-collector.md` Procedure restructured as gated checklist; Forbidden outputs §5 added.

## Side-by-side comparison (CCE-12 pre-fix vs CCE-14 post-fix)

| Run | CCE-12 total_calls | CCE-12 category         | →   | CCE-14 total_calls | CCE-14 by_name     | CCE-14 category         | gh pr list? |
| --: | -----------------: | ----------------------- | --- | -----------------: | ------------------ | ----------------------- | :---------: |
|   1 |                  0 | A: zero tool calls      | →   |                  6 | {Read: 1, Bash: 5} | data returned           |      ✓      |
|   2 |                  5 | B: called and discarded | →   |                  0 | {}                 | A: zero tool calls      |      ✗      |
|   3 |                  0 | A: zero tool calls      | →   |                  0 | {}                 | A: zero tool calls      |      ✗      |
|   4 |                  0 | A: zero tool calls      | →   |                  4 | {Bash: 3, Read: 1} | B: called and discarded |      ✓      |
|   5 |                  0 | A: zero tool calls      | →   |                  5 | {Read: 1, Bash: 4} | B: called and discarded |      ✓      |

Raw artifacts: `2026-05-20-cce14-run<N>-source-collector.{stream.jsonl,stdout.txt,stderr.txt,prompt.txt,meta.json}` in this directory.

## Headline

CCE-12 baseline: Category A in 4 of 5 runs; gh pr list invoked in 0 of 5.
CCE-14 post-fix: Category A in 2 of 5 runs; gh pr list invoked in 3 of 5.

## Acceptance check

- Target: ≥4 of 5 runs in Category B/C/data-returned, with gh pr list (or gh api repos/.../pulls) invoked.
- Result: **FAIL** — Category A count is 2/5 (target ≤1) and gh pr list invocation count is 3/5 (target ≥4).

## Delta

2 of 4 CCE-12 Cat-A runs converted (runs 4 and 5 now invoke tools and reach `gh pr list`); the remaining 2 (runs 2 and 3) still emitted empty JSON in a single ~4–5s turn without any tool call. The mandatory-checklist restructure is necessary but insufficient — the agent is non-deterministically complying. Run 4 exhibited a new failure mode: the checklist elicited tool use and correct data retrieval, but the agent prepended an "Insight" prose block before the JSON output, breaking `_extract_final_assistant_text` and causing dispatch to return None. Escalation path warranted: file CCE-15 for (a) XML-tagged required-output wrapper to prevent prose contamination, and (b) investigation of why 2/5 runs still skip the checklist entirely despite §5 Forbidden.

## Follow-up

File CCE-15 with scope:

1. XML-tagged `<output>` wrapper to prevent prose contamination of the JSON response (run 4 root cause).
2. Stronger compliance forcing for the gated checklist — investigate whether adding an explicit `STOP: do not output JSON until you have completed all checklist steps` gate prevents the 2/5 Category-A bypass.

## Methodology notes

The CCE-14 commits (Tasks 1-5: prompt restructure, Forbidden §5, three Stage-4-deferred items) are NOT in the dispatch window `a2a9dba..b2cd07a` — that window predates this branch. The agent loads the CCE-14 version of `agents/source-collector.md` at runtime via `--plugin-dir`, so the comparison isolates the prompt change as the only intervening variable.

Run 4 dispatch returned `None` despite the agent successfully invoking `gh pr list` and retrieving PR data. The failure was in `_extract_final_assistant_text`: the agent output an "Insight" prose block (backtick-fenced) followed by the JSON, which prevented clean JSON extraction. This is categorized as B: called and discarded (tools ran, correct data retrieved, output format violated). The underlying data was present in the stdout artifact.
