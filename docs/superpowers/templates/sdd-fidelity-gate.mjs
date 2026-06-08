// SDD fidelity — the verification ladder, canonical tested implementation.
//
// This is the EXECUTABLE source of truth for the gate logic documented in
// `sdd-fidelity-gate.md`. The markdown mirrors this gate LOGIC as inline per-tier
// snippets (it does NOT reproduce the composed runner functions — those are the
// module's public API: runImplementerWithTier0 / runTier1 / runTier2Before /
// runTier2After / runReviewerGate / runFidelityLadder). The halt `kind` strings
// and the shared pure-helper names are kept in sync by
// `tests/templates/test_sdd_fidelity_gate_template_sync.py`, and the behaviour is
// unit-tested in `sdd-fidelity-gate.test.mjs` (run via
// `tests/templates/test_sdd_fidelity_gate_node.py` or `node --test`).
//
// Everything is dependency-injected so it runs under `node:test` with fakes and,
// unchanged, inside an inline Workflow script. `deps`:
//   bash(cmd)         -> Promise<string> stdout; THROWS on non-zero exit
//   agent(prompt,opts)-> Promise<object> structured report
//   log(msg)          -> void
//   halt(payload)     -> void  (terminal in production; callers return immediately after)
//
// Each gate returns { halted: boolean, ... }. The caller stops the task on the
// first { halted: true }. `halt` is invoked exactly once before such a return.

export function expectedHit(p, expected) {
  // Path-segment-boundary prefix match. "src" matches "src" and "src/x", NOT "src2/x".
  return [...expected].some((e) => p === e || p.startsWith(e + "/"));
}

export async function gitReady(bash, tree) {
  // Non-git host or a repo with no commits → Tier 0 not applicable (skip, never throw).
  try {
    await bash(`git -C "${tree}" rev-parse --is-inside-work-tree`);
    await bash(`git -C "${tree}" rev-parse --verify HEAD`);
    return true;
  } catch {
    return false;
  }
}

export async function dirtyPaths(bash, tree) {
  // Repo-root-relative, rename/copy-aware set of currently-dirty paths.
  const porcelain = await bash(`git -C "${tree}" status --porcelain`);
  const out = new Set();
  for (const l of porcelain.split("\n").filter(Boolean)) {
    const body = l.slice(3); // strip 2-char status code + separating space
    const arrow = body.indexOf(" -> "); // rename/copy renders as "old -> new"
    if (arrow >= 0) {
      out.add(body.slice(0, arrow).trim()); // old path (rename source)
      out.add(body.slice(arrow + 4).trim()); // new path (rename dest)
    } else {
      out.add(body.trim());
    }
  }
  return out;
}

export async function committedSince(bash, tree, sinceTs) {
  // Paths committed in the dispatch window (covers the commit-then-clean-tree case).
  const recent = await bash(
    `git -C "${tree}" log --since="${sinceTs}" --name-only --pretty=format:`,
  );
  return new Set(
    recent
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean),
  );
}

export async function observedForTask(bash, tree, baselineDirty, sinceTs) {
  // Task-attributed observed set: newly-dirty (∖ baseline) ∪ committed-in-window.
  const dirtyNow = await dirtyPaths(bash, tree);
  const newlyDirty = [...dirtyNow].filter((p) => !baselineDirty.has(p));
  const committed = await committedSince(bash, tree, sinceTs);
  return new Set([...newlyDirty, ...committed]);
}

