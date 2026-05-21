# CCE-15: Source-Collector Root-Cause Sweep Baseline — 5-Run Mode B Ceremony

**Jira:** [CCE-15](https://designitright.atlassian.net/browse/CCE-15)
**Branch:** `feat/CCE-15-source-collector-root-cause-sweep`
**Date:** 2026-05-21
**Dispatch window:** `a2a9dba273bf5ef82ef6d450d3eb44ee27e04681..b2cd07af5cdcf0482515fc757a6ee6def3af278d` (IDENTICAL to CCE-12 and CCE-14)
**PR filter:** `docs-agent/*`
**Interventions:**

- `dispatch_subagent` now passes `claude --setting-sources project,local` (skips user-level settings.json where the `explanatory-output-style` plugin is enabled). Originally tried `--bare` but it disables OAuth.
- `source_collector.schema.json` tightened with `additionalProperties: false` at top level + per-PR item.
- `_rescue_json_object` helper added in `dispatch_subagent` as defense in depth; rescue events surface via `prose_contamination_rescued: <agent>` in `partial_reasons`.
- `dispatch_validated` wires the `out_reasons` collector through to its returned reasons list.

## Three-column comparison (CCE-12 → CCE-14 → CCE-15)

| Run | CCE-12 cat | CCE-14 cat        | CCE-15 total_calls | CCE-15 by_name     | CCE-15 cat    | gh pr list? | rescue? |              schema-valid?              |
| --: | ---------- | ----------------- | -----------------: | ------------------ | ------------- | :---------: | :-----: | :-------------------------------------: |
|   1 | A          | data-returned     |                  0 | {}                 | A (bypass)    |      N      |    N    | N (schema_invalid: missing jira_issues) |
|   2 | B          | A                 |                  3 | {Read: 1, Bash: 2} | data-returned |      Y      |    N    |                    Y                    |
|   3 | A          | A                 |                  0 | {}                 | A (bypass)    |      N      |    N    | N (schema_invalid: missing jira_issues) |
|   4 | A          | B (rescue-failed) |                  0 | {}                 | A (bypass)    |      N      |    N    |     N (schema_invalid: missing prs)     |
|   5 | A          | B                 |                  0 | {}                 | A (bypass)    |      N      |    N    | N (schema_invalid: missing jira_issues) |

Raw artifacts: `2026-05-21-cce15-run<N>-source-collector.{stream.jsonl,stdout.txt,stderr.txt,prompt.txt,meta.json}` in this directory.

## Headline

CCE-12 baseline: Category A in 4 of 5 runs; `gh pr list` invoked in 0 of 5.
CCE-14 post-fix: Category A in 2 of 5 runs; `gh pr list` invoked in 3 of 5.
CCE-15 post-fix: Category A in 4 of 5 runs; `gh pr list` invoked in 1 of 5.
Prose contamination: CCE-14 1/5 (Run 4 "★ Insight" block) → CCE-15 0/5.

## Acceptance check

| Metric                             | CCE-12  | CCE-14 | CCE-15 actual | Target                                        | Verdict |
| ---------------------------------- | ------- | ------ | ------------- | --------------------------------------------- | ------- |
| Category A (empty + zero tools)    | 4 / 5   | 2 / 5  | 4 / 5         | ≤ 1 / 5                                       | FAIL    |
| `gh pr list` invocations           | 0 / 5   | 3 / 5  | 1 / 5         | ≥ 4 / 5                                       | FAIL    |
| Runs returning real PR data        | 0 / 5   | 1 / 5  | 1 / 5         | ≥ 3 / 5                                       | FAIL    |
| Prose contamination failures       | n/a     | 1 / 5  | 0 / 5         | 0 / 5                                         | PASS    |
| Phantom-field acceptances (silent) | unknown | 2 / 5  | 0 / 5         | 0 / 5 (prevented OR logged as schema_invalid) | PASS    |

Overall: **PARTIAL PASS** — observability improved dramatically (every failure is now visible in `partial_reasons` where pre-CCE-15 they were silent), but the bypass rate did not drop and `gh pr list` invocation dropped vs CCE-14.

## Delta from CCE-14

**What worked (Task 1 + Task 2):** Zero `★ Insight` prose contamination across all 5 runs (CCE-14 Run 4's failure mode is fully eliminated by `--setting-sources project,local`). All 4 bypass runs produced inventive non-canonical shapes (phantom `commits`, `jira_keys`, `issues`, `diffs`, `rescue_reason`, `sources`, `warnings`) — ALL were caught by the tightened schema and surfaced as `schema_invalid: ...` in `partial_reasons`. Pre-CCE-15, the CCE-14 Runs 2&3 emitted `{prs:[],jira_issues:[],commits:[]}` and were SILENTLY accepted as empty-success runs. Now they're loud.

**What didn't move (Task 3 + Task 4):** The rescue path stayed cold across all 5 runs because Task 1 eliminated the contamination class at root. `prose_contamination_rescued: ...` never appeared in any REASONS. The rescue helper remains valuable as defense-in-depth for future contamination patterns from other injection sources.

**What got worse (or got revealed):** Bypass rate appears higher in this sample (4/5 vs CCE-14's 2/5). Two hypotheses, neither resolvable at n=5:

1. Sample variance — n=5 has wide confidence intervals.
2. `--setting-sources project,local` removed positive contextual cues from user-level settings (e.g., CLAUDE.md voice guidance, hook-injected context) that the agent was implicitly relying on. Run 4's hallucinated `"Production dispatch invoked in restricted environment; no git/PR/Jira fetch tools available — returning empty source set rather than ..."` warning is suggestive: the agent INFERRED restriction from missing context, despite `--allowedTools` being unchanged.

The fixed acceptance criteria miss on bypass-related metrics is exactly the residual failure mode CCE-16 (the structural prompt change deferred from CCE-15's risks section) is positioned to address.

## Follow-up

**File CCE-16 with scope:**

1. **Structural prompt change to prevent single-turn bypass.** Forced two-turn protocol OR XML-tagged required-output envelope that requires the agent to stage intermediate evidence before emitting final JSON. Bypass behavior at 4/5 is the dominant remaining failure mode.
2. **Explicit "you have full tool access" cue in the prompt.** Run 4 demonstrates the agent will hallucinate restriction. The prompt should explicitly state "Bash, Read, Edit, Write, WebFetch are available; do not infer restriction from your environment context."
3. **Consider per-agent context augmentation.** Stripping user-level settings (Task 1) was necessary to kill the "★ Insight" contamination but may have over-pruned positive cues. CCE-16 could explore restoring specific positive cues via explicit `--system-prompt` / `--append-system-prompt` rather than the all-or-nothing `--setting-sources` filter.

## Methodology notes

The CCE-15 commits (`4699e91` originally added `--bare`; superseded by `1bb04c8` which swapped for `--setting-sources project,local` because `--bare` disables OAuth; `6177c92` tightened the schema; `0b143b8` added the rescue helper; `b2b32b0` wired rescue propagation through `dispatch_validated`) are NOT in the dispatch window `a2a9dba..b2cd07a` — that window predates this branch. The agent loads the CCE-15 version of `agents/source-collector.md` at runtime via `--plugin-dir`, and `dispatch_subagent` runs from the working tree, so all four interventions are active during measurement.

Task 5's measurement script calls `dispatch_validated` (not `dispatch_subagent` directly as the original plan stated). This was changed in-flight so the full pipeline is exercised — including Task 2's schema validation and Task 4's rescue propagation. The CCE-12 and CCE-14 baselines called `dispatch_subagent` directly; the comparison is still meaningful because the schema-validation column is a NEW dimension this baseline exposes for the first time.

Each run was executed serially (NOT in parallel) with a fresh `DOCS_AGENT_DEBUG_DIR` to ensure subagent context isolation. `CLAUDE_STOP_VERIFY=0` was set per the existing convention (CCE-10) to prevent the global stop-verify hook from contaminating stdout — note this is independent of `--setting-sources`, which addresses a different contamination pathway.

A pre-existing test-suite issue (2 failures in `tests/orchestrator/test_state_carry_forward.py` — `test_prior_run_partial_reasons_do_not_carry_forward` and `test_fresh_run_after_failed_run_starts_with_empty_reasons`) exists on `main` (verified by bisection against d241420 and a2a9dba) and is NOT a CCE-15 regression. Should be filed as a separate ticket; pytest was run with `--ignore=tests/orchestrator/test_state_carry_forward.py` to confirm CCE-15 work didn't break anything else (187 passed).
