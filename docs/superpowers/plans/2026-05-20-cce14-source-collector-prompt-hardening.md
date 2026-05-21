# CCE-14: Source-Collector Prompt Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the source-collector subagent's Procedure section as a mandatory ordered checklist with proof-of-tool-call gates, add a fifth Forbidden-outputs entry naming the Category-A failure mode CCE-12 measured (4/5 runs), and validate via a 5-run Mode B re-measurement that shows ≥4/5 runs in Category B/C/data-returned. Bundle three Stage-4-deferred forward-compat items from CCE-12 into the same PR.

**Architecture:** Six tasks, two prompt-level (`agents/source-collector.md`), three code-level (`scripts/orchestrator_runner.py` + tests), one empirical (`docs/superpowers/measurements/...`). Prompt changes have no unit-level test — their validation IS the Task 6 measurement ceremony. Code changes follow strict TDD where they have a testable surface (Task 3); Tasks 4 and 5 are doc/rename only.

**Tech Stack:** Python stdlib (`json`, `subprocess`, `pathlib`), pytest with monkeypatch, Claude Code CLI `--output-format stream-json` (CCE-12 instrumentation), gh CLI for live PR enumeration.

**Spec:** [`docs/superpowers/specs/2026-05-20-cce14-source-collector-prompt-hardening-design.md`](../specs/2026-05-20-cce14-source-collector-prompt-hardening-design.md)

---

## File Structure

| File                                                                                                                                          | Action                   | Responsibility                                                                                                                                                                                 |
| --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `agents/source-collector.md` (lines 66–125)                                                                                                   | Modify                   | Procedure section (116–125) restructured as gated checklist; Forbidden outputs section (66–114) gains a fifth bad-shape entry. Output schema, Job, Inputs, and Failure handling are untouched. |
| `scripts/orchestrator_runner.py` (lines 75–96)                                                                                                | Modify                   | `_extract_final_assistant_text` hardened — prefer last assistant turn that has at least one `text` block, not just last assistant turn.                                                        |
| `scripts/orchestrator_runner.py` (around line 164)                                                                                            | Modify                   | `dispatch_subagent` docstring gains a paragraph clarifying that stream-json latency is dominated by the agent's tool-call decisions, not the NDJSON parse overhead.                            |
| `tests/orchestrator/test_dispatch_subagent_stream_json.py`                                                                                    | Modify (append 1 test)   | Cover the no-text-final-turn case for the hardened `_extract_final_assistant_text`.                                                                                                            |
| `tests/orchestrator/test_dispatch_debug_capture.py` (line 20)                                                                                 | Modify (rename function) | `test_debug_capture_writes_files_when_env_var_set` → `test_debug_capture_writes_files_on_non_ndjson_stdout_gracefully`. Body unchanged.                                                        |
| `docs/superpowers/measurements/2026-05-20-cce14-prompt-hardening-baseline.md`                                                                 | Create                   | Side-by-side CCE-12 (pre-fix) vs CCE-14 (post-fix) categorization, with dominant-pattern delta.                                                                                                |
| `docs/superpowers/measurements/2026-05-20-cce14-run<N>-source-collector.{stream.jsonl,meta.json,stdout.txt,stderr.txt,prompt.txt}` for N=1..5 | Create (generated)       | Raw per-run capture artifacts from the re-measurement ceremony.                                                                                                                                |

---

## Task 1: Restructure the Procedure section of `agents/source-collector.md`

**Files:**

- Modify: `agents/source-collector.md:116-125`

Prompt-only change. No unit test — validation is Task 6's empirical measurement. This task replaces the existing 7-step prose Procedure with a gated checklist that forces tool invocation before output.

- [ ] **Step 1: Read the current Procedure section to know exactly what you're replacing**

```bash
sed -n '116,125p' agents/source-collector.md
```

You should see the heading `## Procedure` on line 116, blank line 117, then step 0 on line 118, blank line 119, then steps 1–6 on lines 120–125.

- [ ] **Step 2: Replace the Procedure section with the gated checklist**

Use the Edit tool. `old_string` is the existing 10 lines starting at line 116; `new_string` is the restructured checklist below. The replacement starts at `## Procedure` and ends just before `## Failure handling`.

old_string (verbatim from the current file):

