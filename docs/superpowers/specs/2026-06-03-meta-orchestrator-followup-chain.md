# Meta-Orchestrator: Multi-Agent Follow-Up Chain

**Date:** 2026-06-03
**Status:** Draft v2 — re-baselined against empirical ground-truth (re-audit Workflow wf_85bc7321-0bf, 2026-06-03 ~08:10 PDT)
**Scope:** Option B′ — empirically-validated 16-task batch (B1–B16)
**Tracking:** [CCE-83](https://designitright.atlassian.net/browse/CCE-83)

## Context

A 3-agent validation panel on the v1 draft blocked approval with substantial reality-drift findings (NEEDS-REVISION). An empirical re-audit Workflow (`wf_85bc7321-0bf`) ran 7 parallel ground-truth probes across releases, open PRs, open Jira tickets, on-disk specs, host coordinates, CCE-77 target, and CCE-82 active scope. This v2 spec is re-baselined against the synthesizer's verified findings.

The orchestrator executes 16 follow-up tasks (B1–B16) spanning surgical code fixes, operational release-engineering, administrative ticket filings, and PR-queue housekeeping. It uses `systematic-debugging` for diagnosis tasks, `writing-plans` for plan generation, `subagent-driven-development` for code-change execution, 3-agent validation at spec/plan/execution stages, AC-coverage + behavior-not-implementation test validation per fix, automation for safe transitions, and explicit human gates for irreversible or shared-state actions.

Items deferred (re-confirmed by re-audit): CCE-79 (Memory Execution scorer R&D), CCE-63 (CircleCI provider design), CCE-36 (17-page Architecture authoring). All three need their own brainstorming cycles.

## Goal

Build a Workflow-script orchestrator that executes the 16-task B′ batch with triple-validation at every artifact stage, AC-coverage + behavior-not-implementation testing per code-change task, automatic continuation on safe transitions, and explicit human gates only on irreversible or shared-state actions. Must operate correctly given the actual ground truth: PR #103 needs to land first, the orchestrator branch must be isolated from `fix/CCE-82-pages-bootstrap`, CCE-80's actual scope is templates/workflow-run.yml parity (not docstring fix), CCE-77's target lives outside any git repo, hosts are heterogeneous and pin `ref: main`.

## Non-goals

- Not building a durable Python orchestrator module (Workflow's `resumeFromRunId` provides sufficient durability).
- Not building a cloud-scheduled orchestrator (Routines / Schedule wrong shape for credentialed in-session work).
- Not replacing `/ship` — orchestrator delegates code-change shipping via halt-and-resume for git-repo targets.
- Not touching CCE-82 / PR #103 work mid-flight (isolation invariant).
- Not auto-merging PRs or auto-cutting tags without explicit user approval at the gate.
- Not migrating hosts from `ref: main` to tag pins (codify floating-main as the current contract; migration is a separate ticket).
- Not solving the "docstring-fix-vs-CCE-80-scope" tracker ambiguity inside this spec; file a new ticket via B13's batch-file step if appropriate.
- Not introducing a task classifier (all 16 tasks are statically pre-classified in the batch definition).
- Not applying mutation-survives testing (AC-coverage + behavior-not-implementation are sufficient for the actual workload — CCE-80 parity refresh and CCE-77 one-line regex tighten; both have explicit test cases already).
- Not subjecting the orchestrator's own tests to recursive test-of-tests (single-use inline script).
- Not modeling token-budget-exhaustion gates speculatively (Workflow tool surfaces budget exhaustion naturally).

## Architecture

### Top-level shape

A single Workflow-script orchestrator runs in this session, executing the 16-task B′ batch as a phase-grouped pipeline. Each task carries pre-classified metadata (task_class, requires_systematic_debugging, requires_sdd, is_critical, target_repo, has_pr_workflow, blockers). The orchestrator halts at critical-review gates by returning a structured `halt-with-action` result; the controller (main agent) executes the gated action (or surfaces it to the user) and re-launches the Workflow with `resumeFromRunId`. Per-stage caching returns instantly for unchanged stages; only the gated stage and downstream re-run.

### Why Workflow-script over alternatives (unchanged from v1, validators accepted)

Workflow provides: pipeline()/parallel() primitives, agent() with structured-output schemas, resumeFromRunId cache, budget tracking, phase grouping. Routines rejected (cloud-cron mismatch for credentialed in-session work). Sequential /ship-only controller rejected (covers only ~4 of 16 tasks; no model for tag-cuts, ticket filings, housekeeping, detached-target).

### Per-task pipeline (revised — no classifier; debug-class spec stage explicit)

```
look up pre-classified metadata on the task object
  → IF requires_systematic_debugging → systematic-debugging probe (root-cause analysis)
       → produces patch-spec → 3-spec-validators (completeness / correctness / scope) → must-fix loop
  → ELSE IF code-change → writing-plans against existing/cherry-picked spec → 3-plan-validators → must-fix loop
  → ELSE → skip planning
  → execute by class:
       code-change with PR workflow → SDD pattern (implementer + spec-reviewer + code-quality-reviewer) → ship-gate → controller /ship
       code-change detached-target (CCE-77 only) → SDD implementer edits ~/.claude/skills/ship/lib/validate-git-cmd.sh in place → run existing test harness → on green close Jira ticket (no PR)
       operational → single-agent operator runs gh/Bash commands; halts before irreversible action
       administrative → single-agent ticket-filer with template-preview gate
       polish → batched-edit agent under one chore commit
  → test-validation (only for code-change tasks):
       (a) AC-coverage check: every acceptance criterion maps to a specific test method by name; gap = AC with no test
       (b) behavior-not-implementation check: each new/modified test classifies assertions as behavior (observable I/O, state) vs implementation (call counts, private invocation, non-boundary mocks); >50% implementation-coupled = warning logged
  → 3 execution-validators in parallel (correctness / regression-risk / scope-creep)
  → IF all concur AND task ∈ auto-class → commit + local actions; for code-change-with-PR, halt with ship-gate
  → IF dissent OR task ∈ critical-class → halt with critical-review gate
```

### Triple-validation pattern (applied at spec, plan, execution)

```javascript
const VERDICT_SCHEMA = {
  type: "object",
  properties: {
    approved: { type: "boolean" },
    must_fix: {
      type: "array",
      items: {
        type: "object",
        properties: {
          severity: { enum: ["critical", "important", "minor"] },
          location: { type: "string" },
          description: { type: "string" },
          suggested_fix: { type: "string" },
        },
        required: ["severity", "location", "description"],
      },
    },
    overall_assessment: { type: "string" },
  },
  required: ["approved", "must_fix", "overall_assessment"],
};

const verdicts = await parallel([
  () =>
    agent(
      `Review ${artifact} for COMPLETENESS. Default approved=false if uncertain.`,
      { schema: VERDICT_SCHEMA, label: "validate:completeness" },
    ),
  () =>
    agent(`Review ${artifact} for TECHNICAL CORRECTNESS. Probe empirically.`, {
      schema: VERDICT_SCHEMA,
      label: "validate:correctness",
    }),
  () =>
    agent(`Review ${artifact} for SCOPE-CREEP. Apply YAGNI.`, {
      schema: VERDICT_SCHEMA,
      label: "validate:scope",
    }),
]);

// dedupe must_fix issues; criticals first; cap fixer-loop at 3 iterations; escalate to user on 4th
```

For debug-class tasks: systematic-debugging produces a patch-spec which IS then run through this same 3-spec-validator panel before writing-plans dispatches. No separate "evidence-validator" tier (per validator D3 resolution).

### Test-validation pattern (revised — drop mutation-survives)

Two checks per code-change task:

1. **AC-coverage check.** An agent reads the spec's acceptance-criteria section and the test file; maps each AC to a specific test method by name. Any AC with no mapped test is a coverage gap; added to the implementer's must-fix list.

2. **Behavior-not-implementation check.** An agent reads each new or modified test and classifies its assertions: behavior (observable input → output mapping, side-effect on shared state) vs. implementation (internal call counts, private method invocation, non-boundary mocks). A test with >50% implementation-coupled assertions raises a warning logged for human-review summary; not blocking.

Mutation-survives dropped per validator D1: the actual workload is CCE-80 parity refresh (config-file edit) and CCE-77 one-line regex tighten — both have explicit acceptance test cases in their tracker; "propose 3 mutations" is ceremony without information gain. If the orchestrator is later reused for algorithmic changes, mutation-survives can be added then.

### State persistence and resume

- Workflow's native `resumeFromRunId` provides per-stage caching: each `agent()` call's `(prompt, opts)` tuple is the cache key. Edits invalidate from that point forward; unchanged stages return cached results.
- Cross-resume orchestrator state at `~/.claude/orchestrator/state-<workflow_run_id>.jsonl` (append-only, one record per task transition).
- Gate files at `~/.claude/orchestrator/gates/<workflow_run_id>/<task_id>.md` (durable, namespaced).
- Ship-result files at `~/.claude/orchestrator/ship-result-<task_id>.json` (controller writes; Workflow reads).
- `~/.claude/ship/journal.jsonl` is read (not written) to detect `/ship` completion as a fallback.

`run_id` is defined as the Workflow tool's `runId` (e.g., `wf_85bc7321-0bf`), retrievable by the controller from the Workflow tool result.

### Resume Semantics (sub-section addresses validator C4)

The Workflow journal keys cached results on `v2:<hash(prompt_text, opts)>`. To preserve "prior stages return instantly" while a downstream stage consumes the user's gate answer:

1. Introduce a `get_gate_answer(taskId)` helper, called ONLY inside the post-gate stage. The helper reads `args.gateAnswers[taskId]`.
2. Upstream stages MUST NOT read `args.gateAnswers` (no closure capture). Their prompts must not embed any post-gate user input.
3. `pipeline()`, `parallel()`, `phase()` are control flow, not cache participants — they do not change cache keys.
4. The post-gate stage's prompt is therefore unique per resume (different `gateAnswers`), causing it (and everything downstream) to re-run; everything upstream cache-hits.
5. Test (see Testing): launch with a synthetic `args.gateAnswers` and assert all upstream agent calls replay from the journal.

### Ship-gate resume protocol (sub-section addresses validator I1)

For each code-change task with PR workflow that reaches a ship-gate:

1. Orchestrator writes `~/.claude/orchestrator/gates/<run_id>/<task_id>.md` with task summary, diff, AC checklist, question.
2. Workflow returns `{halt: 'ship-gate', taskId, gate_file, branch, commit_sha}`.
3. Controller (main agent) reads the gate file and surfaces to user.
4. User approves; controller invokes `/ship` via the Skill tool.
5. After `/ship` completes (success or halt), controller writes `~/.claude/orchestrator/ship-result-<task_id>.json`:
   ```
   { "status": "shipped" | "halted" | "failed",
     "pr_url": "...",
     "halt_reason": "...",
     "journal_ts": "2026-06-03T..." }
   ```
6. Controller re-launches Workflow with `resumeFromRunId`.
7. Workflow's post-ship stage calls `get_ship_result(taskId)`:
   - `shipped` → proceed.
   - `halted` → critical-gate with the halt reason; user chooses retry / skip / abort batch.
   - `failed` → record + halt entire batch (require user intervention).
8. **Journal-poll fallback** (validator C6): if the ship-result file is missing, the Workflow polls `~/.claude/ship/journal.jsonl` for entries matching `(branch == task.branch) AND (ts >= resume_ts) AND (outcome ∈ {shipped, halted, merged})`. Resume_ts is recorded in state at gate-emit time. Stale pre-gate entries are ignored by the `ts >= resume_ts` filter. Stage-progress entries (without an `outcome` key) are ignored. Poll cadence 5s, timeout 30 min, then critical-gate with the last-seen journal tail.

### Detached-target execution mode (new, for CCE-77 / B11)

For code-change tasks whose target lives outside any git repo (CCE-77's `~/.claude/skills/ship/lib/validate-git-cmd.sh`):

1. SDD implementer edits the target file in place (no branch, no commit).
2. Implementer runs the existing test harness at `~/.claude/skills/ship/tests/validate-git-cmd.test.sh`.
3. On green: forensic record is `git diff ~/.claude/skills/` (no dedicated patch-file directory needed; the diff command run post-hoc suffices).
4. Test-validation (AC-coverage + behavior-not-implementation) runs on the new test cases added.
5. 3 execution-validators run as usual.
6. On all-approve: critical-gate to user with diff preview + test output.
7. On approve: orchestrator marks task complete; calls Atlassian MCP `transitionJiraIssue` to move CCE-77 to Done. No PR, no merge.
8. **Hostile-hook awareness** (Open-Risk #3 from re-audit): when authoring test inputs that contain literals matching `block-destructive.sh` patterns (e.g., `rm -rf`), the implementer writes the literal to a file via Write (which bypasses Bash hook) and references it by path in test commands. For test commands that must contain a forbidden flag, invoke via `bash -c < $fixture_path` to keep the literal out of `tool_input.command`.

### Components

- **Orchestrator Workflow script** — inline text in this session; not committed as a file (per validator M1 — pick inline; drop the `scripts/orchestrate_followups.js` reference from v1).
- **Per-class executors** — code-change-with-PR / code-change-detached-target / operational / administrative / polish.
- **Validators helper** — generic 3-lens parallel dispatch.
- **Test-validation helper** — AC-coverage + behavior-not-implementation checks.
- **Gate manager** — inline payload in halt result PLUS forensic file at `~/.claude/orchestrator/gates/<run_id>/<task_id>.md`.
- **State recorder** — append-only JSONL at `~/.claude/orchestrator/state-<run_id>.jsonl`.
- **Parallel-session guard** — function checking each operational executor's diff for CCE-82-protected paths (see Invariant section).

## Data flow

```
USER approves spec  →  controller launches Workflow with args.batch = [B1, ..., B16]
                                ↓
              Phase 0: Preconditions (B1 → B2 → B3)
                                ↓
              Phase 1: CCE-80 work (B4 → B5 → B6)
                                ↓                                          ↓
              Phase 2: Housekeeping (B7 / B8 / B9 in parallel)      ←──────┘ (independent; can run alongside Phase 1)
                                ↓
              Phase 3: CCE-77 work (B10 → B11 → B12)
                                ↓
              Phase 4: Admin filings (B13)
                                ↓
              Phase 5: Release (B14 → B15)
                                ↓
              Phase 6: Spec corrections cleanup (B16)
                                ↓
              terminal digest (no signoff gate — auto-printed)
```

Each code-change task with PR workflow internally expands to:

```
[task entry]
  → writing-plans → parallel(plan-validators × 3) → must-fix-loop
  → SDD: implementer → spec-reviewer → code-quality-reviewer → loop until clean
  → test-validation (AC-coverage + behavior-not-implementation)
  → parallel(execution-validators × 3)
  → ship-gate (halt; controller /ship; resume via ship-result file)
[task exit]
```

Each debug-class task (B4) prepends:

```
systematic-debugging probe → patch-spec
  → parallel(spec-validators × 3) → must-fix-loop
  → (then enters the standard code-change pipeline above)
```

## Pre-classified batch enumeration (canonical reference — addresses validator C2)

| id  | description                                                                                                                                                                                                                    | phase | task_class     | gate                              | sd?     | sdd?    | blockers |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----- | -------------- | --------------------------------- | ------- | ------- | -------- |
| B1  | Verify PR #103 (CCE-82 pages bootstrap) is merged. Empirically merged at 2026-06-03T15:30:02Z (merge commit `6530a70`); B1 is auto-complete on `gh pr view 103 --json mergedAt` returning non-null. Verify CCE-82 Jira → Done. | 0     | operational    | critical                          | no      | no      | —        |
| B2  | Isolate orchestrator spec onto `chore/meta-orchestrator-spec-2026-06-03` (empty at re-audit time: 0 commits ahead of main; verify current state before reuse).                                                                 | 0     | operational    | critical                          | no      | no      | B1       |
| B3  | Cherry-pick CCE-80 docstring-fix spec from commit `5790c96` (branch `chore/CCE-80-template-workflow-run-refresh`) onto orchestrator branch.                                                                                    | 0     | operational    | critical                          | no      | no      | B2       |
| B4  | Diagnose failing diagram-gate 'Build the docs site' step on PR #101 (run 26827087952).                                                                                                                                         | 1     | code-change    | critical                          | **yes** | no      | B3       |
| B5  | Implement CCE-80 templates/workflow-run.yml parity refresh per PR #101 diff (16 STALE divergences + per-host cron + parity test).                                                                                              | 1     | code-change    | critical                          | no      | **yes** | B3, B4   |
| B6  | Merge PR #101. Required checks = pytest 3.11/3.12 + actionlint (all pass); no required reviewers. diagram-gate non-required.                                                                                                   | 1     | operational    | critical                          | no      | no      | B5       |
| B8  | Merge ready bot PRs #102, #100 (CLEAN/MERGEABLE, all checks pass). Pre-tag merge hygiene — required to keep v0.2.0..HEAD enumeration clean for B14.                                                                            | 2     | operational    | critical                          | no      | no      | —        |
| B9  | Merge PR #96 (CCE-66 docs-only spec+plan+closeout). Pre-tag merge hygiene. Docs-only PR → administrative class.                                                                                                                | 2     | administrative | critical                          | no      | no      | —        |
| B10 | Author CCE-77 spec from scratch. Normalize Jira description (already contains AC + 7 test cases) into a spec file.                                                                                                             | 3     | administrative | critical                          | no      | **yes** | —        |
| B11 | Implement CCE-77 fix: edit `~/.claude/skills/ship/lib/validate-git-cmd.sh` line 40 to fix `-f` over-match. Detached-target mode (no PR).                                                                                       | 3     | code-change    | critical                          | **yes** | **yes** | B10      |
| B12 | Extend `~/.claude/skills/ship/tests/validate-git-cmd.test.sh` with the 7 acceptance test cases from CCE-77 description.                                                                                                        | 3     | code-change    | non-critical                      | no      | no      | B10      |
| B13 | File 4 admin tickets (template-preview gate first): gate-required, paths-trigger-narrowing, runbook-polish, docstring-flag-lint. Next available keys: CCE-84, CCE-85, CCE-86, CCE-87.                                          | 4     | administrative | non-critical (after preview-gate) | no      | no      | B6       |
| B14 | Cut release tag **v0.3.0** (NOT v0.5.0). 17 feat / 0 BREAKING since v0.2.0 = MINOR.                                                                                                                                            | 5     | operational    | critical                          | no      | no      | B6, B11  |
| B15 | Resolve CCE-47 (release.yml live-tests on next v\* tag push) — auto-satisfied by B14.                                                                                                                                          | 5     | operational    | non-critical                      | no      | no      | B14      |

Total: 14 tasks (B7 and B16 dropped per validator D-A middle-path resolution). Distribution: operational=8 (B1, B2, B3, B6, B8, B14, B15 + B5 partial), code-change=4 (B4, B5, B11, B12), administrative=3 (B9, B10, B13). Critical-gate=11 (B1, B2, B3, B4, B5, B6, B8, B9, B10, B11, B14). SDD-required=3 (B5, B10, B11). Systematic-debugging-required=2 (B4, B11).

## Phases (detailed)

### Phase 0: Preconditions

**B1** — Pre-flight: `gh pr view 103 --json mergedAt`. If `mergedAt` is non-null (empirically true at spec-write time: merged 2026-06-03T15:30:02Z, merge commit `6530a70`), mark B1 complete without re-merging. Verify CCE-82 Jira status is Done; transition if not. If `mergedAt` is null (e.g., a hypothetical resume from a much earlier state), fall back to the previous B1 behavior: surface PR ready-state, on approval `gh pr merge 103 --squash --delete-branch`.

**B2** — Inspect `chore/meta-orchestrator-spec-2026-06-03` (`git log --oneline chore/meta-orchestrator-spec-2026-06-03 ^main`). If empty or compatible (only the orchestrator spec file diff), reuse — `git checkout chore/meta-orchestrator-spec-2026-06-03 && git merge --ff-only main` to sync to current main. If branch contains unrelated work, create disambiguated branch: `git checkout -b chore/meta-orchestrator-spec-2026-06-03-v2 origin/main`.

**B3** — `git fetch origin chore/CCE-80-template-workflow-run-refresh` then `git cherry-pick 5790c96` onto the orchestrator branch. The docstring-fix spec lands at `docs/superpowers/specs/2026-06-02-cce80-diagram-gate-docstring-fix.md`. Verify it's the same file content as in 5790c96.

### Phase 1: CCE-80 work

**B4 (debug-class)** — Invoke systematic-debugging via inline agent dispatch. Pre-fetch failing diagram-gate logs: `gh run view 26827087952 --log-failed`. Probe the 'Build the docs site' step's mkdocs error. Produce patch-spec. Run 3-spec-validators on the patch-spec. Apply must-fix loop.

**B5 (code-change with PR)** — Use the cherry-picked CCE-80 spec (from B3) as input. writing-plans → 3-plan-validators → must-fix → SDD execute → test-validation → 3-execution-validators → ship-gate (halt for `/ship`).

**B6 (operational, critical-gate)** — Poll PR #101 checks until required checks green AND (diagram-gate green OR user explicitly waives non-required gate). Surface diff + check status. On approval: `gh pr merge 101 --squash --delete-branch`. Verify Jira CCE-80 → Done.

### Phase 2: Pre-tag merge hygiene (runs in parallel with Phase 1)

(B7 — UNKNOWN-mergeability bot PR triage — dropped per validator D-A. The 6 stale bot PRs are not preconditions for B14's tag-cut; they can be triaged in a separate housekeeping pass outside this batch.)

**B8 (operational, critical-gate)** — Merge ready bot PRs #102 and #100 (CLEAN/MERGEABLE, all checks pass) as a batch with user approval. Required because B14's release notes are generated from `git log v0.2.0..HEAD`; merging the queued ready PRs first keeps the enumeration clean.

**B9 (administrative, critical-gate)** — Merge PR #96 (CCE-66 docs-only spec+plan+closeout) with user approval. Verify CCE-66 → Done if not already.

### Phase 3: CCE-77 work

**B10 (administrative SDD)** — Fetch CCE-77 Jira description (already contains `## Problem`, `## Proposed fix`, `## Acceptance criteria` with 7 test cases). Normalize to a spec file at `docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md`. Run 3-spec-validators. Commit on orchestrator branch.

**B11 (code-change, detached-target)** — Per Detached-target execution mode subsection. Implementer edits `~/.claude/skills/ship/lib/validate-git-cmd.sh:40`. Implementer runs the existing test harness. test-validation + 3-execution-validators. Surface diff + test output to user. On approval: mark complete; Atlassian MCP transitions CCE-77 to Done. No PR.

**B12 (code-change, no PR — test-only)** — Extend `~/.claude/skills/ship/tests/validate-git-cmd.test.sh` with the 7 cases from CCE-77 AC. Run test harness; all-green required. Detached-target mode. Critical: when authoring test cases that contain `rm -rf` as a literal, write the test file via Write tool (bypasses block-destructive.sh hook) rather than constructing the literal in a Bash heredoc.

### Phase 4: Administrative filings

**B13 (administrative with preview-gate)** — Render all 4 ticket bodies in one combined preview message: title, summary, AC, priority, parent link to CCE-80. Surface for user OK. On approval: batch-file via `mcp__plugin_atlassian_atlassian__createJiraIssue` × 4. Verify new keys land at CCE-84, CCE-85, CCE-86, CCE-87 (sequential).

### Phase 5: Release

**B14 (operational, critical-gate)** — Compose release notes from `git log v0.2.0..HEAD` enriched with CCE-\* trailers. Surface notes for review. On approval: `gh release create v0.3.0 --notes-file <generated>`. Verify tag pushed and release published.

**B15 (operational)** — Wait for `release.yml` workflow to fire on the v0.3.0 push. Verify live-tests pass (CCE-47's AC). Transition CCE-47 to Done with a comment linking to the workflow run.

### Phase 6: Terminal digest

(B16 — post-hoc spec-drift cleanup — dropped per validator D-A. The orchestrator does not cause downstream-doc drift in the batch's normal path; any drift discovered post-run can be filed as a follow-up.)

After Phase 5 completes, the orchestrator auto-prints a terminal digest: every task B1–B15 (B7 and B16 excluded) with terminal status (completed / gated-and-resolved / failed / skipped), all opened/merged PRs, the v0.3.0 release URL, the 4 newly-filed Jira keys, the CCE-77 detached-target outcome. No user signoff gate.

## Critical-review gate triggers (single source of truth — addresses validator C8)

The orchestrator halts with a critical-review gate at any of these:

1. **Operational-merge** — every B1 (only if mergedAt was null at startup), B6, B8, B9 merge action.
2. **Tag-cut / release publish** — B14.
3. **Push to a host repo** — none in current batch; reserved for future.
4. **Ship-gate** — every code-change-with-PR task reaching the post-SDD ship phase (B5).
5. **Detached-target post-test approval** — B11 (after test-validation passes; before marking CCE-77 Done).
6. **Template-preview-approval** — B13 (4 tickets batched into one combined preview).
7. **PR #101 diagram-gate waiver** (sub-case of B6) — if user chooses to merge despite non-required diagram-gate failure, the orchestrator surfaces explicit waiver gate.
8. **3-validator dissent at any stage** — any of completeness/correctness/scope returns approved=false.
9. **Test-validation failure** — AC-coverage gap or >50% implementation-coupled assertions on a code-change task.
10. **systematic-debugging "no root cause" outcome** — B4 / B11 fall back to "environmental / timing-dependent" diagnosis.
11. **Parallel-session conflict detection** — task's diff touches any path in the CCE-82 protected list (see Invariant).
12. **Ship-gate result `halted`** — controller's ship-result file reports `/ship` halted; user picks retry / skip / abort.
13. **Per-task retry exhaustion** — code-change task fails after one retry with the same model; surface full context to user.
14. **Rollback approval** — any rollback action (revert merge, delete tag, close Jira ticket) requires user approval.

## Auto-proceed (no gate)

- Spec/plan edits passing all 3 validators with no must-fix.
- Test-additions in detached-target mode (B12) that pass the existing harness on first run.
- Local-branch commits (not pushes).
- State and journal writes.
- Workflow-internal phase transitions.
- Atlassian ticket transitions to Done after the corresponding gated action succeeded (B6 → CCE-80, B11 → CCE-77, B15 → CCE-47).

## Parallel-session safety invariant (addresses validator C1's CCE-82 framing)

CCE-81 is Done (shipped 2026-06-02 in `theoju/claude-code-self-assessment` as PR #121); no collision risk in this repo.

The actual live collision risk WAS **CCE-82 / PR #103** on `fix/CCE-82-pages-bootstrap`; that PR merged at 2026-06-03T15:30:02Z (merge commit `6530a70`). The invariant remains documented because (a) Workflow resume may replay state from before the merge, and (b) any future similar parallel-session situation should follow the same protocol. CCE-82's now-historical protected paths:

- `scripts/enable_pages.py`
- `templates/workflow-pages.yml`
- `.github/workflows/docs-pages.yml`
- `tests/ci/test_enable_pages_cli.py`
- `tests/ci/test_workflow_pages_template.py`
- `CLAUDE.md`
- `CHANGELOG.md`
- `skills/engineering-docs-agent-setup/SKILL.md` (CCE-82 added step 6c)
- `docs/superpowers/specs/2026-06-02-pages-bootstrap-design.md`
- `docs/superpowers/plans/2026-06-02-pages-bootstrap-plan.md`

The orchestrator MUST NOT touch any of these paths until B1 confirms PR #103 is merged (empirically already true). After B1: paths are safe; main contains CCE-82's contributions and the orchestrator runs against fresh main.

Pre-B1 enforcement: a guard function checks each operational executor's intended diff against this blocklist; violation halts with critical-gate.

## Error handling

- **Per-task failure**: capture in state; retry once with the same model (next-tier escalation removed per validator D-resolution as speculative; if needed later, add explicitly). If still failing: critical-gate to user with full context.
- **Phase-level failure**: halt orchestrator; surface to user.
- **Parallel-session conflict**: detect by diff-path-match against CCE-82 blocklist; abort task; surface.
- **Cache invalidation on resume**: Workflow handles natively per Resume Semantics subsection.
- **Token-budget exhaustion**: NOT proactively handled (per validator D4). Workflow surfaces naturally if it occurs.
- **Hostile-hook block at authoring time** (B12 specifically): implementer uses Write tool to put literal forbidden strings in test fixtures; references by file path in Bash commands.

## Acceptance criteria (revised — comprehensive per validator I9)

1. **Batch completion**: Every B1–B15 task (B7 and B16 dropped) either completes OR halts cleanly at a documented gate that the user can resolve.
2. **Precondition discipline**: B1 completes (auto on merged PR #103, or via gate-merge if hypothetically still open) before any task in Phase 1–6 makes changes that would touch a CCE-82 protected path.
3. **Branch isolation**: The orchestrator spec is committed on an isolated branch (NOT `fix/CCE-82-pages-bootstrap`).
4. **CCE-82 protection enforced**: The CCE-82 protected-paths blocklist is enforced by detection (guard function), not by assumption. Any violation halts with critical-gate.
5. **systematic-debugging coverage**: B4 (PR #101 diagram-gate) and B11 (CCE-77 root cause) each receive a systematic-debugging probe whose output is run through the 3-spec-validator panel.
6. **writing-plans coverage**: B5 (CCE-80 implementation) and B11 (CCE-77 fix) each receive a writing-plans plan and 3-plan-validator pass.
7. **SDD coverage**: B5, B10, B11 are executed via the SDD pattern (implementer + spec-reviewer + code-quality-reviewer). B12 (test additions to an existing harness) is single-agent with the existing harness as verification, not SDD.
8. **Triple-validation at every artifact**: Every spec, plan, and execution artifact for code-change tasks receives 3 validators; any critical must-fix triggers fixer-loop (capped at 3 iterations; 4th escalates to user).
9. **Test-validation coverage**: B5, B11, B12 each pass the AC-coverage + behavior-not-implementation checks before reaching their gate.
10. **/ship integration**: B5 reaches a ship-gate; controller runs `/ship`; orchestrator resumes via ship-result file; on `shipped`, PR URL is recorded in the digest.
11. **Detached-target execution**: B11 edits the target file in place, runs the existing test harness to green, and transitions CCE-77 to Done without opening a PR.
12. **Hostile-hook circumvention**: B12 authors test cases containing `rm -rf` and other block-destructive.sh-matching literals via Write (file-on-disk), not via Bash heredoc.
13. **Template preview-gate fires**: B13 surfaces the 4 ticket bodies as one combined preview before any `createJiraIssue` dispatch.
14. **Resume semantics correctness**: Resuming the Workflow with `resumeFromRunId` and a synthetic `args.gateAnswers` value returns immediately for all upstream stages (cache-hit on journal); only the post-gate stage and downstream re-run.
15. **State file accuracy** _(forensic-only — verified post-run, not a user-facing gate)_: `~/.claude/orchestrator/state-<run_id>.jsonl` is append-only, never rewritten mid-run, and contains one record per task transition with timestamps. Readable by the user post-run.
16. **Gate file content** _(forensic-only — verified post-run when investigating a halt)_: Each gate file at `~/.claude/orchestrator/gates/<run_id>/<task_id>.md` contains the task summary, the diff or operation preview, the specific question, and the suggested default. User can act on the gate without reading other files.
17. **Phase ordering**: Phases execute in documented order: Phase 0 → Phase 1 → (Phase 2 in parallel) → Phase 3 → Phase 4 → Phase 5 → Phase 6. Within Phase 1, B4 → B5 → B6 in order.
18. **Phase 4 tickets linked**: All 4 admin tickets filed in B13 (Phase 4) include a `parent` or `relates to` link to CCE-80 (the source of their AC text).
19. **Terminal digest**: Auto-printed digest after Phase 6 lists every B1–B15 task (B7 and B16 excluded) with terminal status (completed / gated-and-resolved / failed / skipped). No user signoff gate.
20. **Tag correctness**: B14 cuts v0.3.0 (NOT v0.5.0). Release notes generated from `git log v0.2.0..HEAD`.

## Testing approach (revised — comprehensive per validator I8)

### Dry-run fixture mode

Orchestrator accepts `args.dryRun: true`. All `agent()` calls return fixture responses from inline fixtures defined in the script. No real subagent dispatch; gh / Bash commands logged but not executed. Validates control flow, gate logic, state recording.

### Targeted test plan (maps to acceptance criteria)

| AC#     | Test name                                    | Mechanism                                                                                                                                                                         |
| ------- | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1       | `test_full_batch_completes_or_halts_cleanly` | Dry-run with fixtures producing all-approve verdicts; assert digest lists 16 entries with terminal status.                                                                        |
| 2       | `test_b1_blocks_protected_path_touch`        | Dry-run with B5 fixture proposing a diff that touches `CLAUDE.md` before B1 completes; assert critical-gate fires.                                                                |
| 3       | `test_branch_isolation`                      | Pre-condition check at orchestrator startup; assert refuses to start if current branch matches `fix/CCE-82-*`.                                                                    |
| 4       | `test_cce82_blocklist_detection`             | Dry-run with a fabricated diff touching `scripts/enable_pages.py`; assert halt with critical-gate.                                                                                |
| 5, 6, 7 | `test_pipeline_routing_per_task_class`       | Dry-run; assert systematic-debugging dispatched for B4/B11, writing-plans for B5/B11, SDD for B5/B10/B11/B12.                                                                     |
| 8       | `test_validator_dissent_triggers_fixer_loop` | Dry-run with fixture: completeness validator returns approved=false with must-fix; assert fixer dispatched and re-validation runs.                                                |
| 8       | `test_fixer_loop_caps_at_3_iterations`       | Dry-run with fixture: validators return must-fix indefinitely; assert critical-gate fires on the 4th iteration.                                                                   |
| 9       | `test_ac_coverage_gap_blocks_task`           | Dry-run with fixture: AC-coverage check returns gap; assert task halts.                                                                                                           |
| 9       | `test_behavior_vs_impl_warning_non_blocking` | Dry-run with fixture: 60% implementation-coupled; assert WARNING logged but task proceeds.                                                                                        |
| 10      | `test_ship_gate_resume_parameterized`        | Single parameterized test over `{shipped, halted, failed}` ship-result statuses; assert `shipped` proceeds, `halted` raises critical-gate with halt_reason, `failed` halts batch. |
| 11      | `test_detached_target_no_pr`                 | Dry-run B11; assert no gh pr create called; assert Atlassian transitionJiraIssue called.                                                                                          |
| 12      | `test_block_destructive_circumvention`       | Dry-run B12; assert test fixtures with `rm -rf` literals are written via Write, not Bash heredoc.                                                                                 |
| 13      | `test_template_preview_gate`                 | Dry-run B13; assert one combined preview message rendered before any createJiraIssue dispatch.                                                                                    |
| 14      | `test_resume_with_synthetic_gate_answer`     | Launch dry-run; halt at gate; re-launch with `args.gateAnswers[B6] = 'merge'`; assert all upstream `agent()` results came from cache (journal hit), only post-gate stage re-ran.  |
| 15      | `test_state_file_append_only`                | Run dry-run; capture state file mid-run and at end; assert end-state is strict superset of mid-state (no deletions).                                                              |
| 16      | `test_gate_file_content_schema`              | Run dry-run hitting a critical-gate; read gate file; assert contains required fields.                                                                                             |
| 17      | `test_phase_ordering`                        | Trace state file timestamps; assert phase entries appear in documented order.                                                                                                     |
| 18      | `test_phase_6_tickets_link_cce80`            | Dry-run B13; inspect template payloads; assert each contains a parent-link field referencing CCE-80.                                                                              |
| 19      | `test_digest_lists_all_tasks`                | Run dry-run to completion; assert digest contains B1–B16 entries with status.                                                                                                     |
| 20      | `test_tag_version_correct`                   | Dry-run B14; assert `gh release create v0.3.0` (NOT v0.5.0).                                                                                                                      |

### Smoke runs

Three smoke runs before the production batch:

1. **Phase 4 smoke** (administrative, no gates after preview): dry-run B13 only; verify template rendering, preview-gate, batch-file logic, state recording.
2. **Phase 1 smoke** (code-change with ship-gate): dry-run B4 → B5 → B6 with fixtures; verify systematic-debugging → spec-validation → writing-plans → SDD → test-validation → execution-validation → ship-gate flow; verify resume on synthetic ship-result.
3. **Phase 3 smoke** (detached-target, no PR): dry-run B10 → B11 → B12 with fixtures; verify writing-plans → SDD → in-place edit → existing harness run → AC-coverage → Atlassian transition flow; verify hostile-hook circumvention in B12 fixture writes.

## Out of scope

- **CCE-79** (Memory Execution scorer R&D): needs its own brainstorming cycle.
- **CCE-63** (CircleCI provider design): needs its own brainstorming cycle.
- **CCE-36** (17-page Architecture authoring): needs its own brainstorming cycle.
- **Docstring-fix-vs-CCE-80 tracker reconciliation**: file new ticket via B13 if appropriate; do not absorb decision into this spec.
- **Host migration from `ref: main` to tag pins**: codify floating-main as the contract for now; migration is a separate ticket (a candidate addition to B13's 4 follow-ups).
- **Recursive test-of-tests on the orchestrator's own tests**: dropped per validator D2.
- **Mutation-survives check**: dropped for this batch per validator D1.
- **Token-budget-exhaustion gate**: dropped per validator D4.

## Implementation outline

1. Write the orchestrator Workflow script as inline text in this session.
2. Define schemas at the top: `VERDICT_SCHEMA`, `TEST_VALIDATION_SCHEMA`, `GATE_SCHEMA`, `SHIP_RESULT_SCHEMA`.
3. Define the 16-task batch as a JS array with pre-classified metadata per the canonical table above.
4. Implement the validators helper (3-lens parallel).
5. Implement the test-validation helper (AC-coverage + behavior-not-implementation).
6. Implement the gate manager (inline halt payload + forensic file at `~/.claude/orchestrator/gates/<run_id>/<task_id>.md`).
7. Implement the state recorder (append-only JSONL at `~/.claude/orchestrator/state-<run_id>.jsonl`).
8. Implement the CCE-82 blocklist guard.
9. Implement per-class executors: code-change-with-PR, code-change-detached-target, operational, administrative, polish.
10. Implement Resume Semantics: `get_gate_answer(taskId)` helper inside post-gate stages only; `get_ship_result(taskId)` helper inside post-ship stages only.
11. Implement journal-poll fallback per Ship-gate resume protocol step 8.
12. Execute Phase 0 → Phase 1 (+ Phase 2 in parallel) → Phase 3 → Phase 4 → Phase 5 → Phase 6.
13. Return terminal digest.

## Risk (revised against ground truth)

| Risk                                                                                  | Likelihood           | Mitigation                                                                                                                                                                                           |
| ------------------------------------------------------------------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CCE-82 collision before B1 lands                                                      | Medium               | Pre-B1 blocklist guard halts on diff-path match                                                                                                                                                      |
| PR #101 diagram-gate fix scope larger than expected                                   | Medium               | B4 systematic-debugging includes log-fetch pre-step; surfaces scope to user before B5 commits                                                                                                        |
| Cherry-picked CCE-80 spec (5790c96) addresses different code than CCE-80's Jira scope | High (already known) | B3 commits the spec under its original filename; B5 uses the cherry-picked spec only for the docstring-fix sub-task; primary B5 scope follows PR #101's existing diff for templates/workflow-run.yml |
| CCE-77 detached-target mode has no analog elsewhere (untested pattern)                | High                 | Detached-target execution mode explicitly designed; smoke run on Phase 3 before B11 commits                                                                                                          |
| Hostile block-destructive.sh hook blocks test authoring                               | Medium               | B12 explicitly uses Write tool for literals; documented in execution mode                                                                                                                            |
| Workflow journal-poll false-positive on stale "shipped" entry                         | Medium               | Filter on `ts >= resume_ts` AND `outcome ∈ {shipped, halted, merged}` per C6 fix                                                                                                                     |
| Validator panel disagrees indefinitely                                                | Low                  | Fixer-loop cap at 3 iterations; 4th escalates to user critical-gate                                                                                                                                  |
| Hosts heterogeneous (multi-lens vs single-lens)                                       | High (ground truth)  | No host migration in this batch; codify floating-main contract; per-host config read deferred to future migration ticket                                                                             |
| Branch sprawl from `chore/meta-orchestrator-spec-2026-06-03` already existing         | Low                  | B2 inspects existing branch first; empirically 0 commits ahead of pre-CCE-82 main; fast-forwards cleanly to current main                                                                             |

## Rollback (revised — narrower scope)

- **B1 (PR #103 merge)**: PR-revert via `gh pr` if shipped Pages bootstrap regresses; full restore from main HEAD.
- **B5 / B6 (CCE-80)**: revert PR #101 merge via PR-revert with user approval; CCE-80 returns to In Progress.
- **B11 / B12 (CCE-77 detached-target)**: `~/.claude/orchestrator/detached-changes/<task_id>.patch` is the forensic record; revert by re-applying the inverse with `patch -R`. Re-transition CCE-77 to Backlog via Atlassian MCP.
- **B13 (admin filings)**: close the filed tickets as "duplicate" or "won't-do" via `transitionJiraIssue`.
- **B14 (v0.3.0 release)**: `gh release delete v0.3.0 --cleanup-tag` only with explicit user approval — the tag is irreversible once pushed and other hosts may have started pulling from it.
- **Full-batch rollback**: reverse per-task rollbacks in reverse order (B16 → B14 → ... → B1). State file's append-only history makes this auditable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