// Tier 0 — always on. Dispatches the implementer and verifies the on-disk delta.
// Returns { report, observed, halted }. `report` is the authoritative (possibly
// retried) implementer report for downstream tiers.
export async function runImplementerWithTier0({
  task,
  implementerPrompt,
  schema,
  deps,
}) {
  const { bash, agent, log, halt } = deps;
  const TREE = task.worktree || ".";
  const tier0Ok = await gitReady(bash, TREE);
  if (!tier0Ok) {
    log(
      `SDD fidelity: no git / no HEAD at ${TREE} — Tier 0 not applicable for ${task.id}; relying on Tier 1/2 + reviewer.`,
    );
  }

  // Baseline BEFORE dispatch — porcelain otherwise reports ALL uncommitted changes,
  // including a prior task's, which would mask this task's no-op.
  const dispatchTs = (await bash("date -u +%Y-%m-%dT%H:%M:%SZ")).trim();
  const baselineDirty = tier0Ok ? await dirtyPaths(bash, TREE) : new Set();

  let report = await agent(implementerPrompt, {
    label: `impl:${task.id}`,
    schema,
  });

  if (
    tier0Ok &&
    (report.status === "DONE" || report.status === "DONE_WITH_CONCERNS")
  ) {
    let observed = await observedForTask(bash, TREE, baselineDirty, dispatchTs);
    const expected = new Set(task.expected_touch_paths || []);

    if (expected.size === 0) {
      log(
        `SDD fidelity: task ${task.id} declares no expected_touch_paths — Tier 0 no-op check disabled (declare the floor to enable it).`,
      );
    } else {
      let overlap = [...observed].filter((p) => expectedHit(p, expected));

      // (a) NO-OP — only task.zero_diff_allowed (PLAN-authored) exempts.
      if (overlap.length === 0 && !task.zero_diff_allowed) {
        log(
          `SDD fidelity: ${report.status} but no edits to ${[...expected].join(", ")}. Re-dispatching once.`,
        );
        const retryPrompt = `${implementerPrompt}\n\n---\n\nGATE-FEEDBACK: status="${report.status}" but the on-disk diff is empty for: ${[...expected].join(", ")}. Re-execute the task and produce ACTUAL file edits. If this task genuinely needs zero diff, do NOT self-exempt — return status="NEEDS_CONTEXT" with an explanation so a human can mark it zero-diff in the plan.`;
        report = await agent(retryPrompt, {
          label: `impl-retry:${task.id}`,
          schema,
        });
        observed = await observedForTask(bash, TREE, baselineDirty, dispatchTs); // REFRESH
        overlap = [...observed].filter((p) => expectedHit(p, expected));
        if (overlap.length === 0 && !task.zero_diff_allowed) {
          halt({
            kind: "sdd_fidelity_empty_diff",
            task: task.id,
            expected: [...expected],
            observed: [...observed],
            message:
              "Implementer reported DONE twice without on-disk evidence. Manual investigation required.",
          });
          return { report, observed, halted: true };
        }
      }

      // (a') PARTIAL-COVERAGE — soft warning (never a halt).
      const uncovered = [...expected].filter(
        (e) => ![...observed].some((p) => p === e || p.startsWith(e + "/")),
      );
      if (uncovered.length > 0 && !task.zero_diff_allowed) {
        log(
          `SDD fidelity: ${task.id} left expected paths untouched: ${uncovered.join(", ")} (partial implementation — review).`,
        );
      }
    }

    // (b) CLAIMED-vs-OBSERVED — against the authoritative report + refreshed observed.
    const claimed = new Set(report.changed_files || []);
    const phantom = [...claimed].filter((p) => !observed.has(p));
    if (phantom.length > 0) {
      halt({
        kind: "sdd_fidelity_claim_mismatch",
        task: task.id,
        claimed: [...claimed],
        observed: [...observed],
        phantom,
        message:
          "Implementer claimed changed_files absent from the git delta. Self-report contradicts on-disk state.",
      });
      return { report, observed, halted: true };
    }
    // collateral — soft warning. Reuses `expected` from above.
    const collateral = [...observed].filter(
      (p) => !claimed.has(p) && !expectedHit(p, expected),
    );
    if (claimed.size > 0 && collateral.length > 0) {
      log(
        `SDD fidelity: ${task.id} touched unclaimed paths: ${collateral.join(", ")} (scope creep — review).`,
      );
    }

    return { report, observed, halted: false };
  }

  return { report, observed: new Set(), halted: false };
}

export async function runTier1({ task, deps }) {
  const { bash, halt } = deps;
  if (!task.verify_cmd) return { halted: false };
  try {
    await bash(task.verify_cmd); // bash() throws on non-zero exit
    return { halted: false };
  } catch (e) {
    halt({
      kind: "sdd_fidelity_verify_failed",
      task: task.id,
      cmd: task.verify_cmd,
      error: String(e),
      message:
        "Consumer-tool verification failed: the tree changed but the change does not satisfy its contract.",
    });
    return { halted: true };
  }
}