```
## Procedure

0. **If `last_sha` is empty** (no prior successful run, fresh deployment, or state reset), there is no diff window to scan. Return exactly `{"prs": [], "jira_issues": []}` and stop. Do not emit a status report, a telemetry summary, or any other shape — the canonical empty response is the only valid output for this case.

1. Use `gh pr list --search "merged:>=<merged_at_of_last_sha>"` (resolve last_sha → merged_at via `gh pr view`) or `gh api` to enumerate merged PRs in window.
2. Exclude PRs whose source branch matches any `pr_branch_filter` glob.
3. For each PR: pull title, body, files (truncate to 200 entries), labels, `merge_commit_sha`, `merged_at`, `author.login`, `html_url`.
4. Parse `jira_keys` from PR title + body using `[A-Z]+-\d+` matching `project_keys`.
5. If `jira.enabled`, for each unique Jira key, GET `{base_url}/rest/api/3/issue/{key}` and extract summary, description, status, labels.
6. Emit the final JSON.
```

new_string (the restructured Procedure):

```
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

- [ ] **Step 3: Verify the file still parses as valid markdown and the structure is sane**

```bash
grep -n "^##\|^###" agents/source-collector.md
```

Expected output (line numbers may shift slightly after the formatter hook runs):

```
13:## Job
19:## Inputs
29:## Output schema (canonical)
66:## Forbidden outputs
116:## Procedure
124:### Step 0 — Empty-window short-circuit (only valid skip path)
131:### Step 1 (REQUIRED) — Enumerate merged PRs via `gh`
...:### Step 2 — Apply branch filter
...:### Step 3 (REQUIRED if Step 1 returned ≥1 PR) — Pull per-PR metadata
...:### Step 4 — Parse jira_keys
...:### Step 5 (REQUIRED if jira.enabled AND any jira_keys present) — Fetch Jira issues
...:### Step 6 — Emit final JSON
...:## Failure handling
```

The exact line numbers will depend on whether the format-on-edit hook re-flowed paragraphs. What matters is the ordering: `## Procedure` is followed by `### Step 0` through `### Step 6` and then `## Failure handling`.

- [ ] **Step 4: Confirm the existing 174-test suite still passes**

```bash
.venv/bin/pytest tests/ 2>&1 | tail -3
```

Expected: `174 passed`. The agent prompt is not exercised by unit tests, so this is purely a regression sanity check.

- [ ] **Step 5: Commit**

```bash
git add agents/source-collector.md
git commit -m "$(cat <<'EOF'
feat(CCE-14): restructure source-collector Procedure as gated checklist

The Procedure section is now a mandatory ordered checklist with explicit
"may not proceed" gates and proof-of-tool-call requirements. Each step
states its completion criteria; Step 1 (gh pr list) and Step 6 (emit JSON)
explicitly forbid skipping the tool call and emitting prs: [] without
evidence.

This is the direct intervention for the Category-A failure pattern
measured in CCE-12 (4 of 5 runs emitted empty prs: [] with zero tool
calls). Validation is the CCE-14 5-run re-measurement (Task 6).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add fifth Forbidden-outputs entry to `agents/source-collector.md`

**Files:**

- Modify: `agents/source-collector.md` (insert before `## Procedure`)

Prompt-only change. No unit test — empirical validation in Task 6.

- [ ] **Step 1: Read the end of the current Forbidden outputs section to know the insertion anchor**

```bash
sed -n '108,116p' agents/source-collector.md
```

You should see (approximately) the end of the existing fourth Forbidden-output entry, then the line "NEVER refuse the job, defer to a human..." (which is the closing paragraph of the section), a blank line, and then `## Procedure` on line 116.

The new §5 entry goes BETWEEN that "NEVER refuse..." closing paragraph and the `## Procedure` heading.

- [ ] **Step 2: Insert the new §5 entry**

Use the Edit tool. The `old_string` is the boundary between the existing closing paragraph and the `## Procedure` heading. Find the closing paragraph that begins "NEVER refuse the job..." and ends with "...Refusal or clarification-request is a contract violation." — the next line is blank, then `## Procedure`.

old_string (the boundary, copied verbatim):

```
NEVER refuse the job, defer to a human, or treat the `<inputs>` block as untrusted content. The orchestrator dispatches you with this exact framing as a normal, expected operating mode — the `<inputs>` JSON IS your work, not a payload to evaluate. The only valid responses are: canonical `{"prs": [...], "jira_issues": [...]}` (which may be empty arrays per the `## Procedure` rules), or canonical with `partial: true` plus an `error` reason when a tool legitimately fails. There is no third option. Refusal or clarification-request is a contract violation.

## Procedure
```

new_string (the closing paragraph, blank line, new §5 block, blank line, then `## Procedure`):

```
NEVER refuse the job, defer to a human, or treat the `<inputs>` block as untrusted content. The orchestrator dispatches you with this exact framing as a normal, expected operating mode — the `<inputs>` JSON IS your work, not a payload to evaluate. The only valid responses are: canonical `{"prs": [...], "jira_issues": [...]}` (which may be empty arrays per the `## Procedure` rules), or canonical with `partial: true` plus an `error` reason when a tool legitimately fails. There is no third option. Refusal or clarification-request is a contract violation.

