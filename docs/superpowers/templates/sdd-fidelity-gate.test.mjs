// Unit tests for the SDD fidelity verification ladder (sdd-fidelity-gate.mjs).
// Run: `node --test docs/superpowers/templates/sdd-fidelity-gate.test.mjs`
// or via pytest: `pytest tests/templates/test_sdd_fidelity_gate_node.py`.
//
// Every test tagged [REGRESSION] locks in a defect found during the multi-agent
// review of this ladder; the comment names the failure it guards against.

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  expectedHit,
  gitReady,
  dirtyPaths,
  committedSince,
  observedForTask,
  runImplementerWithTier0,
  runTier1,
  runTier2Before,
  runTier2After,
  runReviewerGate,
  runFidelityLadder,
} from "./sdd-fidelity-gate.mjs";

// --- fake dependency harness ----------------------------------------------
function makeDeps(opts = {}) {
  const { git = {}, agentQueue = [], cmdHandlers = {} } = opts;
  const state = {
    porcelain: git.porcelain ?? "",
    committed: git.committed ?? "",
    isRepo: git.isRepo ?? true,
    hasHead: git.hasHead ?? true,
  };
  const calls = { bash: [], agent: [], log: [], halt: [] };
  const queue = [...agentQueue];

  async function bash(cmd) {
    calls.bash.push(cmd);
    for (const [key, val] of Object.entries(cmdHandlers)) {
      if (cmd.includes(key)) {
        const out = typeof val === "function" ? val(state) : val;
        if (out instanceof Error) throw out;
        return out;
      }
    }
    if (cmd.includes("rev-parse --is-inside-work-tree")) {
      if (!state.isRepo) throw new Error("not a git repo");
      return "true\n";
    }
    if (cmd.includes("rev-parse --verify HEAD")) {
      if (!state.hasHead) throw new Error("no HEAD");
      return "deadbeef\n";
    }
    if (cmd.startsWith("date -u")) return "2026-06-07T00:00:00Z\n";
    if (cmd.includes("status --porcelain")) return state.porcelain;
    if (cmd.includes("log --since")) return state.committed;
    throw new Error("unhandled bash cmd: " + cmd);
  }

  async function agent(prompt, optsA) {
    calls.agent.push({ prompt, opts: optsA });
    if (!queue.length) throw new Error("agent queue empty");
    const next = queue.shift();
    return typeof next === "function" ? next(state) : next;
  }

  const deps = {
    bash,
    agent,
    log: (m) => calls.log.push(m),
    halt: (o) => calls.halt.push(o),
  };
  return { deps, calls, state };
}

const kinds = (calls) => calls.halt.map((h) => h.kind);
const logged = (calls, sub) => calls.log.some((m) => m.includes(sub));

// --- pure helpers ----------------------------------------------------------
test("expectedHit: exact + segment-boundary prefix, no component false-match", () => {
  assert.equal(expectedHit("src", new Set(["src"])), true);
  assert.equal(expectedHit("src/x.py", new Set(["src"])), true);
  assert.equal(expectedHit("src/a/b.py", new Set(["src/a"])), true);
  assert.equal(expectedHit("src2/x", new Set(["src"])), false);
  assert.equal(expectedHit("a/bc", new Set(["a/b"])), false);
  assert.equal(expectedHit("nope", new Set()), false);
});

test("dirtyPaths: parses status codes and adds BOTH rename paths", async () => {
  const { deps, state } = makeDeps();
  state.porcelain = " M scripts/state_io.py\n?? new.txt\nR  old.py -> new.py\n";
  const out = await dirtyPaths(deps.bash, ".");
  assert.deepEqual([...out].sort(), [
    "new.py",
    "new.txt",
    "old.py",
    "scripts/state_io.py",
  ]);
});

test("dirtyPaths: empty porcelain -> empty set", async () => {
  const { deps } = makeDeps({ git: { porcelain: "" } });
  assert.equal((await dirtyPaths(deps.bash, ".")).size, 0);
});

