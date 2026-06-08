# SDD fidelity — the verification ladder (copy-pasteable JS for inline Workflow scripts)

**Status:** convention floor (CCE-92 umbrella, CCE-93 + CCE-94) until the upstream PR (CCE-95) to `obra/superpowers` lands.

**Tested implementation.** The canonical, executable version of every gate below lives in [`sdd-fidelity-gate.mjs`](./sdd-fidelity-gate.mjs) (dependency-injected; runs unchanged inside a Workflow script). It is unit-tested in [`sdd-fidelity-gate.test.mjs`](./sdd-fidelity-gate.test.mjs) — run `node --test docs/superpowers/templates/sdd-fidelity-gate.test.mjs`, or via the integrated suite `pytest tests/templates/test_sdd_fidelity_gate_node.py`. The snippets in this doc mirror that module; `tests/templates/test_sdd_fidelity_gate_template_sync.py` fails the build if the two drift (every `sdd_fidelity_*` outcome and shared helper must appear in both). Edit the `.mjs`, keep this doc in step.

**When to use:** any time you compose the superpowers Subagent-Driven Development pattern inline (a Workflow JS script that dispatches an implementer + spec-reviewer + code-quality-reviewer per task). The skill itself does not (yet) verify that subagent self-reports match on-disk state — this ladder closes that gap. The implementer is gated by Tier 0; the **spec-reviewer** is gated by the reviewer gate. The code-quality-reviewer is intentionally ungated here (it opines on already-verified work); gate it with the same reviewer-gate shape if your loop relies on it.

