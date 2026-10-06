# CCE-199 — Bound the collector payload at source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a far-behind baseline from forcing the source-collector to overflow its output, which classifies the run blind and freezes the watermark forever.

**Architecture:** Hand the collector a detail bound in `sc_inputs`. It returns _every_ in-window PR, with full detail for the oldest N and a metadata-only anchor for the rest — so the payload fits while the orchestrator still sees the whole window and CCE-169/CCE-151's existing `held_back` and unanchored-PR machinery keeps working untouched.

**Tech Stack:** Python 3 (`scripts/orchestrator_runner.py`), agent prompt markdown (`agents/source-collector.md`), JSON Schema (`agents/schemas/source_collector.schema.json`), pytest.

**Spec:** none written. This plan _is_ the capture — see "Provenance" below.

## Provenance, and why this file exists

The analysis behind this plan was produced on **2026-10-02** and was never written to any repository. It survived only as a claude-mem observation (id `51438`, "Nine-Fix Plan to Unblock Docs-Agent Stall"). Four days later a fresh session re-derived the same root cause from scratch and started implementing a **worse** variant of Fix 1, which that observation explicitly warns is unsafe on its own.

Writing it down is the fix for that. `max_detail_prs`, `payload_bounded` and `response_interrupted` appear **0 times** in this repository, so nothing but the observation recorded any of it.

## Global Constraints

- **Fixes 1–3 must ship together.** Fix 1 alone risks silent cursor loss. Fix 4 depends on Fix 3's invariant check.
- **Oldest-first is a safety requirement, not a preference.** The orchestrator only ever sees what the collector chose to return, so a newest-first payload is indistinguishable from an oldest-first one — and advancing the cursor across it strands every older PR behind the baseline, outside every future window. An ADIS run was observed emitting "the 9 most recent".
- **`0` means unlimited and must survive transit.** `resolve_window_cap(config) or DEFAULT` would rewrite an explicit opt-out; use the `is None` discipline `resolve_window_cap` already follows.
- `source_collector_error` stays **blind by default** for every value Fix 4 does not explicitly route. "An unclassified new failure mode is loud, not silent" (CCE-144).
- Tests use fixtures representing **arbitrary hosts**, never this repo's tree. Existing `fake_source_collector.json` fixtures top out at 3 PRs, so no current test can observe a wide window.

## Measured root cause (ADIS host, 2026-10-06)

Run `37493982560` (`event=schedule`):

```
docs-agent PARTIAL: source_collector_error: output_size_limit: 12 of 173 in-window PRs returned
docs-agent PARTIAL: source_collector_partial: true
docs-agent INFO:    auto_merge_skipped: blind_run
##[error]Process completed with exit code 1.
```

| fact                               | value                                                                 |
| ---------------------------------- | --------------------------------------------------------------------- |
| `last_successful_run.head_sha`     | `7863a189` — a commit dated **2026-09-09 08:36:40**                   |
| `last_successful_run.completed_at` | `2026-10-05T18:48:18Z`                                                |
| in-window PRs                      | 173; 12 returned                                                      |
| commits ahead of baseline          | 182                                                                   |
| scheduled nightlies                | 1 success in 6 (10-01 F, 10-02 F, 10-03 F, 10-04 F, 10-05 S, 10-06 F) |

The lone success advanced the baseline from `ffd1eb17` (2026-09-09 03:30:29) to `7863a189` (2026-09-09 08:36:40) — ten commits, five hours of repository history.

**Two traps worth naming.** `completed_at` is recent while `head_sha` is 26 days old, so reading the timestamp makes the baseline look healthy. And `output_size_limit` is **not a contracted error** — it appears 0 times in this repo. The agent invented it because `agents/source-collector.md` sanctions only `git_rate_limit`, `jira_partial: <key>` and `git_unrecoverable: <reason>`, and permits `partial` + `error` only "when a tool legitimately fails". No tool failed; the window was merely too wide to express.

**The bound is on the wrong side of the agent boundary.** Inside `run()`: the collector is dispatched (~`:2814`) and overflows; the error is recorded blind (`:2827`); only then does `resolve_window_cap` run (`:2869`), against the already-truncated output. CCE-169 bounds what the run _admits_; nothing bounds what the collector _emits_, and `sc_inputs` carries no bound at all.

## Why `max_detail_prs` with anchors, not `max_prs` with truncation

A plain `max_prs` that simply returns fewer PRs is the tempting reading and is the unsafe one: the orchestrator then never learns the tail exists, so `held_back` is empty, CCE-151's walk is skipped, and the advance reaches full window HEAD — the exact failure `test_a_capped_run_advances_to_the_cap_boundary_and_says_so` was written to catch, one layer up where that test cannot see it.

Returning **all** PRs with a metadata-only tail keeps every existing interlock honest: the window is fully visible, CCE-169's cap does the admission cut it already does, `merge_sha`-less PRs still reach the `_no_advance_unanchored_deferred` guard, and the payload fits because an anchor is four fields.

---

## Task 1 — Pass the detail bound into the collector

**Files:**

- Modify: `scripts/orchestrator_runner.py` — the `sc_inputs` dict literal in `run()`
- Test: `tests/orchestrator/test_collector_window_bound.py` (create)

**Interfaces:**

- Produces: `sc_inputs["max_detail_prs"]: int`, from `resolve_window_cap(config)`; `0` = unlimited.

