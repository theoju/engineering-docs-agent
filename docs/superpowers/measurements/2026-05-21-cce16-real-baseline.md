# CCE-16: Source-Collector Real Baseline — 5-Run Mode B Ceremony

**Jira:** [CCE-16](https://designitright.atlassian.net/browse/CCE-16)
**Branch:** `fix/CCE-16-plugin-manifest-author`
**Date:** 2026-05-21
**Dispatch window:** `a2a9dba273bf5ef82ef6d450d3eb44ee27e04681..b2cd07af5cdcf0482515fc757a6ee6def3af278d` on theoju/engineering-docs-agent (IDENTICAL to CCE-12, CCE-14, CCE-15)
**PR filter:** `docs-agent/*` (exclude pattern, not include)
**Intervention:** `.claude-plugin/plugin.json` `author` field corrected from string to object — plugin now loads, all 7 subagents available.

## Critical context

This is the **first valid measurement** of the source-collector agent in production. CCE-12, CCE-14, and CCE-15 all measured default Claude Code with an injected user prompt because the plugin manifest was rejected at load time by the Claude CLI's Zod schema validator (`author: expected object, received string`). The agent definition in `agents/source-collector.md` never executed in any prior baseline. See [CCE-16](https://designitright.atlassian.net/browse/CCE-16) for the smoking-gun forensic capture and root-cause analysis.

## Per-run table

| run | total_calls | by_name (gh_pr_list) | duration_s | stop_reason | PRs_returned | classification        |
| --: | ----------: | -------------------: | ---------: | ----------- | ------------ | --------------------- |
|   1 |           6 |                    2 |      149.3 | end_turn    | []           | CORRECT-empty         |
|   2 |           5 |                    1 |      165.2 | end_turn    | [9, 10, 11]  | WRONG (out-of-window) |
|   3 |          10 |                    1 |      223.9 | end_turn    | [9, 10, 11]  | WRONG (out-of-window) |
|   4 |           4 |                    1 |      104.4 | end_turn    | []           | CORRECT-empty         |
|   5 |           9 |                    1 |      194.5 | end_turn    | [9]          | WRONG (out-of-window) |

All 5 runs: `agent_loaded=True, plugin_errors=None` (plugin loads cleanly).

Raw artifacts: `2026-05-21-cce16-run<N>-source-collector.{stream.jsonl,stdout.txt,stderr.txt,prompt.txt,meta.json}` in this directory.

## Window analysis

The dispatch window `a2a9dba..b2cd07af` spans 55 minutes 16 seconds (04:31:46 → 05:27:02 UTC on 2026-05-21). Within that window, zero PRs were merged:

- PR #8 (CCE-10, branch `feat/CCE-10-source-collector-canonical-shape`) IS the `last_sha` — excluded by the exclusive lower bound.
- PR #9 (CCE-12) merged 06:01:49Z — 34 minutes AFTER the `head_sha`.
- PRs #10, #11 (CCE-14, CCE-15) merged hours later still.

The canonical correct output is therefore `{"prs": [], "jira_issues": []}`.

## Headline

The plugin fix works: all 5 runs loaded the plugin cleanly with zero errors and all 7 subagents available — the CCE-16 manifest correction is fully verified. The source-collector agent invoked tools on every run (5/5), confirming the agent definition in `agents/source-collector.md` now executes. Correctness is 2/5: three runs (2, 3, 5) reach forward past `head_sha` into the future and return PRs #9, #10, or #11, which weren't merged until 34 minutes to hours after the head commit. The same inputs producing different outputs across runs is a real source-collector failure mode — now visible for the first time — and is the genuine behavioral issue that CCE-14's prompt-hardening design tried to address.

## Acceptance check

The plan's success criteria:

- Target: ≥4 of 5 runs return canonical JSON with non-empty `prs` array (real PR data from the dispatch window). **N/A** — the window contains zero PRs; the correct answer is empty.
- Target: ≥4 of 5 runs invoke `gh pr list` or `gh api repos/.../pulls`. **PASS (5/5).**
- Target: zero runs with `plugin_errors` populated. **PASS (5/5).**

Revised acceptance against the actual ground truth:

- Target: 5/5 runs return correct output (empty arrays, since no PRs match the window). **FAIL (2/5).**

Result: **PARTIAL PASS** — the plugin-load infrastructure works perfectly (the CCE-16 manifest fix is verified), but the source-collector agent itself exhibits a 3/5 out-of-window failure mode that is the actual structural problem all prior baselines tried to measure but couldn't.

## What this rewrites

Three prior baseline docs document failure modes attributed to source-collector prompt non-compliance. All three measurements actually captured default Claude Code responding (or refusing) to the orchestrator's `<inputs>` framing. Specifically:

- **CCE-12** (stream-json instrumentation baseline) — the instrumentation worked perfectly. The "Category A" classification of 4/5 runs as "zero tool calls" was correct as raw data but mis-attributed to source-collector behavior. The agent was never loaded.
- **CCE-14** (prompt-hardening intervention) — the prompt restructure to a gated checklist + Forbidden §5 was a correct intervention against the documented failure modes, but it **never executed** in any measurement run. The 2/5 Category-A persistence reported in the CCE-14 baseline was default Claude Code's behavior, not a non-compliant source-collector.
- **CCE-15** (root-cause sweep: rescue + schema + setting-sources) — the schema-tightening (Fix #2) and prose-tolerant rescue (Fix #3) remain valid defense-in-depth measures regardless. The `--setting-sources project,local` swap (Fix #1) was unnecessary for the plugin-load problem (which had a different root cause), but `--setting-sources project,local` is still desirable for SessionStart hook exclusion and is retained.

CCE-16 is the first measurement that exercises the actual source-collector prompt. The 3/5 out-of-window-PR failure mode is the genuine source-collector behavior issue CCE-14's prompt design tried to address but couldn't actually test.

## Follow-up

File a follow-up ticket (suggested CCE-17) for the out-of-window-PR failure mode: the agent reaches forward past `head_sha` and returns PRs that weren't yet merged at the head commit. Probable root cause: `gh pr list --state merged` returns PRs in reverse-chronological order; without an explicit `head_sha` ceiling, the agent picks the most recent merged PRs even when they're outside the window. The agent's prompt does explain the window contract; the failure is in following it under the default `gh pr list` query shape.

Recommended fix direction for CCE-17: the agent should bound `gh pr list` queries by merge date derived from `head_sha`'s commit date (use `gh api repos/.../commits/<head_sha> --jq '.commit.committer.date'` to get the ceiling, then `gh pr list --search "merged:<=<ceiling>"`). This is exactly the query shape run 1 used (the only run that combined the date lookup with the bounded search).