export async function runTier2Before({ task, deps }) {
  const { bash, halt } = deps;
  if (!task.red_green) return { halted: false };
  let baselineRed = false;
  try {
    await bash(task.red_green.before);
  } catch {
    baselineRed = true; // CAVEAT: any non-zero exit reads as "red" (see md).
  }
  if (!baselineRed) {
    halt({
      kind: "sdd_fidelity_baseline_not_red",
      task: task.id,
      cmd: task.red_green.before,
      message:
        "red_green.before passed pre-implementation — the check does not discriminate this task's change (already green). Fix the check or the task scope before dispatching.",
    });
    return { halted: true };
  }
  return { halted: false };
}

export async function runTier2After({ task, deps }) {
  const { bash, halt } = deps;
  if (!task.red_green) return { halted: false };
  try {
    await bash(task.red_green.after);
    return { halted: false };
  } catch (e) {
    halt({
      kind: "sdd_fidelity_not_green",
      task: task.id,
      cmd: task.red_green.after,
      error: String(e),
      message:
        "red_green.after still fails after the implementer reported DONE.",
    });
    return { halted: true };
  }
}

// concur + low_confidence is contradictory — a low-confidence review cannot concur.
// Applied to EVERY reviewer report (initial AND each retry): a retry can flip a
// previously-confident concur into a low-confidence one, which must not slip through
// as a rubber-stamp lane. Returns true (and halts) when the contradiction is present.
function lowConfidenceConcurHalt(reviewReport, task, halt) {
  if (reviewReport.verdict === "concur" && reviewReport.low_confidence) {
    halt({
      kind: "sdd_fidelity_reviewer_low_confidence_concur",
      task: task.id,
      message:
        "Reviewer returned concur AND low_confidence — contradictory. Routing to human.",
    });
    return true;
  }
  return false;
}

export async function runReviewerGate({
  task,
  specReviewerPrompt,
  schema,
  deps,
}) {
  const { agent, log, halt } = deps;
  let reviewReport = await agent(specReviewerPrompt, {
    label: `spec-review:${task.id}`,
    schema,
  });

  if (reviewReport.verdict !== "concur") return { reviewReport, halted: false };

  // (0) concur + low_confidence is contradictory — checked on the initial report
  //     and re-checked after every retry below (a retry can flip to low_confidence).
  if (lowConfidenceConcurHalt(reviewReport, task, halt))
    return { reviewReport, halted: true };

  // (a) Structured findings present? Empty array OK; missing array = silent no-op.
  if (!Array.isArray(reviewReport.findings)) {
    log(
      `SDD fidelity: spec-reviewer returned concur but findings array is missing. Re-dispatching once.`,
    );
    reviewReport = await agent(
      `${specReviewerPrompt}\n\n---\n\nGATE-FEEDBACK: Your previous response returned verdict="concur" but did not include a structured "findings" array. Re-review and respond with findings: [] (no concerns) or findings: [...] (concerns). An empty array is fine; a missing one is not.`,
      { label: `spec-review-retry:${task.id}`, schema },
    );
    if (!Array.isArray(reviewReport.findings)) {
      halt({
        kind: "sdd_fidelity_reviewer_missing_findings",
        task: task.id,
        message:
          "Spec-reviewer returned concur twice without a structured findings array. Manual investigation required.",
      });
      return { reviewReport, halted: true };
    }
    if (reviewReport.verdict !== "concur")
      return { reviewReport, halted: false };
    // (0) re-applied: the findings-retry may have flipped to low_confidence.
    if (lowConfidenceConcurHalt(reviewReport, task, halt))
      return { reviewReport, halted: true };
  }

  // (b) Evidence of reading the declared targets — ADVISORY (self-authored).
  if (task.review_targets && task.review_targets.length > 0) {
    const evidenceTargets = new Set(reviewReport.evidence?.files_read || []);
    const declaredTargets = new Set(task.review_targets);
    const reviewed = [...declaredTargets].filter((t) => evidenceTargets.has(t));

    if (reviewed.length === 0) {
      log(
        `SDD fidelity: spec-reviewer returned concur but evidence.files_read shows none of the declared targets. Re-dispatching once.`,
      );
      reviewReport = await agent(
        `${specReviewerPrompt}\n\n---\n\nGATE-FEEDBACK: verdict="concur" but evidence.files_read shows none of the declared review targets: ${[...declaredTargets].join(", ")}. Re-review by actually opening those files and list them in evidence.files_read. If you genuinely cannot evaluate a target, return verdict="concerns" (not concur) and explain.`,
        { label: `spec-review-retry-evidence:${task.id}`, schema },
      );
      if (reviewReport.verdict !== "concur")
        return { reviewReport, halted: false }; // flipped — let the loop handle it
      // (0) re-applied: the evidence-retry may have flipped to low_confidence.
      if (lowConfidenceConcurHalt(reviewReport, task, halt))
        return { reviewReport, halted: true };
      if (!Array.isArray(reviewReport.findings)) {
        halt({
          kind: "sdd_fidelity_reviewer_missing_findings",
          task: task.id,
          message:
            "Spec-reviewer evidence-retry returned concur without a structured findings array. Manual investigation required.",
        });
        return { reviewReport, halted: true };
      }
      const retryEvidence = new Set(reviewReport.evidence?.files_read || []);
      const retryReviewed = [...declaredTargets].filter((t) =>
        retryEvidence.has(t),
      );
      if (retryReviewed.length === 0) {
        halt({
          kind: "sdd_fidelity_reviewer_no_evidence",
          task: task.id,
          declared: [...declaredTargets],
          observed: [...retryEvidence],
          message:
            "Spec-reviewer concurred twice without evidence of reading review targets. Manual investigation required.",
        });
        return { reviewReport, halted: true };
      }
    }
  }

  return { reviewReport, halted: false };
}