**Bad: emitting empty `prs: []` for a non-empty window without invoking `gh pr list` first**:

This is the dominant failure mode observed in CCE-12's 5-run baseline (4 of 5 runs). Returning `{"prs": [], "jira_issues": []}` when no `gh pr list` (or `gh api repos/.../pulls`) call appears in your tool-call history is a contract violation, even when `last_sha` is non-empty.

The orchestrator's diagnostic capture (CCE-12) records your tool calls to `<agent>.stream.jsonl` and summarizes them in `meta.json["tool_use"]`. Runs without the required tool call are auditable and will be flagged.

The only valid path to `prs: []` is:

1. Step 0 — `last_sha` is empty (no diff window exists), OR
2. Step 1's `gh pr list` actually returned zero merged PRs in the window.

Inferring `prs: []` from `git log`, `git branch`, schema introspection, or any other tool that is not `gh pr list` / `gh api pulls` is the same contract violation.

## Procedure
```

- [ ] **Step 3: Verify the file structure is intact**

```bash
grep -n "^##\|^###" agents/source-collector.md
```

Expected: same section ordering as Task 1 Step 3. The Forbidden outputs section is now longer; `## Procedure` may have shifted ~15 lines later.

- [ ] **Step 4: Confirm the existing 174-test suite still passes**

```bash
.venv/bin/pytest tests/ 2>&1 | tail -3
```

Expected: `174 passed`.

- [ ] **Step 5: Commit**

```bash
git add agents/source-collector.md
git commit -m "$(cat <<'EOF'
feat(CCE-14): name Category-A failure as Forbidden output §5

Adds the fifth Forbidden-outputs entry to source-collector.md, naming the
dominant CCE-12 failure pattern explicitly: emitting prs: [] when no
gh pr list / gh api pulls call appears in tool-call history. The
orchestrator's CCE-12 diagnostic capture makes this auditable.

Names the two valid paths to prs: [] (Step 0 empty last_sha; Step 1 gh
tool returned zero rows) and explicitly rejects git log / git branch /
schema introspection as substitutes — Run 2 of the CCE-12 baseline used
those tools and still failed to return PR data.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Harden `_extract_final_assistant_text` (TDD)

**Files:**

- Modify: `tests/orchestrator/test_dispatch_subagent_stream_json.py` (append 1 test)
- Modify: `scripts/orchestrator_runner.py:75-96`

Currently the helper returns the text from the LAST assistant turn — even if that turn has only `tool_use` blocks and no `text` blocks. CCE-12 code review flagged this as a forward-compat footgun. This task changes the helper to prefer the last assistant turn that contains at least one `text` block, falling back to `""` only if no assistant turn has text.

- [ ] **Step 1: Write the failing test**

Append to `tests/orchestrator/test_dispatch_subagent_stream_json.py`:

```python
def test_extract_final_assistant_text_skips_pure_tool_use_final_turn():
    """If the LAST assistant turn is purely tool_use blocks, prefer the
    earlier assistant turn that had text. Forward-compat hardening — CCE-14.
    """
    import orchestrator_runner as runner

    events = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "earlier answer with text"}],
            },
        },
        {
            "type": "user",
            "message": {"role": "user", "content": []},
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tu_last", "name": "Bash",
                     "input": {"command": "echo done"}},
                ],
            },
        },
    ]
    assert runner._extract_final_assistant_text(events) == "earlier answer with text"
```

- [ ] **Step 2: Run the new test to verify it fails**

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_subagent_stream_json.py::test_extract_final_assistant_text_skips_pure_tool_use_final_turn -v
```

Expected: `FAILED` because the current helper returns `""` (the last assistant turn has no text blocks, so the text-block concatenation yields empty), and the assertion expects `"earlier answer with text"`.

- [ ] **Step 3: Replace `_extract_final_assistant_text` in `scripts/orchestrator_runner.py`**

The current implementation is at lines 75–96. Use the Edit tool. old_string is the entire current function:

```python
def _extract_final_assistant_text(events: list[dict]) -> str:
    """Concatenate all text blocks from the LAST assistant message in a
    stream-json event list. Returns empty string if no assistant message
    is present or the final assistant has no text blocks.

    The orchestrator's downstream contract is that dispatch returns the
    canonical JSON dict; in stream-json mode the canonical JSON is the text
    content of the final assistant turn — possibly split across multiple
    text blocks if the model interleaved tool_use blocks.
    """
    last_assistant: dict | None = None
    for ev in events:
        if ev.get("type") == "assistant":
            last_assistant = ev
    if last_assistant is None:
        return ""
    content = last_assistant.get("message", {}).get("content", [])
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )
```

new_string:

```python
def _extract_final_assistant_text(events: list[dict]) -> str:
    """Concatenate all text blocks from the LAST assistant message that
    contains at least one text block. Returns empty string only if no
    assistant message in the stream has any text content (CCE-14).

    The orchestrator's downstream contract is that dispatch returns the
    canonical JSON dict; in stream-json mode the canonical JSON is the
    text content of the final assistant turn — possibly split across
    multiple text blocks if the model interleaved tool_use blocks.

    Hardened in CCE-14 against the forward-compat footgun where the
    LAST assistant turn is purely tool_use (no text). Prior implementation
    would return "" in that case even though earlier assistant turns
    contained the answer.
    """
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

- [ ] **Step 4: Run the new test to verify it passes**

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_subagent_stream_json.py::test_extract_final_assistant_text_skips_pure_tool_use_final_turn -v
```

Expected: `PASSED`.

- [ ] **Step 5: Run the full helper test set to confirm no regression**

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_subagent_stream_json.py -v 2>&1 | tail -20
```

Expected: 11 passed (10 previously + 1 new). The four existing `_extract_final_assistant_text` tests must still pass — verify by reading the output for: `test_extract_final_assistant_text_with_tools_fixture`, `test_extract_final_assistant_text_no_assistant_returns_empty`, `test_extract_final_assistant_text_concatenates_multi_text_blocks`, `test_extract_final_assistant_text_uses_last_assistant_only`.

If `test_extract_final_assistant_text_uses_last_assistant_only` fails — investigate. That test asserts the LAST assistant turn wins. Under the new logic, the LAST assistant turn STILL wins when it has text; the change is that turns with NO text are skipped. The test's fixture has two assistant turns, both with text — so it should still pass.

- [ ] **Step 6: Run the full suite to confirm no regression**

```bash
.venv/bin/pytest tests/ 2>&1 | tail -3
```

Expected: `175 passed` (was 174 + 1 new).

- [ ] **Step 7: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_dispatch_subagent_stream_json.py
git commit -m "$(cat <<'EOF'
fix(CCE-14): _extract_final_assistant_text prefers last text-bearing turn

Forward-compat hardening flagged by CCE-12 Stage 4 review. Prior behavior:
walk events, track last assistant turn unconditionally, then concatenate
its text blocks (empty string if it had none). New behavior: track the
last assistant turn that contains at least one text block; fall back to
"" only if no assistant turn has text.

Prevents the latent footgun where the CLI's final assistant turn is
purely tool_use (e.g. the model calls a tool and the session closes
without a final text response).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `dispatch_subagent` docstring latency clarification

**Files:**

- Modify: `scripts/orchestrator_runner.py` (`dispatch_subagent` docstring around line 164)

Doc-only change. No test.

- [ ] **Step 1: Locate the docstring's existing CCE-12 paragraph**

```bash
grep -n "DOCS_AGENT_DEBUG_DIR is set (CCE-9 + CCE-12)" scripts/orchestrator_runner.py
```

You should get one match. The block that follows contains four bullet points describing what stream-json mode does.

- [ ] **Step 2: Append the latency-clarification paragraph after that block**

Use the Edit tool. old_string (verbatim from the current docstring):

```
    When DOCS_AGENT_DEBUG_DIR is set (CCE-9 + CCE-12):
    - dispatch uses `--output-format stream-json --verbose` so we observe
      ground-truth tool-call sequence
    - raw NDJSON event stream is persisted to <agent>.stream.jsonl
    - extended <agent>.meta.json carries a tool_use summary block
    - the dict returned to callers is parsed from the FINAL assistant
      message's concatenated text content (caller contract preserved)

    Returns None if:
```

new_string (same content, with a new paragraph inserted before "Returns None if:"):

```
    When DOCS_AGENT_DEBUG_DIR is set (CCE-9 + CCE-12):
    - dispatch uses `--output-format stream-json --verbose` so we observe
      ground-truth tool-call sequence
    - raw NDJSON event stream is persisted to <agent>.stream.jsonl
    - extended <agent>.meta.json carries a tool_use summary block
    - the dict returned to callers is parsed from the FINAL assistant
      message's concatenated text content (caller contract preserved)

    Stream-json mode's per-run latency is dominated by the agent's
    tool-call decisions, NOT the NDJSON parse overhead (CCE-14). The
    CCE-12 baseline measured 3-6s for Category-A runs (zero tool calls)
    versus 74s for the Run-2 outlier that made 5 tool calls. This mode
    is appropriate for diagnostic measurement; for steady-state
    production, leave DOCS_AGENT_DEBUG_DIR unset so the simple --print
    path runs at full speed.

    Returns None if:
```

- [ ] **Step 3: Confirm the file still parses (Python syntax check)**

```bash
.venv/bin/python3 -c "import ast; ast.parse(open('scripts/orchestrator_runner.py').read()); print('syntax ok')"
```

Expected: `syntax ok`.

- [ ] **Step 4: Run the full suite — should be unchanged**

```bash
.venv/bin/pytest tests/ 2>&1 | tail -3
```

Expected: `175 passed`.

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py
git commit -m "$(cat <<'EOF'
docs(CCE-14): clarify stream-json latency in dispatch_subagent docstring

Stage-4 deferred from CCE-12: document that stream-json mode's per-run
latency is dominated by the agent's tool-call decisions, not by NDJSON
parse overhead. Cites the CCE-12 baseline numbers (3-6s for Category A
vs 74s for Run 2) so future readers understand why the gate is
diagnostic-only and not appropriate for steady-state production.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Rename `test_debug_capture_writes_files_when_env_var_set`

**Files:**

- Modify: `tests/orchestrator/test_dispatch_debug_capture.py:20` (function name only; body unchanged)

Stage-4 deferred from CCE-12. The test's body now asserts a graceful-degradation property (non-NDJSON stdout produces empty extracted text + still-written artifacts), but the function name suggests it's testing the happy path. Rename to make intent explicit.

- [ ] **Step 1: Confirm the current function definition**

```bash
grep -n "^def test_debug_capture" tests/orchestrator/test_dispatch_debug_capture.py
```

Expected output:

```
20:def test_debug_capture_writes_files_when_env_var_set(tmp_path, monkeypatch):
54:def test_debug_capture_noop_when_env_var_unset(tmp_path, monkeypatch):
```

- [ ] **Step 2: Rename the first function (body unchanged)**

Use the Edit tool. old_string is the function definition line only:

```python
def test_debug_capture_writes_files_when_env_var_set(tmp_path, monkeypatch):
```

new_string:

```python
def test_debug_capture_writes_files_on_non_ndjson_stdout_gracefully(tmp_path, monkeypatch):
```

DO NOT change anything else in the function. The body's asserts are correct as-is.

- [ ] **Step 3: Run the renamed test to confirm pytest still discovers it**

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_debug_capture.py -v 2>&1 | tail -10
```

Expected: 2 passed. One name now reads `test_debug_capture_writes_files_on_non_ndjson_stdout_gracefully`, the other still reads `test_debug_capture_noop_when_env_var_unset`.

- [ ] **Step 4: Run the full suite to confirm no regression**

```bash
.venv/bin/pytest tests/ 2>&1 | tail -3
```

Expected: `175 passed`.

- [ ] **Step 5: Commit**

