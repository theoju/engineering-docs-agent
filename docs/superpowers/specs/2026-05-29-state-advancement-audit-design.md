# State-advancement audit on partial runs — design spec

**Ticket:** CCE-62
**Author:** Theo Jungeblut (with Claude Opus 4.7)
**Date:** 2026-05-29
**Status:** Draft

## 1. Problem

Per spec §8 (`docs/superpowers/specs/2026-05-19-engineering-docs-agent-design.md`),
the state-advancement contract has two distinct branches:

- **Subagent crash/timeout** (§8 row 1): orchestrator catches, marks
  `current_run.partial=true` with `partial_reasons`, continues independent
  steps; PR body shows "WARNING — Partial run". The run still produces a PR.
- **PR create/update fails** (§8 row 7): hard fail; `state.json` not advanced;
  next run retries the same window.

CCE-40 (durable state persistence) added merge-as-promotion: `state.json` is
now committed in each docs-agent PR, and merging that PR promotes the state
advance to main. CCE-40 §7 row 4 made the subagent-partial intent explicit:
"Partial run merged by human — Intentional. `last_successful_run` advances;
operators see partial-run status in the PR body before merging."

CCE-41 (subagent forensics in CI) added per-dispatch debug capture and
upload-artifact wiring. It does not touch the state-write path.

This spec audits whether the post-CCE-40/41 codebase still satisfies both §8
contracts, and pins the contract with explicit regression tests so a future
change cannot silently regress the invariant.

## 2. Goal

Confirm — with code citations and regression tests — that:

1. A run where any subagent errors still advances `last_successful_run.head_sha`
   on disk (the on-disk state.json is what the docs-agent commit captures, and
   the merge of that PR is what promotes the advance to main). Operator sees
   the partial flag in the PR body and decides whether to merge.

2. A run where the PR cannot be opened/updated leaves main's effective state
   un-advanced. The runner's on-disk write before PR-open is acknowledged as
   ephemeral in the CI runner: `actions/checkout@v5` provisions a fresh
   working tree at the next nightly fire, so the un-pushed disk advance does
   not persist.

3. The invariant is locked behind regression tests so neither contract can be
   silently broken by a future refactor.

## 3. Architecture

No code architecture change is in scope. The audit confirms the existing flow:

```
run() entry
   │
   ▼
load_state_validated(state_path)
   │
   ▼
initialize current_run = {partial: false, partial_reasons: []}
   │
   ▼
dispatch each subagent
   │ on subagent error → add_partial(state, reason)
   │   → flips current_run.partial = true (unless info_only)
   │   → continues pipeline (independent steps survive)
   ▼
[advance state]
state["last_successful_run"] = {head_sha, completed_at}
save_persistent_state(state_path, state)        # unconditional
   │
   ▼
if no_pr: return 0                              # local dev path
   │
   ▼
open_or_append_pr()
   │ git checkout -B docs-agent/<hour>
   │ git add . && git commit
   │ git push -u origin <branch>
   │ gh pr_list_for_branch / gh pr_create
   ▼
on PR failure → return 1; state.json sits in working tree
on PR success → notifier runs; return 0
```

The merge-to-main of the docs-agent PR is what actually promotes the
advance. Until then it lives only on the docs-agent branch and on disk in
the runner's working tree.

## 4. Files touched

### Modify

None to the runner or state_io. The audit confirms the existing code matches
the spec intent.

### Create

| File                                                                  | Purpose                                                                                                                                                                        |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `docs/superpowers/specs/2026-05-29-state-advancement-audit-design.md` | This document.                                                                                                                                                                 |
| `docs/superpowers/plans/2026-05-29-state-advancement-audit.md`        | Executable plan with the test list.                                                                                                                                            |
| `tests/orchestrator/test_state_advancement_invariant.py`              | Regression tests pinning the invariant per scenario: partial-via-source-collector-error advances, partial-via-lint-block advances, PR-open-failure short-circuits to return 1. |

### Remove

None.

## 5. Detailed design

### 5.1 Evidence — current code satisfies the invariant

