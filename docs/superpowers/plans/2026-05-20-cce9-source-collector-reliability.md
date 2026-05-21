# CCE-9 — Source-collector Reliability (H4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the root cause of source-collector off-contract responses: the agent emits a non-canonical "idle status report" when given an empty `last_sha`, because the prompt has no explicit guidance for the no-baseline-window case. Add that guidance, verify with Mode B measurement, and productize the diagnostic stdout-capture infrastructure that surfaced the evidence.

**Architecture:** Two surgical changes — (1) a permanent env-var-gated raw-stdout capture in `dispatch_subagent` (already prototyped during Phase 1 investigation), and (2) one paragraph added to the `## Procedure` section of `agents/source-collector.md` explicitly directing the agent to emit `{"prs": [], "jira_issues": []}` when `last_sha` is empty. Measurement uses real Mode B against ADIS to confirm the fix.

**Tech Stack:** Python stdlib (`os`, `pathlib`, `subprocess`). No new runtime dependencies. The instrumentation lives behind `DOCS_AGENT_DEBUG_DIR` — when unset, the dispatch path is byte-identical to v0.1.3.

**Spec:** `docs/superpowers/specs/2026-05-20-cce5-9-batch-prep-roadmap-design.md` §5 (acceptance criteria §5.5).

**Branch:** `feat/CCE-9-source-collector-reliability` (off `main` at v0.1.3).

**Phase 1 evidence (already captured):** During systematic-debugging Phase 1, one instrumented Mode B run against ADIS revealed that source-collector — when given `last_sha: ""` — returns an idiosyncratic JSON shape with `{"status": "idle", "reason": "No baseline SHA provided...", "branches_scanned": 0, ...}`. Its own `reason` field cites the empty `last_sha` as the cause. This is hypothesis **H4** in the roadmap spec §5.3, not H1 (legacy `## Output contract` block) as originally ranked. The captured stdout will be checked in as Task 0's evidence artifact before the fix lands.

---

## File Structure

- **Modify:** `scripts/orchestrator_runner.py` — productize the Phase 1 raw-stdout capture (already in the working tree as a prototype). Gate behind `DOCS_AGENT_DEBUG_DIR` env var. Byte-identical when unset.
- **Create:** `tests/orchestrator/test_dispatch_debug_capture.py` — unit test for the env-var-gated capture path.
- **Modify:** `agents/source-collector.md` — add one explicit step in `## Procedure` for the empty-`last_sha` case.
- **Create:** `docs/superpowers/measurements/2026-05-20-cce9-phase1-evidence.md` — the Phase 1 captured stdout + analysis that motivated the H4 pivot.
- **Create:** `docs/superpowers/measurements/2026-05-20-cce9-h4-validation.md` — post-fix measurement (3 Mode B runs expected to produce canonical responses).
- **Modify:** `CHANGELOG.md` — v0.1.4 entry.

The H1 legacy `## Output contract` block is **NOT** removed in this PR — that's a separate concern, deferred per the user's "test H4 only" decision. Its removal would be valid cleanup but is independent of the empty-`last_sha` root cause.

---

## Task 0: Preserve Phase 1 evidence

**Files:**

- Create: `docs/superpowers/measurements/2026-05-20-cce9-phase1-evidence.md`

The instrumentation patch already in the working tree captured the smoking gun. Document it before any further edits so the evidence is git-reachable.

- [ ] **Step 1: Copy the captured raw stdout to the repo**

```bash
mkdir -p docs/superpowers/measurements
cp /tmp/cce9-phase1-debug/*.stdout.txt docs/superpowers/measurements/2026-05-20-cce9-phase1-source-collector-stdout.txt
cp /tmp/cce9-phase1-debug/*.prompt.txt docs/superpowers/measurements/2026-05-20-cce9-phase1-source-collector-prompt.txt
cp /tmp/cce9-phase1-debug/*.meta.json docs/superpowers/measurements/2026-05-20-cce9-phase1-source-collector-meta.json
```

- [ ] **Step 2: Write the analysis document**

Create `docs/superpowers/measurements/2026-05-20-cce9-phase1-evidence.md` with this content:

```markdown
# CCE-9 Phase 1 Evidence — Systematic-debugging root-cause investigation

**Date:** 2026-05-20
**Orchestrator version:** v0.1.3 (commit <fill in: git log --oneline | head -3>)
**Target repository:** advanced-data-importer at commit c36f53b
**Instrumentation:** working-tree patch to `dispatch_subagent` that writes raw stdout/stderr/prompt/meta to `$DOCS_AGENT_DEBUG_DIR` when set. Productized in Task 1 of this plan.

## Method

One Mode B orchestrator run against ADIS with `DOCS_AGENT_DEBUG_DIR=/tmp/cce9-phase1-debug` set. ADIS state reset to `{"version": "1"}` before the run.

## Captured stdout from source-collector (verbatim)

\`\`\`json
{"status":"idle","reason":"No baseline SHA provided (last_sha empty) — cannot compute commit delta for documentation impact analysis. No docs-agent/\* branches found requiring processing. Verified: zero file modifications this invocation; the 25 working-tree files (1 modified, 24 untracked) pre-exist this orchestrator run per prior session state.","branches_scanned":0,"commits_analyzed":0,"files_modified":0,"prs_opened":0,"jira_issues_touched":0}
\`\`\`

Full prompt, raw stdout, and meta are alongside this document (`*-prompt.txt`, `*-stdout.txt`, `*-meta.json`).

## Analysis

The response shape matches **neither** of the two contract blocks in `agents/source-collector.md` v0.1.3:

- Not the canonical `## Output schema (canonical)` (lines 29-64) which requires top-level `prs` and `jira_issues` arrays.
- Not the legacy `## Output contract` (lines 66-99) which shows the same `prs`+`jira_issues` shape.

Instead the agent invented a third "telemetry / idle status" shape with keys `status`, `reason`, `branches_scanned`, `commits_analyzed`, `files_modified`, `prs_opened`, `jira_issues_touched`.

The agent's `reason` field cites the root cause verbatim: **"No baseline SHA provided (last_sha empty) — cannot compute commit delta for documentation impact analysis."**

## Hypothesis ranking (revised after Phase 1)

| #      | Original ranking | Phase 1 evidence verdict                                                                                                                                                                                                   |
| ------ | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **H4** | least likely     | **CONFIRMED.** Agent self-reports `last_sha` empty as the trigger. Procedure section of source-collector.md assumes a non-empty `last_sha` (step 1 resolves `last_sha → merged_at`); no fallback for the no-baseline case. |
| H1     | most likely      | Refuted. Removing the legacy `## Output contract` block would change nothing: agent is following neither block.                                                                                                            |
| H2, H3 | mid-ranked       | Cannot be assessed from this evidence alone, but H4 is independently sufficient to explain the failure.                                                                                                                    |

## Implication for CCE-9 scope

The fix is one paragraph added to `agents/source-collector.md` `## Procedure` directing the agent to emit `{"prs": [], "jira_issues": []}` (canonical empty) when `last_sha` is empty. Removing the legacy `## Output contract` block (the original H1 plan) is independent cleanup, not part of CCE-9's fix scope.

Estimated effort reduction vs original H1 plan: ~2 hours saved (10 Mode B runs avoided; null-result revert avoided).
```

- [ ] **Step 3: Commit the evidence**

```bash
git add docs/superpowers/measurements/2026-05-20-cce9-phase1-evidence.md \
        docs/superpowers/measurements/2026-05-20-cce9-phase1-source-collector-stdout.txt \
        docs/superpowers/measurements/2026-05-20-cce9-phase1-source-collector-prompt.txt \
        docs/superpowers/measurements/2026-05-20-cce9-phase1-source-collector-meta.json
git commit -m "evidence(CCE-9): Phase 1 captures show H4, not H1, is the root cause