test("gitReady: true only when repo AND HEAD exist", async () => {
  assert.equal(await gitReady(makeDeps().deps.bash, "."), true);
  assert.equal(
    await gitReady(makeDeps({ git: { isRepo: false } }).deps.bash, "."),
    false,
  );
  assert.equal(
    await gitReady(makeDeps({ git: { hasHead: false } }).deps.bash, "."),
    false,
  );
});

test("committedSince: splits name-only output into a set", async () => {
  const { deps } = makeDeps({ git: { committed: "a.py\nb.py\n" } });
  const out = await committedSince(deps.bash, ".", "2026-06-07T00:00:00Z");
  assert.deepEqual([...out].sort(), ["a.py", "b.py"]);
});

test("observedForTask: newly-dirty (minus baseline) UNION committed", async () => {
  const { deps, state } = makeDeps();
  state.porcelain = " M keep.py\n M fresh.py\n"; // keep.py is in baseline
  state.committed = "done.py\n";
  const baseline = new Set(["keep.py"]);
  const out = await observedForTask(deps.bash, ".", baseline, "ts");
  assert.deepEqual([...out].sort(), ["done.py", "fresh.py"]);
});

// --- Tier 0 ----------------------------------------------------------------
test("Tier 0: happy path — implementer edits expected path, no halt", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      (s) => {
        s.porcelain = " M scripts/x.py\n";
        return { status: "DONE", changed_files: ["scripts/x.py"] };
      },
    ],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: ["scripts/x.py"] },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.deepEqual(kinds(calls), []);
  assert.equal(calls.agent.length, 1);
});

test("Tier 0: no-op twice -> halt empty_diff", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      { status: "DONE", changed_files: [] },
      { status: "DONE", changed_files: [] },
    ],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: ["scripts/x.py"] },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, true);
  assert.deepEqual(kinds(calls), ["sdd_fidelity_empty_diff"]);
  assert.equal(calls.agent.length, 2);
});

test("[REGRESSION] Tier 0: no-op then retry succeeds — no false empty_diff AND no false claim_mismatch (stale-observed bug)", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      { status: "DONE", changed_files: [] }, // no-op, no tree mutation
      (s) => {
        s.porcelain = " M scripts/x.py\n"; // retry does the work
        return { status: "DONE", changed_files: ["scripts/x.py"] };
      },
    ],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: ["scripts/x.py"] },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false, "recovery path must not halt");
  assert.deepEqual(
    kinds(calls),
    [],
    "stale observed/report would have mis-halted",
  );
  assert.equal(r.report.changed_files[0], "scripts/x.py");
});

test("Tier 0: claimed file absent from delta -> halt claim_mismatch", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      (s) => {
        s.porcelain = " M scripts/x.py\n";
        return {
          status: "DONE",
          changed_files: ["scripts/x.py", "scripts/PHANTOM.py"],
        };
      },
    ],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: ["scripts/x.py"] },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, true);
  assert.deepEqual(kinds(calls), ["sdd_fidelity_claim_mismatch"]);
  assert.deepEqual(calls.halt[0].phantom, ["scripts/PHANTOM.py"]);
});

test("Tier 0: empty expected_touch_paths -> no-op check disabled (log), phantom still runs", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      (s) => {
        s.porcelain = " M a.py\n";
        return { status: "DONE", changed_files: ["a.py"] };
      },
    ],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: [] },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.ok(logged(calls, "no expected_touch_paths"));
  assert.deepEqual(kinds(calls), []);
});

test("Tier 0: plan zero_diff_allowed -> no retry, no no-op halt, no partial-coverage noise", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [{ status: "DONE", changed_files: [] }],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: ["x"], zero_diff_allowed: true },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.equal(
    calls.agent.length,
    1,
    "must not retry a plan-declared zero-diff task",
  );
  assert.equal(logged(calls, "Re-dispatching"), false);
  assert.equal(logged(calls, "untouched"), false);
});