**Subagent-partial path:**

- `scripts/state_io.py:220-236` — `add_partial(state, reason, *, info_only=False)`
  flips `current_run.partial = True` (unless `info_only`) and appends the
  reason.
- `scripts/orchestrator_runner.py:1048-1058, 1076, 1116-1126, 1145, 1151,
1154, 1182, 1205-1208, 1268-1269, 1287, 1305, 1316, 1344-1348` — every
  add_partial call site.
- `scripts/orchestrator_runner.py:1373-1383` — unconditional state advance
  after all subagent dispatches:
  ```python
  state["last_successful_run"] = {
      "head_sha": state["current_run"]["head_sha"],
      "completed_at": now,
  }
  save_persistent_state(state_path, state)
  ```
  No check on `state["current_run"]["partial"]`. This matches CCE-40 §7 row 4
  intent.
- `scripts/orchestrator_runner.py:1394` — `partial=state["current_run"]["partial"]`
  is passed to `open_or_append_pr` so the commit message gets "(partial)"
  suffix and the PR body shows the digest.

**PR-open-failure path:**

- `scripts/orchestrator_runner.py:1389-1402` — when `open_or_append_pr`
  returns `pr_number=None`, the runner writes state.json again (still
  advanced) and returns 1.
- The CI workflow's `actions/checkout@v5` step (line 60-66 of
  `.github/workflows/docs-agent-nightly.yml`) checks out main fresh at every
  fire. The runner's working-tree advance is ephemeral when the run can't
  push it to a branch.
- CCE-40 §7 row 3 explicitly chose this interpretation: "Runner writes
  state.json with new SHA but PR open fails: State.json sits in the runner's
  local working tree; nothing reaches main. Next run reads the unchanged
  committed state and tries again with the same window. Self-healing."

**Edge case — push succeeds but `gh pr_create` fails:**

- `scripts/orchestrator_runner.py:1781-1851` — `git push` runs before
  `gh pr_create`.
- If push succeeds and PR-create fails, the docs-agent branch on origin
  carries the advance and the docs in one commit, but no PR exists.
- Next nightly: `_remote_already_processed_window` (lines 1637-1677) checks
  if `origin/<branch>` already advanced to our HEAD. For the same hour
  branch on the same HEAD: skip. For a fresh day with a new HEAD: process
  normally because main's state is still un-advanced.
- An operator who notices the orphan branch and manually merges it gets the
  same outcome as a normal merge — both state advance and docs land
  together.

**`--no-pr` path:**

- `scripts/orchestrator_runner.py:1385-1386` short-circuits after the state
  write. Local-dev users WILL see state.json advance on disk even for
  partial runs. This is not a production-promotion path; the operator
  inspects `git diff` before committing.

### 5.2 Verdict

**The invariant holds.** Both branches of §8 are satisfied by current code as
interpreted by CCE-40 §7. The risk is regression: no existing test pins the
post-partial-run state on disk, so a future refactor could silently break
either branch without breaking any current test.

### 5.3 Regression tests to add

Three deterministic, fixture-driven tests (matching the dry-run pattern used
across `tests/orchestrator/`):

1. **`test_partial_run_via_source_collector_error_advances_state`** —
   Use `tests/orchestrator/fakes_sc_error` (existing fixture that triggers
   `source_collector_error` partial reason). Run with `--no-pr`. Assert:
   - `state.json:last_successful_run.head_sha` equals the repo HEAD at run
     start.
   - `current_run.json:current_run.partial` is true.
   - `current_run.json:current_run.partial_reasons` contains an entry
     matching `source_collector_error`.

2. **`test_partial_run_via_lint_block_advances_state`** —
   Use `tests/orchestrator/fakes_block` (existing fixture that triggers
   `lint_block` partial reason). Run with `--no-pr`. Assert:
   - `state.json:last_successful_run.head_sha` equals HEAD.
   - `current_run.json:current_run.partial` is true.
   - `current_run.json:current_run.partial_reasons` contains a `lint_block`
     entry.