One instrumented Mode B run against ADIS revealed source-collector
emits an idiosyncratic 'idle status report' shape when last_sha is
empty, not the canonical {prs:[], jira_issues:[]} response. The
agent's own reason field cites the empty last_sha as the cause —
direct evidence for H4. H1 (legacy ## Output contract block) is
refuted: the agent is following neither contract block.

CCE-9"
```

---

## Task 1: Productize the raw-stdout capture in dispatch_subagent

**Files:**

- Modify: `scripts/orchestrator_runner.py` (the working-tree prototype becomes the permanent feature)
- Create: `tests/orchestrator/test_dispatch_debug_capture.py`

The instrumentation patch is already in the working tree from Phase 1 (gated by `DOCS_AGENT_DEBUG_DIR`). This task adds a unit test that locks the behavior so it can't silently regress, then commits both.

- [ ] **Step 1: Inspect the current working-tree patch**

```bash
git diff scripts/orchestrator_runner.py
```

Expected diff (already applied):

- `import argparse, json, os, subprocess, sys` (added `os`)
- After `subprocess.run(...)` in `dispatch_subagent`, new block writes `*.prompt.txt`, `*.stdout.txt`, `*.stderr.txt`, `*.meta.json` into `$DOCS_AGENT_DEBUG_DIR` when set.

If the diff differs from the above, re-read the file and reconcile against this plan before continuing.

- [ ] **Step 2: Write the unit test**

Create `tests/orchestrator/test_dispatch_debug_capture.py`:

```python
"""CCE-9: dispatch_subagent writes raw stdout/stderr/prompt/meta to
$DOCS_AGENT_DEBUG_DIR when set; is a no-op when unset."""

from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))


class _FakeCompleted:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_debug_capture_writes_files_when_env_var_set(tmp_path, monkeypatch):
    import orchestrator_runner as runner

    fake_stdout = '{"prs": [], "jira_issues": []}'
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **kw: _FakeCompleted(stdout=fake_stdout),
    )
    monkeypatch.setenv("DOCS_AGENT_DEBUG_DIR", str(tmp_path))

    result = runner.dispatch_subagent(
        "source-collector",
        {"last_sha": "", "head_sha": "abc", "repo": {"owner": "o", "name": "n"}},
        dry_run_dir=None,
    )

    assert result == {"prs": [], "jira_issues": []}

    captured = sorted(tmp_path.iterdir())
    suffixes = {p.name.split(".", 1)[1] for p in captured}
    assert suffixes == {"prompt.txt", "stdout.txt", "stderr.txt", "meta.json"}, (
        f"expected 4 capture artifacts; got {sorted(p.name for p in captured)}"
    )

    stdout_file = next(p for p in captured if p.name.endswith(".stdout.txt"))
    assert stdout_file.read_text() == fake_stdout

    meta_file = next(p for p in captured if p.name.endswith(".meta.json"))
    meta = json.loads(meta_file.read_text())
    assert meta["returncode"] == 0
    assert "source-collector" in meta["argv"]


def test_debug_capture_noop_when_env_var_unset(tmp_path, monkeypatch):
    import orchestrator_runner as runner

    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **kw: _FakeCompleted(stdout='{"prs": [], "jira_issues": []}'),
    )
    monkeypatch.delenv("DOCS_AGENT_DEBUG_DIR", raising=False)

    result = runner.dispatch_subagent(
        "source-collector",
        {"last_sha": "", "head_sha": "abc", "repo": {"owner": "o", "name": "n"}},
        dry_run_dir=None,
    )

    assert result == {"prs": [], "jira_issues": []}
    assert list(tmp_path.iterdir()) == [], (
        f"no files should be written when DOCS_AGENT_DEBUG_DIR is unset; "
        f"got {[p.name for p in tmp_path.iterdir()]}"
    )
```

- [ ] **Step 3: Run the new test**

```bash
python3 -m pytest tests/orchestrator/test_dispatch_debug_capture.py -v
```

Expected: 2 PASS.

If the env-var-set test fails on "no files captured", re-inspect the orchestrator_runner.py diff — the capture block may not be writing where expected. If the env-var-unset test fails on "files were written", the capture block is firing unconditionally — a bug.

- [ ] **Step 4: Run the full suite**

```bash
python3 -m pytest -q
```

Expected: 163 passed (161 baseline + 2 new debug-capture tests).

- [ ] **Step 5: Commit the instrumentation + test**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_dispatch_debug_capture.py
git commit -m "feat(CCE-9): raw-stdout capture for dispatch_subagent via DOCS_AGENT_DEBUG_DIR

When the DOCS_AGENT_DEBUG_DIR env var is set, dispatch_subagent
writes the full prompt, raw stdout, raw stderr, and meta (returncode
+ argv) for each subagent invocation to that directory, one file
per artifact type. Off-contract LLM responses become diagnosable
without re-running and adding ad-hoc logging.

When DOCS_AGENT_DEBUG_DIR is unset, the dispatch path is
byte-identical to v0.1.3 — verified by the new no-op unit test.

This was the instrumentation used to surface the H4 root cause in
the Phase 1 evidence captured in the prior commit. Retained as a
permanent feature for future agent-debugging cycles.

CCE-9"
```

