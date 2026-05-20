# CCE-9 — Source-collector Reliability (H1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test hypothesis H1 — that the legacy `## Output contract` block in `agents/source-collector.md` competes with the canonical `## Output schema` block and causes off-contract responses. Measure baseline → apply H1 → measure post-H1 → land or null-result per the roadmap spec.

**Architecture:** Build a tiny reusable measurement helper (`scripts/measure_source_collector.sh`) that resets ADIS state and runs the orchestrator in Mode B N times, capturing per-run outcomes. Use it twice — once for the pre-H1 baseline, once for the post-H1 comparison. The orchestrator code and tests are unchanged; the only runtime artifact altered is one agent's prompt.

**Tech Stack:** bash + Python stdlib (no new dependencies). MkDocs is irrelevant to this ticket (HTML preview is a follow-up after CCE-9 closes).

**Spec:** `docs/superpowers/specs/2026-05-20-cce5-9-batch-prep-roadmap-design.md` §5 (CCE-9 acceptance criteria §5.5).

**Branch:** `feat/CCE-9-source-collector-reliability` (off `main` at v0.1.3).

---

## File Structure

- **Create:** `scripts/measure_source_collector.sh` — reusable bash helper that resets ADIS state, runs the orchestrator N times, captures each run's `state.json`, and prints a summary table. Lives in `scripts/` alongside the runners, not in `tests/` (it's a measurement tool, not a unit test).
- **Create:** `docs/superpowers/measurements/2026-05-20-cce9-baseline.md` — verbatim record of the 5 pre-H1 Mode B runs (per-run outcome + tally).
- **Create:** `docs/superpowers/measurements/2026-05-20-cce9-post-h1.md` — verbatim record of the 5 post-H1 Mode B runs + decision narrative.
- **Modify:** `agents/source-collector.md` — delete the legacy `## Output contract` block (lines 66-99 in the v0.1.3 source).
- **Modify:** `CHANGELOG.md` — add the v0.1.4 entry IF H1 lands; on null-result we revert the agent change and the CHANGELOG diff goes away too.

The drift-prevention lint at `tests/agents/test_schema_md_sync.py` is touched only at the verification stage — no edits expected, just a confirmation run.

---

## Task 1: Build the measurement helper

**Files:**

- Create: `scripts/measure_source_collector.sh`

- [ ] **Step 1: Write the script**

Create `scripts/measure_source_collector.sh` with this content:

```bash
#!/usr/bin/env bash
# CCE-9 measurement helper. Resets ADIS state, runs the orchestrator in
# Mode B (real LLM dispatch) N times, captures per-run state.json, and
# prints a summary tally.
#
# Usage: scripts/measure_source_collector.sh <label> <iterations>
#   label       — short tag for output files (e.g. "baseline" or "post-h1")
#   iterations  — how many runs to execute (typically 5)
#
# Outputs:
#   /tmp/cce9-<label>-run<N>-state.json   (one per run)
#   stdout: summary table

set -euo pipefail

LABEL="${1:?usage: $0 <label> <iterations>}"
ITERS="${2:?usage: $0 <label> <iterations>}"

ADIS_ROOT="/Users/theo/Projects/advanced-data-importer"
STATE_PATH="$ADIS_ROOT/.engineering-docs-agent/state.json"
ORCH="$(git rev-parse --show-toplevel)/scripts/orchestrator_runner.py"

echo "CCE-9 measurement: label=$LABEL iterations=$ITERS"
echo "Orchestrator: $(git rev-parse HEAD)"
echo "Target repo: $ADIS_ROOT"
echo "---"

declare -a OUTCOMES

for i in $(seq 1 "$ITERS"); do
  echo "[run $i/$ITERS] resetting state to clean baseline"
  echo '{"version": "1"}' > "$STATE_PATH"

  echo "[run $i/$ITERS] dispatching orchestrator (Mode B, --no-pr)"
  GITHUB_REPOSITORY=designitright/advanced-data-importer \
    python3 "$ORCH" --repo-root "$ADIS_ROOT" --no-pr >/dev/null 2>&1 || true

  OUT="/tmp/cce9-$LABEL-run$i-state.json"
  cp "$STATE_PATH" "$OUT"

  REASONS=$(python3 -c "
import json, sys
s = json.load(open('$OUT'))
cr = s.get('current_run', {})
partial = cr.get('partial', False)
reasons = cr.get('partial_reasons', [])
if not partial and not reasons:
  print('SUCCESS')
elif any('schema_invalid: source-collector' in r for r in reasons):
  print('SCHEMA_INVALID')
elif any('source_collector_invalid' in r for r in reasons):
  print('DISPATCH_NONE')
else:
  print('OTHER: ' + '; '.join(reasons))
")
  echo "[run $i/$ITERS] outcome: $REASONS"
  OUTCOMES+=("$REASONS")
done

echo "---"
echo "Summary for $LABEL ($ITERS runs):"
printf '%s\n' "${OUTCOMES[@]}" | sort | uniq -c | sort -rn
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x scripts/measure_source_collector.sh
```

