# Meta-Orchestrator Follow-Up Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a Workflow-script meta-orchestrator that executes a 14-task B′ batch (B1–B6, B8–B15) with triple-validation at every artifact stage, AC-coverage + behavior-not-implementation testing per code-change task, automation for safe transitions, and explicit human gates only on irreversible/shared-state actions.

**Architecture:** Inline Workflow script in this session (not committed) composes per-phase executors over a pre-classified 14-task batch; halts at gates by returning `{halt, taskId, payload}` structures; controller resumes via `resumeFromRunId` with cached upstream stages instantly hitting the journal. Code-change tasks with PR workflow halt at a ship-gate so the controller can invoke `/ship`; the detached-target task (CCE-77) edits in place outside any git repo, verifies via the existing bash test harness, and transitions Jira directly with no PR.

**Tech Stack:** Workflow tool (JS), Agent dispatch with structured schemas (VERDICT_SCHEMA), gh CLI, git CLI, Atlassian MCP, `/ship` skill, `superpowers:writing-plans`, `superpowers:subagent-driven-development`, `superpowers:systematic-debugging`, pytest (for the CCE-80 implementation in B5), bash test harness at `~/.claude/skills/ship/tests/validate-git-cmd.test.sh` (for B11/B12).

**Project constraints:**

- Commit trailer on every commit: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
- NEVER use `-f` / `--force` / `--no-verify` / `--amend`
- Test runner: `python3 -m pytest`
- Stdlib-first Python; pytest TDD; fixture-driven dry-run path
- Branch protection on `main`: required = `pytest (3.11)`, `pytest (3.12)`, `actionlint`. `diagram-gate` is non-required.

---

## Phase A: Orchestrator infrastructure

### Task 1: Create orchestrator state directory

**Files:**

- Create: `~/.claude/orchestrator/` (directory)
- Create: `~/.claude/orchestrator/gates/` (sub-directory)

- [ ] **Step 1: Create directories**

Run:

```bash
mkdir -p ~/.claude/orchestrator/gates
```

- [ ] **Step 2: Verify**

Run:

```bash
ls -la ~/.claude/orchestrator/
```

Expected: `gates/` sub-directory exists, parent directory writable by current user.

- [ ] **Step 3: Create `detached-changes/` sub-directory** (for B11/B12 forensic patch files per spec line 467)

Run:

```bash
mkdir -p ~/.claude/orchestrator/detached-changes
```

Expected: exit 0, directory present.

### Task 2: Compose Workflow script preamble — schemas and helpers

**Files:**

- Compose: inline Workflow script (in this session, dispatched via Workflow tool — not committed).

The preamble defines:

- `meta` block (required Workflow contract): `name`, `description`, `phases` for B1-B15 grouping
- `VERDICT_SCHEMA` (used by every validator panel)
- `TEST_VALIDATION_SCHEMA` (AC-coverage + behavior-not-implementation)
- `SHIP_RESULT_SCHEMA` (Workflow reads ship-result-<task_id>.json)
- `GATE_PAYLOAD_SCHEMA` (inline halt payload)
- Helper functions: `validators_panel(artifact_text, label_prefix)`, `gate_halt(taskId, kind, payload)`, `state_append(taskId, transition, detail)`, `get_gate_answer(taskId)` (callable ONLY inside post-gate stage), `get_ship_result(taskId)` (callable ONLY inside post-ship stage)

- [ ] **Step 1: Compose the `meta` block**

```javascript
export const meta = {
  name: "meta-orchestrator-followup-chain",
  description:
    "CCE-83: execute 14-task B-prime batch with triple-validation at every artifact stage",
  phases: [
    { title: "Phase 0: Preconditions" },
    { title: "Phase 1: CCE-80 work" },
    { title: "Phase 2: Pre-tag merge hygiene" },
    { title: "Phase 3: CCE-77 work" },
    { title: "Phase 4: Admin filings" },
    { title: "Phase 5: Release" },
    { title: "Phase 6: Terminal digest" },
  ],
};
```

- [ ] **Step 2: Compose `VERDICT_SCHEMA`**

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
```

- [ ] **Step 3: Compose `TEST_VALIDATION_SCHEMA`**

```javascript
const TEST_VALIDATION_SCHEMA = {
  type: "object",
  properties: {
    ac_coverage: {
      type: "array",
      items: {
        type: "object",
        properties: {
          ac_id: { type: "string" },
          covering_test: { type: "string" },
          gap: { type: "boolean" },
        },
        required: ["ac_id", "gap"],
      },
    },
    behavior_vs_impl: {
      type: "object",
      properties: {
        total_assertions: { type: "number" },
        behavior_assertions: { type: "number" },
        impl_coupled_assertions: { type: "number" },
        warning: { type: "boolean" },
      },
      required: [
        "total_assertions",
        "behavior_assertions",
        "impl_coupled_assertions",
        "warning",
      ],
    },
  },
  required: ["ac_coverage", "behavior_vs_impl"],
};
```

- [ ] **Step 4: Compose `SHIP_RESULT_SCHEMA`**

```javascript
const SHIP_RESULT_SCHEMA = {
  type: "object",
  properties: {
    status: { enum: ["shipped", "halted", "failed"] },
    pr_url: { type: "string" },
    halt_reason: { type: "string" },
    journal_ts: { type: "string" },
  },
  required: ["status"],
};
```

- [ ] **Step 5: Compose `validators_panel()` helper**

```javascript
async function validators_panel(artifact_text, label_prefix) {
  const lenses = [
    {
      lens: "completeness",
      prompt: `Review for COMPLETENESS — does it cover every requirement? Default approved=false if uncertain.`,
    },
    {
      lens: "correctness",
      prompt: `Review for TECHNICAL CORRECTNESS — does the prescribed approach actually work? Probe empirically.`,
    },
    {
      lens: "scope",
      prompt: `Review for SCOPE-CREEP — does it add anything beyond what was asked? Apply YAGNI.`,
    },
  ];
  const verdicts = await parallel(
    lenses.map(
      ({ lens, prompt }) =>
        () =>
          agent(`${prompt}\n\nArtifact under review:\n\n${artifact_text}`, {
            schema: VERDICT_SCHEMA,
            label: `${label_prefix}:${lens}`,
          }),
    ),
  );
  return verdicts.filter(Boolean);
}
```

- [ ] **Step 6: Compose `RUN_ID` + path constants + state/gate helpers**

Workflow scripts cannot use `Date.now()`, `Math.random()`, or argless `new Date()` (they would break resume). All timestamps and randomness come from Bash subshells via `agent()` dispatch. JavaScript also does NOT expand `~` — paths must use `$HOME` inside Bash strings.

````javascript
// args.runId is injected by the controller when dispatching the orchestrator;
// fallback is a stable session identifier so dry-runs and tests work without args.
const RUN_ID = args?.runId || "session-default";
const HOME_ENV = "$HOME"; // expanded by Bash subshells, never by JS
const STATE_PATH = `${HOME_ENV}/.claude/orchestrator/state-${RUN_ID}.jsonl`;
const GATES_DIR = `${HOME_ENV}/.claude/orchestrator/gates/${RUN_ID}`;
const DETACHED_CHANGES_DIR = `${HOME_ENV}/.claude/orchestrator/detached-changes`;
const SHIP_RESULT_PATH = (taskId) =>
  `${HOME_ENV}/.claude/orchestrator/ship-result-${taskId}.json`;

// State recorder — addresses spec AC#15 (append-only JSONL with one record per transition).
// Spawns Bash via agent() because Workflow JS has no filesystem access.
async function state_append(taskId, transition, detail) {
  const detail_json = JSON.stringify(detail ?? "");
  await agent(
    `Run a single Bash command that:
1. Ensures the directory exists: mkdir -p "$(dirname "${STATE_PATH}")"
2. Appends one JSON line to ${STATE_PATH} with this exact shape:
   {"ts":"<UTC ISO-8601>","taskId":"${taskId}","transition":"${transition}","detail":${detail_json}}
   where <UTC ISO-8601> comes from: date -u +"%Y-%m-%dT%H:%M:%SZ"
Use printf (not echo -e) to preserve literal characters.
Report only the exit code of the append.`,
    { label: `state:append:${taskId}:${transition}` },
  );
}

// Gate manager — addresses spec AC#16: writes the forensic .md file BEFORE returning the halt structure.
async function gate_halt(taskId, kind, payload) {
  const md = [
    `# Gate: ${taskId} — ${kind}`,
    ``,
    `**Run:** ${RUN_ID}`,
    ``,
    `## Task summary`,
    ``,
    payload.summary || "(no summary provided)",
    ``,
    `## Operation preview / diff`,
    ``,
    "```",
    payload.diff || payload.command || JSON.stringify(payload, null, 2),
    "```",
    ``,
    `## Specific question`,
    ``,
    payload.question || `Approve ${taskId} (${kind}) to proceed?`,
    ``,
    `## Suggested default`,
    ``,
    payload.suggested || payload.next_action || "(no suggestion)",
    ``,
  ].join("\n");
  await agent(
    `Use the Write tool to create a file at ${GATES_DIR}/${taskId}.md (create the directory first via Bash mkdir -p ${GATES_DIR}) with this exact content:

${md}

Report only "written" on success.`,
    { label: `gate:write:${taskId}:${kind}` },
  );
  await state_append(taskId, "gated", `${kind}:${GATES_DIR}/${taskId}.md`);
  return { halt: "critical-gate", taskId, kind, payload };
}

// Called ONLY inside post-gate stages. Reading args.gateAnswers here is what causes
// resume re-execution from this point forward (Workflow's cache-bust trigger).
function get_gate_answer(taskId) {
  return args?.gateAnswers?.[taskId];
}

// Called ONLY inside post-ship stages. File-based IPC per spec lines 152-158;
// args.shipResults retained as a secondary fallback for dry-runs and tests.
async function get_ship_result(taskId) {
  const file_content = await agent(
    `Run: cat "${SHIP_RESULT_PATH(taskId)}" 2>/dev/null || printf MISSING
Report only the literal output, nothing else.`,
    { label: `ship-result:read:${taskId}` },
  );
  const trimmed = (file_content || "").trim();
  if (trimmed && trimmed !== "MISSING") {
    try {
      return JSON.parse(trimmed);
    } catch {
      // fall through to args fallback if the file is malformed
    }
  }
  return args?.shipResults?.[taskId];
}
````

- [ ] **Step 7: Compose `cce82_blocklist_guard()` — spec AC#4 + line 349**

```javascript
// 10 protected paths from spec lines 336-344 (CCE-82's now-historical scope)
const CCE82_PROTECTED_PATHS = [
  "scripts/enable_pages.py",
  "templates/workflow-pages.yml",
  ".github/workflows/docs-pages.yml",
  "tests/ci/test_enable_pages_cli.py",
  "tests/ci/test_workflow_pages_template.py",
  "CLAUDE.md",
  "CHANGELOG.md",
  "skills/engineering-docs-agent-setup/SKILL.md",
  "docs/superpowers/specs/2026-06-02-pages-bootstrap-design.md",
  "docs/superpowers/plans/2026-06-02-pages-bootstrap-plan.md",
];

// Returns a gate_halt structure on violation, or null when safe.
// Invoke at the start of every operational executor BEFORE any mutating action.
async function cce82_blocklist_guard(diff_text, taskId) {
  if (!diff_text) return null;
  const matches = CCE82_PROTECTED_PATHS.filter((p) => diff_text.includes(p));
  if (matches.length === 0) return null;
  return await gate_halt(taskId, "cce82-blocklist-violation", {
    summary: `Intended diff touches ${matches.length} CCE-82-protected path(s): ${matches.join(", ")}`,
    diff: diff_text,
    question:
      "These paths were reserved during the CCE-82 parallel-session work. Approve to proceed (post-PR #103 merge they should be safe)?",
    suggested: "review against latest origin/main before approving",
  });
}
```

> Iter-2 deletion: Steps 8 (`retry_once`), 9 (`rollback_gate`), 10
> (`check_blockers_satisfied`) were removed after the validator scope lens
> flagged them as defensive code with zero call sites in the plan body. Spec
> trigger #13 (retry policy) and #14 (rollback policy) are documentation-level
> recovery guidance and can be invoked ad-hoc with `gate_halt(taskId, 'retry-exhausted', payload)`
> or `gate_halt(taskId, 'rollback-approval', payload)` directly when a future
> task needs them. AC#17 (phase ordering) is enforced structurally by the
> sequential `await phase0(); await parallel([...]); await phase3(); ...`
> driver in Task 3 Step 3 — not by a runtime blocker-satisfaction guard.

- [ ] **Step 8: Self-check preamble**

Verify:

- Every schema has `required` arrays.
- Every helper documented.
- `RUN_ID` is wired from `args?.runId` with a fallback.
- All filesystem paths use `$HOME` (Bash-expanded) — no JS `~` literals remain.
- `state_append`, `gate_halt`, `get_ship_result`, `cce82_blocklist_guard` are all `async function`.
- `args.gateAnswers` is read only inside post-gate stages (helpers called inside post-gate stages are fine).
- `args.shipResults` is read only inside post-ship stages.

### Task 3: Define batch enumeration (B1-B15)

**Files:**

- Inline in Workflow script body.

Per spec batch table at lines 233-248. Pre-classified metadata per task.

- [ ] **Step 1: Define the BATCH constant**