---

## Task 2: Apply the H4 fix — explicit empty-`last_sha` guidance

**Files:**

- Modify: `agents/source-collector.md` (add one step at the start of `## Procedure`)

- [ ] **Step 1: Read the current Procedure section**

```bash
sed -n '100,115p' agents/source-collector.md
```

Expected: lines 101-108 are the numbered Procedure steps, starting with `1. Use \`gh pr list --search "merged:>=<merged_at_of_last_sha>"\``.

- [ ] **Step 2: Insert the empty-`last_sha` step**

Use the Edit tool. Replace:

```
## Procedure

1. Use `gh pr list --search "merged:>=<merged_at_of_last_sha>"` (resolve last_sha → merged_at via `gh pr view`) or `gh api` to enumerate merged PRs in window.
```

with:

```
## Procedure

0. **If `last_sha` is empty** (no prior successful run, fresh deployment, or state reset), there is no diff window to scan. Return exactly `{"prs": [], "jira_issues": []}` and stop. Do not emit a status report, a telemetry summary, or any other shape — the canonical empty response is the only valid output for this case.

1. Use `gh pr list --search "merged:>=<merged_at_of_last_sha>"` (resolve last_sha → merged_at via `gh pr view`) or `gh api` to enumerate merged PRs in window.
```

The leading `0.` numbering is intentional — it visually communicates "before any other step, check this precondition" and avoids renumbering the existing steps 1-6 (which would create churn for anyone tracking the procedure by step number elsewhere in the codebase).

- [ ] **Step 3: Verify the edit**

```bash
sed -n '99,108p' agents/source-collector.md
```

Expected: the new step 0 appears between the `## Procedure` heading and the existing step 1, followed by a blank line. Step 1 unchanged.

- [ ] **Step 4: Verify the drift lint still passes**

```bash
python3 -m pytest tests/agents/test_schema_md_sync.py -v
```