// Full ladder composition. Ordering is load-bearing: Tier 2 `before` asserts red
// PRE-dispatch; implementer+Tier 0 run; Tier 1; Tier 2 `after` asserts green;
// then the reviewer gate. Stops at the first halt.
//
// CALLER CONTRACT — a task is complete ONLY when `halted === false && concurred === true`.
// `halted === false` alone is NOT a pass: it is also returned when the reviewer
// verdict is non-concur (concerns/blocked) or the implementer did not finish
// (status BLOCKED/NEEDS_CONTEXT, surfaced as stage "implementer_incomplete").
// Gate task completion on `concurred`, never on `halted` alone.
export async function runFidelityLadder({
  task,
  implementerPrompt,
  specReviewerPrompt,
  implementerSchema,
  reviewerSchema,
  deps,
}) {
  const before = await runTier2Before({ task, deps });
  if (before.halted) return { halted: true, stage: "tier2_before" };

  const t0 = await runImplementerWithTier0({
    task,
    implementerPrompt,
    schema: implementerSchema,
    deps,
  });
  if (t0.halted) return { halted: true, stage: "tier0", report: t0.report };

  // Implementer did not complete — do NOT run Tier 1/2 or dispatch the reviewer
  // against an unchanged tree. On a Tier-0-only host the reviewer is the sole
  // correctness check and could "concur" on a no-op (the B11 mode). Surface the
  // incomplete status to the caller (not a pass: concurred === false).
  if (t0.report.status !== "DONE" && t0.report.status !== "DONE_WITH_CONCERNS")
    return {
      halted: false,
      stage: "implementer_incomplete",
      report: t0.report,
      concurred: false,
    };

  const t1 = await runTier1({ task, deps });
  if (t1.halted) return { halted: true, stage: "tier1", report: t0.report };

  const after = await runTier2After({ task, deps });
  if (after.halted)
    return { halted: true, stage: "tier2_after", report: t0.report };

  const rev = await runReviewerGate({
    task,
    specReviewerPrompt,
    schema: reviewerSchema,
    deps,
  });
  if (rev.halted)
    return {
      halted: true,
      stage: "reviewer",
      report: t0.report,
      reviewReport: rev.reviewReport,
    };

  return {
    halted: false,
    report: t0.report,
    observed: t0.observed,
    reviewReport: rev.reviewReport,
    // First-class pass signal: true only when the reviewer actually concurred.
    // A non-concur verdict returns halted:false here too — callers MUST key on this.
    concurred: rev.reviewReport?.verdict === "concur",
  };
}