```javascript
const BATCH = [
  {
    id: "B1",
    phase: "Phase 0: Preconditions",
    task_class: "operational",
    description: "Verify PR #103 merged",
    critical: true,
    requires_systematic_debugging: false,
    requires_sdd: false,
    target_repo: "theoju/engineering-docs-agent",
    blockers: [],
  },
  {
    id: "B2",
    phase: "Phase 0: Preconditions",
    task_class: "operational",
    description: "Verify orchestrator branch isolation",
    critical: true,
    requires_systematic_debugging: false,
    requires_sdd: false,
    target_repo: "theoju/engineering-docs-agent",
    blockers: ["B1"],
  },
  {
    id: "B3",
    phase: "Phase 0: Preconditions",
    task_class: "operational",
    description: "Cherry-pick CCE-80 docstring-fix spec from 5790c96",
    critical: true,
    requires_systematic_debugging: false,
    requires_sdd: false,
    target_repo: "theoju/engineering-docs-agent",
    blockers: ["B2"],
  },
  {
    id: "B4",
    phase: "Phase 1: CCE-80 work",
    task_class: "code-change",
    description:
      "Diagnose failing diagram-gate Build the docs site step on PR #101",
    critical: true,
    requires_systematic_debugging: true,
    requires_sdd: false,
    target_repo: "theoju/engineering-docs-agent",
    blockers: ["B3"],
  },
  {
    id: "B5",
    phase: "Phase 1: CCE-80 work",
    task_class: "code-change",
    description: "Implement CCE-80 templates/workflow-run.yml parity refresh",
    critical: true,
    requires_systematic_debugging: false,
    requires_sdd: true,
    target_repo: "theoju/engineering-docs-agent",
    branch: "chore/CCE-80-template-workflow-run-refresh",
    blockers: ["B3", "B4"],
  },
  {
    id: "B6",
    phase: "Phase 1: CCE-80 work",
    task_class: "operational",
    description: "Merge PR #101 with required-check verification",
    critical: true,
    requires_systematic_debugging: false,
    requires_sdd: false,
    target_repo: "theoju/engineering-docs-agent",
    pr: 101,
    blockers: ["B5"],
  },
  {
    id: "B8",
    phase: "Phase 2: Pre-tag merge hygiene",
    task_class: "operational",
    description: "Merge ready bot PRs #102 and #100",
    critical: true,
    requires_systematic_debugging: false,
    requires_sdd: false,
    target_repo: "theoju/engineering-docs-agent",
    prs: [102, 100],
    blockers: [],
  },
  {
    id: "B9",
    phase: "Phase 2: Pre-tag merge hygiene",
    task_class: "administrative",
    description: "Merge PR #96 (CCE-66 docs-only)",
    critical: true,
    requires_systematic_debugging: false,
    requires_sdd: false,
    target_repo: "theoju/engineering-docs-agent",
    pr: 96,
    blockers: [],
  },
  {
    id: "B10",
    phase: "Phase 3: CCE-77 work",
    task_class: "administrative",
    description: "Author CCE-77 spec from Jira description",
    critical: true,
    requires_systematic_debugging: false,
    requires_sdd: true,
    target_repo: "theoju/engineering-docs-agent",
    blockers: [],
  },
  {
    id: "B11",
    phase: "Phase 3: CCE-77 work",
    task_class: "code-change-detached",
    description:
      "Fix -f over-match in ~/.claude/skills/ship/lib/validate-git-cmd.sh",
    critical: true,
    requires_systematic_debugging: true,
    requires_sdd: true,
    target_repo: null,
    target_path: "~/.claude/skills/ship/lib/validate-git-cmd.sh",
    blockers: ["B10"],
  },
  {
    id: "B12",
    phase: "Phase 3: CCE-77 work",
    task_class: "code-change-detached",
    description:
      "Extend validate-git-cmd.test.sh with 7 CCE-77 acceptance cases",
    critical: false,
    requires_systematic_debugging: false,
    requires_sdd: false,
    target_repo: null,
    target_path: "~/.claude/skills/ship/tests/validate-git-cmd.test.sh",
    blockers: ["B10"],
  },
  {
    id: "B13",
    phase: "Phase 4: Admin filings",
    task_class: "administrative",
    description: "File 4 follow-up CCE tickets with template-preview gate",
    critical: false,
    requires_systematic_debugging: false,
    requires_sdd: false,
    expected_keys: ["CCE-84", "CCE-85", "CCE-86", "CCE-87"],
    blockers: ["B6"],
  },
  {
    id: "B14",
    phase: "Phase 5: Release",
    task_class: "operational",
    description: "Cut v0.3.0 release tag",
    critical: true,
    requires_systematic_debugging: false,
    requires_sdd: false,
    target_repo: "theoju/engineering-docs-agent",
    tag: "v0.3.0",
    blockers: ["B6", "B11"],
  },
  {
    id: "B15",
    phase: "Phase 5: Release",
    task_class: "operational",
    description: "Close out CCE-47 on release.yml live-tests verification",
    critical: false,
    requires_systematic_debugging: false,
    requires_sdd: false,
    target_repo: "theoju/engineering-docs-agent",
    jira: "CCE-47",
    blockers: ["B14"],
  },
];
```

- [ ] **Step 2: Sanity-check enumeration**

Verify: 14 entries, IDs match spec (B7 and B16 absent), blockers reference only existing IDs.

```javascript
// In the script body, before any phase execution:
const ids = new Set(BATCH.map((t) => t.id));
for (const t of BATCH) {
  for (const b of t.blockers) {
    if (!ids.has(b)) throw new Error(`${t.id} blocker ${b} not in BATCH`);
  }
}
```

- [ ] **Step 3: Top-level driver — Phase 1 || Phase 2 parallel execution**

Per spec line 198 + AC#17: Phase 1 (CCE-80 work: B4 → B5 → B6) and Phase 2
(pre-tag merge hygiene: B8, B9) have no inter-phase blocker and MUST run in
parallel. Phase 0 (B1, B2, B3) gates them both; Phase 3 (B10–B12) gates on
Phase 1 + Phase 2 completion; Phases 4, 5, 6 follow sequentially.

```javascript
async function phase0() {
  // B1 → B2 → B3 (sequential per blockers in BATCH)
  await b1_executor();
  await b2_executor();
  await b3_executor();
}

async function phase1() {
  // B4 → B5 → B6 (sequential per blockers)
  await b4_executor();
  await b5_executor();
  await b6_executor();
}

async function phase2() {
  // B8 + B9 (parallel within phase — independent operationals)
  await parallel([() => b8_executor(), () => b9_executor()]);
}

async function phase3() {
  // B10 → B11 (B11 blocked by B10) || B12 (B12 also blocked by B10)
  await b10_executor();
  await parallel([() => b11_executor(), () => b12_executor()]);
}

async function phase4() {
  await b13_executor();
}
async function phase5() {
  await b14_executor();
  await b15_executor();
}
async function phase6() {
  await digest_executor();
}

// Top-level driver
await phase0();
await parallel([() => phase1(), () => phase2()]);
await phase3();
await phase4();
await phase5();
await phase6();
```

- [ ] **Step 4: Document the CCE-82 blocklist-guard invocation pattern**

Per validator I7 + spec AC#4 / line 349: every mutating executor (code-change
B5/B11/B12; operational merges B6/B8/B9/B14; administrative filings B13;
release B15) MUST invoke `cce82_blocklist_guard` BEFORE any mutating action.
Read-only verifications (B1, B2) skip the guard since they make no diff. The
guard takes the intended diff/paths and returns either `null` (safe) or a
`gate_halt` structure (halt the executor immediately).

Phase ordering (spec AC#17) is enforced **structurally** by the top-level
driver in Step 3 — sequential `await phase0(); await parallel([...]); await
phase3(); ...` is what guarantees blockers complete before dependents start.
There is no separate runtime blocker-satisfaction guard.

Canonical inline pattern (used at the top of every mutating executor body):

```javascript
// At the top of the executor body, before any mutating dispatch:
const blocklist_halt = await cce82_blocklist_guard(intended_diff, "B<N>");
if (blocklist_halt) return blocklist_halt;
// ... task-specific stages follow ...
```

Worked example — B5 (Task 11) is the canonical demo. Task 11 Step 2 dispatches
SDD which produces the CCE-80 diff; the guard is invoked immediately after the
diff is captured (see Task 11 for the inlined invocation). Other mutating
executors follow the same shape: compute the intended diff, run the guard,
return its halt structure if non-null, otherwise continue.

- [ ] **Step 5: Executor function-naming convention**

The Phase J test tasks (Tasks 35–54) and the top-level driver in Step 3
reference each batch item's executor as `b<N>_executor()` (e.g., `b1_executor`,
`b5_executor`, `b11_executor`). The convention is documentation-level — the
implementer assembles each `b<N>_executor` as an `async function` that wraps
the code blocks of the corresponding task (or task range, for B5 and B11):

- `b1_executor` ← Task 4 code blocks
- `b2_executor` ← Task 5 code blocks
- `b3_executor` ← Task 6 code blocks
- `b4_executor` ← Tasks 7 + 8 + 9 code blocks
- `b5_executor` ← Tasks 10 + 11 + 12 + 13 + 14 code blocks
- `b6_executor` ← Task 15 code blocks
- `b8_executor` ← Task 16 code blocks
- `b9_executor` ← Task 17 code blocks
- `b10_executor` ← Tasks 18 + 19 + 20 code blocks
- `b11_executor` ← Tasks 21 + 21b + 21c + 21d + 21e + 22 + 23 + 24 code blocks
- `b12_executor` ← Task 25 code blocks
- `b13_executor` ← Tasks 26 + 27 code blocks
- `b14_executor` ← Tasks 28 + 29 code blocks
- `b15_executor` ← Task 30 code blocks
- `digest_executor` ← Phase H tasks

Phase J test tasks invoke the orchestrator with `args.scope=['B<N>']` to run a
single executor in isolation (rather than calling `b<N>_executor()` directly),
which keeps the Workflow boundary clean. Example test dispatch:

```javascript
const result = await workflow(
  { name: "meta-orchestrator-followup-chain" },
  { dryRun: true, scope: ["B5"], fixtures: PHASE_1_FIXTURES },
);
```

---

## Phase B: Phase 0 — Preconditions

### Task 4: B1 — Verify PR #103 merged

**Files:**