3. **`test_pr_open_failure_returns_1_and_acknowledges_ephemeral_advance`** —
   In-process call to `orchestrator_runner.run()` with `no_pr=False`,
   monkeypatching `open_or_append_pr` to return `(None, [("forced_failure",
False)])`. Assert:
   - The function returns 1 (per spec §8 row 7 "hard fail").
   - `state.json` on disk has `last_successful_run.head_sha` advanced (this
     pins the CCE-40 §7 row 3 "ephemeral in working tree" model: the on-disk
     write is intentional; CI's checkout cycle is what enforces "not
     advanced to main").
   - `current_run.json:current_run.partial_reasons` contains the
     `forced_failure` reason.

The third test is the subtle one. It pins the explicit design choice from
CCE-40 §7 — "on-disk advance is the working-tree write the next checkout
discards" — so a future change that tries to "fix" the advance by gating it
on PR success would break the test and require an explicit spec update.

## 6. Migration & backward compatibility

No code change. No migration concerns.

## 7. Risk & mitigation

| Risk                                                                             | Mitigation                                                                                                                                |
| -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Future refactor moves state advance earlier or removes the partial-aware PR body | Regression tests in §5.3 cover both branches; any change that breaks the invariant breaks at least one test.                              |
| Local-dev `--no-pr` partial run leaves advanced state.json in working tree       | Acknowledged by spec — operator inspects `git diff` before committing. Not a production path.                                             |
| Orphan docs-agent branch after `push` succeeds, `gh pr_create` fails             | Covered by CCE-40 §7 row 3 self-healing analysis; the `_remote_already_processed_window` guard handles same-hour reruns without surprise. |
| Test fixture drift (fakes_sc_error / fakes_block change shape)                   | Tests assert on partial_reasons string-contains, not exact text; lower-bound coupling to fixture content.                                 |

## 8. Acceptance criteria

- [ ] `docs/superpowers/specs/2026-05-29-state-advancement-audit-design.md`
      exists and articulates the invariant + evidence.
- [ ] `docs/superpowers/plans/2026-05-29-state-advancement-audit.md` exists
      with executable steps.
- [ ] `tests/orchestrator/test_state_advancement_invariant.py` exists with
      the three tests in §5.3.
- [ ] Full pytest passes (`python3 -m pytest`).
- [ ] PR opened against main; CCE-62 commented with PR URL.

## 9. Out of scope

- **Refactoring the state advance to be conditional on PR success.** CCE-40
  §7 row 3 explicitly chose the current model. Any such refactor needs its
  own ticket and supersedes the CCE-40 contract.
- **Cross-host state-storage substrates** (S3, KV, GitHub issue body):
  rejected in CCE-40 brainstorm.
- **Bug investigation in source-collector or lint-runner subagents.** This
  audit only covers the orchestrator's state-write contract.

## 10. References

- `docs/superpowers/specs/2026-05-19-engineering-docs-agent-design.md` §8 —
  the original error-handling table.
- `docs/superpowers/specs/2026-05-28-durable-state-persistence.md` §7 row 3 —
  CCE-40's "self-healing" choice for the PR-open-failure case.
- `docs/superpowers/specs/2026-05-28-durable-state-persistence.md` §7 row 4 —
  CCE-40's "intentional advance on partial" choice.
- `scripts/orchestrator_runner.py:1373-1402` — the unconditional state
  advance and PR-open-failure return path.
- `scripts/state_io.py:194-217` — `save_persistent_state` and
  `save_current_run`.
- `scripts/state_io.py:220-236` — `add_partial`.
- `.github/workflows/docs-agent-nightly.yml:60-66` — `actions/checkout@v5`
  with `fetch-depth: 0`; the fresh checkout enforces "ephemeral disk write"
  semantics across nightly fires.
- `tests/orchestrator/test_runner_state_promotion.py` — existing OK-path
  state-promotion tests (post-CCE-40).
- `tests/orchestrator/test_pipeline_integration.py:670-684` — existing
  partial-run test; asserts partial flag but not on-disk state.json.
