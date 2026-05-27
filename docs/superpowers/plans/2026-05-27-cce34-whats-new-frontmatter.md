# CCE-34 What's-New Frontmatter Spec (Recommendation D) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Author and ship a retroactive design spec documenting the already-shipped whats-new frontmatter fix (PR #44), plus a scoped "Known divergence / future work" section on the two whats-new writers — without designing the reconciliation.

**Architecture:** One new Markdown spec under `docs/superpowers/specs/`, co-located on the existing fix branch `fix/CCE-34-whats-new-frontmatter` (PR #44) so a single validation run covers the fix code, its tests, and the new spec together. The already-committed code (`_compose_whats_new` + its tests) is the source of truth the spec must describe accurately; **this plan writes no production code.** Because the deliverable is documentation of as-built code, the usual TDD arc inverts: the spec is the artifact under test, and validation means every code/test reference in it is grep-verifiable and the full suite stays green.

**Tech Stack:** Markdown (the spec). Python 3 / pytest (`python3 -m pytest`) for the validation gate. `git` + `gh` for the ship phase.

---

## Branch & Ship Constraint (read before Task 1)

**Branch:** All work happens on the **existing** `fix/CCE-34-whats-new-frontmatter` branch (currently checked out, tip `17e4e89`). Do **not** create a new branch. The fix code and its three tests already live here; adding the spec here means "validating all changes and new code" is one suite run over one tree.

**Ship constraint (resolved in Phase Ship, not a surprise):** `/ship`'s Stage 0 pre-flight **halts** on an existing open PR — it only opens _new_ PRs in v1. PR #44 is already open on this branch. Therefore a literal `/ship` invocation will stop before running tests. Phase Ship applies `/ship`'s **validation discipline** (test → simplify → code-review → commit) and completes by pushing to update PR #44, with merge gated on explicit user authorization. The alternative path (merge #44 first, then a clean `/ship` of the spec on its own branch) is offered at the execution handoff.

**Guardrails (carry into every commit/push step):** never use `-f` / `--force` / `--no-verify` / `--amend`. Commit trailer: `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`. Merges to `main` and Jira status transitions require explicit user authorization.

---

## File Structure

- **Create:** `docs/superpowers/specs/2026-05-27-cce34-whats-new-frontmatter-design.md` — the recommendation-D spec. Sole new artifact.
- **Reference only (already committed on this branch — do NOT modify):**
  - `scripts/orchestrator_runner.py:769-798` — `_compose_whats_new(existing, entry)` helper.
  - `scripts/orchestrator_runner.py:1190` — call site `whats_new.write_text(_compose_whats_new(existing, entry))`.
  - `tests/orchestrator/test_pipeline_integration.py:592,619,632` — the three frontmatter tests.
- **Style reference (read, do not edit):** `docs/superpowers/specs/2026-05-26-cce34-item1-semantic-routing-design.md` — the immediately-prior CCE-34 spec; match its structure and voice.

---

### Task 1: Author the recommendation-D spec

**Files:**

- Create: `docs/superpowers/specs/2026-05-27-cce34-whats-new-frontmatter-design.md`

**Scene-setting for the implementer subagent:** This is a _retroactive_ design spec. The fix it documents already shipped in PR #44 on this branch (`fix/CCE-34-whats-new-frontmatter`). You are NOT changing any code. You are writing one Markdown spec that (1) records the as-built fix and (2) flags an architectural divergence as future work — explicitly _without_ designing that future work. Match the voice in `CLAUDE.md` ("Voice & style"): direct, concrete, second person for the reader, third person for the system, short paragraphs, code names as `file_path:line_number`. Use `docs/superpowers/specs/2026-05-26-cce34-item1-semantic-routing-design.md` as the structural template.

- [ ] **Step 1: Read the source-of-truth code and the style template**

Run, and read the output, so the spec's claims are exact:

```bash
sed -n '769,798p;1170,1192p' scripts/orchestrator_runner.py
sed -n '592,665p' tests/orchestrator/test_pipeline_integration.py
sed -n '1,40p' docs/superpowers/specs/2026-05-26-cce34-item1-semantic-routing-design.md
```

Expected: you see `def _compose_whats_new`, the `whats_new.write_text(_compose_whats_new(existing, entry))` call site, the three `test_*` functions, and the prior spec's header/structure.

- [ ] **Step 2: Write the spec file**

Create `docs/superpowers/specs/2026-05-27-cce34-whats-new-frontmatter-design.md` with exactly these sections and content (adapt prose to match house voice; keep every code reference accurate to Step 1):

```markdown
# CCE-34 — What's-New Frontmatter Preservation (as-built)

- **Status:** As-built. Shipped in PR #44 (`fix(CCE-34): preserve whats-new frontmatter on programmatic prepend`).
- **Date:** 2026-05-27
- **Ticket:** CCE-34
- **Related:** PR #44; spec `2026-05-26-cce34-item1-semantic-routing-design.md` (the work whose dry-run surfaced this bug).

## Context

This spec is retroactive. The fix already shipped; the document exists to capture _why_ the change was made and one durable architectural finding the fix exposed.

The bug surfaced during a no-API dry-run of the CCE-34 semantic-routing work. Running the orchestrator's programmatic path against a host whose `whats-new.md` already carried YAML frontmatter produced a file whose frontmatter was no longer at line 1.

## Problem & root cause

The orchestrator built a dated entry (`## <timestamp>` plus optional `### Gaps flagged`) and wrote it with a naive prepend — `entry + existing`. When `existing` began with a `--- ... ---` frontmatter block and a `# What's New` title, the new `## <date>` section landed **above** both. Frontmatter must sit at line 1 for the static-site tooling and for `archive_indexes.parse_frontmatter` to read it, so the naive prepend corrupted the file's structure.

## The fix (as built)

`scripts/orchestrator_runner.py:769` adds `_compose_whats_new(existing, entry)`, wired in at the call site `scripts/orchestrator_runner.py:1190` (`whats_new.write_text(_compose_whats_new(existing, entry))`, replacing `entry + existing`).

The algorithm:

1. Empty/whitespace `existing` → return `entry` unchanged.
2. Otherwise peel a leading `--- ... ---` frontmatter block via `existing.split("---", 2)` — the same delimiter convention as `archive_indexes.parse_frontmatter` (`text.split("---", 2)`), so the two helpers share assumptions.
3. Keep the header region (leading blanks plus a single `# ` title) up to the first `## ` dated section.
4. Insert `entry` immediately before that first `## ` section so entries stay reverse-chronological.
5. Reassemble as `preamble + header + entry + tail`.

**Graceful degradation:** with no frontmatter and no title, the result reduces to the prior `entry + existing` behavior, so hosts without frontmatter are unaffected.

## Testing (as built)

Three tests in `tests/orchestrator/test_pipeline_integration.py`:

- `test_compose_whats_new_preserves_frontmatter` (`:592`) — unit: frontmatter and `# ` title are preserved; the new entry lands before the first `## `.
- `test_compose_whats_new_no_frontmatter_prepends` (`:619`) — unit: degradation to the simple prepend.
- `test_whats_new_prepend_preserves_frontmatter` (`:632`) — integration through `run()` with a frontmatter'd `docs/site-src/whats-new.md` seeded via `_init_host(..., seed_files=...)`.

Full suite at fix time: 557 passed, 3 skipped.

## Known divergence / future work

The fix exposed a more durable finding than the bug itself: the system has **two** whats-new writers.

- **LLM skill path** — `skills/engineering-docs-agent/SKILL.md` step 9, the production nightly path. Authors the dated entry as prose and is frontmatter-aware. A real nightly run (commit `21ff6b7`) placed its `## 2026-05-27` section correctly below `# What's New`, so the **live site was never corrupted**.
- **Python script path** — `scripts/orchestrator_runner.py`, the programmatic / dry-run / test / documented-bootstrap path. Mechanical prepend; this is the path that carried the bug and that `_compose_whats_new` fixes.

These two writers can drift in output format and are unevenly tested. This spec records the divergence as an **open architectural question**. It does not prescribe a reconciliation — sharing a helper, collapsing to one writer, or converging the formats are all candidate future work for a separate brainstorm/spec, not decided here.

## Scope & non-goals

- **Severity:** a programmatic-path defect, not a live-site corruptor — production authoring goes through the frontmatter-aware skill path.
- **Non-goals:** reconciling the two writers; changing skill-path authoring; redesigning the whats-new file format.

## Files changed (all in PR #44)

- `scripts/orchestrator_runner.py` — added `_compose_whats_new`; rewired the prepend call site.
- `tests/orchestrator/test_pipeline_integration.py` — added the three tests above (`_init_host` already supported `seed_files`).
```

- [ ] **Step 3: Self-check the spec against the code**

Verify every code reference resolves (catches drift between prose and tree):

```bash
grep -n "_compose_whats_new" scripts/orchestrator_runner.py
grep -n "def test_compose_whats_new_preserves_frontmatter\|def test_compose_whats_new_no_frontmatter_prepends\|def test_whats_new_prepend_preserves_frontmatter" tests/orchestrator/test_pipeline_integration.py
grep -n "21ff6b7" /dev/null; git cat-file -t 21ff6b7
```

Expected: the helper `def` and call site appear; all three test names appear; `git cat-file -t 21ff6b7` prints `commit`. If any reference is wrong, fix the spec text to match the tree (never the reverse — the code is shipped and authoritative).

- [ ] **Step 4: Commit the spec**

```bash
git add docs/superpowers/specs/2026-05-27-cce34-whats-new-frontmatter-design.md
git commit -m "docs(CCE-34): add as-built spec for whats-new frontmatter fix

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

**Spec-compliance review (D-scope) checklist for the reviewer subagent:**

- Documents the as-built fix (`_compose_whats_new`, call site, algorithm, degradation). ✓ required.
- Includes a "Known divergence / future work" section naming **both** writers (skill path = production/frontmatter-aware; script path = the fixed one). ✓ required.
- Does **NOT** design the reconciliation (no shared-helper/single-writer/format-convergence _decision_). ✗ if present → over-built, cut it.
- States severity honestly (programmatic-path defect, not live-site corruptor). ✓ required.
- No section about _new_ code to write (this is as-built). ✗ if present.

**Code-quality review checklist for the reviewer subagent:** every `file:line` reference resolves against the tree; voice matches `CLAUDE.md` (direct, concrete, second/third person split, short paragraphs); no placeholders/TBDs; reads as a peer of `2026-05-26-cce34-item1-semantic-routing-design.md`.

---

### Task 2: Validate all changes and new code

**Files:** none modified — this task is a verification gate over the branch.

**Scene-setting:** "Validating all changes and new code" means proving the fix code (already on this branch) is green AND that the spec describes it truthfully. This task produces no edits unless it finds a discrepancy; if it does, the discrepancy is a spec error (fix the spec) or a real code regression (STOP, escalate — do not silently patch shipped code).

- [ ] **Step 1: Run the full suite**

```bash
python3 -m pytest -q
```

Expected: `557 passed, 3 skipped` (or more passing if the suite grew). Any failure → STOP and escalate; do not proceed to ship.

- [ ] **Step 2: Run the three frontmatter tests in isolation and confirm they exercise the fix**

```bash
python3 -m pytest tests/orchestrator/test_pipeline_integration.py::test_compose_whats_new_preserves_frontmatter \
  tests/orchestrator/test_pipeline_integration.py::test_compose_whats_new_no_frontmatter_prepends \
  tests/orchestrator/test_pipeline_integration.py::test_whats_new_prepend_preserves_frontmatter -v
```

Expected: 3 passed. These are the tests the spec cites; confirming them green keeps the spec's "Testing (as built)" section truthful.

- [ ] **Step 3: Cross-check each spec claim against the tree**

For every code reference in the spec, confirm it resolves (this is the spec's real "test"):

```bash
sed -n '769,798p' scripts/orchestrator_runner.py   # algorithm matches the spec's 5 steps
grep -n "_compose_whats_new(existing, entry)" scripts/orchestrator_runner.py   # call site wired
grep -n 'split("---", 2)' scripts/orchestrator_runner.py scripts/archive_indexes.py  # shared convention claim
```

Expected: the helper body matches the spec's described 5-step algorithm; the call site appears (at/near line 1190); `split("---", 2)` appears in **both** files (substantiating the "shared assumptions" claim). If the spec overstates or misstates any of these, correct the spec text in a **new follow-up commit** — never amend Task 1's commit:

```bash
git add docs/superpowers/specs/2026-05-27-cce34-whats-new-frontmatter-design.md
git commit -m "docs(CCE-34): correct spec reference to match as-built code

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

- [ ] **Step 4: Voice/style pass**

Re-read the spec against `CLAUDE.md` "Voice & style". Confirm: no hedging ("perhaps", "might consider"), short paragraphs, code names navigable. Fix inline with a follow-up commit if needed (same message pattern as Step 3). No-op if clean.

**Spec-compliance review:** the validation actually ran (paste suite output: `557 passed`), all three named tests passed, every spec reference resolved.

**Code-quality review:** no shipped code was modified; any spec corrections are accurate and committed (not amended).

---

## Phase Ship (orchestrator-driven, human-gated — not a subagent task)

Run after Tasks 1–2 are both ✓. This phase applies `/ship`'s validation discipline; it does not blindly invoke `/ship` because Stage 0 would halt on PR #44.

- [ ] **Step 1: Confirm clean tree and green suite**

```bash
git status --porcelain && python3 -m pytest -q
```

Expected: empty status (all spec work committed), `557 passed, 3 skipped`.

- [ ] **Step 2: Decide the ship path (present to the user, do not assume)**

Two options — surface both, recommend Path A:

- **Path A (recommended): update PR #44 in place.** Spec is co-located with the fix. Push the new spec commit(s) to the existing branch; PR #44 auto-updates to carry code + tests + spec as one cohesive unit.

  ```bash
  git push origin fix/CCE-34-whats-new-frontmatter
  ```

  A literal `/ship` is intentionally NOT invoked here — its Stage 0 pre-flight halts on the already-open PR #44. The `/ship` quality gates (test, code-review) were satisfied by Task 2 and the per-task two-stage reviews.

- **Path B (only if the user wants a literal `/ship` run):** merge PR #44 first (lands the fix + tests on `main`), then move the spec commit onto a fresh branch off the updated `main` and `/ship` it as its own PR. This honors a literal `/ship` but splits the change across two PRs and requires merge authorization for #44 up front.

- [ ] **Step 3: Push (Path A) and report PR #44 status**

```bash
git push origin fix/CCE-34-whats-new-frontmatter
gh pr view 44 --json number,state,mergeable,statusCheckRollup
```

Expected: push succeeds (no `-f`); PR #44 shows the new commit(s) and CI re-running. Report the check status to the user.

- [ ] **Step 4: Merge — only on explicit user authorization**

Per `CLAUDE.md` plugin conventions, merge on a green _integrated_ suite. Before requesting merge: `git fetch origin`, merge `origin/main` into the branch locally, re-run `python3 -m pytest -q`, confirm green. Then ask the user to authorize the merge of PR #44. Do **not** merge without an explicit "yes".

- [ ] **Step 5: Jira (optional, no transition without authorization)**

A CCE-34 comment linking PR #44 + this spec is allowed. A status _transition_ requires explicit user authorization.

---

## Self-Review (author's check of this plan against the spec scope)

1. **Spec coverage:** Task 1 produces every recommendation-D section (as-built fix + scoped divergence + non-goals); Task 2 validates all changes and new code; Phase Ship lands it via `/ship` discipline. ✓
2. **Placeholder scan:** no TBD/TODO; the spec body is given verbatim; all commands have expected output. ✓
3. **Type/reference consistency:** `_compose_whats_new` signature, call-site line 1190, the three test names, and `split("---", 2)` are used identically in the plan, the embedded spec, and the validation greps. ✓
4. **Scope guard:** the plan explicitly forbids designing the two-writer reconciliation and forbids modifying shipped code. ✓