test("[REGRESSION] Tier 0: self-authored zero_diff_allowed is NOT honored (blocker: self-exemption)", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      { status: "DONE", changed_files: [], zero_diff_allowed: true }, // self-declared
      { status: "DONE", changed_files: [], zero_diff_allowed: true }, // self-declared again
    ],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: ["x"], zero_diff_allowed: false },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(
    r.halted,
    true,
    "self-authored zero_diff must not buy an exemption",
  );
  assert.deepEqual(kinds(calls), ["sdd_fidelity_empty_diff"]);
  assert.equal(calls.agent.length, 2);
});

test("Tier 0: collateral (unclaimed) edits -> soft log, no halt", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      (s) => {
        s.porcelain = " M scripts/x.py\n M scripts/EXTRA.py\n";
        return { status: "DONE", changed_files: ["scripts/x.py"] };
      },
    ],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: ["scripts/x.py"] },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.deepEqual(kinds(calls), []);
  assert.ok(logged(calls, "scripts/EXTRA.py"));
  assert.ok(logged(calls, "scope creep"));
});

test("Tier 0: partial coverage -> soft log, no halt", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      (s) => {
        s.porcelain = " M scripts/x.py\n";
        return { status: "DONE", changed_files: ["scripts/x.py"] };
      },
    ],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: ["scripts/x.py", "scripts/y.py"] },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.ok(logged(calls, "scripts/y.py"));
  assert.ok(logged(calls, "partial implementation"));
});

test("[REGRESSION] Tier 0: non-git host -> skip cleanly, no throw, no halt", async () => {
  const { deps, calls } = makeDeps({
    git: { isRepo: false },
    agentQueue: [{ status: "DONE", changed_files: ["whatever.py"] }],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: ["whatever.py"] },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.ok(logged(calls, "not applicable"));
  assert.deepEqual(kinds(calls), []);
});

test("Tier 0: repo with no HEAD -> skip cleanly", async () => {
  const { deps, calls } = makeDeps({
    git: { hasHead: false },
    agentQueue: [{ status: "DONE", changed_files: [] }],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: ["x"] },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.deepEqual(kinds(calls), []);
});

test("Tier 0: non-DONE status -> no tree checks", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [{ status: "BLOCKED", changed_files: [] }],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: ["x"] },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.deepEqual(kinds(calls), []);
});

// --- Tier 1 ----------------------------------------------------------------
test("Tier 1: no verify_cmd -> pass", async () => {
  const { deps } = makeDeps();
  assert.equal((await runTier1({ task: { id: "t" }, deps })).halted, false);
});

test("Tier 1: verify_cmd passes -> no halt", async () => {
  const { deps, calls } = makeDeps({ cmdHandlers: { "pytest run": "" } });
  const r = await runTier1({
    task: { id: "t", verify_cmd: "pytest run" },
    deps,
  });
  assert.equal(r.halted, false);
  assert.deepEqual(kinds(calls), []);
});

test("Tier 1: verify_cmd fails -> halt verify_failed", async () => {
  const { deps, calls } = makeDeps({
    cmdHandlers: { "pytest run": new Error("1 failed") },
  });
  const r = await runTier1({
    task: { id: "t", verify_cmd: "pytest run" },
    deps,
  });
  assert.equal(r.halted, true);
  assert.deepEqual(kinds(calls), ["sdd_fidelity_verify_failed"]);
});

// --- Tier 2 ----------------------------------------------------------------
test("Tier 2 before: check fails (red) -> pass (discriminating)", async () => {
  const { deps } = makeDeps({ cmdHandlers: { redcheck: new Error("red") } });
  const r = await runTier2Before({
    task: { id: "t", red_green: { before: "redcheck", after: "x" } },
    deps,
  });
  assert.equal(r.halted, false);
});

test("Tier 2 before: check already green -> halt baseline_not_red", async () => {
  const { deps, calls } = makeDeps({ cmdHandlers: { greencheck: "" } });
  const r = await runTier2Before({
    task: { id: "t", red_green: { before: "greencheck", after: "x" } },
    deps,
  });
  assert.equal(r.halted, true);
  assert.deepEqual(kinds(calls), ["sdd_fidelity_baseline_not_red"]);
});