- [ ] **Step 1: Write the failing test** — capture `sc_inputs` at the dispatch seam by monkeypatching `orun.dispatch_validated`, since the value has no downstream signal of its own. Reuse `_seed_capped_host` from `test_window_cap.py`. Assert the key is present, equals a non-default cap (7, so a hardcoded `10` fails), and that an explicit `0` arrives as `0`.
- [ ] **Step 2: Run it and watch it fail** — `rtk proxy python3 -m pytest tests/orchestrator/test_collector_window_bound.py -q`. Expect absent-key assertions. Confirm the output ends in a `N failed` line.
- [ ] **Step 3: Add the field** to the `sc_inputs` literal with a comment naming CCE-199, the line-ordering reason CCE-169 cannot cover this, and the `0`-is-unlimited rule.
- [ ] **Step 4: Re-run** — expect pass.
- [ ] **Step 5: Commit** — `fix(CCE-199): hand the source-collector its own detail bound`

## Task 2 — Contract the bounded payload in the agent prompt

**Files:**

- Modify: `agents/source-collector.md` — `## Inputs`, and the Step 3 per-PR metadata rules
- Modify: `agents/schemas/source_collector.schema.json` — allow an anchor-shaped `prs[]` item
- Test: `tests/schemas/test_source_collector_schema.py`, plus the contract assertion in Task 1's file

**Interfaces:**

- Consumes: `max_detail_prs` from Task 1.
- Produces: anchor items `{number, url, merge_sha, merged_at}`; a contracted `payload_bounded: <detailed> of <total>` reason instead of an invented string.

- [ ] **Step 1: Write the failing contract test** — assert `` `max_detail_prs` `` appears in the prompt and that the text after it requires **oldest**-first selection. The agent is a prompt, so the prompt is the only place the guarantee can live and a text assertion is the only available guard.
- [ ] **Step 2: Run it and watch it fail.**
- [ ] **Step 3: Document the field** in `## Inputs`: emit full detail for the **oldest** `max_detail_prs` PRs; emit every remaining in-window PR as a metadata anchor; never drop a PR from the payload; set `partial: true` with `payload_bounded: <detailed> of <total>` when the tail is non-empty. State plainly that newest-first selection strands older PRs permanently.
- [ ] **Step 4: Widen the output schema** so an anchor item validates while a detailed item still does. Keep `additionalProperties: false`.
- [ ] **Step 5: Re-run both test files** — expect pass.
- [ ] **Step 6: Commit** — `fix(CCE-199): contract the bounded collector payload with metadata anchors`

## Task 3 — Guard the cursor against a short or empty window

**Files:**

- Modify: `scripts/orchestrator_runner.py` — the advance path
- Test: `tests/orchestrator/test_collector_window_bound.py`

**Interfaces:**

- Consumes: the anchored payload from Task 2.

- [ ] **Step 1: Write the failing test** — a payload whose detailed prefix is shorter than the known window must NOT advance to window HEAD. Mirror `test_a_capped_run_advances_to_the_cap_boundary_and_says_so`'s structure and assert `advanced != head` and that a reason is emitted.
- [ ] **Step 2: Run it and watch it fail.**
- [ ] **Step 3: Add the invariant check** — refuse a cursor advance past the last PR the collector actually detailed. This is the guard that makes Task 4 safe; without it Task 1 alone is a silent-cursor-loss hazard.
- [ ] **Step 4: Re-run, then run the full suite** — `rtk proxy python3 -m pytest -q`. Nothing in `test_window_cap.py`, `test_cursor_backed_merge.py`, `test_time_budget.py` or `test_deferral_skip.py` may regress.
- [ ] **Step 5: Commit** — `fix(CCE-199): refuse a cursor advance past the collector's detailed prefix`

## Task 4 — Route collector errors by severity (depends on Task 3)

**Files:**

- Modify: `scripts/orchestrator_runner.py` — the `sources.get("error")` branch
- Test: `tests/orchestrator/test_collector_window_bound.py`

- [ ] **Step 1: Write the failing test** — a `payload_bounded` error with a usable payload is `degraded=True` (run merges, cursor advances to the detailed prefix); an error with an **empty** payload stays `degraded=False` (blind). Assert an unrecognised error string is still blind.
- [ ] **Step 2: Run it and watch it fail.**
- [ ] **Step 3: Route by severity**, keeping blind as the default for everything unnamed.
- [ ] **Step 4: Run the full suite.** `test_classification_coverage.py` requires an explicit classification kwarg at every blocking call site.
- [ ] **Step 5: Commit** — `fix(CCE-199): classify a bounded collector payload degraded, not blind`

## Deferred — tracked, not in this plan

From the 2026-10-02 analysis, kept so they are not lost again:

- **Fix 5** — widen the interrupt detector to catch a safety-classifier notice and retry the dispatch once.
- **Fix 6** — add a `response_interrupted` contract token, so a harness-layer interrupt need not be expressed as empty arrays.
- **Fix 9** — print per-reason fatal/info classification in the shutdown dump by intersecting `blind_reasons`.
- **Fixes 7 and 8** — the watcher verdict rename `cron_not_firing` → `run_not_succeeding` and its test. **Already landed, ADIS-side** (`advanced-data-importer/scripts/docs_agent_stall_watch.py`); this repo's copy still carries the old label. Related: ADIS-1051, where `last_scheduled_run` trusts `workflow_runs[0]` and can report a stale run, masking every leg below it.

## Host-side note

ADIS vendors this plugin at `ref:main`, so Tasks 1–4 propagate without an ADIS-side change. `run.window_pr_cap` is unset on that host, so it takes `DEFAULT_WINDOW_PR_CAP` (10). Setting it alone fixes nothing — the cap is applied downstream of the overflow.

The immediate unblock, independent of this plan, is to step the ADIS baseline forward by hand so the window narrows. That is an unblock and not a fix: the PRs in the stepped-over span are never documented.