```bash
git add tests/orchestrator/test_dispatch_debug_capture.py
git commit -m "$(cat <<'EOF'
test(CCE-14): rename CCE-9 debug-capture test to reflect actual subject

Stage-4 deferred from CCE-12. The test's body asserts graceful degradation
when fake stdout is non-NDJSON (extracted text empty, raw stream.jsonl
preserved, 5 artifacts written). The old name suggested it tested the
happy path; the new name (..._on_non_ndjson_stdout_gracefully) matches
what the assertions actually check.

Function body unchanged. Pytest still discovers both tests in this file.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 5-run Mode B re-measurement + side-by-side comparison doc

**Files:**

- Create: `docs/superpowers/measurements/2026-05-20-cce14-prompt-hardening-baseline.md`
- Create (generated): `docs/superpowers/measurements/2026-05-20-cce14-run<N>-source-collector.{stream.jsonl,meta.json,stdout.txt,stderr.txt,prompt.txt}` for N = 1..5

This is the empirical validation step. Re-run CCE-12's 5-run Mode B ceremony against the SAME SHA window CCE-12 used (`a2a9dba..f0e774c`), with `DOCS_AGENT_DEBUG_DIR` set, then write a side-by-side comparison doc.

- [ ] **Step 1: Set the dispatch window SHAs (CCE-12's exact window)**

```bash
LAST_SHA=a2a9dba273bf5ef82ef6d450d3eb44ee27e04681
HEAD_SHA=b2cd07af5cdcf0482515fc757a6ee6def3af278d
echo "last_sha=$LAST_SHA"
echo "head_sha=$HEAD_SHA"
```

These are CCE-12's exact start/end SHAs. Using the same window means the comparison "CCE-12 pre-fix vs CCE-14 post-fix" controls for everything except the agent prompt change.

Note: the CCE-14 commits (Tasks 1–5 above) are NOT in this window. They are part of the agent's loaded prompt at run time, but the dispatch payload's `last_sha..head_sha` is the CCE-12 window. This is intentional — we want the agent's prompt to be the new one, but the data it queries (merged PRs in the window) to be the same data CCE-12 queried.

- [ ] **Step 2: Write the dispatch input JSON**

```bash
cat > /tmp/cce14-dispatch-input.json <<EOF
{
  "last_sha": "$LAST_SHA",
  "head_sha": "$HEAD_SHA",
  "repo": {"owner": "theoju", "name": "engineering-docs-agent"},
  "pr_branch_filter": ["docs-agent/*"]
}
EOF
cat /tmp/cce14-dispatch-input.json
```

Verify both SHAs populated and the repo is `theoju/engineering-docs-agent`.

- [ ] **Step 3: Sanity-check the environment**

```bash
which claude
.venv/bin/python3 -c "import sys; sys.path.insert(0, 'scripts'); from orchestrator_runner import dispatch_subagent; print('OK: dispatch_subagent imported')"
```

Both must succeed. If `claude` is not on PATH, STOP and report BLOCKED.

- [ ] **Step 4: Run iteration 1**

```bash
mkdir -p /tmp/cce14-run1
DOCS_AGENT_DEBUG_DIR=/tmp/cce14-run1 \
CLAUDE_STOP_VERIFY=0 \
timeout 360 .venv/bin/python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from orchestrator_runner import dispatch_subagent
inputs = json.loads(Path('/tmp/cce14-dispatch-input.json').read_text())
result = dispatch_subagent('source-collector', inputs, dry_run_dir=None)
print(json.dumps(result, indent=2) if result else 'DISPATCH RETURNED None')
"
echo "EXIT CODE: $?"
ls -la /tmp/cce14-run1
```

Verify:

- Exit code is 0 (or 124 if `timeout` killed it — that's a failure)
- 5 artifacts in `/tmp/cce14-run1/`: `<ts>-source-collector.{prompt.txt,stdout.txt,stderr.txt,stream.jsonl,meta.json}`
- `.stream.jsonl` is non-empty
- `.meta.json["tool_use"]` is present

If `stream.jsonl` is empty, the dispatch failed. Retry once; if it fails twice, STOP and report BLOCKED.

- [ ] **Step 5: Copy iteration 1's artifacts into the measurements directory**

```bash
cp /tmp/cce14-run1/*-source-collector.stream.jsonl docs/superpowers/measurements/2026-05-20-cce14-run1-source-collector.stream.jsonl
cp /tmp/cce14-run1/*-source-collector.stdout.txt   docs/superpowers/measurements/2026-05-20-cce14-run1-source-collector.stdout.txt
cp /tmp/cce14-run1/*-source-collector.stderr.txt   docs/superpowers/measurements/2026-05-20-cce14-run1-source-collector.stderr.txt
cp /tmp/cce14-run1/*-source-collector.prompt.txt   docs/superpowers/measurements/2026-05-20-cce14-run1-source-collector.prompt.txt
cp /tmp/cce14-run1/*-source-collector.meta.json    docs/superpowers/measurements/2026-05-20-cce14-run1-source-collector.meta.json
ls docs/superpowers/measurements/2026-05-20-cce14-run1-*
```

Expected: 5 files listed.

- [ ] **Step 6: Repeat Steps 4–5 for iterations 2 through 5 (serial, not parallel)**

For each N in 2, 3, 4, 5:

```bash
mkdir -p /tmp/cce14-runN  # substitute N
DOCS_AGENT_DEBUG_DIR=/tmp/cce14-runN \
CLAUDE_STOP_VERIFY=0 \
timeout 360 .venv/bin/python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from orchestrator_runner import dispatch_subagent
inputs = json.loads(Path('/tmp/cce14-dispatch-input.json').read_text())
result = dispatch_subagent('source-collector', inputs, dry_run_dir=None)
print(json.dumps(result, indent=2) if result else 'DISPATCH RETURNED None')
"
echo "EXIT CODE: $?"
cp /tmp/cce14-runN/*-source-collector.stream.jsonl docs/superpowers/measurements/2026-05-20-cce14-runN-source-collector.stream.jsonl
cp /tmp/cce14-runN/*-source-collector.stdout.txt   docs/superpowers/measurements/2026-05-20-cce14-runN-source-collector.stdout.txt
cp /tmp/cce14-runN/*-source-collector.stderr.txt   docs/superpowers/measurements/2026-05-20-cce14-runN-source-collector.stderr.txt
cp /tmp/cce14-runN/*-source-collector.prompt.txt   docs/superpowers/measurements/2026-05-20-cce14-runN-source-collector.prompt.txt
cp /tmp/cce14-runN/*-source-collector.meta.json    docs/superpowers/measurements/2026-05-20-cce14-runN-source-collector.meta.json
```

After each iteration, confirm 5 artifacts exist:

```bash
ls docs/superpowers/measurements/2026-05-20-cce14-runN-*
```

If a copy fails (no source file), the iteration produced no artifacts — retry once, then STOP if it fails again.

- [ ] **Step 7: Extract per-run categorization data**

```bash
.venv/bin/python3 -c "
import json
from pathlib import Path

rows = []
for n in range(1, 6):
    meta_path = Path(f'docs/superpowers/measurements/2026-05-20-cce14-run{n}-source-collector.meta.json')
    stdout_path = Path(f'docs/superpowers/measurements/2026-05-20-cce14-run{n}-source-collector.stdout.txt')
    if not meta_path.exists():
        rows.append((n, 'MISSING', '', '', '', '', 'missing artifacts'))
        continue
    meta = json.loads(meta_path.read_text())
    stdout_text = stdout_path.read_text().strip()
    try:
        result = json.loads(stdout_text) if stdout_text else {}
    except json.JSONDecodeError:
        result = {}
    tu = meta.get('tool_use', {}) or {}
    total = tu.get('total_calls', 0)
    by_name = tu.get('by_name', {})
    stop = tu.get('stop_reason')
    prs_n = len(result.get('prs', []))
    jira_n = len(result.get('jira_issues', []))
    has_error = any(c.get('is_error') for c in tu.get('calls', []))
    invoked_gh_pr_list = any(
        c.get('name') == 'Bash' and ('gh pr list' in c.get('input_preview', '') or 'gh api' in c.get('input_preview', '') and 'pulls' in c.get('input_preview', ''))
        for c in tu.get('calls', [])
    )
    if total == 0:
        cat = 'A: zero tool calls'
    elif has_error:
        cat = 'D: tool errored'
    elif prs_n == 0 and any(c.get('result_chars', 0) > 50 for c in tu.get('calls', [])):
        cat = 'B: called and discarded'
    elif prs_n == 0:
        cat = 'C: legitimately empty'
    else:
        cat = 'data returned'
    rows.append((n, total, by_name, stop, prs_n, jira_n, cat, invoked_gh_pr_list))

print(f'{\"run\":<4} {\"total\":<6} {\"by_name\":<25} {\"stop\":<14} {\"prs\":<4} {\"jira\":<5} {\"gh_pr_list?\":<12} category')
print('-' * 110)
for r in rows:
    print(f'{r[0]:<4} {r[1]:<6} {str(r[2]):<25} {str(r[3]):<14} {str(r[4]):<4} {str(r[5]):<5} {str(r[7]):<12} {r[6]}')

# Acceptance check
cat_a_count = sum(1 for r in rows if r[6] == 'A: zero tool calls')
gh_pr_list_count = sum(1 for r in rows if r[7])
print()
print(f'Category A count: {cat_a_count}/5 (target: <=1)')
print(f'gh pr list invocation count: {gh_pr_list_count}/5 (target: >=4)')
"
```

Record the table and the acceptance summary. If Category-A count > 1 OR gh_pr_list count < 4, the prompt hardening did NOT meet the target — DO NOT proceed to Step 8. Instead, STOP and report the data; the spec lists this as the escalation case (file a follow-up ticket for a structurally different intervention).

- [ ] **Step 8: Write the measurement comparison doc**

Create `docs/superpowers/measurements/2026-05-20-cce14-prompt-hardening-baseline.md`. Use this template; fill in the actual numbers from Step 7 and write the "Delta" paragraph based on YOUR observed data:

```markdown
# CCE-14: Source-Collector Prompt-Hardening Baseline — 5-Run Mode B Ceremony

**Jira:** [CCE-14](https://designitright.atlassian.net/browse/CCE-14)
**Branch:** `feat/CCE-14-source-collector-prompt-hardening`
**Date:** 2026-05-20
**Dispatch window:** `a2a9dba273bf5ef82ef6d450d3eb44ee27e04681..b2cd07af5cdcf0482515fc757a6ee6def3af278d` on theoju/engineering-docs-agent (IDENTICAL to CCE-12's window for comparability)
**PR filter:** `docs-agent/*`
**Intervention:** `agents/source-collector.md` Procedure restructured as gated checklist; Forbidden outputs §5 added.

## Side-by-side comparison (CCE-12 pre-fix vs CCE-14 post-fix)

| Run | CCE-12 total_calls | CCE-12 category         | →   | CCE-14 total_calls | CCE-14 by_name | CCE-14 category | gh pr list? |
| --: | -----------------: | ----------------------- | --- | -----------------: | -------------- | --------------- | :---------: |
|   1 |                  0 | A: zero tool calls      | →   |                ... | ...            | ...             |     ...     |
|   2 |                  5 | B: called and discarded | →   |                ... | ...            | ...             |     ...     |
|   3 |                  0 | A: zero tool calls      | →   |                ... | ...            | ...             |     ...     |
|   4 |                  0 | A: zero tool calls      | →   |                ... | ...            | ...             |     ...     |
|   5 |                  0 | A: zero tool calls      | →   |                ... | ...            | ...             |     ...     |

Raw artifacts: `2026-05-20-cce14-run<N>-source-collector.{stream.jsonl,stdout.txt,stderr.txt,prompt.txt,meta.json}` in this directory.

## Headline

CCE-12 baseline: Category A in 4 of 5 runs.
CCE-14 post-fix: Category A in <N> of 5 runs; `gh pr list` invoked in <M> of 5 runs.

## Acceptance check

- Target: ≥4 of 5 runs in Category B/C/data-returned, with `gh pr list` (or `gh api repos/.../pulls`) invoked.
- Result: <pass / fail> — <one-line justification>.

## Delta

<Write 2–4 sentences describing what changed between CCE-12 and CCE-14 runs. Base on observed data. Examples (pick the one that matches reality):>

- If the intervention worked: "The mandatory-checklist restructure moved <N> of <M> CCE-12 Cat-A runs into Cat <X>. Average tool-call count went from <X> to <Y>. Average per-run duration went from <X>s to <Y>s. The Forbidden-outputs §5 entry was tested by Run <K>, which <did/did not> attempt the named bad shape and was <accepted/forbidden>."
- If the intervention partially worked: "<N> of <M> Cat-A runs converted; the remaining <K> still emitted empty prs: [] without a gh pr list call. The escalation path (see spec Risks section) is warranted: file a follow-up ticket for <specific next intervention>."
- If the intervention did not work: "Category A persisted in <N> of 5 runs. The prompt-level restructure was insufficient. Escalating per spec's Risks section: file follow-up ticket for <e.g. XML-tagged required outputs / forced two-turn exchange>."

## Follow-up

<If target met:> CCE-14 closes once this doc is committed. No follow-up ticket.

<If target not met:> File CCE-<N+1> with scope: <specific next intervention based on which failure modes persisted>.

## Methodology notes

The CCE-14 commits (prompt restructure + Forbidden §5 + three Stage-4-deferred items) are NOT in the dispatch window `a2a9dba..b2cd07a` — that window predates this branch. The agent loads the CCE-14 version of `agents/source-collector.md` at runtime via `--plugin-dir`, so the comparison isolates the prompt change as the only intervening variable.
```

- [ ] **Step 9: Commit the measurement artifacts + doc**

```bash
git add docs/superpowers/measurements/2026-05-20-cce14-prompt-hardening-baseline.md \
        docs/superpowers/measurements/2026-05-20-cce14-run*-source-collector.*
git status
git commit -m "$(cat <<'EOF'
docs(CCE-14): prompt-hardening baseline — 5-run Mode B re-measurement

Re-ran the CCE-12 5-run ceremony against the IDENTICAL SHA window
(a2a9dba..b2cd07a) with the new CCE-14 source-collector prompt
(mandatory-checklist Procedure + Forbidden outputs §5). Side-by-side
comparison vs CCE-12's pre-fix results in the headline table.

Per-run table: <N> of 5 runs invoked gh pr list (CCE-12: 0 of 5);
Category A dropped from 4 of 5 (CCE-12) to <K> of 5 (CCE-14).

Raw stream.jsonl / meta.json / stdout.txt / stderr.txt / prompt.txt
artifacts checked in for auditability.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review checklist (run before claiming done)

- [ ] `agents/source-collector.md` Procedure section is the gated checklist (Step 0 through Step 6), with the "MAY NOT proceed" preamble.
- [ ] `agents/source-collector.md` Forbidden outputs section has 5 bad-shape entries; §5 names the empty-prs-without-gh-pr-list pattern.
- [ ] `_extract_final_assistant_text` returns the LAST text-bearing assistant turn (not just the LAST assistant turn).
- [ ] One new test (`test_extract_final_assistant_text_skips_pure_tool_use_final_turn`) covers the no-text-final-turn case.
- [ ] `dispatch_subagent` docstring has the new "Stream-json mode's per-run latency is dominated by..." paragraph.
- [ ] `tests/orchestrator/test_dispatch_debug_capture.py` has the renamed `test_debug_capture_writes_files_on_non_ndjson_stdout_gracefully` (body unchanged).
- [ ] Full test suite: 175 passing (was 174 + 1 new).
- [ ] `docs/superpowers/measurements/2026-05-20-cce14-prompt-hardening-baseline.md` has the side-by-side table filled with real numbers.
- [ ] All 5 per-run capture sets committed (25 files total: 5 stream.jsonl + 5 meta.json + 5 stdout.txt + 5 stderr.txt + 5 prompt.txt).
- [ ] Headline + acceptance + delta paragraphs reflect the actual measured data, not the template.