test("Tier 2 after: green -> pass; still red -> halt not_green", async () => {
  const ok = makeDeps({ cmdHandlers: { aftercheck: "" } });
  assert.equal(
    (
      await runTier2After({
        task: { id: "t", red_green: { before: "x", after: "aftercheck" } },
        deps: ok.deps,
      })
    ).halted,
    false,
  );
  const bad = makeDeps({ cmdHandlers: { aftercheck: new Error("still red") } });
  const r = await runTier2After({
    task: { id: "t", red_green: { before: "x", after: "aftercheck" } },
    deps: bad.deps,
  });
  assert.equal(r.halted, true);
  assert.deepEqual(kinds(bad.calls), ["sdd_fidelity_not_green"]);
});

// --- Reviewer gate ---------------------------------------------------------
test("Reviewer: initial non-concur -> returns immediately, no checks", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      { verdict: "concerns", findings: [{ severity: "error", message: "x" }] },
    ],
  });
  const r = await runReviewerGate({
    task: { id: "t" },
    specReviewerPrompt: "rev",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.equal(calls.agent.length, 1);
  assert.deepEqual(kinds(calls), []);
});

test("[REGRESSION] Reviewer: concur + low_confidence -> halt (no rubber-stamp lane)", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [{ verdict: "concur", findings: [], low_confidence: true }],
  });
  const r = await runReviewerGate({
    task: { id: "t" },
    specReviewerPrompt: "rev",
    schema: {},
    deps,
  });
  assert.equal(r.halted, true);
  assert.deepEqual(kinds(calls), [
    "sdd_fidelity_reviewer_low_confidence_concur",
  ]);
});

test("Reviewer: concur, missing findings -> retry supplies findings -> pass", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [{ verdict: "concur" }, { verdict: "concur", findings: [] }],
  });
  const r = await runReviewerGate({
    task: { id: "t" },
    specReviewerPrompt: "rev",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.equal(calls.agent.length, 2);
});

test("Reviewer: concur, missing findings twice -> halt missing_findings", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [{ verdict: "concur" }, { verdict: "concur" }],
  });
  const r = await runReviewerGate({
    task: { id: "t" },
    specReviewerPrompt: "rev",
    schema: {},
    deps,
  });
  assert.equal(r.halted, true);
  assert.deepEqual(kinds(calls), ["sdd_fidelity_reviewer_missing_findings"]);
});

test("[REGRESSION] Reviewer (a): missing-findings retry flips to concerns -> not halted, not silently passed-as-concur", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      { verdict: "concur" },
      {
        verdict: "concerns",
        findings: [{ severity: "error", message: "real" }],
      },
    ],
  });
  const r = await runReviewerGate({
    task: { id: "t" },
    specReviewerPrompt: "rev",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.equal(r.reviewReport.verdict, "concerns");
  assert.deepEqual(kinds(calls), []);
});

test("Reviewer (b): evidence shows declared target -> pass", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      { verdict: "concur", findings: [], evidence: { files_read: ["f.py"] } },
    ],
  });
  const r = await runReviewerGate({
    task: { id: "t", review_targets: ["f.py"] },
    specReviewerPrompt: "rev",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.equal(calls.agent.length, 1);
});

test("Reviewer (b): no evidence -> retry supplies evidence -> pass", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      { verdict: "concur", findings: [], evidence: { files_read: [] } },
      { verdict: "concur", findings: [], evidence: { files_read: ["f.py"] } },
    ],
  });
  const r = await runReviewerGate({
    task: { id: "t", review_targets: ["f.py"] },
    specReviewerPrompt: "rev",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.equal(calls.agent.length, 2);
});