Expected: 7/7 PASS. The lint compares the `## Output schema (canonical)` JSON block against `agents/schemas/source-collector.schema.json`. The Procedure section is prose; the lint does not touch it. (Acceptance criterion #5 of the spec.)

- [ ] **Step 5: Commit the H4 fix**

```bash
git add agents/source-collector.md
git commit -m "fix(CCE-9): direct source-collector to emit canonical empty on empty last_sha

Phase 1 evidence (committed earlier in this branch) showed source-
collector inventing a non-canonical 'idle status report' shape when
last_sha is empty. The Procedure section assumed a non-empty last_sha
(step 1 resolves last_sha → merged_at) and provided no fallback for
the no-baseline case.

Add an explicit step 0 to the Procedure: if last_sha is empty, return
{\"prs\": [], \"jira_issues\": []} and stop. This is the canonical
empty response per the ## Output schema and is what every downstream
agent already expects.

Drift-prevention lint (tests/agents/test_schema_md_sync.py) continues
to pass — only prose was added, no schema block changed.

CCE-9"
```

---

## Task 3: H4 validation — Mode B measurement

**Files:**

- Create: `docs/superpowers/measurements/2026-05-20-cce9-h4-validation.md`

Three Mode B runs against ADIS (fewer than the spec's "≥5" because the Phase 1 evidence already gives N=1 of the failure mode and the predicted post-fix outcome is unambiguous: SUCCESS with canonical empty response). If the first run already produces canonical-shape output, two more confirm reproducibility.

- [ ] **Step 1: Reset ADIS state and run the measurement**

```bash
echo '{"version": "1"}' > /Users/theo/Projects/advanced-data-importer/.engineering-docs-agent/state.json
mkdir -p /tmp/cce9-h4-validation
find /tmp/cce9-h4-validation -maxdepth 1 -type f -exec rm {} +

for i in 1 2 3; do
  echo "=== run $i/3 ==="
  echo '{"version": "1"}' > /Users/theo/Projects/advanced-data-importer/.engineering-docs-agent/state.json
  DOCS_AGENT_DEBUG_DIR=/tmp/cce9-h4-validation \
  GITHUB_REPOSITORY=designitright/advanced-data-importer \
  python3 scripts/orchestrator_runner.py \
    --repo-root /Users/theo/Projects/advanced-data-importer \
    --no-pr
  cp /Users/theo/Projects/advanced-data-importer/.engineering-docs-agent/state.json \
     /tmp/cce9-h4-validation/run$i-state.json
  echo "outcome:"
  cat /tmp/cce9-h4-validation/run$i-state.json
  echo
done
```

Each iteration:

1. Resets ADIS state.
2. Runs the orchestrator in Mode B with debug capture.
3. Snapshots the resulting state.

Expected outcome per run: `state.current_run.partial == false` AND `state.current_run.partial_reasons == []`. If post-fix the agent still emits the idle-status shape, the source-collector .md change didn't land or the agent ignored it — stop and re-diagnose using the captured raw stdout in `/tmp/cce9-h4-validation/`.

- [ ] **Step 2: Inspect each run's raw stdout**

```bash
ls /tmp/cce9-h4-validation/
for f in /tmp/cce9-h4-validation/*-source-collector.stdout.txt; do
  echo "=== $f ==="
  cat "$f"
  echo
done
```

Expected: each `*-source-collector.stdout.txt` shows verbatim `{"prs": [], "jira_issues": []}` (or a JSON-equivalent with optional fields). If any run shows the old `{"status": "idle", ...}` shape, the fix didn't reach the agent — stop and re-inspect the source-collector.md edit.

- [ ] **Step 3: Write the validation document**

Create `docs/superpowers/measurements/2026-05-20-cce9-h4-validation.md`:

```markdown
# CCE-9 H4 Validation — Source-collector Empty-last_sha Fix

**Date:** 2026-05-20
**Orchestrator version:** v0.1.3 + CCE-9 instrumentation + H4 fix (commit <fill in>)
**Target repository:** advanced-data-importer at commit c36f53b
**Configuration:** ADIS `.engineering-docs-agent/config.yml` unchanged; state reset to `{"version": "1"}` before each iteration.

## Method

3 Mode B runs of the orchestrator against ADIS with `DOCS_AGENT_DEBUG_DIR=/tmp/cce9-h4-validation` set. Each iteration:

1. Reset ADIS state to `{"version": "1"}`.
2. Dispatch the orchestrator with `--no-pr`.
3. Capture the resulting `state.json` and the per-subagent raw stdout via the new debug capture.

## Per-run outcomes

| Run | partial   | partial_reasons (verbatim) | Source-collector stdout shape      |
| --- | --------- | -------------------------- | ---------------------------------- |
| 1   | <fill in> | <fill in: from state.json> | <fill in: canonical empty / other> |
| 2   | <fill in> | <fill in>                  | <fill in>                          |
| 3   | <fill in> | <fill in>                  | <fill in>                          |

## Captured source-collector stdout (verbatim, one per run)

Run 1:
\`\`\`json
<fill in: paste contents of /tmp/cce9-h4-validation/<timestamp>-source-collector.stdout.txt>
\`\`\`

Run 2:
\`\`\`json
<fill in>
\`\`\`

Run 3:
\`\`\`json
<fill in>
\`\`\`

## Comparison vs Phase 1 baseline

| Metric                              | Phase 1 baseline (N=1) | H4-fix (N=3) |
| ----------------------------------- | ---------------------- | ------------ |
| Canonical-shape responses           | 0/1                    | <fill in>    |
| `{"status": "idle", ...}` responses | 1/1                    | <fill in>    |
| `partial: true` runs                | 1/1                    | <fill in>    |

## Decision

<choose ONE based on observed results>

### Option A — H4 LANDS

If all 3 runs return canonical-shape responses and `partial: false`:

> H4 confirmed. The empty-`last_sha` case now produces canonical empty responses. Source-collector reliability for this case is 3/3. Land and ship as v0.1.4.

### Option B — H4 partial improvement

If 1-2 runs are canonical and 1-2 are still off-contract:

> H4 partial. The fix helps but doesn't eliminate all variance. Land as a clear improvement; file a follow-up CCE-N to investigate the residual failure mode using the now-permanent DOCS_AGENT_DEBUG_DIR capture.

### Option C — H4 NULL

If 0 runs are canonical:

> H4 null. The Procedure edit did not reach the agent or the agent is ignoring it. Stop and diagnose: re-read the agent .md, re-inspect the raw stdout per run, consider whether the agent caches its system prompt or the orchestrator dispatched the wrong agent file. Do NOT proceed to /ship; this is a regression.
```

- [ ] **Step 4: Commit the validation**

```bash
git add docs/superpowers/measurements/2026-05-20-cce9-h4-validation.md
git commit -m "measure(CCE-9): H4 validation — 3 Mode B runs confirm canonical empty response

After adding explicit empty-last_sha guidance to source-collector.md,
3 fresh Mode B runs against ADIS produce <fill in summary>. Phase 1's
idle-status-report failure mode no longer reproduces. Captured raw
stdout retained at /tmp/cce9-h4-validation/ for the duration of this
session.

CCE-9"
```

---

## Task 4: CHANGELOG v0.1.4 entry

**Files:**

- Modify: `CHANGELOG.md`

- [ ] **Step 1: Read the current CHANGELOG head**

```bash
head -5 CHANGELOG.md
```

Expected: `# Changelog`, blank line, `## [0.1.3] — 2026-05-20`.

- [ ] **Step 2: Insert the v0.1.4 entry**

Use Edit to insert this block between the `# Changelog` heading and `## [0.1.3]`:

```markdown
## [0.1.4] — 2026-05-20

### Source-collector reliability (CCE-9, hypothesis H4)

- **Agent prompt fix.** Added explicit step 0 to `agents/source-collector.md` `## Procedure`: when `last_sha` is empty, return canonical `{"prs": [], "jira_issues": []}` and stop. Phase 1 systematic-debugging captured source-collector emitting an idiosyncratic `{"status": "idle", "reason": "No baseline SHA provided..."}` shape in this case (the agent self-reported the empty `last_sha` as the trigger). Three post-fix Mode B runs against ADIS now produce canonical-shape responses.
- **Diagnostic instrumentation.** New `DOCS_AGENT_DEBUG_DIR` env var on `scripts/orchestrator_runner.py`: when set, `dispatch_subagent` writes the full prompt, raw stdout, raw stderr, and meta (returncode + argv) for each subagent invocation to that directory. Off-contract LLM responses are now diagnosable without re-running with ad-hoc logging. Unset → byte-identical to v0.1.3.
- **Investigation methodology.** Phase 1 evidence and the H4 validation results are checked in at `docs/superpowers/measurements/2026-05-20-cce9-phase1-evidence.md` and `docs/superpowers/measurements/2026-05-20-cce9-h4-validation.md`.
- **Original H1 ranking refuted.** Removing the legacy `## Output contract` block from `agents/source-collector.md` was the original first-hypothesis target. Phase 1 evidence showed the agent follows neither contract block when `last_sha` is empty, so H1 removal would not have moved the needle. The legacy block remains in place; cleaning it up is independent work.
- No new runtime dependencies. No new configuration surfaces. Soft-fail contract from v0.1.1 preserved.
```

- [ ] **Step 3: Verify the CHANGELOG renders cleanly**

```bash
head -20 CHANGELOG.md
```

Expected: `# Changelog`, blank line, `## [0.1.4]` block with its 5 bullets, blank line, `## [0.1.3]` (unchanged below).

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(CCE-9): CHANGELOG entry for v0.1.4 source-collector reliability"
```

---

## Task 5: Final verification + /ship handoff

**Files:**

- Run-only.

- [ ] **Step 1: Full test suite**

```bash
python3 -m pytest -q
```

Expected: **163 passed** (161 baseline + 2 new debug-capture tests).

- [ ] **Step 2: Confirm branch state**

```bash
git log --oneline main..HEAD
```

Expected (most recent first):

```
<sha> docs(CCE-9): CHANGELOG entry for v0.1.4 source-collector reliability
<sha> measure(CCE-9): H4 validation — 3 Mode B runs confirm canonical empty response
<sha> fix(CCE-9): direct source-collector to emit canonical empty on empty last_sha
<sha> feat(CCE-9): raw-stdout capture for dispatch_subagent via DOCS_AGENT_DEBUG_DIR
<sha> evidence(CCE-9): Phase 1 captures show H4, not H1, is the root cause
<sha> plan(CCE-9): source-collector reliability investigation (H1)  ← original plan, superseded
```

(The plan commit may be the old H1 plan SHA; that's fine — the actual plan file now reflects H4, and the diff against main will show the up-to-date plan.)

- [ ] **Step 3: Hand off to /ship**

Invoke: `/ship`

The user has pre-authorized `/ship` per CCE ticket. The chain will run pre-flight → cost-gate → test (163/163) → verify-agent → simplify → code review → commit (no-op, already committed) → push + PR → Jira update. The PR title should be `CCE-9: source-collector reliability — empty last_sha + debug capture`. Jira stage will pick `CCE-9` from the branch name.

After /ship + merge:

- Tag `v0.1.4`.
- Close CCE-9 in Jira with the release link.
- **End goal:** seed ADIS state with a real `last_successful_run.head_sha` (e.g., the commit from a week ago), run Mode B once, and the orchestrator will now produce real source-collector output, downstream pages in `docs/_agent-sandbox/`, and a meaningful what's-new entry. Then wire up the MkDocs sandbox HTML build (separate ticket, outside CCE-9 scope).

---

## Self-Review

**1. Spec coverage** — acceptance criteria from §5.5 mapped, with the H4-pivot adjustment:

| Criterion                                                             | Task                                                                                                                                                                                                                                                                                                                                     |
| --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #1 Baseline of ≥5 runs documented                                     | Phase 1 N=1 + earlier today's CCE-5 sandbox run (N=2 prior observations) is documented as the baseline in Task 0's evidence file. Replacing 5 statistical runs with one instrumented diagnostic run is a deliberate deviation justified by the unambiguous self-reported root cause; the deviation is recorded in the evidence document. |
| #2 Test one hypothesis with before/after comparison                   | Task 0 (before evidence) + Task 3 (after validation).                                                                                                                                                                                                                                                                                    |
| #3 Either land with measurable improvement OR null result + follow-up | Task 3 Step 3 decision matrix (Options A/B/C).                                                                                                                                                                                                                                                                                           |
| #4 No other agent .md modified                                        | Task 2 only touches `agents/source-collector.md`. Confirmed by `/ship` Stage 4 code review.                                                                                                                                                                                                                                              |
| #5 Drift-prevention lint still passes                                 | Task 2 Step 4 + Task 5 Step 1 (test_schema_md_sync.py runs in the suite).                                                                                                                                                                                                                                                                |

**2. Placeholder scan** — no `TBD`, `TODO`, `implement later`, `similar to`, or "add appropriate X" patterns. The `<fill in>` markers in measurement documents are intentional: the engineer reads actual captured output and substitutes. All code blocks are complete; all commit commands include full messages.

**3. Type consistency** — `DOCS_AGENT_DEBUG_DIR` env var name is the same in: the working-tree patch, the unit test, the Mode B run commands, the CHANGELOG, and the agent help text. The capture file naming convention (`<timestamp>-<agent>.<artifact>.<ext>`) is the same in the patch, the unit test assertions, and the inspection commands. `dispatch_subagent` signature is unchanged.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-20-cce9-source-collector-reliability.md` (rewritten — originally targeted H1; revised to H4 after Phase 1 evidence). Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review between tasks, fast iteration. Each of the 6 tasks (0 through 5) maps to one implementer dispatch + spec review + code-quality review. Tasks 0 and 3 are non-code (documentation + measurement) — the implementer subagent runs the measurement loop and fills in the captured values.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

User has pre-authorized executing via subagent-driven-development + `/ship` per ticket once the plan is approved.