- [ ] **Step 3: Smoke-test the script against ADIS with iterations=1**

```bash
scripts/measure_source_collector.sh smoke 1
```

Expected:

- stdout shows `[run 1/1] outcome: <SCHEMA_INVALID|DISPATCH_NONE|OTHER|SUCCESS>`
- a `/tmp/cce9-smoke-run1-state.json` file is created
- summary table at the end

This is a sanity check, not a baseline. Delete the smoke output file: `rm /tmp/cce9-smoke-run1-state.json`.

- [ ] **Step 4: Commit the helper**

```bash
git add scripts/measure_source_collector.sh
git commit -m "feat(CCE-9): add scripts/measure_source_collector.sh measurement helper

Reusable bash helper for testing source-collector reliability
hypotheses. Resets ADIS state to a clean baseline before each run,
dispatches the orchestrator in Mode B with --no-pr, captures per-run
state.json to /tmp/cce9-<label>-run<N>-state.json, and prints a
tally of outcomes (SUCCESS / SCHEMA_INVALID / DISPATCH_NONE / OTHER).

CCE-9"
```

---

## Task 2: Baseline measurement (5 Mode B runs, pre-H1)

**Files:**

- Create: `docs/superpowers/measurements/2026-05-20-cce9-baseline.md`

This task runs 5 real Mode B orchestrator invocations against ADIS. Each run takes ~30s-3min depending on which subagents are dispatched. Total wall time: ~5-15 minutes. Token usage on the Anthropic API is real but small (source-collector fails early in the baseline, so only 1-2 subagents per run typically).

- [ ] **Step 1: Run the helper for the baseline**

```bash
mkdir -p docs/superpowers/measurements
scripts/measure_source_collector.sh baseline 5 | tee docs/superpowers/measurements/2026-05-20-cce9-baseline-raw.log
```

The `tee` captures the helper's stdout (including the per-run outcomes and summary tally) into a raw log file alongside the measurement document. Both go into the same commit.

- [ ] **Step 2: Inspect each captured state.json**

```bash
for i in 1 2 3 4 5; do
  echo "=== run $i ==="
  cat /tmp/cce9-baseline-run$i-state.json
  echo
done
```

Expected: each shows `current_run.partial: true` with a `partial_reasons` list. The reasons are what CCE-9 is investigating.

- [ ] **Step 3: Write the baseline measurement document**