**Failure mode this prevents.** An implementer subagent returns `status: DONE`, no actual edits applied. The spec-reviewer then operates on the unchanged tree, sees nothing wrong, and passes. The orchestrator marks the task complete on phantom work. Real incident: 2026-06-04 B11 (this repo's CCE-77 ship-validator task), forensic patch at `~/.claude/orchestrator/detached-changes/B11.patch`.

**Root cause.** The reviewer validated _intent_ (is the plan sound?) without validating _execution_ (did the plan run?). LLM reviewers are tuned to judge semantic correctness — "is this code right?" — not process correctness — "did the action actually happen?". A spec that reads as valid earns `concur` even when no tool call ever touched the tree. So the fix cannot live inside any prompt — it has to be a mechanical check against authority the subagent cannot author.

---

## The organizing principle: authority externality

Rank every check by **who authored the evidence it trusts**:

- **Self-authored** (model prose, model JSON) — improvable, never sound. A confident model emits plausible prose _and_ plausible JSON _and_ a plausible "yes I did that."
- **External authority** (git state, a consumer tool's exit code, a tool-call log) — the subagent cannot fake it.

Two rules drive the whole ladder:

1. **Trust nothing the subagent authors about its own work.** Verify against artifacts it cannot fabricate. (This includes its `zero_diff_allowed` and `low_confidence` self-declarations — those are advisory, never an exemption the gate honors.)
2. **A structured field is trustworthy _iff_ it is a dereferenceable pointer to external state.** `changed_files` (diff against `git status`), `commit_sha` (check it out), `verify_cmd` (run it) are verifiable. `summary` and `evidence.files_read` are self-authored — advisory, never the sole basis for passing a gate.

---

## Declare-then-discharge: the ladder at a glance

The **plan declares**, per task, what "done" looks like externally. The **gate discharges** the strongest tier the task declares, mechanically, _before_ trusting any self-report.

| Tier                | Trigger                 | Evidence source          | Failure mode it closes                             |
| ------------------- | ----------------------- | ------------------------ | -------------------------------------------------- |
| **0** (always)      | —                       | git (external)           | _no-op_ + implementer over-claiming changed files  |
| **1** (if declared) | `task.verify_cmd`       | consumer tool (external) | _wrong-op_ (changed the file, change invalid)      |
| **2** (if declared) | `task.red_green`        | discriminating check     | _no-op_ + _wrong-op_ + "it was already green"      |
| **reviewer**        | after `verdict: concur` | structured findings      | reviewer rubber-stamp (LAZY reviewer; see caveats) |

**The tiers differ by host-requirement and cost, not by orthogonal failure modes** — Tier 2 subsumes Tier 0's no-op coverage when it can run. The reason to **ship Tier 0 first** is _universality_: it needs only git, so it is the one tier every host can run, and it independently closes the _no-op_ mode. It does **not** close the _didn't-look_ (reviewer rubber-stamp) mode — that needs the reviewer gate. Ship Tier 0 first; do not read "Tier 0 first" as "Tier 0 is enough."

**Graceful degradation _is_ the selection logic.** A bare host (no tests, no consumer tool) runs Tier 0 only — enough to catch the B11 no-op. A host with no git at all skips Tier 0 cleanly (logged, never thrown) and leans on Tiers 1–2 + the reviewer. A rich host lights up every tier from the same gate. **Important:** on a Tier-0-only host, "mechanically verified" means only "some bytes changed in an expected path" — there the reviewer is the _sole_ correctness check and must review at full rigor (see the reviewer gate).

**Composed entry point.** The `.mjs` exposes each tier as a function and composes them in `runFidelityLadder({task, implementerPrompt, specReviewerPrompt, ...})`, which runs `tier2.before → implementer+Tier 0 → Tier 1 → tier2.after → reviewer`, stopping at the first halt. Two caller contracts it enforces that the inline snippets below leave implicit:

- **A task passes only when `halted === false && concurred === true`.** `halted === false` alone is _not_ a pass — it is also returned when the reviewer verdict is non-concur, so callers MUST gate on `concurred`, never on `halted` alone.
- **A non-completing implementer short-circuits.** If the implementer returns `BLOCKED`/`NEEDS_CONTEXT`, the ladder returns immediately (stage `implementer_incomplete`, `concurred: false`) — it does **not** run Tiers 1–2 or dispatch the reviewer against an unchanged tree (on a Tier-0-only host that would reopen the B11 no-op-concur mode). The "insert after `status: DONE` / `verdict: concur`" framing in the per-tier sections below is exactly this gate.

---

## Preconditions & applicability

- **Execution model.** Tier 0 assumes the implementer edits the **same working tree** the orchestrator scans, **serially**. If you dispatch implementers under `isolation: 'worktree'` or in parallel (`superpowers:dispatching-parallel-agents`), point the helpers at the implementer's worktree via `task.worktree` (threaded into `git -C` below) — otherwise the orchestrator's tree shows an empty delta and Tier 0 false-halts honest work.
- **`halt()` must be terminal.** Each gate assumes `halt()` aborts the task. The snippets add an explicit `return` after every `halt()` as belt-and-suspenders; keep them if your host's `halt` records-and-returns rather than throwing.
- **No git / no commits → skip, never error.** Tier 0 is detected, not assumed (see `gitReady` below). A non-git host or a repo with no HEAD is a clean skip with a `log()`, per the plugin's degrade-gracefully mandate — not a thrown exception and not a halt.

---

## The task contract + schemas (declare these first)

These are defined once and referenced by every tier below. (Kept above the code so a copied tier block never hits an undefined symbol.)

```js
// Declared by the PLAN, per task. Only expected_touch_paths is needed for the Tier 0
// floor; the rest light up higher tiers where the host supports them.
const TASK_CONTRACT = {
  id: "string", // task id, used in labels + halt payloads
  expected_touch_paths: ["repo-root-relative paths or dir prefixes"], // Tier 0 floor; matched at path-segment boundaries (NOT globs)
  zero_diff_allowed: false, // Tier 0 opt-out — PLAN-authored only, never read from the implementer
  verify_cmd: "shell command", // Tier 1 — optional consumer tool
  red_green: { before: "shell cmd", after: "shell cmd" }, // Tier 2 — optional differential
  review_targets: ["repo-root-relative paths"], // reviewer gate — optional
  worktree: ".", // path the implementer edits; "." for the orchestrator tree
};

const IMPLEMENTER_SCHEMA = {
  type: "object",
  required: ["status", "changed_files"], // changed_files REQUIRED so the forensic check can't be dodged by omission
  properties: {
    status: {
      enum: ["DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED"],
    },
    summary: { type: "string" }, // advisory only — never a gate input
    changed_files: { type: "array", items: { type: "string" } }, // dereferenced in Tier 0(b)
    commit_sha: { type: "string" }, // dereferenceable: `git cat-file -e <sha>` + diff match
    test_cmd: { type: "string" },
    test_result: {
      type: "object",
      properties: { passed: { type: "integer" }, failed: { type: "integer" } },
    },
    // NOTE: no self-authored zero_diff_allowed. A genuinely zero-diff task returns
    // status="NEEDS_CONTEXT" so a HUMAN sets task.zero_diff_allowed in the plan.
  },
};

const SPEC_REVIEWER_SCHEMA = {
  type: "object",
  required: ["verdict", "findings"],
  properties: {
    verdict: { enum: ["concur", "concerns", "blocked"] },
    findings: {
      type: "array",
      items: {
        type: "object",
        required: ["severity", "message"],
        properties: {
          file: { type: "string" },
          line: { type: "integer" },
          severity: { enum: ["info", "warn", "error"] },
          message: { type: "string" },
        },
      },
    },
    evidence: {
      type: "object",
      properties: { files_read: { type: "array", items: { type: "string" } } },
    },
    low_confidence: { type: "boolean", default: false },
  },
};
```

`required: ["verdict","findings"]` only forces field _presence_, and only if `agent(prompt,{schema})` hard-enforces the schema. The empty-vs-missing _semantic_ is enforced by the JS gate below — the missing-`findings` retry branch is the fallback for orchestrators that do not hard-enforce schemas.

---

## Shared helpers

```js
// Detect git + HEAD once. Non-git host or no commits → Tier 0 not applicable.
async function gitReady(tree) {
  try {
    await bash(`git -C "${tree}" rev-parse --is-inside-work-tree`);
    await bash(`git -C "${tree}" rev-parse --verify HEAD`);
    return true;
  } catch {
    return false;
  }
}

// Repo-root-relative, rename-aware set of currently-dirty paths.
// Caveat: paths with special chars are C-quoted under core.quotepath; for full
// robustness switch to `status --porcelain -z` (NUL-delimited). ASCII-path common case here.
async function dirtyPaths(tree) {
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

// Paths committed in the dispatch window (covers the commit-then-clean-tree case).
async function committedSince(tree, sinceTs) {
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

// Path-segment-boundary prefix match. "src" matches "src" and "src/x", NOT "src2/x".
const expectedHit = (p, expected) =>
  [...expected].some((e) => p === e || p.startsWith(e + "/"));
```

---

## Tier 0 — always on (CCE-93)

Insert **after** the implementer returns `status: DONE` and **before** dispatching the spec-reviewer. The delta is attributed to _this_ task by diffing against a baseline captured _before_ dispatch (so a tree already dirty from a prior task can't mask a no-op).

```js
const TREE = task.worktree || ".";
const tier0Ok = await gitReady(TREE);
if (!tier0Ok) {
  log(
    `SDD fidelity: no git / no HEAD at ${TREE} — Tier 0 not applicable for ${task.id}; relying on Tier 1/2 + reviewer.`,
  );
}

// Baseline BEFORE dispatch — porcelain otherwise reports ALL uncommitted changes,
// including a prior task's, which would mask this task's no-op.
const dispatchTs = (await bash("date -u +%Y-%m-%dT%H:%M:%SZ")).trim(); // trim: bash() returns a trailing newline
const baselineDirty = tier0Ok ? await dirtyPaths(TREE) : new Set();

// Task-attributed observed set: newly-dirty (∖ baseline) ∪ committed-in-window.
async function observedForTask() {
  const dirtyNow = await dirtyPaths(TREE);
  const newlyDirty = [...dirtyNow].filter((p) => !baselineDirty.has(p));
  const committed = await committedSince(TREE, dispatchTs);
  return new Set([...newlyDirty, ...committed]);
}

// ASSEMBLY ORDER (canonical — see runFidelityLadder in the .mjs): if task.red_green is
// declared, its `before` check (Tier 2) runs FIRST — ahead of the baseline capture above
// AND this dispatch. It asserts red against the pre-implementation tree; running it before
// the baseline also folds any file it touches into baselineDirty, so a read-only `before`
// is subtracted out of `observed` and cannot pollute Tier 0.
const implReport = await agent(implementerPrompt, {
  label: `impl:${task.id}`,
  schema: IMPLEMENTER_SCHEMA,
});

if (
  tier0Ok &&
  (implReport.status === "DONE" || implReport.status === "DONE_WITH_CONCERNS")
) {
  let report = implReport; // becomes the retry report if we re-dispatch
  let observed = await observedForTask();
  const expected = new Set(task.expected_touch_paths || []);

  if (expected.size === 0) {
    // No declared floor → the no-op check cannot run meaningfully. Don't route this
    // through the empty-diff halt (which would false-fire on correct work).
    log(
      `SDD fidelity: task ${task.id} declares no expected_touch_paths — Tier 0 no-op check disabled (declare the floor to enable it).`,
    );
  } else {
    let overlap = [...observed].filter((p) => expectedHit(p, expected));

    // (a) NO-OP — only task.zero_diff_allowed (PLAN-authored) exempts.
    if (overlap.length === 0 && !task.zero_diff_allowed) {
      log(
        `SDD fidelity: ${implReport.status} but no edits to ${[...expected].join(", ")}. Re-dispatching once.`,
      );

      const retryPrompt = `${implementerPrompt}\n\n---\n\nGATE-FEEDBACK: status="${implReport.status}" but the on-disk diff is empty for: ${[...expected].join(", ")}. Re-execute the task and produce ACTUAL file edits. If this task genuinely needs zero diff, do NOT self-exempt — return status="NEEDS_CONTEXT" with an explanation so a human can mark it zero-diff in the plan.`;

      report = await agent(retryPrompt, {
        label: `impl-retry:${task.id}`,
        schema: IMPLEMENTER_SCHEMA,
      });
      observed = await observedForTask(); // REFRESH — do not reuse the pre-retry snapshot
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
        return;
      }
    }

    // (a') PARTIAL-COVERAGE — soft. Warn (don't halt) if some expected prefixes saw no edit.
    const uncovered = [...expected].filter(
      (e) => ![...observed].some((p) => p === e || p.startsWith(e + "/")),
    );
    if (uncovered.length > 0 && !task.zero_diff_allowed) {
      log(
        `SDD fidelity: ${task.id} left expected paths untouched: ${uncovered.join(", ")} (partial implementation — review).`,
      );
    }
  }

  // (b) CLAIMED-vs-OBSERVED — bidirectional, against the AUTHORITATIVE report + REFRESHED observed.
  const claimed = new Set(report.changed_files || []);
  const phantom = [...claimed].filter((p) => !observed.has(p)); // claimed but absent on disk
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
    return;
  }
  // collateral — soft. Edits on disk the implementer didn't claim (and outside the floor): log for scope review.
  // Reuses `expected` declared at the top of this block.
  const collateral = [...observed].filter(
    (p) => !claimed.has(p) && !expectedHit(p, expected),
  );
  if (claimed.size > 0 && collateral.length > 0) {
    log(
      `SDD fidelity: ${task.id} touched unclaimed paths: ${collateral.join(", ")} (scope creep — review).`,
    );
  }
}
```

**What Tier 0 catches, precisely:** _no-op_ (nothing changed in the floor) via the bidirectional baseline diff, and _over-claim_ (the implementer's `changed_files` lists a path the git delta does not show) via block (b). It does **not** prove the change is _correct_ (that's Tier 1/2) and does not catch a _destructive-op_ where a deletion satisfies a content-must-exist floor — declare `verify_cmd`/`red_green` for those. The claimed-vs-observed check uses only git, no harness tool-call log — but it is cooperation-dependent (it inspects a field the implementer fills) and one-directional on halt (collateral is a soft warning, not a block).

---

## Tier 1 — consumer-tool verification (runs only if `task.verify_cmd` is declared)

Tier 0 proves _something_ changed. Tier 1 proves the change is _valid_ — by running the real tool that consumes the artifact (`mkdocs build --strict`, `npx tsc --noEmit`, `pytest tests/x`, `ajv validate`). This is the repo's "verify with the actual consumer tool, not `test -f`" invariant applied per-task.

```js
if (task.verify_cmd) {
  try {
    await bash(task.verify_cmd); // bash() throws on non-zero exit
  } catch (e) {
    halt({
      kind: "sdd_fidelity_verify_failed",
      task: task.id,
      cmd: task.verify_cmd,
      error: String(e),
      message:
        "Consumer-tool verification failed: the tree changed but the change does not satisfy its contract.",
    });
    return;
  }
}
```

**Coverage limit:** not every task has a cheap, deterministic consumer (a prose decision, a config tweak). Those stay at Tier 0 — which still catches the no-op. Declare `verify_cmd` only where a real consumer exists.

---

## Tier 2 — red→green differential (runs only if `task.red_green` is declared)

The strongest _generic_ correctness check that needs no bespoke consumer: a discriminating check that **must fail before** implementation and **must pass after**. Defeats no-op, wrong-op, _and_ the "it was already green, so `concur` is technically true" case. It is the superpowers TDD idiom (red → green) used as a gate.

```js
// BEFORE dispatching the implementer: assert the check currently FAILS (is red).
if (task.red_green) {
  let baselineRed = false;
  try {
    await bash(task.red_green.before);
  } catch {
    baselineRed = true; // CAVEAT: any non-zero exit reads as "red". A tool that errors for
    // an ENVIRONMENTAL reason (missing binary, usage error, "no tests collected") also lands
    // here, giving a false "discriminating". Where it matters, accept ONLY the tool's
    // tests-ran-and-failed code as red and treat usage/collection codes as "cannot establish red".
  }
  if (!baselineRed) {
    halt({
      kind: "sdd_fidelity_baseline_not_red",
      task: task.id,
      cmd: task.red_green.before,
      message:
        "red_green.before passed pre-implementation — the check does not discriminate this task's change (already green). Fix the check or the task scope before dispatching.",
    });
    return;
  }
}

// ... dispatch implementer, run Tier 0, run Tier 1 ...

// AFTER Tier 0/1 pass: assert the same check now PASSES (is green).
if (task.red_green) {
  try {
    await bash(task.red_green.after);
  } catch (e) {
    halt({
      kind: "sdd_fidelity_not_green",
      task: task.id,
      cmd: task.red_green.after,
      error: String(e),
      message:
        "red_green.after still fails after the implementer reported DONE.",
    });
    return;
  }
}
```

**Ordering is load-bearing:** `before` runs _first_ — ahead of the Tier 0 baseline capture and the dispatch (else you can't prove the check discriminates); `after` runs _post-Tier-0_ (else you'd assert green against an unchanged tree). Keep them on opposite sides of the implementer call. Because `before` runs ahead of the baseline, a read-only check is fully neutralized — anything it dirties is folded into `baselineDirty` and subtracted from `observed`. The only residual risk is a `before` with _delayed/async_ side effects landing after the baseline snapshot; keep `before` synchronous and read-only.

---

## Reviewer gate — spec-reviewer-PASS post-condition (CCE-94)

This gate inputs the reviewer's **self-authored** `findings` and `evidence.files_read`. By rule #2, those do **not** dereference to external state — so this gate is an **advisory proxy**: it catches the _lazy_ reviewer (returned `concur` with no structured output) but **not** the _lying_ reviewer (lists plausible paths it never opened). Treat it as the weakest rung, not a peer of the git-backed tiers. The only fully sound reviewer-fidelity signal is that findings reference real diff hunks (which _are_ external) — and, eventually, a harness tool-call log (see **Known limitations** below: the transcript-persistence gap is why that isn't wired yet).

**Rigor is detection-conditional:** when neither Tier 1 nor Tier 2 ran for this task, the reviewer is the _sole_ correctness check — instruct it to review at full rigor, not as a post-verification quality pass. The "judgment on already-verified work" reduction applies **only** when Tiers 1–2 actually discharged.

Insert **after** the spec-reviewer returns `verdict: concur`, **before** marking the task complete.

```js
let reviewReport = await agent(specReviewerPrompt, {
  label: `spec-review:${task.id}`,
  schema: SPEC_REVIEWER_SCHEMA,
});

if (reviewReport.verdict === "concur") {
  // (0) concur + low_confidence is contradictory — a low-confidence review cannot concur.
  //     Do not let it pass as a rubber-stamp lane; route to a human. Checked here on
  //     the initial report AND re-checked after each retry below (a retry can flip a
  //     previously-confident concur into a low-confidence one — see CCE-95 review).
  if (reviewReport.low_confidence) {
    halt({
      kind: "sdd_fidelity_reviewer_low_confidence_concur",
      task: task.id,
      message:
        "Reviewer returned concur AND low_confidence — contradictory. Routing to human.",
    });
    return;
  }

  // (a) Structured findings present? Empty array = explicit "no concerns";
  //     MISSING array = silent no-op. Reassign reviewReport to the retry so a
  //     flipped verdict or new findings are NOT silently dropped.
  if (!Array.isArray(reviewReport.findings)) {
    log(
      `SDD fidelity: spec-reviewer returned concur but findings array is missing. Re-dispatching once.`,
    );
    reviewReport = await agent(
      `${specReviewerPrompt}\n\n---\n\nGATE-FEEDBACK: Your previous response returned verdict="concur" but did not include a structured "findings" array. Re-review and respond with findings: [] (no concerns) or findings: [...] (concerns). An empty array is fine; a missing one is not.`,
      { label: `spec-review-retry:${task.id}`, schema: SPEC_REVIEWER_SCHEMA },
    );
    if (!Array.isArray(reviewReport.findings)) {
      halt({
        kind: "sdd_fidelity_reviewer_missing_findings",
        task: task.id,
        message:
          "Spec-reviewer returned concur twice without a structured findings array. Manual investigation required.",
      });
      return;
    }
    if (reviewReport.verdict !== "concur") return; // re-review no longer concurs — let the loop handle it
    // (0) re-applied: the findings-retry may have flipped to low_confidence.
    if (reviewReport.low_confidence) {
      halt({
        kind: "sdd_fidelity_reviewer_low_confidence_concur",
        task: task.id,
        message:
          "Reviewer returned concur AND low_confidence — contradictory. Routing to human.",
      });
      return;
    }
  }

  // (b) Evidence of reading the declared targets — ADVISORY (self-authored; see header).
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
        {
          label: `spec-review-retry-evidence:${task.id}`,
          schema: SPEC_REVIEWER_SCHEMA,
        },
      );
      if (reviewReport.verdict !== "concur") return; // retry flipped to concerns/blocked — let the loop handle it
      // (0) re-applied: the evidence-retry may have flipped to low_confidence.
      if (reviewReport.low_confidence) {
        halt({
          kind: "sdd_fidelity_reviewer_low_confidence_concur",
          task: task.id,
          message:
            "Reviewer returned concur AND low_confidence — contradictory. Routing to human.",
        });
        return;
      }
      if (!Array.isArray(reviewReport.findings)) {
        halt({
          kind: "sdd_fidelity_reviewer_missing_findings",
          task: task.id,
          message:
            "Spec-reviewer evidence-retry returned concur without a structured findings array. Manual investigation required.",
        });
        return;
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
        return;
      }
    }
  }
}
```

---

## Known limitations

- **`evidence.files_read` is advisory** (self-authored). It catches the lazy reviewer, not the lying one. See the reviewer-gate header.
- **Destructive-op:** a deletion (` D path`) parses as a "touch" and satisfies the Tier 0 floor. For content-must-exist tasks, declare `verify_cmd`/`red_green`.
- **Path normalization:** the helpers compare repo-root-relative paths (all git calls use `git -C "$TREE"`). If your implementer reports absolute or `./`-prefixed paths, normalize both sides before the set comparison, or the forensic/evidence checks false-fire.
- **Cooperation-dependent forensics:** claimed-vs-observed inspects a field the implementer fills. `changed_files` is `required` in the schema to make omission a schema violation, but a truly adversarial subagent is out of scope for a git-only check — that needs the harness tool-call log.
- **No durable PASS record (yet):** the gate emits durable output only on `halt()`. To make a green task's verification _auditable and replayable_, persist a per-task record (dispatchTs, baseline ref, observed set, per-tier outcome) into the commit trailer / PR body / state file on the pass path too.

---

## Anti-patterns

- **Trusting `status: DONE` without scanning the tree.** The original bug. Self-reports are advisory; on-disk state is authoritative.
- **Reading a structured field's _content_ as evidence.** A field is trustworthy only if it dereferences to external state. `changed_files` → diff against git; `summary`/`evidence.files_read` → advisory.
- **Honoring a self-authored exemption.** `zero_diff_allowed` counts only from the plan; `low_confidence` cannot co-exist with `concur`. Never let the policed party grant itself a pass.
- **Re-dispatching unlimited times.** At most one retry _per gate-check_: the implementer gets one (2 dispatches total); the reviewer's findings and evidence checks each get one, so a reviewer can reach three dispatches. Bounded, never a loop — a persistent fail is a plan or subagent bug, not a transient miss.
- **Treating missing `findings` as `findings: []`.** Missing = never considered; explicit empty = considered, found nothing.
- **Asserting `red_green.after` without first proving `before` is red.** A check already green proves nothing.
- **Reading "ship Tier 0 first" as "Tier 0 is enough."** Tier 0 closes _no-op_ only. The _didn't-look_ mode needs the reviewer gate; _wrong-op_ needs Tier 1/2.

---

## Provenance

- **Incident:** 2026-06-04 B11 (CCE-77 ship-validator task execution). Forensic patch: `~/.claude/orchestrator/detached-changes/B11.patch`.
- **Meta-lesson:** captured in CCE-77 closing comment and CCE-83 plan closeout (PR #104).
- **Umbrella ticket:** CCE-92. Children: CCE-93 (implementer / Tier 0), CCE-94 (reviewer gate), CCE-95 (upstream PR). **Tiers 1–2 (consumer-tool, red→green) are convention-only floor extensions with no separate ticket** — file one under CCE-92 if a host's loop depends on them.
- **Upstream tracking:** CCE-95 — the (not-yet-opened) PR to `obra/superpowers`; when it lands, this template can be deleted (if upstream structured output makes it redundant) or kept as a porting guide.
- **Independent reference (not corroboration-as-fact):** per a maintainer comment on `obra/superpowers#1701` (2026-06-07, a _distinct_ third-party thread, not the CCE-95 PR), the same pre-reviewer tree-delta gate is reported in use elsewhere. Treat as a see-also, not a verified production endorsement — the design's soundness rests on the git mechanics above, not on a third party.