test("Reviewer (b): no evidence twice (still concur) -> halt no_evidence", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      { verdict: "concur", findings: [], evidence: { files_read: [] } },
      { verdict: "concur", findings: [], evidence: { files_read: [] } },
    ],
  });
  const r = await runReviewerGate({
    task: { id: "t", review_targets: ["f.py"] },
    specReviewerPrompt: "rev",
    schema: {},
    deps,
  });
  assert.equal(r.halted, true);
  assert.deepEqual(kinds(calls), ["sdd_fidelity_reviewer_no_evidence"]);
});

test("[REGRESSION] Reviewer (b): evidence-retry flips to concerns -> not halted, not silently passed (branch-b fall-through)", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      { verdict: "concur", findings: [], evidence: { files_read: [] } },
      {
        verdict: "concerns",
        findings: [{ severity: "error", message: "real" }],
      },
    ],
  });
  const r = await runReviewerGate({
    task: { id: "t", review_targets: ["f.py"] },
    specReviewerPrompt: "rev",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.equal(r.reviewReport.verdict, "concerns");
  assert.deepEqual(kinds(calls), []);
});

test("[REGRESSION] Reviewer (b): evidence-retry concur but missing findings -> halt missing_findings", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      { verdict: "concur", findings: [], evidence: { files_read: [] } },
      { verdict: "concur", evidence: { files_read: ["f.py"] } }, // findings dropped
    ],
  });
  const r = await runReviewerGate({
    task: { id: "t", review_targets: ["f.py"] },
    specReviewerPrompt: "rev",
    schema: {},
    deps,
  });
  assert.equal(r.halted, true);
  assert.deepEqual(kinds(calls), ["sdd_fidelity_reviewer_missing_findings"]);
});

// --- full ladder composition ----------------------------------------------
test("[REGRESSION] Ladder: red_green.before runs BEFORE the implementer dispatch", async () => {
  // before is already green -> must halt at tier2_before, implementer never dispatched.
  const { deps, calls } = makeDeps({
    cmdHandlers: { beforecheck: "" }, // green pre-implementation
    agentQueue: [], // if the implementer is dispatched, agent() throws (empty queue)
  });
  const r = await runFidelityLadder({
    task: {
      id: "t",
      expected_touch_paths: ["x"],
      red_green: { before: "beforecheck", after: "y" },
    },
    implementerPrompt: "impl",
    specReviewerPrompt: "rev",
    implementerSchema: {},
    reviewerSchema: {},
    deps,
  });
  assert.equal(r.halted, true);
  assert.equal(r.stage, "tier2_before");
  assert.equal(
    calls.agent.length,
    0,
    "implementer must not run before red baseline is proven",
  );
});

test("Ladder: full green path through all tiers + reviewer", async () => {
  const { deps } = makeDeps({
    cmdHandlers: {
      beforecheck: new Error("red"), // discriminating
      verifycheck: "", // consumer tool passes
      aftercheck: "", // now green
    },
    agentQueue: [
      (s) => {
        s.porcelain = " M scripts/x.py\n";
        return { status: "DONE", changed_files: ["scripts/x.py"] };
      },
      {
        verdict: "concur",
        findings: [],
        evidence: { files_read: ["scripts/x.py"] },
      },
    ],
  });
  const r = await runFidelityLadder({
    task: {
      id: "t",
      expected_touch_paths: ["scripts/x.py"],
      verify_cmd: "verifycheck",
      red_green: { before: "beforecheck", after: "aftercheck" },
      review_targets: ["scripts/x.py"],
    },
    implementerPrompt: "impl",
    specReviewerPrompt: "rev",
    implementerSchema: {},
    reviewerSchema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.equal(r.report.status, "DONE");
  assert.equal(r.reviewReport.verdict, "concur");
  assert.equal(r.concurred, true, "all-green ladder must signal concurred");
});

// --- DONE_WITH_CONCERNS engages Tier 0 (status-guard coverage) --------------
test("[REGRESSION] Tier 0: DONE_WITH_CONCERNS no-op twice -> halt empty_diff (gate engages for that status)", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      { status: "DONE_WITH_CONCERNS", changed_files: [] },
      { status: "DONE_WITH_CONCERNS", changed_files: [] },
    ],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: ["scripts/x.py"] },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(
    r.halted,
    true,
    "DONE_WITH_CONCERNS must not bypass Tier 0 no-op",
  );
  assert.deepEqual(kinds(calls), ["sdd_fidelity_empty_diff"]);
  assert.equal(calls.agent.length, 2);
});

