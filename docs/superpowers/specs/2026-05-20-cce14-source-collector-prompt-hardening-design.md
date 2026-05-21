# CCE-14: Source-Collector Prompt Hardening — Design

**Status:** Draft for review
**Jira:** [CCE-14](https://designitright.atlassian.net/browse/CCE-14)
**Parent:** Cure for the failure mode CCE-12 measured (CCE-12 shipped the instrument)
**Branch:** `feat/CCE-14-source-collector-prompt-hardening`

## Problem

CCE-12's 5-run Mode B baseline (`docs/superpowers/measurements/2026-05-20-cce12-tool-use-baseline.md`) measured the source-collector subagent's actual production behavior:

| Run | total_calls | by_name            | category                |
| --: | ----------: | ------------------ | ----------------------- |
|   1 |           0 | {}                 | A: zero tool calls      |
|   2 |           5 | {Bash: 3, Read: 2} | B: called and discarded |
|   3 |           0 | {}                 | A: zero tool calls      |
|   4 |           0 | {}                 | A: zero tool calls      |
|   5 |           0 | {}                 | A: zero tool calls      |

**Dominant pattern: Category A in 4 of 5 runs.** The agent emits `{"prs": [], "jira_issues": []}` in a single ~3–6s turn without invoking any tool. Run 2 made 5 tool calls — `git log`, `git branch`, schema read — but never `gh pr list`; it explored the repo's git metadata instead of collecting PR data.

The dispatch surface, CLI args, and tool grants are all correct (verified end-to-end by CCE-2/3/12). The agent's _system prompt_ is what fails: the current Procedure section lists `gh pr list` at step 1, but the agent ignores it 4 of 5 times and short-circuits to an empty response.

CCE-14 is the cure. The lever is the same one that worked in CCE-10: restructure the prompt, don't just add more assertions. CCE-10 fixed canonical-shape compliance by naming bad shapes in the negative space (Forbidden outputs). CCE-14 applies the same lever to the positive space: each Procedure step becomes a named obligation with a "may not proceed" gate, plus a fifth Forbidden-output entry for the specific shape we measured.

## Goals

1. Eliminate the Category A failure pattern: at least 4 of 5 re-measurement runs must show `total_calls > 0` with at least one `gh pr list` (or `gh api repos/.../pulls`) invocation.
2. Preserve the Category-0 escape hatch: when `last_sha` is empty, the canonical `{"prs": [], "jira_issues": []}` response (no tool calls) remains correct.
3. Roll in the three Stage-4-deferred items from CCE-12's code review (forward-compat hardening + test rename + docstring clarification).
4. Validate with a 5-run Mode B re-measurement against the exact same SHA window CCE-12 used, and publish a side-by-side comparison.

## Non-goals

- Other agents (pr-summarizer, gap-detector, etc.). The same Category A pattern may exist elsewhere; file separate tickets if discovered.
- Tool-use budgets, retry-on-no-tool-calls, or circuit breakers at the orchestrator. Defer until the re-measurement shows whether prompt-only hardening is sufficient.
- Migration to a different model.
- Restructuring the Forbidden outputs section's existing four entries. They work as-is per CCE-10.
- Output schema or Job/Inputs sections of `agents/source-collector.md`. CCE-10 nailed the schema; touching it risks regression.

## Approach

Restructure the Procedure section of `agents/source-collector.md` as a mandatory ordered checklist with explicit "may not proceed" gates and proof-of-tool-call requirements. Add a fifth Forbidden-output entry naming the dominant Category A shape. Roll in the three Stage-4-deferred items as a small bundle.

### Why restructure (not just add assertions)

The current Procedure already says "Use `gh pr list`" at step 1. The 4-of-5 Category A baseline is direct evidence that adding another assertion of the same shape ("you MUST use `gh pr list`") will not move the needle — the agent already has that instruction and ignores it. The lever that demonstrably works on this codebase is structural: name the failure modes, gate the steps, give the agent a structure it cannot shortcut without producing a recognizably-bad shape.

### Why source-collector only

The Category A pattern was measured for source-collector. Other agents are untested for this failure mode. Generalizing the restructure prematurely risks regressing agents that don't have the problem. Each agent's prompt should be tightened against measured failure, not speculative failure.

## Architecture

The Procedure section is the only structural change to `agents/source-collector.md`. The rest of the file (Job, Inputs, Output schema, Forbidden outputs §1–4, Failure handling) is untouched except for adding entry §5 to Forbidden outputs.

### Restructured Procedure

```markdown
## Procedure

You MUST complete the steps below in order. You MAY NOT proceed to step N+1
until step N has been completed AND its evidence is visible in your tool-call
history. You MAY NOT emit your final response until ALL applicable steps are
complete.

### Step 0 — Empty-window short-circuit (only valid skip path)

IF `last_sha` is empty (no prior successful run, fresh deployment, or state
reset), emit exactly `{"prs": [], "jira_issues": []}` and stop. This is the
ONLY case in which Steps 1–5 are skipped. Do not proceed past this step
otherwise.

### Step 1 (REQUIRED) — Enumerate merged PRs via `gh`

You MUST invoke `gh pr list ...` (or the equivalent
`gh api repos/<owner>/<name>/pulls?state=closed`). If you have not invoked
one of those tools, you have not completed Step 1.

The tool MUST be invoked even if you suspect the window is empty. Suspicion
is not evidence; tool output is. Emitting `prs: []` without first invoking
one of these tools is a contract violation (see Forbidden outputs §5).

Resolve `last_sha → merged_at` via `gh pr view <last_sha>` if needed, then
query merged PRs since that timestamp. Use:

gh pr list --state merged --search "merged:>=<merged_at_of_last_sha>"

or the `gh api` equivalent.

### Step 2 — Apply branch filter

Only proceed if Step 1 produced output. Exclude PRs whose source branch
matches any `pr_branch_filter` glob.

### Step 3 (REQUIRED if Step 1 returned ≥1 PR) — Pull per-PR metadata

For each remaining PR: pull `title`, `body`, `files` (truncate to 200 entries),
`labels`, `merge_commit_sha`, `merged_at`, `author.login`, `html_url`. Use
`gh api repos/<owner>/<name>/pulls/<number>` or `gh pr view <number> --json ...`.

If Step 1 returned 0 PRs, skip to Step 6 and emit `{"prs": [], "jira_issues": []}`.

### Step 4 — Parse jira_keys

Parse `jira_keys` from each PR's `title + body` using the regex `[A-Z]+-\d+`,
matching only project keys listed in `jira.project_keys`.

### Step 5 (REQUIRED if jira.enabled AND any jira_keys present) — Fetch Jira issues

For each unique Jira key, GET `{base_url}/rest/api/3/issue/{key}` and extract
`summary`, `description`, `status`, `labels`. If `jira.enabled` is false OR
no keys were parsed in Step 4, skip this step.

### Step 6 — Emit final JSON

Before emitting, verify:

- Have you invoked the tools required by Step 1, Step 3 (if applicable), and
  Step 5 (if applicable)?
- If `prs: []`, was Step 1's tool output actually empty (not just unread)?

If either check fails, return to the missing step. Otherwise emit the final
JSON per the Output schema. Return ONLY the JSON object — no prose, no
markdown fences, no commentary.
```

### New Forbidden outputs §5

```markdown
**Bad: emitting empty `prs: []` for a non-empty window without invoking
`gh pr list` first**:

This is the dominant failure mode observed in CCE-12's 5-run baseline
(4 of 5 runs). Returning `{"prs": [], "jira_issues": []}` when no
`gh pr list` (or `gh api repos/.../pulls`) call appears in your tool-call
history is a contract violation, even when `last_sha` is non-empty.

The orchestrator's diagnostic capture (CCE-12) records your tool calls
to `<agent>.stream.jsonl` and summarizes them in `meta.json["tool_use"]`.
Runs without the required tool call are auditable and will be flagged.

The only valid path to `prs: []` is:

1. Step 0 — `last_sha` is empty (no diff window exists), OR
2. Step 1's `gh pr list` actually returned zero merged PRs in the window.

Inferring `prs: []` from `git log`, `git branch`, schema introspection, or
any other tool that is not `gh pr list` / `gh api pulls` is the same
contract violation.
```

### Three Stage-4 deferred items (rolled in)

These three forward-compat hardening items were deferred from CCE-12's Stage 4 code review. CCE-14 bundles them because each is a small change and all three sit in the same dispatch-related code/test files.

**1. `_extract_final_assistant_text` hardening** — `scripts/orchestrator_runner.py:75-96`

Currently walks events and tracks the LAST assistant turn, even if that turn has only `tool_use` blocks and no `text` blocks. If the CLI ever closes a session with the final assistant turn being purely tool calls (the `result` event closes without a text response), the function returns `""` and the dispatch returns `None`, silently degrading to a partial reason.

Change: prefer the last assistant turn that contains at least one `text` block. Fall back to `""` only if no assistant turn has text content.

```python
def _extract_final_assistant_text(events: list[dict]) -> str:
    last_assistant_with_text: dict | None = None
    for ev in events:
        if ev.get("type") != "assistant":
            continue
        content = ev.get("message", {}).get("content", [])
        has_text = any(
            isinstance(b, dict) and b.get("type") == "text" for b in content
        )
        if has_text:
            last_assistant_with_text = ev
    if last_assistant_with_text is None:
        return ""
    content = last_assistant_with_text.get("message", {}).get("content", [])
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )
```

The existing four tests for this helper continue to pass; one new test exercises the no-text-final-turn case.

**2. `dispatch_subagent` docstring latency clarification** — `scripts/orchestrator_runner.py:164-…`

Add a paragraph to the docstring explaining that stream-json mode's per-run latency is dominated by the agent's tool-call decisions (e.g., CCE-12 Run 2 ran 74s with 5 tool calls; the other four Category-A runs completed in 3–6s), not the NDJSON parse overhead. This is appropriate for diagnostics but not for steady-state production where the `DOCS_AGENT_DEBUG_DIR` gate should be off.

**3. Test rename** — `tests/orchestrator/test_dispatch_debug_capture.py`

Rename `test_debug_capture_writes_files_when_env_var_set` → `test_debug_capture_writes_files_on_non_ndjson_stdout_gracefully`. The function body and assertions are unchanged; the new name makes the test's actual subject (graceful-degradation on degenerate input) explicit.

## File changes

| File                                                                                                                                          | Action                                            | Purpose                                                                            |
| --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `agents/source-collector.md`                                                                                                                  | Modify (Procedure section + Forbidden outputs §5) | Restructure Procedure as mandatory checklist; add fifth Forbidden-output entry     |
| `scripts/orchestrator_runner.py`                                                                                                              | Modify (lines 75–96, 164– docstring)              | Two helper hardening tweaks (one logic, one doc)                                   |
| `tests/orchestrator/test_dispatch_subagent_stream_json.py`                                                                                    | Modify (add 1 test)                               | Cover the no-text-final-turn case for the hardened `_extract_final_assistant_text` |
| `tests/orchestrator/test_dispatch_debug_capture.py`                                                                                           | Modify (rename one test)                          | Rename for intent clarity                                                          |
| `docs/superpowers/measurements/2026-05-20-cce14-prompt-hardening-baseline.md`                                                                 | Create                                            | Side-by-side comparison: CCE-12 (pre-fix) vs CCE-14 (post-fix) categorization      |
| `docs/superpowers/measurements/2026-05-20-cce14-run<N>-source-collector.{stream.jsonl,meta.json,stdout.txt,stderr.txt,prompt.txt}` for N=1..5 | Create (generated)                                | Raw per-run capture artifacts from the re-measurement ceremony                     |

## Success criteria

1. **Behavior:** A 5-run Mode B ceremony against the SAME SHA window CCE-12 used (`a2a9dba..f0e774c`) shows **≥4 of 5 runs in Category B/C/data-returned**. Specifically:
   - `total_calls > 0` AND at least one tool call is `gh pr list` or `gh api repos/.../pulls`.
   - Category A acceptable only when `last_sha` is empty (the documented Step-0 short-circuit).
2. **No regression:** Full test suite (174 tests) remains green. One new test for the hardened helper brings total to 175.
3. **Measurement doc:** `2026-05-20-cce14-prompt-hardening-baseline.md` contains a side-by-side table — CCE-12 runs in one column, CCE-14 runs in the next — and explicitly names the delta.
4. **Stage-4 deferreds closed:** All three items implemented in the same PR; CCE-12's code review notes can be marked addressed in the PR description.

## Out of scope (deferred)

- Other agents' Procedure sections (pr-summarizer, gap-detector, etc.). File separate tickets if measurement reveals the same pattern.
- Always-on stream-json as production default. Same trade-offs as CCE-12; separate decision.
- Tool-use budgets / retry-on-no-tool-calls / circuit breakers. These need post-fix baseline data to design well.
- Manifest version bump (0.1.1 → 0.1.5 to reflect accumulated CCE-9/10/11/12/14 work). Worth its own small bookkeeping ticket; not blocking.
- Restructuring agent prompts as XML-tagged blocks or forced multi-turn exchanges. Escalation path if checklist-style restructure proves insufficient.

## Risks and mitigations

| Risk                                                                   | Mitigation                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Restructure regresses CCE-10's canonical-shape compliance              | Output schema section is untouched; only Procedure changes. The CCE-12 instrumentation is still active for the re-measurement, so any shape regression is visible in the first run.                                                                                                                                                                                                                                                |
| Agent reads "you MUST" / "MAY NOT proceed" as guidance and still skips | This is the empirical bet. CCE-10 demonstrated the same agent does follow restructured prompts (5/5 canonical shape after the rewrite). If the re-measurement still shows persistent Category A, escalate to a different structural approach via a follow-up ticket (e.g., XML-tagged required-outputs format, or forced two-turn exchange). The escalation is cheap because CCE-14's measurement methodology is now standardized. |
| Step 6 self-verification creates a loop                                | Self-check is one sentence ("verify… if either check fails, return to the missing step"), not a recursive state machine. The agent reads it, runs the check, emits or retries once.                                                                                                                                                                                                                                                |
| `_extract_final_assistant_text` change breaks an existing test         | Tested manually against current fixtures: the with-tools fixture's final turn IS a text block, so behavior is identical for the canonical case. New test specifically covers the previously-untested no-text-final-turn case.                                                                                                                                                                                                      |
| Test rename breaks discovery in CI or local workflows                  | pytest discovers tests by `test_*` prefix and function name; no project tooling pins specific test names. Safe rename.                                                                                                                                                                                                                                                                                                             |

## Open questions

None blocking. The architectural decision (restructure vs. add-clauses) was settled in brainstorming based on the CCE-12 baseline data. Remaining choices (gate language, Forbidden-output §5 wording, deferred-item scoping) are made above as defensible defaults.