Create `docs/superpowers/measurements/2026-05-20-cce9-baseline.md` with this structure (fill in the actual observed values from your tee'd log):

```markdown
# CCE-9 Baseline Measurement — Source-collector Reliability (Pre-H1)

**Date:** 2026-05-20
**Orchestrator version:** v0.1.3 (commit <fill in: git rev-parse HEAD>)
**Target repository:** advanced-data-importer at commit c36f53b
**Configuration:** ADIS `.engineering-docs-agent/config.yml` unchanged from prior runs; state reset to `{"version": "1"}` before each iteration.

## Method

Each run executed via `scripts/measure_source_collector.sh baseline 5`. Per iteration:

1. ADIS state reset to clean baseline (`{"version": "1"}`).
2. Orchestrator dispatched in Mode B (real LLM dispatch) with `--no-pr`.
3. Resulting `state.json` captured to `/tmp/cce9-baseline-run<N>-state.json`.
4. Outcome classified by `partial_reasons` contents.

## Per-run outcomes

| Run | Outcome   | partial_reasons (verbatim)                                                              |
| --- | --------- | --------------------------------------------------------------------------------------- |
| 1   | <fill in> | <fill in: copy the actual partial_reasons list from /tmp/cce9-baseline-run1-state.json> |
| 2   | <fill in> | <fill in>                                                                               |
| 3   | <fill in> | <fill in>                                                                               |
| 4   | <fill in> | <fill in>                                                                               |
| 5   | <fill in> | <fill in>                                                                               |

## Tally

<fill in from the helper's summary output — e.g. "5 SCHEMA_INVALID" or "3 DISPATCH_NONE, 2 SCHEMA_INVALID">

## Interpretation

Source-collector's canonical-shape rate in the v0.1.3 baseline is <fill in: e.g. "0/5 = 0%">. This is the comparison anchor for the post-H1 measurement in Task 5.
```

The `<fill in>` markers are intentional — they tell the engineer exactly what to substitute. Read the actual `/tmp/cce9-baseline-run<N>-state.json` files for the per-run `partial_reasons` lists.

- [ ] **Step 4: Commit the baseline**

```bash
git add docs/superpowers/measurements/2026-05-20-cce9-baseline.md docs/superpowers/measurements/2026-05-20-cce9-baseline-raw.log
git commit -m "measure(CCE-9): baseline source-collector reliability (5 Mode B runs, pre-H1)

Records 5 Mode B runs against ADIS at v0.1.3 to establish the
canonical-shape rate before testing hypothesis H1 (legacy ## Output
contract block conflicting with canonical schema). Per-run outcomes
and tally documented; raw helper output retained alongside.

CCE-9"
```

---

## Task 3: Apply H1 — remove the legacy `## Output contract` block

**Files:**

- Modify: `agents/source-collector.md` (delete lines 66-99 in the v0.1.3 source)

- [ ] **Step 1: Verify the current state of the file**

Read the file first to confirm the legacy block is still at the expected location:

```bash
sed -n '60,100p' agents/source-collector.md
```

Expected to show lines 60-100 including the `## Output contract` heading at line 66, the explanatory paragraph at line 68, the example JSON object at lines 70-99, and the blank line before `## Procedure` at line 100. If the file structure differs, stop and report.

- [ ] **Step 2: Delete the legacy block**

Use the Edit tool to remove the block. The `old_string` is the exact text from line 66 through line 99 inclusive — the entire `## Output contract` heading, its explanatory paragraph, and the JSON example. The `new_string` is empty.

````python
# Edit tool invocation:
#   file_path: /Users/theo/Projects/engineering-docs-agent/agents/source-collector.md
#   old_string: """## Output contract
#
# The canonical schema is in §Output schema above. The shape described here is the same; the schema is authoritative if they disagree.
#
# Return ONLY a JSON object matching:
#
# ```json
# {
#   "prs": [
#     {
#       "number": 142,
#       "title": "...",
#       "body": "...",
#       "merge_sha": "abc123",
#       "merged_at": "2026-05-19T07:00:00Z",
#       "author": "user",
#       "files": [{ "path": "...", "additions": 0, "deletions": 0 }],
#       "labels": ["..."],
#       "jira_keys": ["ADIS-235"],
#       "url": "https://github.com/owner/repo/pull/142"
#     }
#   ],
#   "jira_issues": [
#     {
#       "key": "ADIS-235",
#       "summary": "...",
#       "description": "...",
#       "status": "Done",
#       "labels": ["architecture"],
#       "url": "https://acme.atlassian.net/browse/ADIS-235"
#     }
#   ]
# }
# ```
#
# """
#   new_string: ""
````

Use the literal text from the file (read it with the Read tool first to get exact whitespace and quotes). The Edit must remove the entire block plus the trailing blank line, leaving `## Procedure` to immediately follow `Return ONLY a JSON object that validates against this schema. No prose, no markdown fences around the response, no commentary.` from the canonical schema section.

- [ ] **Step 3: Verify the edit**

```bash
grep -n "^##" agents/source-collector.md
```

Expected output (headings only, in order):

```
13:## Job
19:## Inputs
29:## Output schema (canonical)
<line>:## Procedure
<line>:## Failure handling
```

No `## Output contract` heading should remain. If grep still shows it, the edit didn't land — re-read and re-edit.

- [ ] **Step 4: Verify the drift lint still passes**

```bash
python3 -m pytest tests/agents/test_schema_md_sync.py -v
```

Expected: all 7 parameterized cases PASS. The lint compares the `## Output schema (canonical)` JSON block against `agents/schemas/source-collector.schema.json`. The legacy `## Output contract` block we just removed was prose, not a schema block — its removal does not affect the lint. (This is acceptance criterion #5 of the spec.)

If the lint fails on the source-collector case, stop and inspect — the canonical schema block may have been accidentally modified. Revert via `git checkout agents/source-collector.md` and re-attempt the edit more carefully.

- [ ] **Step 5: Commit the H1 change**

```bash
git add agents/source-collector.md
git commit -m "fix(CCE-9): remove legacy ## Output contract block from source-collector.md

Tests hypothesis H1 (roadmap spec §5.3): the legacy ## Output contract
block presents a second JSON example alongside the canonical
## Output schema, which may compete for the LLM's attention and cause
off-contract responses (observed N=2/2 in Mode B against ADIS at
v0.1.3).

The removed block was prose-with-example; the canonical schema in
§Output schema remains the single source of truth. Drift lint
(tests/agents/test_schema_md_sync.py) continues to pass since it
only checks the canonical schema block against the .json file.

Measurement to follow in next commit.

CCE-9"
```

---

## Task 4: Post-H1 measurement (5 Mode B runs)

**Files:**

- Create: `docs/superpowers/measurements/2026-05-20-cce9-post-h1.md`

Same measurement protocol as Task 2, but now the source-collector prompt has had the legacy block removed. If H1 is correct, the canonical-shape rate should improve materially.

- [ ] **Step 1: Run the helper for the post-H1 measurement**

```bash
scripts/measure_source_collector.sh post-h1 5 | tee docs/superpowers/measurements/2026-05-20-cce9-post-h1-raw.log
```

This run may take significantly longer than the baseline. If source-collector now returns canonical-shape responses, the full downstream pipeline (pr-summarizer, page-author, content-validator, gap-detector, etc.) fires per run. Expect each run to take 1-4 minutes; total wall time 5-20 minutes.

- [ ] **Step 2: Inspect each captured state.json**

```bash
for i in 1 2 3 4 5; do
  echo "=== run $i ==="
  cat /tmp/cce9-post-h1-run$i-state.json
  echo
done
```

- [ ] **Step 3: Write the post-H1 measurement document**

Create `docs/superpowers/measurements/2026-05-20-cce9-post-h1.md` with this structure (fill in actual values from the tee'd log and the captured state.json files):

```markdown
# CCE-9 Post-H1 Measurement — Source-collector Reliability

**Date:** 2026-05-20
**Orchestrator version:** v0.1.3 (commit <fill in>)
**Agent prompt:** v0.1.3 + H1 (legacy ## Output contract block removed; commit <fill in>)
**Target repository:** advanced-data-importer at commit c36f53b
**Configuration:** unchanged from baseline; state reset to `{"version": "1"}` before each iteration.

## Method

Same as baseline (see `2026-05-20-cce9-baseline.md` for protocol details).

## Per-run outcomes

| Run | Outcome   | partial_reasons (verbatim) |
| --- | --------- | -------------------------- |
| 1   | <fill in> | <fill in>                  |
| 2   | <fill in> | <fill in>                  |
| 3   | <fill in> | <fill in>                  |
| 4   | <fill in> | <fill in>                  |
| 5   | <fill in> | <fill in>                  |

## Tally

<fill in from the helper's summary output>

## Comparison vs baseline

| Outcome        | Baseline (n=5) | Post-H1 (n=5) | Δ         |
| -------------- | -------------- | ------------- | --------- |
| SUCCESS        | <fill in>      | <fill in>     | <fill in> |
| SCHEMA_INVALID | <fill in>      | <fill in>     | <fill in> |
| DISPATCH_NONE  | <fill in>      | <fill in>     | <fill in> |
| OTHER          | <fill in>      | <fill in>     | <fill in> |

## Decision

<choose ONE of the following two options based on observed results>

### Option A — H1 LANDS

If the post-H1 SUCCESS rate is materially better than baseline (e.g. baseline 0/5 → post-H1 ≥3/5), record the decision verbatim:

> H1 confirmed. The legacy `## Output contract` block was a meaningful contributor to off-contract responses. Removal lands; ships as v0.1.4.

Proceed to Task 5 (CHANGELOG + ship).

### Option B — H1 NULL RESULT

If the post-H1 rate is not materially better than baseline (no obvious improvement, or worse), record the decision verbatim:

> H1 null result. Removing the legacy `## Output contract` block did not measurably improve source-collector reliability. Reverting `agents/source-collector.md` to v0.1.3. Filing CCE-N follow-up to test H2 (final-reminder line) next.

Then execute the revert procedure in Task 5 (Option B branch).
```

- [ ] **Step 4: Commit the post-H1 measurement**

```bash
git add docs/superpowers/measurements/2026-05-20-cce9-post-h1.md docs/superpowers/measurements/2026-05-20-cce9-post-h1-raw.log
git commit -m "measure(CCE-9): post-H1 source-collector reliability (5 Mode B runs)

Records 5 Mode B runs against ADIS after removing the legacy
## Output contract block from agents/source-collector.md. Compares
canonical-shape rate against the baseline established in the prior
measure() commit. Decision (land vs null-result) documented in the
measurement file.

CCE-9"
```

---

## Task 5: Decision — land or null-result

This task forks based on the decision recorded in Task 4 Step 3.

### Option A — H1 LANDS (post-H1 rate materially better than baseline)

**Files:**

- Modify: `CHANGELOG.md`

- [ ] **Step A1: Add v0.1.4 CHANGELOG entry**

Read `CHANGELOG.md` first to confirm it currently starts with `# Changelog` then `## [0.1.3]`. Then insert the new v0.1.4 section between them:

```markdown
## [0.1.4] — 2026-05-20

### Source-collector reliability (CCE-9, hypothesis H1)

- Removed the legacy `## Output contract` block from `agents/source-collector.md`. The block was a second prose-with-example specification of the output shape, presented alongside the canonical `## Output schema` JSON Schema block introduced in v0.1.2. Empirically — 5 Mode B runs against ADIS — the two blocks competed for the LLM's attention and biased it toward off-contract responses (baseline canonical-shape rate: <fill in from measurement>; post-H1 rate: <fill in>).
- Investigation methodology and per-run outcomes documented at `docs/superpowers/measurements/2026-05-20-cce9-baseline.md` and `docs/superpowers/measurements/2026-05-20-cce9-post-h1.md`.
- Drift-prevention lint at `tests/agents/test_schema_md_sync.py` continues to pass — the canonical schema block is the only authoritative source.
- New `scripts/measure_source_collector.sh` helper retained for future hypothesis testing (H2, H3, H4) if reliability regresses.
- No code changes. No new dependencies. No new configuration.
```

Fill in the actual rates from the measurement files.

- [ ] **Step A2: Commit the CHANGELOG**

```bash
git add CHANGELOG.md
git commit -m "docs(CCE-9): CHANGELOG entry for v0.1.4 source-collector reliability"
```

- [ ] **Step A3: Hand off to /ship (proceeds to Task 6)**

### Option B — H1 NULL RESULT (no material improvement)

**Files:**

- Revert: `agents/source-collector.md` (back to v0.1.3 — restore the legacy `## Output contract` block)
- No CHANGELOG entry (no shipped change)
- Out-of-band: file `CCE-N` ticket in Jira for the next hypothesis (H2 = final-reminder line)

- [ ] **Step B1: Revert the H1 change**

```bash
git revert <SHA-of-H1-commit-from-Task-3>
```

This produces a clean revert commit that restores the legacy block. Verify with:

```bash
grep -n "^##" agents/source-collector.md
```

Expected to once again show `## Output contract` as a heading.

- [ ] **Step B2: Verify lint still passes after revert**

```bash
python3 -m pytest tests/agents/test_schema_md_sync.py -v
```

Expected: 7/7 PASS.

- [ ] **Step B3: Commit (no-op if revert already committed)**

The revert in Step B1 is already a commit. No further commit needed unless edits were made.

- [ ] **Step B4: File CCE-N for H2**

Use the Atlassian MCP to file a follow-up ticket:

- **Title:** `CCE-N: test hypothesis H2 (final-reminder line) for source-collector reliability`
- **Body:** "CCE-9 measured null result for H1 (legacy ## Output contract block removal). Per roadmap spec §5.3, next hypothesis to test is H2: add a one-line schema restatement as a 'final reminder' at the end of the source-collector prompt. See `docs/superpowers/measurements/2026-05-20-cce9-post-h1.md` for the null-result evidence and `docs/superpowers/measurements/2026-05-20-cce9-baseline.md` for the baseline measurements."
- **Issue type:** Task
- **Project:** CCE

- [ ] **Step B5: Hand off to /ship (proceeds to Task 6 with measurement-only diff)**

Note: even in the null-result case the branch still has 4 commits worth of measurement infrastructure + measurement documents that are valuable to preserve. /ship will open a PR titled `CCE-9: source-collector reliability investigation (H1 null result)` and the diff will contain only the helper script, both measurement docs, and the revert. No agent .md change ships.

---

## Task 6: Final verification + /ship handoff

**Files:**

- Run-only.

- [ ] **Step 1: Full test suite green-light**

```bash
python3 -m pytest -q
```

Expected: 161 passed (no new tests added in CCE-9; the drift lint at `tests/agents/test_schema_md_sync.py` continues to pass).

If failures, stop and diagnose. Source-collector lives in `agents/`, not in `tests/`, so the only test that touches it is `test_schema_md_sync.py::test_schema_md_sync[source-collector]`.

- [ ] **Step 2: Confirm branch state**

```bash
git log --oneline main..HEAD
```

For Option A (H1 lands), expect commits (most recent first):

```
<sha> docs(CCE-9): CHANGELOG entry for v0.1.4 source-collector reliability
<sha> measure(CCE-9): post-H1 source-collector reliability (5 Mode B runs)
<sha> fix(CCE-9): remove legacy ## Output contract block from source-collector.md
<sha> measure(CCE-9): baseline source-collector reliability (5 Mode B runs, pre-H1)
<sha> feat(CCE-9): add scripts/measure_source_collector.sh measurement helper
```

For Option B (null result), the `fix(CCE-9):` commit is followed by a `Revert "fix(CCE-9): ..."` commit (no CHANGELOG entry).

- [ ] **Step 3: Hand off to /ship**

Invoke: `/ship`

The user has pre-authorized `/ship` per CCE ticket. The chain will run pre-flight → cost-gate → test (161/161) → verify-agent → simplify → code review → commit (no-op, already committed) → push + PR → Jira update. The Jira stage will pick `CCE-9` from the branch name `feat/CCE-9-source-collector-reliability`.

After /ship completes and PR is merged:

- **Option A:** tag `v0.1.4`. Then do a clean Mode B run against ADIS to populate `docs/_agent-sandbox/` with real content. Then wire up the MkDocs sandbox HTML preview (separate ticket, outside CCE-9 scope) so the end-goal HTML render is visible.
- **Option B:** no tag. The CCE-N H2 follow-up ticket carries the work forward.

---

## Self-Review

**1. Spec coverage** — all 5 acceptance criteria from spec §5.5 mapped:

| Criterion                                                             | Task                                                                                                     |
| --------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| #1 Baseline of ≥5 runs documented                                     | Task 2 (5 runs via the helper, committed to `docs/superpowers/measurements/2026-05-20-cce9-baseline.md`) |
| #2 H1 tested with one before/after comparison                         | Tasks 2 + 3 + 4 (baseline → H1 → measurement)                                                            |
| #3 Either land with measurable improvement OR null result + follow-up | Task 5 Option A (land) or Option B (revert + file CCE-N)                                                 |
| #4 No other agent .md modified                                        | Task 3 (only `agents/source-collector.md` touched); reinforced by /ship Stage 4 code review              |
| #5 Drift-prevention lint still passes                                 | Task 3 Step 4 + Task 6 Step 1 (test_schema_md_sync.py is in the regular suite and runs in `pytest -q`)   |

**2. Placeholder scan** — no `TBD`, `TODO`, `implement later`, `similar to`, or "add appropriate X" patterns. The `<fill in>` markers in measurement documents are intentional — they direct the engineer to substitute actual observed values from the captured `/tmp/cce9-<label>-run<N>-state.json` files. Every commit command includes its exact message body. The helper script content is shown in full.

**3. Type consistency** — `OUTCOMES` is a bash array of strings. `REASONS` is a string (the classifier output). `state["current_run"]["partial_reasons"]` is a list — matches what CCE-5 just shipped. The classifier's labels (`SUCCESS`, `SCHEMA_INVALID`, `DISPATCH_NONE`, `OTHER`) are used consistently across the script's stdout, the measurement document tables, and the CHANGELOG entry.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-20-cce9-source-collector-reliability.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review between tasks, fast iteration. Each of the 6 tasks above maps to one implementer dispatch + spec review + code-quality review. Note: Tasks 2 and 4 involve real Mode B dispatch costs (token usage on the Anthropic API); the implementer subagent should be allowed to invoke `scripts/measure_source_collector.sh` directly.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

User has pre-authorized executing via subagent-driven-development + `/ship` per ticket once the plan is approved. End goal: a successful Mode B run against ADIS that produces real content into `docs/_agent-sandbox/`, then a follow-up MkDocs sandbox HTML preview pipeline.