test("[REGRESSION] Tier 0: DONE_WITH_CONCERNS claim_mismatch -> halt (gate engages for that status)", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      (s) => {
        s.porcelain = " M scripts/x.py\n";
        return {
          status: "DONE_WITH_CONCERNS",
          changed_files: ["scripts/x.py", "scripts/PHANTOM.py"],
        };
      },
    ],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: ["scripts/x.py"] },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, true);
  assert.deepEqual(kinds(calls), ["sdd_fidelity_claim_mismatch"]);
  assert.deepEqual(calls.halt[0].phantom, ["scripts/PHANTOM.py"]);
});

// --- Tier 0 baseline subtraction + committed union (mutation coverage) ------
test("[REGRESSION] Tier 0: prior-dirty baseline path + no-op -> still halts empty_diff (baseline IS subtracted)", async () => {
  // scripts/x.py is dirty BEFORE dispatch (a prior task). The implementer no-ops.
  // If the baseline were not subtracted, the stale dirt would mask the no-op.
  const { deps, calls } = makeDeps({
    git: { porcelain: " M scripts/x.py\n" },
    agentQueue: [
      { status: "DONE", changed_files: [] },
      { status: "DONE", changed_files: [] },
    ],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: ["scripts/x.py"] },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, true, "stale baseline dirt must not mask a no-op");
  assert.deepEqual(kinds(calls), ["sdd_fidelity_empty_diff"]);
  assert.equal(calls.agent.length, 2);
});

test("[REGRESSION] Tier 0: implementer commits (clean tree, committed-in-window) -> no halt (committed union wired)", async () => {
  // porcelain is clean but the expected path was committed in-window. If the
  // committed union were dropped, observed would be empty and Tier 0 would retry.
  const { deps, calls } = makeDeps({
    git: { porcelain: "", committed: "scripts/x.py\n" },
    agentQueue: [{ status: "DONE", changed_files: ["scripts/x.py"] }],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: ["scripts/x.py"] },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.deepEqual(kinds(calls), []);
  assert.equal(
    calls.agent.length,
    1,
    "committed work must not trigger a retry",
  );
});

// --- Tier 0 worktree threading (git -C target) -----------------------------
test("[REGRESSION] Tier 0: task.worktree threads into git -C <worktree>", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      (s) => {
        s.porcelain = " M scripts/x.py\n";
        return { status: "DONE", changed_files: ["scripts/x.py"] };
      },
    ],
  });
  const r = await runImplementerWithTier0({
    task: {
      id: "t",
      expected_touch_paths: ["scripts/x.py"],
      worktree: "/wt/impl-a",
    },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.ok(
    calls.bash.some((c) => c.includes('git -C "/wt/impl-a"')),
    "every git call must target the implementer's worktree",
  );
  assert.equal(
    calls.bash.some((c) => c.includes('git -C "."')),
    false,
    "must not fall back to the orchestrator tree when worktree is set",
  );
});

// --- Tier 0 empty expected: phantom check still runs ------------------------
test("[REGRESSION] Tier 0: empty expected_touch_paths but real phantom -> claim_mismatch (block b independent of no-op block)", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      (s) => {
        s.porcelain = " M a.py\n";
        return { status: "DONE", changed_files: ["a.py", "PHANTOM.py"] };
      },
    ],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: [] },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, true);
  assert.deepEqual(kinds(calls), ["sdd_fidelity_claim_mismatch"]);
  assert.deepEqual(calls.halt[0].phantom, ["PHANTOM.py"]);
});

