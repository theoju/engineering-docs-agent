# CCE-10 Source-collector canonical-shape compliance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make source-collector emit canonical `{"prs":[…],"jira_issues":[…]}` on 5/5 consecutive Mode B runs by closing the three confirmed root causes from CCE-9 + CCE-11 evidence (hook stdout contamination, status-report reflex, F1 `issues`/`jira_issues` rename).

**Architecture:** Three independent fixes shipped as one PR. Fix 1 is a 3-line code change to `scripts/orchestrator_runner.py` that passes `CLAUDE_STOP_VERIFY=0` to every subprocess invocation, neutralizing the global `~/.claude/hooks/stop-verify.sh` for child Claude sessions. Fixes 2 and 3 are two surgical edits to `agents/source-collector.md`: add a new `## Forbidden outputs` subsection naming the observed bad shapes with concrete JSON examples, and remove the legacy `## Output contract` block (current lines 66-99) that redundantly duplicates the canonical schema. Final ceremony is 5 consecutive Mode B runs against the CCE-11 self-host harness captured with `DOCS_AGENT_DEBUG_DIR`.

**Tech Stack:** Python 3 (stdlib + pytest + monkeypatch), Claude Code CLI (`claude -p ... --agent ...`), bash, gh CLI. No new dependencies.

**Branch:** `feat/CCE-10-source-collector-canonical-shape` (already created off `main`; spec already committed at `7f337be`).

**Spec:** `docs/superpowers/specs/2026-05-20-cce10-source-collector-canonical-shape-design.md`

---

## File structure

| File                                                                                     | Action | Responsibility                                                                                                                                                           |
| ---------------------------------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `tests/orchestrator/test_dispatch_subagent_env.py`                                       | Create | Unit test that asserts `dispatch_subagent` passes `CLAUDE_STOP_VERIFY=0` to subprocess `env` while preserving the rest of `os.environ`                                   |
| `scripts/orchestrator_runner.py`                                                         | Modify | `dispatch_subagent()` body: insert `env={**os.environ, "CLAUDE_STOP_VERIFY": "0"}` overlay and pass via `run_kwargs["env"]`                                              |
| `agents/source-collector.md`                                                             | Modify | Remove legacy `## Output contract` block (current lines 66-99) and add a new `## Forbidden outputs` subsection between `## Output schema (canonical)` and `## Procedure` |
| `docs/superpowers/measurements/2026-05-20-cce10-canonical-shape-validation.md`           | Create | Per-run outcome table, summary, conclusion (pass/fail vs 5/5 criterion)                                                                                                  |
| `docs/superpowers/measurements/2026-05-20-cce10-run<N>-source-collector-stdout.txt` (×5) | Create | Raw captured stdout per run from `DOCS_AGENT_DEBUG_DIR`                                                                                                                  |

---

## Conventions