- Reads: gh API (PR #103 metadata).
- Writes: `~/.claude/orchestrator/state-<run_id>.jsonl` (transition record).

- [ ] **Step 1: Compose the B1 executor stage**

```javascript
phase("Phase 0: Preconditions");
const b1_merged_ts = await agent(
  `Run: gh pr view 103 --json mergedAt,state,mergeCommit
Report only the JSON output. If mergedAt is non-null, B1 is auto-complete.`,
  { label: "B1:verify-103-merged" },
);
await state_append("B1", "auto-completed", `PR #103 merged at ${b1_merged_ts}`);
```

- [ ] **Step 2: If `mergedAt` is null (hypothetical resume from much earlier state)**

The B1 stage halts with a critical-gate:

```javascript
if (!b1_merged_ts || b1_merged_ts.includes("null")) {
  return await gate_halt("B1", "merge-103", {
    summary:
      "PR #103 (CCE-82 pages bootstrap) is not yet merged. User approval to proceed?",
    suggested: "gh pr merge 103 --squash --delete-branch",
  });
}
```

- [ ] **Step 3: Verify CCE-82 Jira status**

```javascript
const cce82_status = await agent(
  `Use mcp__plugin_atlassian_atlassian__getJiraIssue with cloudId="designitright.atlassian.net" and issueIdOrKey="CCE-82". Report only the status.name.`,
  { label: "B1:verify-cce82-jira" },
);
if (cce82_status !== "Done") {
  // transition CCE-82 to Done via Atlassian MCP transitionJiraIssue
  await agent(
    `Use mcp__plugin_atlassian_atlassian__getTransitionsForJiraIssue then transitionJiraIssue to move CCE-82 to Done.`,
    { label: "B1:transition-cce82" },
  );
}
await state_append("B1", "completed", "CCE-82 Jira = Done");
```

### Task 5: B2 — Verify orchestrator branch isolation

**Files:**

- Reads: `git branch --show-current`, `git log` on `chore/meta-orchestrator-spec-2026-06-03`.

- [ ] **Step 1: Verify current branch**

```javascript
const branch = await agent(
  `Run: git -C /Users/theo/Projects/engineering-docs-agent branch --show-current
Report the branch name.`,
  { label: "B2:current-branch" },
);
if (branch !== "chore/meta-orchestrator-spec-2026-06-03") {
  return await gate_halt("B2", "wrong-branch", {
    summary: `Expected chore/meta-orchestrator-spec-2026-06-03; got ${branch}. User direction?`,
    suggested: "git checkout chore/meta-orchestrator-spec-2026-06-03",
  });
}
await state_append("B2", "completed", `on branch ${branch}`);
```

- [ ] **Step 2: Verify branch is at current main HEAD or fast-forwardable**

```javascript
const ahead_behind = await agent(
  `Run: git -C /Users/theo/Projects/engineering-docs-agent rev-list --left-right --count origin/main...HEAD
Report the two numbers (behind, ahead).`,
  { label: "B2:ahead-behind" },
);
// If behind > 0, fast-forward; if ahead > 0, that's our spec + CCE-83 commits, which is fine.
```

### Task 6: B3 — Cherry-pick CCE-80 docstring-fix spec

**Files:**

- Creates: `docs/superpowers/specs/2026-06-02-cce80-diagram-gate-docstring-fix.md` (cherry-picked from commit 5790c96)

- [ ] **Step 1: Fetch the source branch**

```javascript
const fetch_ok = await agent(
  `Run: git -C /Users/theo/Projects/engineering-docs-agent fetch origin chore/CCE-80-template-workflow-run-refresh
Report success or any error.`,
  { label: "B3:fetch-source" },
);
```

- [ ] **Step 2: Cherry-pick commit 5790c96**

```javascript
const cherrypick = await agent(
  `Run: git -C /Users/theo/Projects/engineering-docs-agent cherry-pick 5790c96
If there's a conflict, report the conflicting files; do NOT attempt --strategy or --abort without user approval.`,
  { label: "B3:cherry-pick" },
);
if (cherrypick.includes("CONFLICT")) {
  return await gate_halt("B3", "cherry-pick-conflict", { summary: cherrypick });
}
await state_append("B3", "completed", "cherry-picked 5790c96");
```

- [ ] **Step 3: Verify the spec file is present**

```javascript
const spec_present = await agent(
  `Run: ls /Users/theo/Projects/engineering-docs-agent/docs/superpowers/specs/2026-06-02-cce80-diagram-gate-docstring-fix.md
Report exit code.`,
  { label: "B3:verify-spec-present" },
);
```

---

## Phase C: Phase 1 — CCE-80 work (PR #101)

### Task 7: B4 — Pre-fetch failing diagram-gate logs (systematic-debugging Phase 1)

**Files:**

- Reads: gh workflow run logs (run 26827087952).
- Writes: a transient log file at `/tmp/cce80-diagram-gate-failure.log` for the diagnosis agent to consume.

- [ ] **Step 1: Fetch the failing job's log**

```javascript
phase("Phase 1: CCE-80 work");
await agent(
  `Run: gh run view 26827087952 --log-failed > /tmp/cce80-diagram-gate-failure.log
Report file size and first 100 lines of /tmp/cce80-diagram-gate-failure.log via head -100.`,
  { label: "B4:fetch-failed-log" },
);
await state_append(
  "B4",
  "log-fetched",
  "run 26827087952 stored at /tmp/cce80-diagram-gate-failure.log",
);
```

### Task 8: B4 — Systematic-debugging probe

**Files:**

- Produces: patch-spec text (in-memory; not yet written to disk).

- [ ] **Step 1: Dispatch a systematic-debugging probe**

```javascript
// Shared patch-spec schema (reused by Task 9's fixer iterations).
const PATCH_SPEC_SCHEMA = {
  type: "object",
  properties: {
    root_cause: { type: "string" },
    fix_description: { type: "string" },
    files_to_modify: { type: "array", items: { type: "string" } },
    test_to_add: { type: "string" },
    acceptance_criteria: { type: "array", items: { type: "string" } },
  },
  required: [
    "root_cause",
    "fix_description",
    "files_to_modify",
    "acceptance_criteria",
  ],
};

// `let` (not const): Task 9's must-fix loop reassigns debug_output on each iteration.
let debug_output = await agent(
  `You are running superpowers:systematic-debugging on the failing diagram-gate 'Build the docs site' step on PR #101.

Read /tmp/cce80-diagram-gate-failure.log.

Apply the 4-phase process:
1. Root Cause Investigation: read errors carefully, identify the exact failure mode (mkdocs build error? missing diagram artifact? plugin import? broken link?). Reproduce locally if possible via 'cd /Users/theo/Projects/engineering-docs-agent && python3 -m mkdocs build --strict'.
2. Pattern Analysis: find working examples (e.g., recently-passing diagram-gate runs).
3. Hypothesis: form ONE single hypothesis stating root cause.
4. Implementation: produce a patch-spec describing the minimal fix and the failing test that proves it.

Return a structured patch-spec with: { root_cause, fix_description, files_to_modify, test_to_add, acceptance_criteria[] }.`,
  { schema: PATCH_SPEC_SCHEMA, label: "B4:debug-probe" },
);
await state_append(
  "B4",
  "patch-spec-drafted",
  JSON.stringify(debug_output).slice(0, 200),
);
```

### Task 9: B4 — 3-spec-validator panel on patch-spec

**Files:**

- Reads: in-memory patch-spec from Task 8.
- Validators output: `~/.claude/orchestrator/state-<run_id>.jsonl` (per-validator verdict records).

- [ ] **Step 1: Dispatch validators_panel on the patch-spec**

```javascript
const patch_spec_text = JSON.stringify(debug_output, null, 2);
const b4_verdicts = await validators_panel(patch_spec_text, "B4-patch-spec");
// `let`: reassigned inside the must-fix loop in Step 2.
let must_fix = b4_verdicts.flatMap((v) => v.must_fix || []);
let has_critical = must_fix.some((m) => m.severity === "critical");
```

- [ ] **Step 2: Must-fix loop (capped at 3 iterations)**

```javascript
let iterations = 0;
while (has_critical && iterations < 3) {
  iterations++;
  // Dispatch a "fixer" agent to revise the patch-spec given the must_fix list.
  debug_output = await agent(
    `Given this patch-spec: ${JSON.stringify(debug_output)}\n\nAnd these must-fix items: ${JSON.stringify(must_fix)}\n\nProduce a revised patch-spec addressing every critical must-fix.`,
    { schema: PATCH_SPEC_SCHEMA, label: `B4:fixer-iter-${iterations}` },
  );
  // Re-validate
  const new_verdicts = await validators_panel(
    JSON.stringify(debug_output, null, 2),
    `B4-patch-spec-iter-${iterations}`,
  );
  must_fix = new_verdicts.flatMap((v) => v.must_fix || []);
  has_critical = must_fix.some((m) => m.severity === "critical");
}
if (has_critical) {
  return await gate_halt("B4", "validator-dissent-exhausted", { must_fix });
}
await state_append("B4", "patch-spec-validated", `${iterations} iterations`);
```

### Task 10: B5 — Recursive writing-plans on CCE-80 implementation

**Files:**

- Reads: cherry-picked CCE-80 spec at `docs/superpowers/specs/2026-06-02-cce80-diagram-gate-docstring-fix.md`.
- Reads: B4 patch-spec (in-memory).
- Produces: nested CCE-80 implementation plan (separate file via writing-plans's normal path).

- [ ] **Step 1: Dispatch writing-plans for B5**

```javascript
const b5_plan_path = await agent(
  `Invoke superpowers:writing-plans against the spec at docs/superpowers/specs/2026-06-02-cce80-diagram-gate-docstring-fix.md.

Augment with the B4 patch-spec for the diagram-gate fix: ${JSON.stringify(debug_output)}

Constraints same as outer plan: pytest TDD, commit trailer 'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>', never use -f/--force/--no-verify/--amend, test runner python3 -m pytest.

The plan executes via subagent-driven-development with per-task implementer + spec-reviewer + code-quality-reviewer.

Report the saved plan file path.`,
  { label: "B5:writing-plans" },
);
await state_append("B5", "plan-drafted", b5_plan_path);
```

- [ ] **Step 2: 3-plan-validator panel on the B5 plan**

```javascript
let b5_plan_text = await agent(
  `Read the file at ${b5_plan_path}; report its full content.`,
  { label: "B5:read-plan" },
);
const b5_plan_verdicts = await validators_panel(b5_plan_text, "B5-plan");
let b5_plan_must_fix = b5_plan_verdicts.flatMap((v) => v.must_fix || []);
let b5_plan_has_critical = b5_plan_must_fix.some(
  (m) => m.severity === "critical",
);
let b5_plan_iterations = 0;
while (b5_plan_has_critical && b5_plan_iterations < 3) {
  b5_plan_iterations++;
  b5_plan_text = await agent(
    `Given this plan:\n\n${b5_plan_text}\n\nAnd these must-fix items: ${JSON.stringify(b5_plan_must_fix)}\n\nProduce a revised plan addressing every critical must-fix. Write back to ${b5_plan_path} via the Write tool, then report the new full content.`,
    { label: `B5:plan-fixer-iter-${b5_plan_iterations}` },
  );
  const new_verdicts = await validators_panel(
    b5_plan_text,
    `B5-plan-iter-${b5_plan_iterations}`,
  );
  b5_plan_must_fix = new_verdicts.flatMap((v) => v.must_fix || []);
  b5_plan_has_critical = b5_plan_must_fix.some(
    (m) => m.severity === "critical",
  );
}
if (b5_plan_has_critical) {
  return await gate_halt("B5", "plan-validator-dissent-exhausted", {
    must_fix: b5_plan_must_fix,
  });
}
await state_append("B5", "plan-validated", `${b5_plan_iterations} iterations`);
```

### Task 11: B5 — SDD execution (implementer + spec-reviewer + code-quality-reviewer)

**Files (per cherry-picked CCE-80 spec at `docs/superpowers/specs/2026-06-02-cce80-diagram-gate-docstring-fix.md` + PR #101's existing diff):**

- Modifies: `scripts/scaffold_workflow.py` — Usage docstring (literal-block fencing fix that resolves the `--out PATH` mkdocs-autorefs cross-reference)
- Modifies: `templates/workflow-run.yml` — parity refresh per CCE-80 ticket scope
- Modifies (test file): `tests/test_scaffold_workflow.py` (or sibling) — failing test → green per per-task TDD
- Exact file set is finalized by the B5 plan (Task 10) before SDD dispatch; the implementer subagent re-verifies via `git diff origin/chore/CCE-80-template-workflow-run-refresh` at the start of each implementer turn.

- [ ] **Step 1: Switch to the CCE-80 working branch**

```javascript
await agent(
  `Run: cd /Users/theo/Projects/engineering-docs-agent && git checkout chore/CCE-80-template-workflow-run-refresh
Report current branch.`,
  { label: "B5:checkout-cce80-branch" },
);
```

- [ ] **Step 2: Dispatch SDD against the validated B5 plan**

```javascript
const b5_sdd_result = await agent(
  `Invoke superpowers:subagent-driven-development against the plan at ${b5_plan_path}.

This means: per-task implementer + spec-reviewer + code-quality-reviewer dispatched fresh for each plan task; controller tracks TodoWrite; review loops until each task's reviewers concur.

Constraints: same as before (commit trailer, never -f/--force/--no-verify/--amend, pytest as runner).

Report final status (DONE/BLOCKED), list of commits made, test counts.`,
  { label: "B5:sdd-execute" },
);
await state_append("B5", "sdd-completed", b5_sdd_result);
```

- [ ] **Step 3: Invoke `cce82_blocklist_guard` on the produced diff (Task 3 Step 4 canonical pattern)**

Per Task 3 Step 4: every mutating executor invokes the guard BEFORE the next
mutating dispatch (here, the ship-gate in Task 14). Capture the intended diff
from the SDD-touched working tree, then run the guard inline:

```javascript
const b5_intended_diff = await agent(
  `Run: cd /Users/theo/Projects/engineering-docs-agent && git diff origin/chore/CCE-80-template-workflow-run-refresh
Report only the unified diff.`,
  { label: "B5:get-diff" },
);
const b5_blocklist_halt = await cce82_blocklist_guard(b5_intended_diff, "B5");
if (b5_blocklist_halt) return b5_blocklist_halt;
```

This is the literal pattern every other mutating executor (B6/B8/B9/B11/B12/B13/B14/B15)
replicates inline against its own intended-diff / intended-paths variable.

### Task 12: B5 — Test-validation (AC-coverage + behavior-not-implementation)

**Files:**

- Reads: the cherry-picked CCE-80 spec's acceptance criteria + the test files SDD added.

- [ ] **Step 1: AC-coverage check**

```javascript
const ac_coverage = await agent(
  `Read the spec at docs/superpowers/specs/2026-06-02-cce80-diagram-gate-docstring-fix.md.
Read the test files committed by B5 SDD: enumerate via git show --stat HEAD~5..HEAD (or however many commits B5 added) — only test files.

For each acceptance criterion in the spec, identify the test method that covers it. List ANY AC with no covering test as a 'gap'.`,
  { schema: TEST_VALIDATION_SCHEMA, label: "B5:ac-coverage" },
);
const ac_gaps = ac_coverage.ac_coverage.filter((c) => c.gap);
if (ac_gaps.length > 0) {
  // Dispatch fixer to add missing tests; re-run
  // (must-fix loop similar to Task 9)
}
```

- [ ] **Step 2: Behavior-not-implementation check**

```javascript
const behavior_check = await agent(
  `Read the new/modified test files in B5's SDD commits. For each test assertion, classify as 'behavior' (observable input→output mapping, side-effect on shared state) vs 'implementation' (internal call counts, private method invocation, non-boundary mocks). Report counts.`,
  { schema: TEST_VALIDATION_SCHEMA, label: "B5:behavior-vs-impl" },
);
if (behavior_check.behavior_vs_impl.warning) {
  log(
    `WARNING: B5 tests have ${behavior_check.behavior_vs_impl.impl_coupled_assertions}/${behavior_check.behavior_vs_impl.total_assertions} implementation-coupled assertions. Non-blocking; logged.`,
  );
}
await state_append(
  "B5",
  "test-validation-passed",
  JSON.stringify({
    ac_gaps: 0,
    warning: behavior_check.behavior_vs_impl.warning,
  }),
);
```

### Task 13: B5 — 3-execution-validator panel

**Files:**

- Reads: B5 commit history + diff.

- [ ] **Step 1: Get commit SHAs added by B5 SDD**

```javascript
const b5_shas = await agent(
  `Run: cd /Users/theo/Projects/engineering-docs-agent && git log --oneline origin/chore/CCE-80-template-workflow-run-refresh..HEAD
Report the SHAs and subjects.`,
  { label: "B5:get-shas" },
);
```

- [ ] **Step 2: Dispatch execution validators**

```javascript
const b5_diff = await agent(
  `Run: cd /Users/theo/Projects/engineering-docs-agent && git diff origin/chore/CCE-80-template-workflow-run-refresh..HEAD; report the diff.`,
  { label: "B5:get-diff" },
);
const exec_verdicts = await validators_panel(b5_diff, "B5-execution");
const exec_must_fix = exec_verdicts.flatMap((v) => v.must_fix || []);
if (exec_must_fix.some((m) => m.severity === "critical")) {
  return await gate_halt("B5", "execution-validator-dissent", {
    must_fix: exec_must_fix,
  });
}
await state_append(
  "B5",
  "execution-validated",
  `${exec_verdicts.length} verdicts; 0 critical`,
);
```

### Task 14: B5 — Ship-gate halt; controller runs /ship

**Files:**

- Writes: `~/.claude/orchestrator/gates/<run_id>/B5.md` (forensic).
- Awaits write by controller: `~/.claude/orchestrator/ship-result-B5.json`.

- [ ] **Step 1: Emit the ship-gate halt (record resume timestamp first)**

Per validator iter-2 correctness fix: capture the pre-halt UTC timestamp into
state BEFORE emitting the halt. The post-ship resume stage reads it back from
state to bound the journal-poll window — `args.b5_resume_ts` is not a runtime
arg the controller would set when re-launching, so the source of truth is the
state file.

```javascript
const b5_resume_ts = await agent(
  `Run: date -u +"%Y-%m-%dT%H:%M:%SZ"
Report only the timestamp.`,
  { label: "B5:resume-ts" },
);
await state_append("B5", "ship-gate-emitted", b5_resume_ts);
return await gate_halt("B5", "ship-gate", {
  summary:
    "CCE-80 implementation complete + all validators concur. Ready to /ship.",
  branch: "chore/CCE-80-template-workflow-run-refresh",
  shas: b5_shas,
  diff_summary: "<truncated; see git diff origin/...>",
  next_action: "controller invokes /ship; on shipped, orchestrator resumes",
});
```

The controller (main agent) responds to the halt by:

1. Reading `~/.claude/orchestrator/gates/<run_id>/B5.md`.
2. Surfacing diff + AC checklist to user.
3. On user approval, invoking the `/ship` skill via the Skill tool.
4. After `/ship` returns, writing `~/.claude/orchestrator/ship-result-B5.json` with `{status, pr_url, halt_reason?, journal_ts}`.
5. Re-launching the Workflow with `resumeFromRunId` + `args.shipResults[B5] = <result>`.

- [ ] **Step 2: Post-ship resume stage (called only on resume)**

```javascript
// This stage runs only after the ship-result file is written.
// Its prompt embeds args.shipResults via get_ship_result(); upstream stages cache-hit.
// `let` (not const): the journal-poll success path reassigns ship_result with a
// synthesized record so the switch below routes correctly.
let ship_result = await get_ship_result("B5");
if (!ship_result) {
  // Journal-poll fallback per spec C6 fix.
  // Read the resume_ts recorded in Step 1 from the state file (NOT from args).
  const b5_resume_ts_record = await agent(
    `Run: grep '"taskId":"B5"' ${STATE_PATH} | grep '"transition":"ship-gate-emitted"' | tail -1
Report only the matched JSON line.`,
    { label: "B5:read-resume-ts" },
  );
  const b5_resume_ts = JSON.parse(b5_resume_ts_record).detail;
  const journal_match = await agent(
    `Poll ~/.claude/ship/journal.jsonl for entries matching (branch='chore/CCE-80-template-workflow-run-refresh') AND (ts >= ${b5_resume_ts}) AND (outcome IN [shipped, halted, merged]).
Poll cadence 5s, timeout 30 min. Return the matched entry or 'timeout'.`,
    { label: "B5:journal-poll" },
  );
  if (journal_match === "timeout") {
    return await gate_halt("B5", "ship-result-missing", {
      last_journal_tail: "<paste>",
    });
  }
  // Iter-3 fix: synthesize ship_result from the matched journal entry so the
  // switch below routes correctly. Without this, ship_result stayed null/undefined
  // and the success path silently no-op'd (validator iter-3 correctness C1).
  const entry = JSON.parse(journal_match);
  ship_result = {
    status: ["shipped", "merged"].includes(entry.outcome)
      ? "shipped"
      : "halted",
    pr_url: entry.pr_url || "",
    halt_reason: entry.reason || "",
    journal_ts: entry.ts,
  };
}
switch (ship_result?.status) {
  case "shipped":
    await state_append("B5", "shipped", ship_result.pr_url);
    // Branch-restore: /ship leaves us on the CCE-80 working branch; subsequent
    // operational tasks (B6 merge, B8/B9 hygiene, B10's commit, B14 release)
    // must run on the orchestrator branch.
    await agent(
      `Run: git checkout chore/meta-orchestrator-spec-2026-06-03; report branch`,
      { label: "B5:branch-restore" },
    );
    await state_append(
      "B5",
      "branch-restored",
      "chore/meta-orchestrator-spec-2026-06-03",
    );
    break;
  case "halted":
    return await gate_halt("B5", "ship-halted", {
      halt_reason: ship_result.halt_reason,
    });
  case "failed":
    return { halt: "batch-aborted", reason: "B5 ship failed" };
}
```

### Task 15: B6 — Merge PR #101

**Files:**

- Reads: PR #101 checks via gh CLI.
- Mutates: theoju/engineering-docs-agent (merge action).

- [ ] **Step 1: Poll PR #101 checks**

```javascript
const checks_status = await agent(
  `Run: gh pr checks 101 --json name,state,bucket
Report only the JSON. Verify required checks (pytest (3.11), pytest (3.12), actionlint) are all SUCCESS.`,
  { label: "B6:checks-poll" },
);
```

- [ ] **Step 2: If diagram-gate still failing — gate for waiver**

Parse the `checks_status` JSON from Step 1 to detect a failing `diagram-gate`
check. `gh pr checks --json statusCheckRollup` returns a top-level array of
`{ name, state, conclusion, bucket }` entries; failures surface either as
`state === "FAILURE"` or `conclusion === "FAILURE"`.

```javascript
const checks_parsed = JSON.parse(checks_status);
const rollup = Array.isArray(checks_parsed)
  ? checks_parsed
  : (checks_parsed.statusCheckRollup ?? []);
const diagram_gate_failing = rollup.some(
  (c) =>
    c.name === "diagram-gate" &&
    (c.state === "FAILURE" || c.conclusion === "FAILURE"),
);
if (diagram_gate_failing) {
  return await gate_halt("B6", "diagram-gate-waiver", {
    summary: "diagram-gate is non-required but still failing. Merge anyway?",
    suggested:
      "yes (per branch protection, only pytest+actionlint are required)",
  });
}
```

- [ ] **Step 3: Surface merge diff + status to user**

```javascript
return await gate_halt("B6", "merge-101", {
  summary:
    "PR #101 ready to merge. Required checks all green; reviewDecision=empty (no reviewers required).",
  command: "gh pr merge 101 --squash --delete-branch",
});
```

- [ ] **Step 4: Post-merge resume — verify Jira CCE-80 → Done**

```javascript
// On resume after user-approved merge.
// agent() returns a free-text string; coerce to structured form before access,
// mirroring the checks_status JSON.parse pattern from Task 15 Step 2.
const cce80_status_raw = await agent(
  `Use Atlassian MCP to fetch CCE-80 status; transition to Done if not already.
Report the resulting status as JSON: {"key":"CCE-80","status":"Done"}.`,
  { label: "B6:cce80-done" },
);
const cce80_status = JSON.parse(cce80_status_raw);
await state_append(
  "B6",
  "completed",
  `PR #101 merged; CCE-80 = ${cce80_status.status}`,
);
```

---

## Phase D: Phase 2 — Pre-tag merge hygiene

### Task 16: B8 — Merge ready bot PRs #102 and #100

**Files:**

- Mutates: theoju/engineering-docs-agent.

- [ ] **Step 1: Re-verify both PRs still CLEAN/MERGEABLE**

```javascript
phase("Phase 2: Pre-tag merge hygiene");
const status_102 = await agent(
  `Run: gh pr view 102 --json mergeStateStatus,mergeable,statusCheckRollup
Report only mergeStateStatus, mergeable, and check states.`,
  { label: "B8:status-102" },
);
const status_100 = await agent(
  `Run: gh pr view 100 --json mergeStateStatus,mergeable,statusCheckRollup
Report only mergeStateStatus, mergeable, and check states.`,
  { label: "B8:status-100" },
);
```

- [ ] **Step 2: If still CLEAN/MERGEABLE — gate for batch merge approval**

```javascript
return await gate_halt("B8", "merge-batch-102-100", {
  summary: "Pre-tag merge hygiene: merge ready bot PRs #102 and #100",
  commands: [
    "gh pr merge 102 --squash --delete-branch",
    "gh pr merge 100 --squash --delete-branch",
  ],
});
```

- [ ] **Step 3: Post-merge state-record**

```javascript
await state_append("B8", "completed", "PRs #102, #100 merged");
```

### Task 17: B9 — Merge PR #96 (CCE-66 docs-only)

**Files:**

- Mutates: theoju/engineering-docs-agent.

- [ ] **Step 1: Verify PR #96 status**

```javascript
const status_96 = await agent(
  `Run: gh pr view 96 --json mergeStateStatus,mergeable,statusCheckRollup
Report only mergeStateStatus, mergeable, and check states. Note: UNKNOWN merge state may need rebase.`,
  { label: "B9:status-96" },
);
```

- [ ] **Step 2: If status UNKNOWN — first try update-branch**

```javascript
// status_96 (from Step 1) is a free-text agent response; coerce via JSON.parse
// before accessing structured fields, mirroring Task 15 Step 2's pattern.
const parsed_96 = JSON.parse(status_96);
if (parsed_96.mergeStateStatus === "UNKNOWN") {
  await agent(
    `Run: gh pr update-branch 96
Report result.`,
    { label: "B9:update-branch-96" },
  );
}
```

- [ ] **Step 3: Gate for merge**

```javascript
return await gate_halt("B9", "merge-96", {
  summary:
    "PR #96 (CCE-66 docs-only spec+plan+closeout) — merge for pre-tag hygiene",
  command: "gh pr merge 96 --squash --delete-branch",
});
```

- [ ] **Step 4: Post-merge — verify CCE-66 Done**

```javascript
// On resume.
// agent() returns a free-text string; coerce via JSON.parse before access,
// mirroring Task 15 Step 2's pattern.
const cce66_status_raw = await agent(
  `Use Atlassian MCP to verify CCE-66 = Done; transition if not.
Report the resulting status as JSON: {"key":"CCE-66","status":"Done"}.`,
  { label: "B9:cce66-done" },
);
const cce66_status = JSON.parse(cce66_status_raw);
await state_append(
  "B9",
  "completed",
  `PR #96 merged; CCE-66 = ${cce66_status.status}`,
);
```

---

## Phase E: Phase 3 — CCE-77 work

### Task 18: B10 — Fetch CCE-77 Jira description

**Files:**

- Reads: CCE-77 Jira issue.

- [ ] **Step 1: Fetch CCE-77 full content**

```javascript
phase("Phase 3: CCE-77 work");
const cce77_jira = await agent(
  `Use mcp__plugin_atlassian_atlassian__getJiraIssue with cloudId="designitright.atlassian.net" and issueIdOrKey="CCE-77" and responseContentFormat="markdown".
Report only the description field's text.`,
  { label: "B10:fetch-cce77-jira" },
);
await state_append("B10", "jira-fetched", `${cce77_jira.length} chars`);
```

### Task 19: B10 — SDD spec authoring (implementer + spec-reviewer + code-quality-reviewer)

Per validator C4 / spec AC#7: B10 must use the SDD pattern, not a single-agent
dispatch. Three sub-dispatches drive the artifact: implementer drafts the spec
from the Jira description; spec-reviewer checks Jira-fidelity; code-quality-reviewer
checks markdown/voice/structure conformance. Review loops up to 3 iterations.

**Files:**

- Creates: `docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md`

- [ ] **Step 1: Implementer drafts the spec via Write tool**

```javascript
let cce77_spec_text = await agent(
  `You are the implementer for B10.

Author a spec file at docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md normalizing this Jira description:

${cce77_jira}

Use the same structure as existing CCE specs (Context / Goal / Non-goals / Architecture / Components / Data flow / Error handling / Acceptance criteria / Testing approach / Out of scope / Implementation outline / Risk / Rollback).

Apply project voice and style per /Users/theo/Projects/engineering-docs-agent/CLAUDE.md.

Note critical context: target file is ~/.claude/skills/ship/lib/validate-git-cmd.sh line 40 (NOT ~/.claude/hooks/ship-guardrails.sh, which is a 14-line shim execing the real validator). Target lives outside any git repo — no PR workflow. Test harness at ~/.claude/skills/ship/tests/validate-git-cmd.test.sh has 10 existing cases; B12 will extend with 7 CCE-77 acceptance cases.

End with the required co-author trailer.

Write the spec via the Write tool, then report the full content of the written file.`,
  { label: "B10:implementer" },
);
await state_append(
  "B10",
  "spec-drafted",
  "docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md",
);
```

- [ ] **Step 2: spec-reviewer verifies Jira fidelity**

```javascript
let spec_verdict = await agent(
  `You are the spec-reviewer for B10.

Read the drafted spec content:

${cce77_spec_text}

Compare against the source Jira description:

${cce77_jira}

Verify Jira fidelity: every requirement, acceptance criterion, and context note in the Jira description is preserved in the spec. Flag any over-build (scope additions not in Jira), under-build (Jira requirements missing), or drift (changed intent). Return a VERDICT.`,
  { schema: VERDICT_SCHEMA, label: "B10:spec-reviewer" },
);
```

- [ ] **Step 3: code-quality-reviewer verifies markdown structure + voice**

```javascript
let quality_verdict = await agent(
  `You are the code-quality-reviewer for B10.

Read the drafted spec content:

${cce77_spec_text}

Verify: (1) all canonical spec sections present (Context / Goal / Non-goals / Architecture / Components / Data flow / Error handling / Acceptance criteria / Testing approach / Out of scope / Implementation outline / Risk / Rollback), (2) voice matches /Users/theo/Projects/engineering-docs-agent/CLAUDE.md (direct, concrete, second person for reader-addressing prose, third person for system behavior, short paragraphs), (3) required co-author trailer present, (4) no emojis. Return a VERDICT.`,
  { schema: VERDICT_SCHEMA, label: "B10:quality-reviewer" },
);
```

- [ ] **Step 4: Review loop until both reviewers concur (capped at 3 iterations)**

```javascript
let sdd_iterations = 0;
while (
  (!spec_verdict.approved || !quality_verdict.approved) &&
  sdd_iterations < 3
) {
  sdd_iterations++;
  const combined_must_fix = [
    ...(spec_verdict.must_fix || []),
    ...(quality_verdict.must_fix || []),
  ];
  cce77_spec_text = await agent(
    `You are the implementer revising the B10 spec.

Current spec content:\n\n${cce77_spec_text}\n\nReviewer must-fix items: ${JSON.stringify(combined_must_fix)}\n\nProduce a revised spec addressing every must-fix. Write back to docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md via the Write tool, then report the new full content.`,
    { label: `B10:implementer-iter-${sdd_iterations}` },
  );
  spec_verdict = await agent(
    `Re-review the revised spec against the Jira description (same criteria as before). Return a VERDICT.\n\nSpec:\n${cce77_spec_text}\n\nJira:\n${cce77_jira}`,
    {
      schema: VERDICT_SCHEMA,
      label: `B10:spec-reviewer-iter-${sdd_iterations}`,
    },
  );
  quality_verdict = await agent(
    `Re-review the revised spec for markdown structure + voice conformance (same criteria as before). Return a VERDICT.\n\nSpec:\n${cce77_spec_text}`,
    {
      schema: VERDICT_SCHEMA,
      label: `B10:quality-reviewer-iter-${sdd_iterations}`,
    },
  );
}
if (!spec_verdict.approved || !quality_verdict.approved) {
  return await gate_halt("B10", "sdd-reviewer-dissent", {
    summary: `SDD reviewers did not concur after ${sdd_iterations} iterations.`,
    spec_must_fix: spec_verdict.must_fix,
    quality_must_fix: quality_verdict.must_fix,
    question:
      "Approve current spec as-is, request manual revision, or abort B10?",
  });
}
await state_append(
  "B10",
  "sdd-reviewers-concur",
  `${sdd_iterations} iterations`,
);
```

- [ ] **Step 5: Commit the spec (after SDD review passes)**

```javascript
await agent(
  `Run on orchestrator branch:
git add docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md
git commit -m "$(cat <<'EOF'
docs(CCE-77): spec for /ship guardrails -f token over-match fix

Normalized from CCE-77 Jira description; SDD-validated by spec-reviewer + code-quality-reviewer.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
Report commit SHA.`,
  { label: "B10:commit-spec" },
);
await state_append(
  "B10",
  "spec-committed",
  "CCE-77 spec on orchestrator branch",
);
```

### Task 20: B10 — 3-spec-validator panel + must-fix loop

The SDD review at Task 19 concerned itself with Jira fidelity + structure. This
task runs the orthogonal 3-lens panel (completeness / correctness / scope) on
the committed spec.

**Files:**

- Reads: committed spec.

- [ ] **Step 1: Run validators_panel on the committed spec, with full must-fix loop**

```javascript
let cce77_spec_content = await agent(
  `Read docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md and report its full content.`,
  { label: "B10:read-spec" },
);
const cce77_verdicts = await validators_panel(
  cce77_spec_content,
  "B10-cce77-spec",
);
let cce77_must_fix = cce77_verdicts.flatMap((v) => v.must_fix || []);
let cce77_has_critical = cce77_must_fix.some((m) => m.severity === "critical");
let cce77_iterations = 0;
while (cce77_has_critical && cce77_iterations < 3) {
  cce77_iterations++;
  cce77_spec_content = await agent(
    `Given the current CCE-77 spec content:\n\n${cce77_spec_content}\n\nAnd these must-fix items: ${JSON.stringify(cce77_must_fix)}\n\nProduce a revised spec addressing every critical must-fix. Write back to docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md via the Write tool, then report the new full content.`,
    { label: `B10:spec-fixer-iter-${cce77_iterations}` },
  );
  const new_verdicts = await validators_panel(
    cce77_spec_content,
    `B10-cce77-spec-iter-${cce77_iterations}`,
  );
  cce77_must_fix = new_verdicts.flatMap((v) => v.must_fix || []);
  cce77_has_critical = cce77_must_fix.some((m) => m.severity === "critical");
}
if (cce77_has_critical) {
  return await gate_halt("B10", "spec-validator-dissent-exhausted", {
    must_fix: cce77_must_fix,
  });
}
await state_append("B10", "spec-validated", `${cce77_iterations} iterations`);
```

- [ ] **Step 2: Amend commit if the validator loop revised the spec**

```javascript
if (cce77_iterations > 0) {
  await agent(
    `Run on orchestrator branch:
git add docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md
git commit -m "$(cat <<'EOF'
docs(CCE-77): spec revisions from 3-lens validator must-fix loop

${cce77_iterations} iteration(s) of completeness/correctness/scope review.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
Report commit SHA.`,
    { label: "B10:commit-spec-revisions" },
  );
}
```

### Task 21: B11 — Pre-flight: empirical reproduction

**Files:**

- Reads: `~/.claude/skills/ship/lib/validate-git-cmd.sh` (line 40 area).
- Writes: `/tmp/cce77-repro.log`.

- [ ] **Step 1: Reproduce the over-match**

```javascript
const repro = await agent(
  `Verify CCE-77 reproduction:

For each command:
  rm -f /tmp/foo
  mv -f /tmp/a /tmp/b
  grep -f /tmp/patterns.txt /tmp/file.txt
  tar -f /tmp/archive.tar
  git push -f
  git commit --amend
  git commit --no-verify

Run each as: echo '{"tool_name":"Bash","tool_input":{"command":"<cmd>"}}' | bash ~/.claude/skills/ship/lib/validate-git-cmd.sh; echo "exit=$?"

For the first 4, expected exit=2 with 'blocked -f' stderr (this is the over-match bug).
For the last 3, expected exit=2 (legitimate block — should keep working).

Report all 7 exit codes + any stderr.`,
  { label: "B11:reproduce" },
);
await state_append("B11", "reproduced", repro);
```

- [ ] **Step 2: Read validate-git-cmd.sh:40 area**

```javascript
const validator_source = await agent(
  `Read /Users/theo/.claude/skills/ship/lib/validate-git-cmd.sh lines 30-60. Report verbatim.`,
  { label: "B11:read-validator" },
);
```

### Task 21b: B11 — Systematic-debugging probe

Per validator C2 / spec AC#5: B11 must run the full 4-phase systematic-debugging
process before any edit, mirroring Task 8 for B4. The probe consumes the repro
log + validator source from Task 21 and emits a structured patch-spec using the
shared `PATCH_SPEC_SCHEMA`.

**Files:**

- Produces: B11 patch-spec text (in-memory; not yet written to disk).

- [ ] **Step 1: Dispatch a systematic-debugging probe**

```javascript
// `let` (not const): Task 21c's must-fix loop reassigns b11_debug_output on each iteration.
let b11_debug_output = await agent(
  `You are running superpowers:systematic-debugging on the -f over-match in ~/.claude/skills/ship/lib/validate-git-cmd.sh:40.

Reproduction evidence:\n${repro}\n\nValidator source (lines 30-60):\n${validator_source}\n\nApply the 4-phase process:
1. Root Cause Investigation: identify the exact match pattern that triggers the over-match. The current line 40 reads roughly: if [[ " $CMD " == *" -f "* ]]; then ... Why does it fire on rm -f / mv -f / grep -f / tar -f?
2. Pattern Analysis: find working examples — how do other validators in ~/.claude/skills/ship/lib/ scope token matches to specific commands?
3. Hypothesis: form ONE single hypothesis stating root cause.
4. Implementation: produce a patch-spec describing the minimal fix (narrow the match to git push / git commit contexts only) and the failing test that proves it.

Return a structured patch-spec with: { root_cause, fix_description, files_to_modify, test_to_add, acceptance_criteria[] }.`,
  { schema: PATCH_SPEC_SCHEMA, label: "B11:debug-probe" },
);
await state_append(
  "B11",
  "patch-spec-drafted",
  JSON.stringify(b11_debug_output).slice(0, 200),
);
```

### Task 21c: B11 — 3-spec-validator panel on B11 patch-spec

Per validator C2: the B11 patch-spec must pass the same 3-lens panel as B4's
patch-spec, with the same must-fix loop capped at 3 iterations.

**Files:**

- Reads: in-memory B11 patch-spec from Task 21b.

- [ ] **Step 1: Dispatch validators_panel on the B11 patch-spec**

```javascript
const b11_patch_spec_text = JSON.stringify(b11_debug_output, null, 2);
const b11_patch_verdicts = await validators_panel(
  b11_patch_spec_text,
  "B11-patch-spec",
);
let b11_patch_must_fix = b11_patch_verdicts.flatMap((v) => v.must_fix || []);
let b11_patch_has_critical = b11_patch_must_fix.some(
  (m) => m.severity === "critical",
);
```

- [ ] **Step 2: Must-fix loop (capped at 3 iterations)**

```javascript
let b11_patch_iterations = 0;
while (b11_patch_has_critical && b11_patch_iterations < 3) {
  b11_patch_iterations++;
  b11_debug_output = await agent(
    `Given this patch-spec: ${JSON.stringify(b11_debug_output)}\n\nAnd these must-fix items: ${JSON.stringify(b11_patch_must_fix)}\n\nProduce a revised patch-spec addressing every critical must-fix.`,
    {
      schema: PATCH_SPEC_SCHEMA,
      label: `B11:patch-fixer-iter-${b11_patch_iterations}`,
    },
  );
  const new_verdicts = await validators_panel(
    JSON.stringify(b11_debug_output, null, 2),
    `B11-patch-spec-iter-${b11_patch_iterations}`,
  );
  b11_patch_must_fix = new_verdicts.flatMap((v) => v.must_fix || []);
  b11_patch_has_critical = b11_patch_must_fix.some(
    (m) => m.severity === "critical",
  );
}
if (b11_patch_has_critical) {
  return await gate_halt("B11", "patch-validator-dissent-exhausted", {
    must_fix: b11_patch_must_fix,
  });
}
await state_append(
  "B11",
  "patch-spec-validated",
  `${b11_patch_iterations} iterations`,
);
```

### Task 21d: B11 — writing-plans dispatch on validated patch-spec

Per validator C3 / spec AC#6: B11 must run writing-plans against the now-validated
CCE-77 spec augmented with the B11 patch-spec, mirroring Task 10 Step 1 for B5.

**Files:**

- Reads: CCE-77 spec at `docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md`.
- Reads: B11 patch-spec (in-memory).
- Produces: nested B11 implementation plan via writing-plans's normal path.

- [ ] **Step 1: Dispatch writing-plans for B11**

```javascript
const b11_plan_path = await agent(
  `Invoke superpowers:writing-plans against the spec at docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md.

Augment with the B11 patch-spec: ${JSON.stringify(b11_debug_output)}

Constraints: detached-target (no git repo), test runner is bash ~/.claude/skills/ship/tests/validate-git-cmd.test.sh, no commits (target outside any repo), forensic patch saved to ${DETACHED_CHANGES_DIR}/B11.patch after edit.

The plan executes via subagent-driven-development with per-task implementer + spec-reviewer + code-quality-reviewer.

Report the saved plan file path.`,
  { label: "B11:writing-plans" },
);
await state_append("B11", "plan-drafted", b11_plan_path);
```

### Task 21e: B11 — 3-plan-validator panel

Mirrors Task 10 Step 2: validates the writing-plans output before SDD execution.

**Files:**

- Reads: drafted B11 plan file.

- [ ] **Step 1: Read plan and run validators_panel with must-fix loop**

```javascript
let b11_plan_text = await agent(
  `Read the file at ${b11_plan_path}; report its full content.`,
  { label: "B11:read-plan" },
);
const b11_plan_verdicts = await validators_panel(b11_plan_text, "B11-plan");
let b11_plan_must_fix = b11_plan_verdicts.flatMap((v) => v.must_fix || []);
let b11_plan_has_critical = b11_plan_must_fix.some(
  (m) => m.severity === "critical",
);
let b11_plan_iterations = 0;
while (b11_plan_has_critical && b11_plan_iterations < 3) {
  b11_plan_iterations++;
  b11_plan_text = await agent(
    `Given this plan:\n\n${b11_plan_text}\n\nAnd these must-fix items: ${JSON.stringify(b11_plan_must_fix)}\n\nProduce a revised plan addressing every critical must-fix. Write back to ${b11_plan_path} via the Write tool, then report the new full content.`,
    { label: `B11:plan-fixer-iter-${b11_plan_iterations}` },
  );
  const new_verdicts = await validators_panel(
    b11_plan_text,
    `B11-plan-iter-${b11_plan_iterations}`,
  );
  b11_plan_must_fix = new_verdicts.flatMap((v) => v.must_fix || []);
  b11_plan_has_critical = b11_plan_must_fix.some(
    (m) => m.severity === "critical",
  );
}
if (b11_plan_has_critical) {
  return await gate_halt("B11", "plan-validator-dissent-exhausted", {
    must_fix: b11_plan_must_fix,
  });
}
await state_append(
  "B11",
  "plan-validated",
  `${b11_plan_iterations} iterations`,
);
```

### Task 22: B11 — SDD execution (detached-target)

**Files:**

- Modifies: `~/.claude/skills/ship/lib/validate-git-cmd.sh` (line 40, the `-f` token check).

- [ ] **Step 1: Dispatch the implementer agent against the validated B11 plan**

The SDD dispatch now operates against the writing-plans output validated in
Task 21e (path stored in `b11_plan_path`) and the patch-spec validated in
Task 21c (in-memory `b11_debug_output`).

```javascript
const b11_impl = await agent(
  `You are the implementer for CCE-77's fix, executing the validated B11 plan.

Plan: ${b11_plan_path}
Spec: docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md
Patch-spec (validated): ${JSON.stringify(b11_debug_output)}

Edit ~/.claude/skills/ship/lib/validate-git-cmd.sh line 40 to fix the -f token over-match per the patch-spec's fix_description and files_to_modify.

The current line 40 reads (approximately): if [[ " $CMD " == *" -f "* ]]; then ...

The fix: narrow the match to only block -f when it follows 'git push' or 'git commit' (the actual dangerous contexts). Allow rm -f, mv -f, grep -f, tar -f to pass.

After editing, run the existing test harness:
bash ~/.claude/skills/ship/tests/validate-git-cmd.test.sh

Report: edit you made (1-5 lines), test results.

Do NOT commit (target is not in a git repo).`,
  { label: "B11:implementer" },
);
await state_append("B11", "implemented", b11_impl);
```

- [ ] **Step 2: Spec-reviewer**

```javascript
const b11_spec_review = await agent(
  `You are the spec reviewer for B11.

Read the spec at docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md.
Read the current state of ~/.claude/skills/ship/lib/validate-git-cmd.sh.

Verify the edit matches the spec exactly. Report any over-build (added scope), under-build (missing requirements), or drift.`,
  { schema: VERDICT_SCHEMA, label: "B11:spec-reviewer" },
);
```

- [ ] **Step 3: Code-quality-reviewer**

```javascript
const b11_quality = await agent(
  `You are the code-quality reviewer for B11.

Read ~/.claude/skills/ship/lib/validate-git-cmd.sh (the post-edit version).

Verify: bash idioms correct, no new shellcheck warnings, edit is minimal, regex is precise (no further over-match risks).`,
  { schema: VERDICT_SCHEMA, label: "B11:quality-reviewer" },
);
```

- [ ] **Step 4: Must-fix loop if any reviewer dissents**

```javascript
let b11_sdd_iterations = 0;
let b11_sdd_must_fix = [
  ...(b11_spec_review.must_fix || []),
  ...(b11_quality.must_fix || []),
];
let b11_sdd_has_critical = b11_sdd_must_fix.some(
  (m) => m.severity === "critical",
);
while (b11_sdd_has_critical && b11_sdd_iterations < 3) {
  b11_sdd_iterations++;
  await agent(
    `You are the implementer revising the B11 fix.\n\nMust-fix items: ${JSON.stringify(b11_sdd_must_fix)}\n\nRevise ~/.claude/skills/ship/lib/validate-git-cmd.sh per the must-fix items, then re-run bash ~/.claude/skills/ship/tests/validate-git-cmd.test.sh. Report the edit and test results. Do NOT commit.`,
    { label: `B11:implementer-iter-${b11_sdd_iterations}` },
  );
  const new_spec_review = await agent(
    `Re-review the post-edit validate-git-cmd.sh against the CCE-77 spec. Return a VERDICT.`,
    {
      schema: VERDICT_SCHEMA,
      label: `B11:spec-reviewer-iter-${b11_sdd_iterations}`,
    },
  );
  const new_quality = await agent(
    `Re-review the post-edit validate-git-cmd.sh for code quality. Return a VERDICT.`,
    {
      schema: VERDICT_SCHEMA,
      label: `B11:quality-reviewer-iter-${b11_sdd_iterations}`,
    },
  );
  b11_sdd_must_fix = [
    ...(new_spec_review.must_fix || []),
    ...(new_quality.must_fix || []),
  ];
  b11_sdd_has_critical = b11_sdd_must_fix.some(
    (m) => m.severity === "critical",
  );
}
if (b11_sdd_has_critical) {
  return await gate_halt("B11", "sdd-reviewer-dissent-exhausted", {
    must_fix: b11_sdd_must_fix,
  });
}
await state_append(
  "B11",
  "sdd-reviewers-concur",
  `${b11_sdd_iterations} iterations`,
);
```

### Task 23: B11 — Test-validation + 3-execution-validator

**Files:**

- Reads: the validator source (post-edit).
- Reads: test harness results.

- [ ] **Step 1: AC-coverage check against CCE-77 spec (existing 10-case harness)**

Per validator minor M4: B11's AC-coverage check validates against the EXISTING
10-case harness (the harness state prior to B12's extension). Full 17-case
validation happens at B12 (Task 25 Step 4).

```javascript
const b11_ac_coverage = await agent(
  `You are running an AC-coverage check for B11.

Read the spec at docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md and enumerate its 7 acceptance criteria.

Read the existing test harness at ~/.claude/skills/ship/tests/validate-git-cmd.test.sh (10 cases as of B11; B12 will add 7 more).

For each spec AC, identify which existing test case in the harness covers it. List ANY AC with no covering test as a 'gap'.

Return TEST_VALIDATION_SCHEMA shape.`,
  { schema: TEST_VALIDATION_SCHEMA, label: "B11:ac-coverage" },
);
const b11_ac_gaps = b11_ac_coverage.ac_coverage.filter((c) => c.gap);
if (b11_ac_gaps.length > 0) {
  return await gate_halt("B11", "ac-coverage-gap", {
    summary: `B11 AC-coverage check found ${b11_ac_gaps.length} gap(s) against the existing 10-case harness.`,
    gaps: b11_ac_gaps,
    question:
      "Authorize B12 to close these gaps via the 7 new acceptance cases, or revise B11 first?",
  });
}
await state_append(
  "B11",
  "ac-coverage-passed",
  `${b11_ac_coverage.ac_coverage.length} ACs covered`,
);
```

- [ ] **Step 2: Behavior-vs-impl check on the existing 10-case harness**

```javascript
const b11_behavior_check = await agent(
  `You are running a behavior-vs-implementation check for B11.

Read the existing test harness at ~/.claude/skills/ship/tests/validate-git-cmd.test.sh.

For each assertion in the 10 existing cases, classify as 'behavior' (observable input→output mapping: command goes in, exit code + stderr come out) vs 'implementation' (internal call counts, private-function probes, non-boundary mocks). Report counts.

Return TEST_VALIDATION_SCHEMA shape.`,
  { schema: TEST_VALIDATION_SCHEMA, label: "B11:behavior-vs-impl" },
);
if (b11_behavior_check.behavior_vs_impl.warning) {
  log(
    `WARNING: B11 existing harness has ${b11_behavior_check.behavior_vs_impl.impl_coupled_assertions}/${b11_behavior_check.behavior_vs_impl.total_assertions} implementation-coupled assertions. Non-blocking; logged.`,
  );
}
await state_append(
  "B11",
  "behavior-vs-impl-checked",
  JSON.stringify({ warning: b11_behavior_check.behavior_vs_impl.warning }),
);
```

- [ ] **Step 3: 3-execution-validator**

```javascript
const b11_post_diff = await agent(
  `Run: cd ~/.claude && git diff skills/ship/lib/validate-git-cmd.sh 2>/dev/null || diff <(cat /tmp/cce77-original.sh) ~/.claude/skills/ship/lib/validate-git-cmd.sh; report the diff.`,
  { label: "B11:post-diff" },
);
const b11_exec_verdicts = await validators_panel(
  b11_post_diff,
  "B11-execution",
);
```

- [ ] **Step 4: Write the forensic patch file to detached-changes/**

Per spec line 467: detached-target tasks save their diff to
`${DETACHED_CHANGES_DIR}/<task_id>.patch` as the forensic rollback record.

```javascript
await agent(
  `Run: git diff --no-index ~/.claude/skills/ship/lib/validate-git-cmd.sh.orig ~/.claude/skills/ship/lib/validate-git-cmd.sh > ${DETACHED_CHANGES_DIR}/B11.patch 2>/dev/null; printf "diff: %d bytes\\nexit: %d\\n" $(stat -f%z ${DETACHED_CHANGES_DIR}/B11.patch 2>/dev/null || stat -c%s ${DETACHED_CHANGES_DIR}/B11.patch) $?`,
  { label: "B11:patch-save" },
);
await state_append("B11", "patch-saved", `${DETACHED_CHANGES_DIR}/B11.patch`);
```

### Task 24: B11 — Critical-gate; on approval, transitionJiraIssue

**Files:**

- Writes: `~/.claude/orchestrator/gates/<run_id>/B11.md`.

- [ ] **Step 1: Gate for user approval**

```javascript
return await gate_halt("B11", "detached-target-approval", {
  summary:
    "CCE-77 fix complete. Reviewers concur. Diff + test harness output below. No PR (target outside git).",
  diff: b11_post_diff,
  test_output: b11_impl,
  next_action: "On approval, orchestrator transitions CCE-77 → Done",
});
```

- [ ] **Step 2: Post-approval — transition CCE-77 to Done**

```javascript
// On resume with args.gateAnswers[B11] = 'approve'
if (get_gate_answer("B11") === "approve") {
  await agent(
    `Use mcp__plugin_atlassian_atlassian__transitionJiraIssue to move CCE-77 to Done. Use mcp__plugin_atlassian_atlassian__addCommentToJiraIssue to add a comment linking the diff and test output.`,
    { label: "B11:transition-cce77" },
  );
  await state_append("B11", "completed", "CCE-77 = Done");
}
```

### Task 25: B12 — Extend test harness with 7 acceptance cases

**Files:**

- Modifies: `~/.claude/skills/ship/tests/validate-git-cmd.test.sh`.
- Creates (if needed): test fixture files at `/tmp/cce77-fixture-<N>.sh` (for cases containing `rm -rf` literals — hostile-hook circumvention).

- [ ] **Step 1: Read existing test file**

```javascript
const existing_tests = await agent(
  `Read /Users/theo/.claude/skills/ship/tests/validate-git-cmd.test.sh. Report verbatim.`,
  { label: "B12:read-tests" },
);
```

- [ ] **Step 2: Author the 7 new cases via Write tool (hostile-hook circumvention)**

The 7 cases per CCE-77 description:

1. `rm -f /tmp/foo` → NOT blocked (exit 0)
2. `mv -f a b` → NOT blocked (exit 0)
3. `find -f` (if applicable) → NOT blocked (exit 0)
4. `grep -f patterns.txt file.txt` → NOT blocked (exit 0)
5. `tar -f archive.tar` → NOT blocked (exit 0)
6. `git push -f` → blocked (exit 2) — regression test, must keep working
7. `git push --force` → blocked (exit 2) — regression test

```javascript
const new_tests = await agent(
  `You are extending the bash test harness at ~/.claude/skills/ship/tests/validate-git-cmd.test.sh with 7 new cases per CCE-77 acceptance criteria.

Cases 1-5 verify the FIX (over-match cleared): commands should NOT be blocked.
Cases 6-7 verify NO REGRESSION on legitimate blocks: git push -f and --force should still be blocked.

CRITICAL: Use the Write tool to put any 'rm -rf' literals into the file — do NOT compose them in a Bash heredoc here (block-destructive.sh will reject any Bash command containing those literals).

The new cases must use the harness's existing helpers (run_validator, assert_exit). Append to the end of the file.

After writing, run: bash ~/.claude/skills/ship/tests/validate-git-cmd.test.sh

Report: the 7 new test method names, the test run output, any failures.`,
  { label: "B12:author-tests" },
);
await state_append("B12", "tests-added", new_tests);
```

- [ ] **Step 3: Verify all 17 tests pass (10 existing + 7 new)**

```javascript
const test_result = await agent(
  `Run: bash ~/.claude/skills/ship/tests/validate-git-cmd.test.sh
Report exit code and total pass/fail count.`,
  { label: "B12:test-verify" },
);
```

- [ ] **Step 4: Full 17-case AC-coverage check against CCE-77 spec**

Per validator minor M4: B12 runs the FULL 17-case AC-coverage check (10 existing

- 7 new) against the CCE-77 spec's 7 acceptance criteria. B11 validated against
  the existing 10 cases only.

```javascript
const b12_ac_coverage = await agent(
  `You are running an AC-coverage check for B12.

Read the spec at docs/superpowers/specs/2026-06-03-cce77-ship-guardrails-fix.md and enumerate its 7 acceptance criteria.

Read the full test harness at ~/.claude/skills/ship/tests/validate-git-cmd.test.sh (now 17 cases: 10 existing + 7 added by B12).

For each spec AC, identify which test case in the full 17 covers it. List ANY AC with no covering test as a 'gap'. Each of the 7 new cases should map to at least one AC.

Return TEST_VALIDATION_SCHEMA shape.`,
  { schema: TEST_VALIDATION_SCHEMA, label: "B12:ac-coverage" },
);
const b12_ac_gaps = b12_ac_coverage.ac_coverage.filter((c) => c.gap);
if (b12_ac_gaps.length > 0) {
  return await gate_halt("B12", "ac-coverage-gap", {
    summary: `B12 full 17-case AC-coverage check found ${b12_ac_gaps.length} gap(s).`,
    gaps: b12_ac_gaps,
    question: "Revise B12 test cases to close the gaps, or accept and proceed?",
  });
}
await state_append(
  "B12",
  "ac-coverage-passed",
  `${b12_ac_coverage.ac_coverage.length} ACs covered by 17 cases`,
);
```

- [ ] **Step 5: Behavior-vs-impl check on the full 17-case harness**

```javascript
const b12_behavior_check = await agent(
  `You are running a behavior-vs-implementation check for B12.

Read the full test harness at ~/.claude/skills/ship/tests/validate-git-cmd.test.sh (17 cases).

For each assertion, classify as 'behavior' (observable input→output mapping: command goes in, exit code + stderr come out) vs 'implementation' (internal call counts, private-function probes, non-boundary mocks). Report counts.

Return TEST_VALIDATION_SCHEMA shape.`,
  { schema: TEST_VALIDATION_SCHEMA, label: "B12:behavior-vs-impl" },
);
if (b12_behavior_check.behavior_vs_impl.warning) {
  log(
    `WARNING: B12 full harness has ${b12_behavior_check.behavior_vs_impl.impl_coupled_assertions}/${b12_behavior_check.behavior_vs_impl.total_assertions} implementation-coupled assertions. Non-blocking; logged.`,
  );
}
await state_append(
  "B12",
  "behavior-vs-impl-checked",
  JSON.stringify({ warning: b12_behavior_check.behavior_vs_impl.warning }),
);
```

- [ ] **Step 6: 3-execution-validator panel on the new test cases**

```javascript
const b12_diff = await agent(
  `Run: cd ~/.claude && git diff skills/ship/tests/validate-git-cmd.test.sh 2>/dev/null || diff <(cat /tmp/cce77-tests-original.sh) ~/.claude/skills/ship/tests/validate-git-cmd.test.sh; report the diff.`,
  { label: "B12:diff" },
);
const b12_exec_verdicts = await validators_panel(b12_diff, "B12-execution");
const b12_exec_must_fix = b12_exec_verdicts.flatMap((v) => v.must_fix || []);
if (b12_exec_must_fix.some((m) => m.severity === "critical")) {
  return await gate_halt("B12", "execution-validator-dissent", {
    must_fix: b12_exec_must_fix,
  });
}
await state_append(
  "B12",
  "execution-validated",
  `${b12_exec_verdicts.length} verdicts; 0 critical`,
);
```

- [ ] **Step 7: Write the forensic patch file to detached-changes/**

```javascript
await agent(
  `Run: git diff --no-index ~/.claude/skills/ship/tests/validate-git-cmd.test.sh.orig ~/.claude/skills/ship/tests/validate-git-cmd.test.sh > ${DETACHED_CHANGES_DIR}/B12.patch 2>/dev/null; printf "diff: %d bytes\\nexit: %d\\n" $(stat -f%z ${DETACHED_CHANGES_DIR}/B12.patch 2>/dev/null || stat -c%s ${DETACHED_CHANGES_DIR}/B12.patch) $?`,
  { label: "B12:patch-save" },
);
await state_append("B12", "patch-saved", `${DETACHED_CHANGES_DIR}/B12.patch`);
```

---

## Phase F: Phase 4 — Admin filings

### Task 26: B13 — Compose 4 ticket templates

**Files:**

- Reads: CCE-80 spec's "Out of scope" section (for the 4 ticket bodies).
- Produces: in-memory ticket payloads (not yet filed).

- [ ] **Step 1: Read CCE-80 spec's Out-of-scope content**

```javascript
phase("Phase 4: Admin filings");
const cce80_out_of_scope = await agent(
  `Read docs/superpowers/specs/2026-06-02-cce80-diagram-gate-docstring-fix.md.
Extract the section under "Out of scope" listing the 4 follow-up CCE candidates: gate-required, paths-trigger-narrowing, runbook-polish, docstring-flag-lint.
Report each candidate's title + summary verbatim.`,
  { label: "B13:read-out-of-scope" },
);
```

- [ ] **Step 2: Render 4 ticket payloads**

```javascript
const ticket_payloads = [
  {
    summary: "<gate-required title>",
    description:
      "<gate-required body with AC + parent link to CCE-80 + suggested priority>",
    issueTypeName: "Task",
    priority: "Medium",
  },
  // ... 3 more
];
await state_append("B13", "templates-rendered", `4 payloads`);
```

### Task 27: B13 — Template-preview gate + batch-file

**Files:**

- Creates: 4 Jira tickets (CCE-84, 85, 86, 87 expected).

- [ ] **Step 1: Surface the combined preview as one gate**

```javascript
return await gate_halt("B13", "template-preview", {
  summary:
    "Preview of 4 follow-up tickets to file. Approve all, edit, or cancel.",
  payloads: ticket_payloads,
});
```

- [ ] **Step 2: Post-approval — batch-file via createJiraIssue × 4**

```javascript
// On resume with args.gateAnswers[B13] = 'approve'
if (get_gate_answer("B13") === "approve") {
  const filed = [];
  for (const payload of ticket_payloads) {
    const new_key = await agent(
      `Use mcp__plugin_atlassian_atlassian__createJiraIssue with:
projectKey=CCE
issueTypeName=${payload.issueTypeName}
summary=${payload.summary}
contentFormat=markdown
description=${payload.description}
additional_fields={"priority": {"name": "${payload.priority}"}}
cloudId=designitright.atlassian.net
Report only the key of the created issue (e.g. "CCE-84").`,
      { label: `B13:file-${payload.summary.slice(0, 20)}` },
    );
    // Per validator I6 / spec AC#18: every B13 ticket must link back to CCE-80
    // as the parent context.
    await agent(
      `Use mcp__plugin_atlassian_atlassian__createIssueLink with:
sourceIssueKey=${new_key}
destinationIssueKey=CCE-80
relationshipName=Relates
cloudId=designitright.atlassian.net
Report the link payload returned.`,
      { label: `B13:link-${new_key}-to-CCE-80` },
    );
    filed.push(new_key);
  }
  await state_append(
    "B13",
    "completed",
    `Filed + linked to CCE-80: ${filed.join(", ")}`,
  );
}
```

---

## Phase G: Phase 5 — Release

### Task 28: B14 — Compose v0.3.0 release notes

**Files:**

- Reads: `git log v0.2.0..HEAD`.
- Produces: a release-notes markdown blob.

- [ ] **Step 1: Generate release notes**

```javascript
phase("Phase 5: Release");
const release_notes = await agent(
  `Generate v0.3.0 release notes from git log v0.2.0..HEAD on theoju/engineering-docs-agent.

Group commits by Conventional Commits type (feat / fix / docs / chore / test).
For each commit, surface the subject line and any CCE-* ticket trailer.
Include a TL;DR (1-2 sentences) at the top covering the major changes since v0.2.0.

Run: cd /Users/theo/Projects/engineering-docs-agent && git log v0.2.0..HEAD --oneline | head -100

Report the composed release notes in markdown.`,
  { label: "B14:release-notes" },
);
```

### Task 29: B14 — Tag-cut gate; on approval, gh release create

**Files:**

- Creates: `v0.3.0` git tag + GitHub release.

- [ ] **Step 1: Gate for user review**

```javascript
return await gate_halt("B14", "tag-cut-v0.3.0", {
  summary: "Release notes for v0.3.0 below. Approve to publish.",
  notes: release_notes,
  command: 'gh release create v0.3.0 --notes-file <tempfile> --title "v0.3.0"',
});
```

- [ ] **Step 2: Post-approval — publish the release**

```javascript
// On resume with args.gateAnswers[B14] = 'approve'
if (get_gate_answer("B14") === "approve") {
  const release_result = await agent(
    `Write release notes to /tmp/v0.3.0-release-notes.md (via Write tool).
Run: cd /Users/theo/Projects/engineering-docs-agent && gh release create v0.3.0 --notes-file /tmp/v0.3.0-release-notes.md --title "v0.3.0"
Report the release URL.`,
    { label: "B14:gh-release-create" },
  );
  await state_append("B14", "completed", release_result);
}
```

### Task 30: B15 — Wait for release.yml live-tests; close CCE-47

**Files:**

- Reads: gh workflow run logs (release.yml).
- Mutates: CCE-47 Jira issue.

- [ ] **Step 1: Wait for release.yml to fire**

```javascript
const release_run = await agent(
  `Poll: gh run list --workflow=release.yml --limit=1 --json databaseId,status,conclusion
Expect a recent run triggered by the v0.3.0 tag push. Poll every 10s, timeout 15 min.
Report the run ID and conclusion.`,
  { label: "B15:wait-release-run" },
);
```

- [ ] **Step 2: Transition CCE-47 to Done with link to the workflow run**

```javascript
await agent(
  `Use mcp__plugin_atlassian_atlassian__addCommentToJiraIssue to add a comment to CCE-47 saying "v0.3.0 release.yml live-tests verified: ${release_run.url}".
Use mcp__plugin_atlassian_atlassian__transitionJiraIssue to move CCE-47 to Done.`,
  { label: "B15:close-cce47" },
);
await state_append(
  "B15",
  "completed",
  `CCE-47 = Done; verified via ${release_run.url}`,
);
```

---

## Phase H: Phase 6 — Terminal digest (auto-printed; no gate)

### Task 31: Compose + print digest

- [ ] **Step 1: Read state file**

```javascript
phase("Phase 6: Terminal digest");
const state_records = await agent(
  `Read ~/.claude/orchestrator/state-${RUN_ID}.jsonl and report the full content.`,
  { label: "digest:read-state" },
);
```

- [ ] **Step 2: Compose digest**

```javascript
const digest = await agent(
  `Given this orchestrator state log:

${state_records}

Compose a terminal digest with:
- One section per task B1-B15 (B7/B16 excluded), showing terminal status (completed / gated-and-resolved / failed / skipped).
- For B5: include the PR URL recorded in ship-result.
- For B6: include the merge commit + Jira CCE-80 final status.
- For B8/B9: include the merge commits.
- For B11: include the diff hash and CCE-77 final status.
- For B13: list the 4 filed ticket keys.
- For B14: include the release URL.
- For B15: include the CCE-47 final status.

Format as markdown.`,
  { label: "digest:compose" },
);
log(`\n\n=== ORCHESTRATOR TERMINAL DIGEST ===\n${digest}\n`);
return { digest, state_records };
```

---

## Phase I: Smoke runs (before production batch)

The orchestrator script supports `args.dryRun: true`. In dry-run mode, all `agent()` calls return inline fixture responses. Three smoke runs verify the pipeline before live execution.

### Task 32: Smoke run — Phase 4 (B13 administrative)

**Files:**

- Reads: inline fixtures defined in the orchestrator script.

- [ ] **Step 1: Define Phase 4 fixtures inline**

Per validator minor M5: fixture values consumed by typed dispatches (those with
`{ schema: ... }`) must satisfy the schema's `required` fields, or the dry-run
dispatch will fail validation. Distinguish:

- Free-text dispatches (no `schema:` in the `agent()` options) — string fixture
  values are fine.
- Typed dispatches — fixture values must be schema-shaped objects.

**Iter-2 fixture-resolution helper.** Review loops emit iter-tagged labels
like `B10:spec-reviewer-iter-1`, `B10:spec-reviewer-iter-2`, `B11:spec-reviewer-iter-3`.
Defining a fixture entry per iteration is noisy; the agent runtime resolves
labels using exact-match first, then strips the `-iter-N` suffix and retries.
Document this once at the top of every `PHASE_<X>_FIXTURES` block (applies to
Tasks 32, 33, 34):

```javascript
// Fixture resolution: exact label match wins; otherwise strip iter-N suffix
// and retry. The agent runtime calls this when args.dryRun is true.
function resolve_fixture(label, fixtures) {
  if (label in fixtures) return fixtures[label];
  const base = label.replace(/-iter-\d+$/, "");
  return fixtures[base];
}
// Worked example: a lookup for "B10:spec-reviewer-iter-2" misses the exact
// key but matches the base entry "B10:spec-reviewer" in PHASE_3_FIXTURES,
// which returns APPROVED_VERDICT.
```

```javascript
// In the orchestrator script, near the top:
const PHASE_4_FIXTURES = {
  // Free-text dispatches: strings OK.
  "B13:read-out-of-scope": "<sample CCE-80 Out-of-scope section text>",
  "B13:file-gate-required": "CCE-84",
  "B13:file-paths-trigger-narrowing": "CCE-85",
  "B13:file-runbook-polish": "CCE-86",
  "B13:file-docstring-flag-lint": "CCE-87",
  "B13:link-CCE-84-to-CCE-80": "linked",
  "B13:link-CCE-85-to-CCE-80": "linked",
  "B13:link-CCE-86-to-CCE-80": "linked",
  "B13:link-CCE-87-to-CCE-80": "linked",
};
```

- [ ] **Step 2: Launch dry-run scoped to B13**

```javascript
// Via Workflow tool with args.dryRun=true and args.scope=['B13']
const dry_run_result = /* Workflow invocation */
```

- [ ] **Step 3: Verify**

Assert: template-preview gate fired; 4 createJiraIssue dispatches logged (not executed); state file has 4 'filed' transitions; no actual Jira mutations.

### Task 33: Smoke run — Phase 1 (B4 → B5 → B6 code-change with ship-gate)

- [ ] **Step 1: Define Phase 1 fixtures inline**

```javascript
const APPROVED_VERDICT = {
  approved: true,
  must_fix: [],
  overall_assessment: "sample fixture: all lenses approved",
};
const SAMPLE_TEST_VALIDATION = {
  ac_coverage: [{ ac_id: "AC1", covering_test: "test_sample", gap: false }],
  behavior_vs_impl: {
    total_assertions: 10,
    behavior_assertions: 10,
    impl_coupled_assertions: 0,
    warning: false,
  },
};

const PHASE_1_FIXTURES = {
  // Free-text dispatches: strings OK.
  "B4:fetch-failed-log": "<sample mkdocs error log>",
  "B5:writing-plans": "docs/superpowers/plans/sample-plan.md",
  "B5:read-plan": "<sample plan content>",
  "B5:sdd-execute": "DONE with 3 commits",
  "B5:get-shas": "abc123 commit 1\ndef456 commit 2",
  "B5:get-diff": "<sample unified diff>",
  "B5:checkout-cce80-branch": "chore/CCE-80-template-workflow-run-refresh",
  "B5:branch-restore": "chore/meta-orchestrator-spec-2026-06-03",
  // Typed dispatches: must be schema-shaped.
  "B4:debug-probe": {
    root_cause: "sample",
    fix_description: "sample",
    files_to_modify: ["scripts/scaffold_workflow.py"],
    acceptance_criteria: ["AC1", "AC2"],
  },
  // validators_panel emits per-lens labels; one fixture per lens.
  "B4-patch-spec:completeness": APPROVED_VERDICT,
  "B4-patch-spec:correctness": APPROVED_VERDICT,
  "B4-patch-spec:scope": APPROVED_VERDICT,
  "B5-plan:completeness": APPROVED_VERDICT,
  "B5-plan:correctness": APPROVED_VERDICT,
  "B5-plan:scope": APPROVED_VERDICT,
  "B5-execution:completeness": APPROVED_VERDICT,
  "B5-execution:correctness": APPROVED_VERDICT,
  "B5-execution:scope": APPROVED_VERDICT,
  // Test-validation dispatches (TEST_VALIDATION_SCHEMA).
  "B5:ac-coverage": SAMPLE_TEST_VALIDATION,
  "B5:behavior-vs-impl": SAMPLE_TEST_VALIDATION,
};
```

- [ ] **Step 2: Dry-run the full Phase 1 chain**

- [ ] **Step 3: Verify**

Assert: systematic-debugging → 3-spec-validator → writing-plans → 3-plan-validator → SDD → test-validation → 3-execution-validator → ship-gate halt → resume with synthetic ship-result → B6 merge halt fired.

### Task 34: Smoke run — Phase 3 (B10 → B11 → B12 detached-target)

- [ ] **Step 1: Define Phase 3 fixtures**

```javascript
const PHASE_3_FIXTURES = {
  // Free-text dispatches: strings OK.
  "B10:fetch-cce77-jira": "<sample Jira description>",
  "B10:implementer": "<sample spec content>",
  "B10:read-spec": "<sample spec content>",
  "B10:commit-spec": "abc123",
  "B11:reproduce": "<7 exit codes>",
  "B11:read-validator": "<lines 30-60>",
  "B11:implementer": "<3-line edit>",
  "B11:post-diff": "<sample diff>",
  "B11:patch-save": "diff: 512 bytes\nexit: 0",
  "B12:read-tests": "<sample test file>",
  "B12:author-tests": "<7 new tests added>",
  "B12:test-verify": "exit=0 pass=17 fail=0",
  "B12:diff": "<sample test diff>",
  "B12:patch-save": "diff: 1024 bytes\nexit: 0",
  // Typed dispatches: must be schema-shaped.
  // B10 SDD reviewers (Task 19).
  "B10:spec-reviewer": APPROVED_VERDICT,
  "B10:quality-reviewer": APPROVED_VERDICT,
  // B10 3-lens spec panel (Task 20).
  "B10-cce77-spec:completeness": APPROVED_VERDICT,
  "B10-cce77-spec:correctness": APPROVED_VERDICT,
  "B10-cce77-spec:scope": APPROVED_VERDICT,
  // B11 patch-spec (Task 21b/21c).
  "B11:debug-probe": {
    root_cause: "sample",
    fix_description: "sample",
    files_to_modify: ["~/.claude/skills/ship/lib/validate-git-cmd.sh"],
    acceptance_criteria: ["AC1", "AC2"],
  },
  "B11-patch-spec:completeness": APPROVED_VERDICT,
  "B11-patch-spec:correctness": APPROVED_VERDICT,
  "B11-patch-spec:scope": APPROVED_VERDICT,
  // B11 plan (Task 21d/21e).
  "B11:writing-plans": "docs/superpowers/plans/sample-b11-plan.md",
  "B11:read-plan": "<sample plan content>",
  "B11-plan:completeness": APPROVED_VERDICT,
  "B11-plan:correctness": APPROVED_VERDICT,
  "B11-plan:scope": APPROVED_VERDICT,
  // B11 SDD reviewers (Task 22).
  "B11:spec-reviewer": APPROVED_VERDICT,
  "B11:quality-reviewer": APPROVED_VERDICT,
  // B11 test-validation (Task 23).
  "B11:ac-coverage": SAMPLE_TEST_VALIDATION,
  "B11:behavior-vs-impl": SAMPLE_TEST_VALIDATION,
  "B11-execution:completeness": APPROVED_VERDICT,
  "B11-execution:correctness": APPROVED_VERDICT,
  "B11-execution:scope": APPROVED_VERDICT,
  // B12 test-validation (Task 25 Step 4-6).
  "B12:ac-coverage": SAMPLE_TEST_VALIDATION,
  "B12:behavior-vs-impl": SAMPLE_TEST_VALIDATION,
  "B12-execution:completeness": APPROVED_VERDICT,
  "B12-execution:correctness": APPROVED_VERDICT,
  "B12-execution:scope": APPROVED_VERDICT,
};
```

- [ ] **Step 2: Dry-run Phase 3 chain**

- [ ] **Step 3: Verify**

Assert: detached-target executor used (not ship-gate); B11 critical-gate fires with diff + test output; B12 uses Write tool for fixture writes (no Bash with `rm -rf` literal); CCE-77 transitionJiraIssue dispatched.

---

## Phase J: Targeted unit-test plan

Per spec lines 389-412 and validator critical C5: the spec's 20-case test plan is
decomposed into 20 discrete tasks (Tasks 35–54). Every task uses
`args.dryRun=true` + a per-test fixture map; assertions read state file content,
gate file content, or executor return values. Tasks below are listed in spec
AC# order.

### Task 35: test_full_batch_completes_or_halts_cleanly (spec line 393, AC#1)

**Fixture input:** all-approve verdicts for every validator panel + APPROVED
ship-result for B5 + 'approve' gate answers for B6/B11/B13/B14.

- [ ] **Step 1:** Build the all-approve fixture map (merge `PHASE_1_FIXTURES`,
      `PHASE_3_FIXTURES`, `PHASE_4_FIXTURES` plus B6/B14/B15 entries).
- [ ] **Step 2:** Dispatch the orchestrator with
      `{ dryRun: true, fixtures: all_approve, gateAnswers: { B6: 'merge', B11: 'approve', B13: 'approve', B14: 'approve' }, shipResults: { B5: { status: 'shipped', pr_url: 'https://example/pr' } } }`.
- [ ] **Step 3:** Assert: the digest object returned by `digest_executor`
      enumerates all 14 batch entries (B1–B6, B8–B15) each with a terminal
      status in {completed, gated-and-resolved, failed, skipped}; no entry
      missing.

### Task 36: test_b1_blocks_protected_path_touch (spec line 394, AC#2)

**Fixture input:** B5 fixture proposing a diff touching `CLAUDE.md` BEFORE B1
emits its `completed` transition.

- [ ] **Step 1:** Build a fixture where `B5:sdd-execute` returns a diff string
      containing `CLAUDE.md` and the state file has NO `B1` `completed`
      transition.
- [ ] **Step 2:** Dispatch
      `await workflow({name:'meta-orchestrator-followup-chain'}, {dryRun: true, scope: ['B5'], fixtures: <built fixture>})`
      to run B5 in isolation through the orchestrator's normal phase machinery.
- [ ] **Step 3:** Assert: return value is a `{ halt: "critical-gate", taskId:
"B5", kind: "cce82-blocklist-violation" }` structure; gate file written at
      `${GATES_DIR}/B5.md`.

### Task 37: test_branch_isolation (spec line 395, AC#3)

**Fixture input:** current branch reported as `fix/CCE-82-pages-bootstrap`.

- [ ] **Step 1:** Build a fixture where `B2:current-branch` returns
      `fix/CCE-82-pages-bootstrap`.
- [ ] **Step 2:** Dispatch
      `await workflow({name:'meta-orchestrator-followup-chain'}, {dryRun: true, scope: ['B2'], fixtures: <built fixture>})`.
- [ ] **Step 3:** Assert: return value is `{ halt: "critical-gate", taskId:
"B2", kind: "wrong-branch" }`; payload `suggested` includes
      `git checkout chore/meta-orchestrator-spec-2026-06-03`.

### Task 38: test_cce82_blocklist_detection (spec line 396, AC#4)

**Fixture input:** fabricated diff touching `scripts/enable_pages.py`.

- [ ] **Step 1:** Call `cce82_blocklist_guard("--- a/scripts/enable_pages.py\n+++ b/scripts/enable_pages.py", "B5")` directly.
- [ ] **Step 2:** Assert: return value is `{ halt: "critical-gate", taskId:
"B5", kind: "cce82-blocklist-violation" }`; payload `summary` lists
      `scripts/enable_pages.py`.

### Task 39: test_pipeline_routing_per_task_class (spec line 397, AC#5+6+7)

Per iter-2 scope consolidation: spec line 397 models AC#5/6/7 as a single test
row covering pipeline-routing across systematic-debugging, writing-plans, and
SDD. The three asserts run in one task instead of three.

**Fixture input:** record `agent()` labels invoked during dry-run of B4, B5,
B10, B11, B12. Dispatches use the `workflow()` wrapper with `args.scope` so
each batch item runs in isolation through the orchestrator's normal phase
machinery.

- [ ] **Step 1: systematic-debugging routing (AC#5)** — Dispatch
      `await workflow({name:'meta-orchestrator-followup-chain'}, {dryRun: true, scope: ['B4','B11'], fixtures: {...PHASE_1_FIXTURES, ...PHASE_3_FIXTURES}})`.
      Assert: labels `B4:debug-probe` and `B11:debug-probe` are present in the
      dispatch log (systematic-debugging dispatched for both).
- [ ] **Step 2: writing-plans routing (AC#6)** — Dispatch
      `await workflow({name:'meta-orchestrator-followup-chain'}, {dryRun: true, scope: ['B5','B11'], fixtures: {...PHASE_1_FIXTURES, ...PHASE_3_FIXTURES}})`.
      Assert: labels `B5:writing-plans` and `B11:writing-plans` are present in
      the dispatch log.
- [ ] **Step 3: SDD reviewer routing (AC#7)** — Dispatch
      `await workflow({name:'meta-orchestrator-followup-chain'}, {dryRun: true, scope: ['B5','B10','B11','B12'], fixtures: {...PHASE_1_FIXTURES, ...PHASE_3_FIXTURES}})`.
      Assert: labels matching `:implementer`, `:spec-reviewer`,
      `:quality-reviewer` are present for B5, B10, B11; assert NO
      `:spec-reviewer` or `:quality-reviewer` label is present for B12 (which
      is single-agent with existing-harness verification per spec AC#7, NOT
      SDD). B12 instead emits its own validators in the 3-execution-validator
      panel (`B12-execution:completeness` / `:correctness` / `:scope`).

### Task 40: test_validator_dissent_triggers_fixer_loop (spec line 398, AC#8)

**Fixture input:** completeness validator returns `{ approved: false, must_fix:
[{ severity: "critical", location: "x", description: "y" }] }` once, then
APPROVED on iteration 2.

- [ ] **Step 1:** Build a counter-driven fixture for
      `B4-patch-spec:completeness`.
- [ ] **Step 2:** Dispatch Task 9 stage (B4 3-spec-validator panel).
- [ ] **Step 3:** Assert: dispatch log contains `B4:fixer-iter-1` and
      `B4-patch-spec-iter-1:*` labels; state file contains
      `patch-spec-validated` with `1 iterations` detail.

### Task 41: test_fixer_loop_caps_at_3_iterations (spec line 399, AC#8)

**Fixture input:** all 3 validators return must-fix indefinitely.

- [ ] **Step 1:** Build a fixture where every `B4-patch-spec*:completeness`
      label returns must-fix with severity critical.
- [ ] **Step 2:** Dispatch the Task 9 must-fix loop.
- [ ] **Step 3:** Assert: return value is `{ halt: "critical-gate", taskId:
"B4", kind: "validator-dissent-exhausted" }` on the 4th iteration; gate
      file written.

### Task 42: test_ac_coverage_gap_blocks_task (spec line 400, AC#9)

**Fixture input:** `B5:ac-coverage` returns `{ ac_coverage: [{ ac_id: "AC3",
gap: true }], behavior_vs_impl: ... }`.

- [ ] **Step 1:** Dispatch Task 12 Step 1.
- [ ] **Step 2:** Assert: task halts (the ac-gap branch fires) with a
      gate-halt structure.

### Task 43: test_behavior_vs_impl_warning_non_blocking (spec line 401, AC#9)

**Fixture input:** `B5:behavior-vs-impl` returns 6 impl-coupled / 10 total with
`warning: true`.

- [ ] **Step 1:** Dispatch Task 12 Step 2.
- [ ] **Step 2:** Assert: a WARNING is logged but the executor does NOT halt;
      state file gains a `test-validation-passed` transition with `warning:
true` detail.

### Task 44: test_ship_gate_resume_parameterized (spec line 402, AC#10)

**Fixture input:** parameterized over `{ shipped, halted, failed }`
ship-results.

- [ ] **Step 1:** Run the test 3 times — once per ship-result status — passing
      `shipResults: { B5: { status: <status>, ... } }`.
- [ ] **Step 2:** Assert per case: `shipped` → state file gains
      `B5/shipped` + `B5/branch-restored`; `halted` → return value is
      `{ halt: "critical-gate", taskId: "B5", kind: "ship-halted" }`; `failed`
      → return value is `{ halt: "batch-aborted", reason: "B5 ship failed" }`.

### Task 45: test_detached_target_no_pr (spec line 403, AC#11)

**Fixture input:** dry-run B11 with full `PHASE_3_FIXTURES`.

- [ ] **Step 1:** Dispatch
      `await workflow({name:'meta-orchestrator-followup-chain'}, {dryRun: true, scope: ['B11'], fixtures: PHASE_3_FIXTURES})`.
- [ ] **Step 2:** Assert: no dispatch label matches `gh pr create`;
      `B11:transition-cce77` is in the log after the gate resolves.

### Task 46: test_block_destructive_circumvention (spec line 404, AC#12)

**Fixture input:** dry-run B12 with fixtures containing `rm -rf` literals in
the test-case payload.

- [ ] **Step 1:** Dispatch
      `await workflow({name:'meta-orchestrator-followup-chain'}, {dryRun: true, scope: ['B12'], fixtures: PHASE_3_FIXTURES})`.
- [ ] **Step 2:** Assert: every dispatch label that writes `rm -rf` literals
      uses the Write tool (label tag contains `author-tests` or fixture write),
      not a Bash heredoc; no Bash dispatch in the log contains the literal
      string `rm -rf`.

### Task 47: test_template_preview_gate (spec line 405, AC#13)

**Fixture input:** dry-run B13 with `PHASE_4_FIXTURES`.

- [ ] **Step 1:** Dispatch
      `await workflow({name:'meta-orchestrator-followup-chain'}, {dryRun: true, scope: ['B13'], fixtures: PHASE_4_FIXTURES})`
      with no `gateAnswers.B13` set.
- [ ] **Step 2:** Assert: return value is `{ halt: "critical-gate", taskId:
"B13", kind: "template-preview" }`; payload `payloads` is an array of 4
      ticket objects; ZERO `createJiraIssue` dispatches in the log.

### Task 48: test_resume_with_synthetic_gate_answer (spec line 406, AC#14)

**Fixture input:** two-phase dispatch — first run halts at B6 gate; second run
sets `gateAnswers: { B6: 'merge' }`.

- [ ] **Step 1:** Run dry-run; capture the run_id and gate state.
- [ ] **Step 2:** Re-dispatch with `resumeFromRunId: <run_id>` and `gateAnswers:
{ B6: 'merge' }`.
- [ ] **Step 3:** Assert: upstream stages report cache-hit (dispatch journal
      shows them re-served from cache, not re-executed); post-gate stage
      records `B6/completed`.

### Task 49: test_state_file_append_only (spec line 407, AC#15)

**Fixture input:** mid-run snapshot vs end-run snapshot.

- [ ] **Step 1:** Dispatch the orchestrator; pause mid-run after Phase 1; copy
      `${STATE_PATH}` to `/tmp/state-mid.jsonl`.
- [ ] **Step 2:** Resume and let complete; copy final `${STATE_PATH}` to
      `/tmp/state-end.jsonl`.
- [ ] **Step 3:** Assert: every line in `state-mid.jsonl` appears verbatim and
      in the same order at the start of `state-end.jsonl` (strict-prefix
      superset).

### Task 50: test_gate_file_content_schema (spec line 408, AC#16)

**Fixture input:** dispatch a path that triggers a critical-gate.

- [ ] **Step 1:** Dispatch with a fixture forcing
      `B4-patch-spec:correctness` critical must-fix at iteration 4.
- [ ] **Step 2:** Read the file written at `${GATES_DIR}/B4.md`.
- [ ] **Step 3:** Assert: contains the required sections — `Task summary`,
      `Operation preview / diff`, `Specific question`, `Suggested default` —
      each non-empty.

### Task 51: test_phase_ordering (spec line 409, AC#17)

**Fixture input:** full all-approve fixture.

- [ ] **Step 1:** Dispatch the orchestrator to completion.
- [ ] **Step 2:** Parse `${STATE_PATH}`; group entries by phase via the BATCH
      `phase` lookup.
- [ ] **Step 3:** Assert: Phase 0 entries have earliest timestamps; Phase 1 and
      Phase 2 entries interleave (they run in parallel per Task 3 Step 3);
      Phase 3 entries come after Phase 1 + Phase 2; Phase 4, 5, 6 entries
      strictly follow Phase 3.

### Task 52: test_phase_6_tickets_link_cce80 (spec line 410, AC#18)

**Fixture input:** dry-run B13 to completion.

- [ ] **Step 1:** Dispatch
      `await workflow({name:'meta-orchestrator-followup-chain'}, {dryRun: true, scope: ['B13'], fixtures: PHASE_4_FIXTURES, gateAnswers: {B13: 'approve'}})`.
- [ ] **Step 2:** Inspect dispatch log for `createIssueLink` labels.
- [ ] **Step 3:** Assert: 4 `B13:link-CCE-*-to-CCE-80` dispatches present; each
      payload references `destinationIssueKey=CCE-80` and
      `relationshipName=Relates`.

### Task 53: test_digest_lists_all_tasks (spec line 411, AC#19)

**Fixture input:** dry-run all-approve to completion.

- [ ] **Step 1:** Dispatch to completion; capture return value's `digest` field.
- [ ] **Step 2:** Assert: digest markdown contains a section for each of B1,
      B2, B3, B4, B5, B6, B8, B9, B10, B11, B12, B13, B14, B15 with a terminal
      status.

### Task 54: test_tag_version_correct (spec line 412, AC#20)

**Fixture input:** dry-run B14.

- [ ] **Step 1:** Dispatch
      `await workflow({name:'meta-orchestrator-followup-chain'}, {dryRun: true, scope: ['B14'], gateAnswers: {B14: 'approve'}})`.
- [ ] **Step 2:** Assert: dispatch log contains a `B14:gh-release-create`
      label whose prompt text includes literal `gh release create v0.3.0`;
      assert NO occurrence of `v0.5.0` anywhere in any dispatch label or
      prompt text.

---

## Self-Review

After writing this plan, the author runs the writing-plans skill's self-review checklist (updated after iter-1's 22 must-fix findings and iter-2's ~13 convergent fixes were applied):

1. **Spec coverage**: Every spec requirement (AC #1-#20) maps to at least one plan task. Triple-validation pattern → Tasks 9, 10, 20, 21c, 21e, 22, 23, 25; AC-coverage + behavior-not-implementation → Tasks 12, 23 (existing 10-case harness), 25 (full 17-case harness); Resume Semantics → Tasks 14 (ship-gate), 24 (B11 gate), 27 (B13 gate), 29 (B14 gate); Ship-gate resume protocol → Task 14 (with branch-restore step + Step 1 resume_ts capture into state); Detached-target execution → Tasks 21, 21b, 21c, 21d, 21e, 22, 23, 24 (now full process parity with B5 — systematic-debugging + writing-plans + SDD); Hostile-hook circumvention → Task 25 Step 2; Phase 4 template-preview gate → Task 27 (with explicit CCE-80 parent-link enforcement via createIssueLink per AC#18); CCE-82 protection invariant → guard fn invoked EXPLICITLY per the canonical pattern in Task 3 Step 4 with the inline worked example in Task 11 Step 3; State file accuracy → all state_append calls now `await`-ed; Gate file content → gate_halt always produces structured payload (writes forensic .md before returning, per Task 2 Step 6); Phase 1 || Phase 2 parallel execution → Task 3 Step 3 top-level driver. **AC#17 (phase ordering) is enforced STRUCTURALLY by the sequential `await phase0(); await parallel([phase1, phase2]); await phase3(); ...` driver in Task 3 Step 3 — not by a runtime blocker-satisfaction guard.**
2. **Placeholder scan**: No TBDs, no "implement later", no "similar to Task N", no "add appropriate error handling". Task 15 Step 2's diagram-gate-failing condition is now concrete JSON parsing of `statusCheckRollup`, not a comment stub. Task 23 Steps 1-2 are now concrete AC-coverage + behavior-vs-impl dispatches, not ellipses. The few `<sample>` placeholders are in fixture definitions which are explicitly meant to be substituted at smoke-run time, not in production code paths.
3. **Type consistency**: VERDICT_SCHEMA used uniformly across all validator panels (Tasks 9, 10, 19, 20, 21c, 21e, 22, 23, 25). TEST_VALIDATION_SCHEMA used in Tasks 12, 23, 25. SHIP_RESULT_SCHEMA used in Task 14. PATCH_SPEC_SCHEMA shared between Tasks 8/9 and 21b/21c. Helper signatures consistent and now all `async`: `validators_panel(text, label_prefix)`, `await gate_halt(taskId, kind, payload)`, `await state_append(taskId, transition, detail)`, `await get_ship_result(taskId)`, `await cce82_blocklist_guard(diff, taskId)`. `get_gate_answer` remains synchronous (reads args). Status-typed agent responses (`status_96`, `cce80_status`, `cce66_status`) coerce via `JSON.parse(...)` before field access, mirroring Task 15 Step 2's `checks_status` pattern.
4. **Foundational helper rewrite (Task 2 Step 6 + Step 7)**: `RUN_ID` wired via `args?.runId || "session-default"`; all paths use `$HOME` (Bash-expanded), never JS `~` literals; `state_append`, `gate_halt`, `get_ship_result` spawn Bash via `agent()` for real filesystem writes; `gate_halt` writes the forensic .md file per spec AC#16 BEFORE returning the halt structure. `cce82_blocklist_guard` (Task 2 Step 7) carries the 10 protected paths from spec lines 336-344 and uses `return await gate_halt(...)` for await consistency.
5. **20-test decomposition (Phase J, Tasks 35–54)**: every test from spec lines 391-412 is now a discrete bite-sized task with fixture input, dispatch invocation, and assert condition documented. **20 tasks total** — spec AC#5/6/7 are consolidated into Task 39 `test_pipeline_routing_per_task_class` (three asserts: systematic-debugging routing, writing-plans routing, SDD reviewer routing) matching the spec's single test row at line 397. Every Phase J test dispatches `await workflow({name:'meta-orchestrator-followup-chain'}, {dryRun: true, scope: ['B<N>'], fixtures: PHASE_<X>_FIXTURES, ...})` so the orchestrator's phase machinery runs the executor in isolation; tests do not call `b<N>_executor()` directly.
6. **Iteration-2 deletions (scope tightening)**: Three helpers were removed from Task 2 after the validator scope lens flagged them as defensive code with zero call sites in the plan body: `retry_once` (spec trigger #13), `rollback_gate` (spec trigger #14), `check_blockers_satisfied` (spec AC#17). Spec triggers #13/#14 are documentation-level recovery guidance and can be invoked ad-hoc via `gate_halt(taskId, 'retry-exhausted', ...)` or `gate_halt(taskId, 'rollback-approval', ...)` when a future task needs them. AC#17 is enforced structurally by the Task 3 Step 3 sequential driver, not by a runtime guard. The remaining live helpers — `state_append`, `gate_halt`, `get_ship_result`, `cce82_blocklist_guard` — all carry call sites throughout Tasks 4-30. Smoke run fixture maps (Tasks 32–34) include the `resolve_fixture` helper at the top of each PHASE\_<X>\_FIXTURES block to fall back from iter-tagged labels (`B10:spec-reviewer-iter-2`) to base labels (`B10:spec-reviewer`); Phase J tests inline their fixture refs without invoking the helper.

---

## Execution Handoff

After plan + 3-agent plan-validation panel approve, transition to subagent-driven-development.

**Recommended execution approach**: `superpowers:subagent-driven-development` (matches the spec's per-task implementer + spec-reviewer + code-quality-reviewer pattern; fresh subagent per task; review checkpoints between).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