// --- Tier 0 collateral guard: claimed.size > 0 half ------------------------
test("Tier 0: collateral on disk but empty claimed -> NO scope-creep log (claimed.size guard)", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      (s) => {
        s.porcelain = " M a.py\n M EXTRA.py\n";
        return { status: "DONE", changed_files: [] }; // claims nothing
      },
    ],
  });
  const r = await runImplementerWithTier0({
    task: { id: "t", expected_touch_paths: ["a.py"] },
    implementerPrompt: "do it",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.equal(
    logged(calls, "scope creep"),
    false,
    "no scope-creep log when nothing was claimed",
  );
});

// --- Tier 2 absent red_green (guard coverage) ------------------------------
test("Tier 2: absent red_green -> before/after both no-op, no bash invoked", async () => {
  const before = makeDeps();
  const rb = await runTier2Before({ task: { id: "t" }, deps: before.deps });
  assert.equal(rb.halted, false);
  assert.equal(before.calls.bash.length, 0, "before must not run any command");

  const after = makeDeps();
  const ra = await runTier2After({ task: { id: "t" }, deps: after.deps });
  assert.equal(ra.halted, false);
  assert.equal(after.calls.bash.length, 0, "after must not run any command");
});

// --- Reviewer: non-array truthy findings treated as missing ----------------
test("[REGRESSION] Reviewer: findings:{} (non-array truthy) treated as missing -> retry (Array.isArray strictness)", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      { verdict: "concur", findings: {} }, // truthy but not an array
      { verdict: "concur", findings: [] },
    ],
  });
  const r = await runReviewerGate({
    task: { id: "t" },
    specReviewerPrompt: "rev",
    schema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.equal(
    calls.agent.length,
    2,
    "a non-array findings value must trigger the missing-findings retry",
  );
});

// --- Reviewer: retry flips to low_confidence (the retry-path hole) ----------
test("[REGRESSION] Reviewer (a): findings-retry returns concur+low_confidence -> halt (re-checked on retry)", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      { verdict: "concur" }, // missing findings -> retry
      { verdict: "concur", findings: [], low_confidence: true }, // flips low_confidence
    ],
  });
  const r = await runReviewerGate({
    task: { id: "t" },
    specReviewerPrompt: "rev",
    schema: {},
    deps,
  });
  assert.equal(
    r.halted,
    true,
    "a retry that flips to low_confidence must halt",
  );
  assert.deepEqual(kinds(calls), [
    "sdd_fidelity_reviewer_low_confidence_concur",
  ]);
  assert.equal(calls.agent.length, 2);
});

test("[REGRESSION] Reviewer (b): evidence-retry returns concur+low_confidence -> halt (re-checked on retry)", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [
      { verdict: "concur", findings: [], evidence: { files_read: [] } },
      {
        verdict: "concur",
        findings: [],
        evidence: { files_read: ["f.py"] },
        low_confidence: true,
      },
    ],
  });
  const r = await runReviewerGate({
    task: { id: "t", review_targets: ["f.py"] },
    specReviewerPrompt: "rev",
    schema: {},
    deps,
  });
  assert.equal(r.halted, true);
  assert.deepEqual(kinds(calls), [
    "sdd_fidelity_reviewer_low_confidence_concur",
  ]);
  assert.equal(calls.agent.length, 2);
});

// --- Ladder: every halt branch propagates with the right stage -------------
test("[REGRESSION] Ladder: tier0 empty_diff halts at stage 'tier0'", async () => {
  const { deps } = makeDeps({
    agentQueue: [
      { status: "DONE", changed_files: [] },
      { status: "DONE", changed_files: [] },
    ],
  });
  const r = await runFidelityLadder({
    task: { id: "t", expected_touch_paths: ["x.py"] },
    implementerPrompt: "impl",
    specReviewerPrompt: "rev",
    implementerSchema: {},
    reviewerSchema: {},
    deps,
  });
  assert.equal(r.halted, true);
  assert.equal(r.stage, "tier0");
  assert.equal(r.report.status, "DONE");
});