- **Branch:** Already on `feat/CCE-10-source-collector-canonical-shape` (created off main at `3a73edc`).
- **Commit subject prefix:** `fix(CCE-10): ...` for code/prompt commits, `docs(CCE-10): ...` for the measurement doc. Include `CCE-10` in the subject per CLAUDE.md so the Atlassian GitHub integration auto-links.
- **Co-author trailer:** `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` on every commit (matches the project's recent commit style).
- **Test runner:** `pytest` from the repo root. Tests live under `tests/`. Existing suite has 163 tests; never let it drop.

---

## Task 1: dispatch_subagent env passthrough

**Files:**

- Create: `tests/orchestrator/test_dispatch_subagent_env.py`
- Modify: `scripts/orchestrator_runner.py:118-124` (insert env overlay before `subprocess.run` call)

The existing CCE-9 test at `tests/orchestrator/test_dispatch_debug_capture.py` establishes the monkeypatch pattern for this module. Follow it. The key difference: we need to capture the `kwargs` (not just return a fake), so we use a closure rather than a `lambda`.

- [ ] **Step 1.1: Write the failing test**

Create `tests/orchestrator/test_dispatch_subagent_env.py` with this content:

```python
"""CCE-10: dispatch_subagent passes CLAUDE_STOP_VERIFY=0 to subprocess env so
the global stop-verify hook does not contaminate subagent stdout with a
"Verification statement:" prose preamble that breaks json.loads()."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))


class _FakeCompleted:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_dispatch_subagent_sets_stop_verify_off(monkeypatch):
    import orchestrator_runner as runner

    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _FakeCompleted(stdout='{"prs": [], "jira_issues": []}')

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.delenv("DOCS_AGENT_DEBUG_DIR", raising=False)

    result = runner.dispatch_subagent(
        "source-collector",
        {"last_sha": "abc", "head_sha": "def", "repo": {"owner": "x", "name": "y"}},
        dry_run_dir=None,
    )

    assert result == {"prs": [], "jira_issues": []}

    env = captured["kwargs"].get("env")
    assert env is not None, (
        "dispatch_subagent must pass an explicit env dict to subprocess.run "
        "so CLAUDE_STOP_VERIFY=0 reaches the child Claude session"
    )
    assert env.get("CLAUDE_STOP_VERIFY") == "0", (
        "env must set CLAUDE_STOP_VERIFY=0 to disable the stop-verify hook "
        "(see ~/.claude/hooks/stop-verify.sh:22)"
    )
    # Sanity check: env must EXTEND os.environ, not replace it. Otherwise
    # the child Claude session loses PATH, HOME, and every other variable
    # the subprocess needs.
    assert env.get("PATH") == os.environ.get("PATH"), (
        "env should extend os.environ via {**os.environ, ...} overlay, "
        "not replace it"
    )
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `pytest tests/orchestrator/test_dispatch_subagent_env.py -v`

Expected: FAIL with `AssertionError: dispatch_subagent must pass an explicit env dict to subprocess.run ...` (because `dispatch_subagent` does not currently pass `env`, so `captured["kwargs"].get("env")` returns None).

- [ ] **Step 1.3: Implement env passthrough in dispatch_subagent**

Open `scripts/orchestrator_runner.py`. Find the block (currently lines 118-124):

```python
    run_kwargs: dict = {"capture_output": True, "text": True, "check": False}
    if cwd is not None:
        run_kwargs["cwd"] = str(cwd)
    try:
        r = subprocess.run(argv, **run_kwargs)
    except FileNotFoundError:
        return None
```

Insert the env overlay between the `cwd` block and the `try` block, so the block becomes:

```python
    run_kwargs: dict = {"capture_output": True, "text": True, "check": False}
    if cwd is not None:
        run_kwargs["cwd"] = str(cwd)
    # CCE-10: pass CLAUDE_STOP_VERIFY=0 so the global stop-verify hook does
    # not contaminate subagent stdout with a "Verification statement:" prose
    # preamble that breaks json.loads(). See agents/source-collector.md and
    # ~/.claude/hooks/stop-verify.sh:22.
    run_kwargs["env"] = {**os.environ, "CLAUDE_STOP_VERIFY": "0"}
    try:
        r = subprocess.run(argv, **run_kwargs)
    except FileNotFoundError:
        return None
```

- [ ] **Step 1.4: Run test to verify it passes**

Run: `pytest tests/orchestrator/test_dispatch_subagent_env.py -v`

Expected: PASS (1 test).

- [ ] **Step 1.5: Run full test suite to verify no regression**

Run: `pytest`

Expected: PASS (164 tests — 163 existing + 1 new).

- [ ] **Step 1.6: Commit**

```bash
git add tests/orchestrator/test_dispatch_subagent_env.py scripts/orchestrator_runner.py
git commit -m "$(cat <<'EOF'
fix(CCE-10): dispatch_subagent passes CLAUDE_STOP_VERIFY=0 to subprocess env

The global ~/.claude/hooks/stop-verify.sh fires inside child Claude sessions
spawned by dispatch_subagent and asks the agent to verify its work. The
agent's verification preamble leaks into stdout before the JSON, breaking
json.loads() in dispatch_subagent. The hook documents its own escape hatch
at line 22: CLAUDE_STOP_VERIFY=0.

Closes the first of three root causes documented in
docs/superpowers/measurements/2026-05-20-cce9-h4-validation.md.

This commit is independently shippable: it unblocks JSON parsing for ALL
subagent dispatches, not just source-collector.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: source-collector.md prompt edits

**Files:**

- Modify: `agents/source-collector.md` (remove current lines 66-99 = legacy `## Output contract` block; insert new `## Forbidden outputs` subsection between current `## Output schema (canonical)` and `## Procedure`)

Both edits live in the same file and travel together — they represent the prompt-side half of CCE-10. Do both before running tests, then commit as one unit.

- [ ] **Step 2.1: Remove the legacy `## Output contract` block**

Open `agents/source-collector.md`. Find this block (currently lines 66-99):

````markdown
## Output contract

The canonical schema is in §Output schema above. The shape described here is the same; the schema is authoritative if they disagree.

Return ONLY a JSON object matching:

```json
{
  "prs": [
    {
      "number": 142,
      "title": "...",
      "body": "...",
      "merge_sha": "abc123",
      "merged_at": "2026-05-19T07:00:00Z",
      "author": "user",
      "files": [{ "path": "...", "additions": 0, "deletions": 0 }],
      "labels": ["..."],
      "jira_keys": ["ADIS-235"],
      "url": "https://github.com/owner/repo/pull/142"
    }
  ],
  "jira_issues": [
    {
      "key": "ADIS-235",
      "summary": "...",
      "description": "...",
      "status": "Done",
      "labels": ["architecture"],
      "url": "https://acme.atlassian.net/browse/ADIS-235"
    }
  ]
}
```
````

Delete it entirely (the entire `## Output contract` heading through the closing ` ``` ` of its JSON example).

- [ ] **Step 2.2: Add the `## Forbidden outputs` subsection**

In `agents/source-collector.md`, insert this new section between the closing line of `## Output schema (canonical)` (the line `Return ONLY a JSON object that validates against this schema. No prose, no markdown fences around the response, no commentary.`) and the `## Procedure` heading:

`````markdown
## Forbidden outputs

NEVER emit any of these shapes. The agent has been observed to invent them when "no work to do." They will fail schema validation and break the orchestrator pipeline.

**Bad: status-report / telemetry shape** (the agent reflexively emits this when there are no PRs in the diff window — do not):

```json
{
  "status": "idle",
  "reason": "...",
  "commits_analyzed": 0,
  "branches_scanned": 0,
  "files_modified": 0
}
```

If `last_sha..HEAD` contains no merged PRs, the correct response is `{"prs": [], "jira_issues": []}`, NOT a status report.

**Bad: array renamed `issues` (or `jira` or `tickets`)**:

```json
{ "prs": [], "issues": [] }
```

The Jira array MUST be named exactly `jira_issues`. Never `issues`, `jira`, `tickets`, `jira_keys`, or any synonym. The schema's `required: ["prs", "jira_issues"]` is non-negotiable.

**Bad: prose preamble before the JSON**:

```
Verification statement:
- No files were changed in this turn.
- ...

{"prs": [], "jira_issues": []}
```

Return ONLY the JSON object. No prose before. No prose after. No markdown fences (` ```json ` etc.) around it. The orchestrator parses stdout with `json.loads()`; any non-JSON content breaks parsing and the entire run fails.
`````

- [ ] **Step 2.3: Run the drift lint to verify schema/md sync is intact**

The drift lint at `tests/agents/test_schema_md_sync.py` enforces that each agent's `.md` Output schema block is in sync with the JSON Schema at `agents/schemas/<agent>.schema.json`. We are not touching the `## Output schema (canonical)` block, so this must still pass.

Run: `pytest tests/agents/test_schema_md_sync.py -v`

Expected: PASS (all agent schema-sync tests green).

- [ ] **Step 2.4: Run the full test suite to verify no regression**

Run: `pytest`

Expected: PASS (164 tests).

- [ ] **Step 2.5: Commit**

```bash
git add agents/source-collector.md
git commit -m "$(cat <<'EOF'
fix(CCE-10): source-collector.md — forbidden-outputs + drop legacy contract

Two prompt edits that travel together:

1. Add a "## Forbidden outputs" subsection with concrete JSON examples
   of the three observed bad shapes: status-report telemetry, "issues"
   rename, and prose preamble. The CCE-9 H4 validation doc established
   that purely positive specification (three sections saying "use canonical
   shape") was insufficient; explicit negative examples are what's new.

2. Remove the legacy "## Output contract" block. It duplicated the
   canonical schema with a redundant example and included a tie-breaker
   meta-instruction ("the schema is authoritative if they disagree") that
   itself signaled ambiguity to the model.

Closes the second and third of three root causes documented in
docs/superpowers/measurements/2026-05-20-cce9-h4-validation.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Measurement — 5 Mode B runs against the CCE-11 self-host harness

**Files:**

- Create: `docs/superpowers/measurements/2026-05-20-cce10-canonical-shape-validation.md`
- Create: `docs/superpowers/measurements/2026-05-20-cce10-run1-source-collector-stdout.txt`
- Create: `docs/superpowers/measurements/2026-05-20-cce10-run2-source-collector-stdout.txt`
- Create: `docs/superpowers/measurements/2026-05-20-cce10-run3-source-collector-stdout.txt`
- Create: `docs/superpowers/measurements/2026-05-20-cce10-run4-source-collector-stdout.txt`
- Create: `docs/superpowers/measurements/2026-05-20-cce10-run5-source-collector-stdout.txt`

This task is ceremony, not code. It validates the fix bundle from Tasks 1 + 2 by running the orchestrator end-to-end 5 times against this very repo (self-host harness from CCE-11) with seeded v0.1.0 state, and confirming source-collector emits canonical shape every time. If any run fails the canonical shape, do not ship — iterate on the prompt instead.

**Pre-flight check before Step 3.1:**

- Working tree must be clean (Tasks 1 + 2 committed).
- `.engineering-docs-agent/config.yml` and `.engineering-docs-agent/state.example.json` must exist (committed in CCE-11).
- `claude` CLI must be installed and authenticated (real Mode B run, not Mode A dry-run).

- [ ] **Step 3.1: Run 1**

```bash
rm -rf /tmp/cce-10-validate-run1
cp .engineering-docs-agent/state.example.json .engineering-docs-agent/state.json
DOCS_AGENT_DEBUG_DIR=/tmp/cce-10-validate-run1 python3 scripts/orchestrator_runner.py --repo-root . --no-pr
# Inspect the captured stdout:
ls /tmp/cce-10-validate-run1
cat /tmp/cce-10-validate-run1/*-source-collector.stdout.txt
# Inspect the resulting state:
cat .engineering-docs-agent/state.json
# Save the captured stdout for the measurement doc:
cp /tmp/cce-10-validate-run1/*-source-collector.stdout.txt docs/superpowers/measurements/2026-05-20-cce10-run1-source-collector-stdout.txt
```

Expected: the source-collector stdout file contains canonical-shape JSON starting with `{"prs":` and containing a `"jira_issues":` top-level key. The state.json `partial_reasons` is empty OR contains only non-source-collector reasons.

Record outcome:

- canonical shape: yes / no
- schema validation: pass / fail (look at `state.json` for `partial_reasons` with `schema_invalid: source-collector: ...`)
- if fail, the shape that was emitted instead

- [ ] **Step 3.2: Run 2**

```bash
rm -rf /tmp/cce-10-validate-run2
cp .engineering-docs-agent/state.example.json .engineering-docs-agent/state.json
DOCS_AGENT_DEBUG_DIR=/tmp/cce-10-validate-run2 python3 scripts/orchestrator_runner.py --repo-root . --no-pr
cp /tmp/cce-10-validate-run2/*-source-collector.stdout.txt docs/superpowers/measurements/2026-05-20-cce10-run2-source-collector-stdout.txt
cat .engineering-docs-agent/state.json
```

Record outcome same as Step 3.1.

- [ ] **Step 3.3: Run 3**

```bash
rm -rf /tmp/cce-10-validate-run3
cp .engineering-docs-agent/state.example.json .engineering-docs-agent/state.json
DOCS_AGENT_DEBUG_DIR=/tmp/cce-10-validate-run3 python3 scripts/orchestrator_runner.py --repo-root . --no-pr
cp /tmp/cce-10-validate-run3/*-source-collector.stdout.txt docs/superpowers/measurements/2026-05-20-cce10-run3-source-collector-stdout.txt
cat .engineering-docs-agent/state.json
```

Record outcome same as Step 3.1.

- [ ] **Step 3.4: Run 4**

```bash
rm -rf /tmp/cce-10-validate-run4
cp .engineering-docs-agent/state.example.json .engineering-docs-agent/state.json
DOCS_AGENT_DEBUG_DIR=/tmp/cce-10-validate-run4 python3 scripts/orchestrator_runner.py --repo-root . --no-pr
cp /tmp/cce-10-validate-run4/*-source-collector.stdout.txt docs/superpowers/measurements/2026-05-20-cce10-run4-source-collector-stdout.txt
cat .engineering-docs-agent/state.json
```

Record outcome same as Step 3.1.

- [ ] **Step 3.5: Run 5**

```bash
rm -rf /tmp/cce-10-validate-run5
cp .engineering-docs-agent/state.example.json .engineering-docs-agent/state.json
DOCS_AGENT_DEBUG_DIR=/tmp/cce-10-validate-run5 python3 scripts/orchestrator_runner.py --repo-root . --no-pr
cp /tmp/cce-10-validate-run5/*-source-collector.stdout.txt docs/superpowers/measurements/2026-05-20-cce10-run5-source-collector-stdout.txt
cat .engineering-docs-agent/state.json
```

Record outcome same as Step 3.1.

- [ ] **Step 3.6: Evaluate against ship criterion**

If 5/5 runs emit canonical shape AND pass schema validation → proceed to Step 3.7.

If fewer than 5/5 pass → DO NOT SHIP. Stop and report:

- Which runs failed and which shape they emitted.
- Whether the failures are uniform (always the same shape) or varied (different bad shapes).
- Whether the captured stdout shows the "Verification statement:" preamble (Task 1's fix didn't take) vs. the agent emitting a non-canonical shape (Task 2's fix didn't take).

Iterate on the prompt or the env passthrough as appropriate, then re-run Steps 3.1–3.5 from the start. Do not commit the partial measurement doc on a failing run — the file is only created after 5/5 success.

- [ ] **Step 3.7: Write the measurement doc**

Create `docs/superpowers/measurements/2026-05-20-cce10-canonical-shape-validation.md` with this content (filling in the per-run rows from your observations):

```markdown
# CCE-10 Canonical-Shape Validation — 5/5 Mode B Runs

**Date:** 2026-05-20
**Orchestrator version:** main + CCE-10 fixes (commits: <task-1-sha>, <task-2-sha>)
**Target repository:** self-host (theoju/engineering-docs-agent at HEAD)
**Configuration:** `.engineering-docs-agent/state.example.json` seed (head_sha = v0.1.0 commit 1f4563c2…)

## Method

5 consecutive Mode B runs of the orchestrator against this very repo with `DOCS_AGENT_DEBUG_DIR=/tmp/cce-10-validate-run<N>` set. State reset to `state.example.json` before each iteration via `cp`. Raw source-collector stdout captured to `2026-05-20-cce10-run<N>-source-collector-stdout.txt`.

## Verdict

✅ **5/5 PASS** — ship criterion met.

## Per-run outcomes

| Run | Canonical shape | Schema validation | First 80 chars of stdout |
| --- | --------------- | ----------------- | ------------------------ |
| 1   | <yes/no>        | <pass/fail>       | `<first 80 chars>`       |
| 2   | <yes/no>        | <pass/fail>       | `<first 80 chars>`       |
| 3   | <yes/no>        | <pass/fail>       | `<first 80 chars>`       |
| 4   | <yes/no>        | <pass/fail>       | `<first 80 chars>`       |
| 5   | <yes/no>        | <pass/fail>       | `<first 80 chars>`       |

Full raw stdouts: `2026-05-20-cce10-run<N>-source-collector-stdout.txt` alongside this document.

## Comparison with pre-fix baseline

| Run set                                   | Canonical shape rate | Notes                                                                  |
| ----------------------------------------- | -------------------- | ---------------------------------------------------------------------- |
| CCE-9 Phase 1 (pre-fix, 1 run)            | 0/1                  | Status-report shape, "Verification statement:" preamble                |
| CCE-9 H4 validation (post-step-0, 3 runs) | 0/3                  | Step 0 partial; reflex unchanged; preamble in 2/3                      |
| CCE-11 self-host dogfood (1 run)          | 0/1                  | Reflex defeated by populated last_sha, but F1 rename `issues`          |
| **CCE-10 (post-bundle, 5 runs)**          | **5/5**              | Fix bundle: env passthrough + forbidden outputs + legacy block removal |

## Conclusion

The CCE-10 bundle eliminates all three confirmed root causes. Source-collector now emits canonical-shape JSON reliably on the self-host harness. Downstream CCE-12 (tool-use diagnostics for `prs:[]`) is now unblocked: with schema validation no longer the failure point, F2 measurements will be attributable.
```

- [ ] **Step 3.8: Commit the measurement doc + raw stdouts**

```bash
git add docs/superpowers/measurements/2026-05-20-cce10-*.md docs/superpowers/measurements/2026-05-20-cce10-run*-source-collector-stdout.txt
git commit -m "$(cat <<'EOF'
docs(CCE-10): canonical-shape validation — 5/5 Mode B runs pass

Measurement protocol from the design spec: 5 consecutive Mode B runs of
the orchestrator against this repo (CCE-11 self-host harness) with seeded
v0.1.0 SHA. All 5 emit canonical {"prs":[...],"jira_issues":[...]} and
pass schema validation.

Ship criterion met. CCE-12 (tool-use diagnostics) is now unblocked.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Post-implementation

After all three tasks land:

1. **Verify branch state:**

   ```bash
   git log main..HEAD --oneline
   # Expected: 4 commits (spec + task1 + task2 + task3)
   ```

2. **Hand off to /ship** for the standard chain (test → verify-agent → simplify → code review → commit → push + PR → Jira transition). The plan stops here; /ship is its own ceremony.

3. **Tag/version decision after merge:** v0.1.5 bump is warranted — this is a reliability fix that changes runtime behavior (the env passthrough means every subagent dispatch now sees a different env). Worth noting in CHANGELOG when /ship is done.

## Acceptance criteria mapping (spec → plan)

| Spec acceptance criterion                                                    | Task / step that implements it                        |
| ---------------------------------------------------------------------------- | ----------------------------------------------------- |
| 1. `dispatch_subagent` passes `CLAUDE_STOP_VERIFY=0`                         | Task 1, Steps 1.3 + 1.6                               |
| 2. Legacy `## Output contract` block removed                                 | Task 2, Steps 2.1 + 2.5                               |
| 3. `## Forbidden outputs` subsection added with concrete examples            | Task 2, Steps 2.2 + 2.5                               |
| 4. Drift lint passes                                                         | Task 2, Step 2.3 (gate) + Step 2.4 (regression check) |
| 5. Full pytest suite passes                                                  | Task 1 Step 1.5 + Task 2 Step 2.4                     |
| 6. 5/5 consecutive Mode B runs emit canonical shape + pass schema validation | Task 3, Steps 3.1–3.6 + Step 3.7 (documentation)      |