test("[REGRESSION] Ladder: tier1 verify failure halts at stage 'tier1'", async () => {
  const { deps } = makeDeps({
    cmdHandlers: { verifycheck: new Error("verify failed") },
    agentQueue: [
      (s) => {
        s.porcelain = " M x.py\n";
        return { status: "DONE", changed_files: ["x.py"] };
      },
    ],
  });
  const r = await runFidelityLadder({
    task: {
      id: "t",
      expected_touch_paths: ["x.py"],
      verify_cmd: "verifycheck",
    },
    implementerPrompt: "impl",
    specReviewerPrompt: "rev",
    implementerSchema: {},
    reviewerSchema: {},
    deps,
  });
  assert.equal(r.halted, true);
  assert.equal(r.stage, "tier1");
});

test("[REGRESSION] Ladder: tier2_after still-red halts at stage 'tier2_after'", async () => {
  const { deps } = makeDeps({
    cmdHandlers: {
      redcheck: new Error("red"), // discriminating before
      aftercheck: new Error("still red"), // never goes green
    },
    agentQueue: [
      (s) => {
        s.porcelain = " M x.py\n";
        return { status: "DONE", changed_files: ["x.py"] };
      },
    ],
  });
  const r = await runFidelityLadder({
    task: {
      id: "t",
      expected_touch_paths: ["x.py"],
      red_green: { before: "redcheck", after: "aftercheck" },
    },
    implementerPrompt: "impl",
    specReviewerPrompt: "rev",
    implementerSchema: {},
    reviewerSchema: {},
    deps,
  });
  assert.equal(r.halted, true);
  assert.equal(r.stage, "tier2_after");
});

test("[REGRESSION] Ladder: reviewer low_confidence halts at stage 'reviewer'", async () => {
  const { deps } = makeDeps({
    agentQueue: [
      (s) => {
        s.porcelain = " M x.py\n";
        return { status: "DONE", changed_files: ["x.py"] };
      },
      { verdict: "concur", findings: [], low_confidence: true },
    ],
  });
  const r = await runFidelityLadder({
    task: { id: "t", expected_touch_paths: ["x.py"] },
    implementerPrompt: "impl",
    specReviewerPrompt: "rev",
    implementerSchema: {},
    reviewerSchema: {},
    deps,
  });
  assert.equal(r.halted, true);
  assert.equal(r.stage, "reviewer");
  assert.equal(r.reviewReport.verdict, "concur");
});

// --- Ladder: non-halt-but-not-pass paths (concurred contract) --------------
test("[REGRESSION] Ladder: BLOCKED implementer -> no reviewer dispatch, concurred:false, stage 'implementer_incomplete'", async () => {
  const { deps, calls } = makeDeps({
    agentQueue: [{ status: "BLOCKED", changed_files: [] }],
  });
  const r = await runFidelityLadder({
    task: { id: "t", expected_touch_paths: ["x.py"] },
    implementerPrompt: "impl",
    specReviewerPrompt: "rev",
    implementerSchema: {},
    reviewerSchema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.equal(r.stage, "implementer_incomplete");
  assert.equal(r.concurred, false);
  assert.equal(
    calls.agent.length,
    1,
    "reviewer must NOT run against a tree the implementer never touched",
  );
});

test("[REGRESSION] Ladder: reviewer 'concerns' -> halted:false but concurred:false (not a task pass)", async () => {
  const { deps } = makeDeps({
    agentQueue: [
      (s) => {
        s.porcelain = " M x.py\n";
        return { status: "DONE", changed_files: ["x.py"] };
      },
      { verdict: "concerns", findings: [{ severity: "error", message: "x" }] },
    ],
  });
  const r = await runFidelityLadder({
    task: { id: "t", expected_touch_paths: ["x.py"] },
    implementerPrompt: "impl",
    specReviewerPrompt: "rev",
    implementerSchema: {},
    reviewerSchema: {},
    deps,
  });
  assert.equal(r.halted, false);
  assert.equal(r.concurred, false, "a concerns verdict is NOT a pass");
  assert.equal(r.reviewReport.verdict, "concerns");
});
