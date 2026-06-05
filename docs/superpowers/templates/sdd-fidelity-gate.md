# SDD fidelity gates — copy-pasteable JS for inline Workflow scripts

**Status:** convention floor (CCE-92 umbrella, CCE-93 + CCE-94) until the upstream PR (CCE-95) to `obra/superpowers` lands.

**When to use:** any time you compose the superpowers Subagent-Driven Development pattern inline (Workflow JS script that dispatches an implementer + spec-reviewer + code-quality-reviewer per task). The skill itself does not (yet) verify that subagent self-reports match on-disk state — these gates close that gap.

**Failure mode this prevents.** An implementer subagent returns `status: DONE` with a `concur` message, no actual edits applied. The spec-reviewer then operates on the unchanged tree, sees nothing wrong, and passes. The orchestrator marks the task complete. Real incident: 2026-06-04 B11 (this repo's CCE-77 ship-validator task), forensic patch at `~/.claude/orchestrator/detached-changes/B11.patch`.

---

## Gate 1 — implementer-DONE post-condition (CCE-93)

Insert **after** the implementer subagent returns `status: DONE` and **before** dispatching the spec-reviewer.

```js
// Capture the dispatch timestamp BEFORE calling the implementer subagent.
// The post-condition scans this window; no earlier-than-dispatch noise.
const dispatchTs = await bash("date -u +%Y-%m-%dT%H:%M:%SZ");

const implReport = await agent(implementerPrompt, {
  label: `impl:${task.id}`,
  schema: IMPLEMENTER_SCHEMA,
});

if (
  implReport.status === "DONE" ||
  implReport.status === "DONE_WITH_CONCERNS"
) {
  // Mechanical post-condition: did the tree actually change in the expected places?
  const porcelain = await bash("git status --porcelain");
  const recent = await bash(
    `git log --since="${dispatchTs}" --name-only --pretty=format:`,
  );

  const changedPaths = new Set([
    ...porcelain
      .split("\n")
      .map((l) => l.slice(3).trim())
      .filter(Boolean),
    ...recent.split("\n").filter(Boolean),
  ]);

  const expected = new Set(task.expected_touch_paths || []);
  const overlap = [...changedPaths].filter((p) =>
    [...expected].some((e) => p === e || p.startsWith(e + "/")),
  );

  if (overlap.length === 0 && !task.zero_diff_allowed) {
    // Re-dispatch ONCE with an explicit prompt naming the discrepancy.
    log(
      `SDD fidelity: implementer reported ${implReport.status} but tree shows no edits to ${[...expected].join(", ")}. Re-dispatching.`,
    );

    const retryPrompt = `${implementerPrompt}\n\n---\n\nGATE-FEEDBACK: Your previous response reported status="${implReport.status}" but on-disk diff is empty for the expected paths: ${[...expected].join(", ")}. Re-execute the task and produce ACTUAL file edits this time. If the task genuinely requires zero diff (review-only, TodoWrite-only, question-to-human), respond with status="DONE" AND include "zero_diff_allowed: true" in your structured tail.`;

    const retry = await agent(retryPrompt, {
      label: `impl-retry:${task.id}`,
      schema: IMPLEMENTER_SCHEMA,
    });

    // Re-scan after retry.
    const retryPorcelain = await bash("git status --porcelain");
    const retryRecent = await bash(
      `git log --since="${dispatchTs}" --name-only --pretty=format:`,
    );
    const retryChanged = new Set([
      ...retryPorcelain
        .split("\n")
        .map((l) => l.slice(3).trim())
        .filter(Boolean),
      ...retryRecent.split("\n").filter(Boolean),
    ]);
    const retryOverlap = [...retryChanged].filter((p) =>
      [...expected].some((e) => p === e || p.startsWith(e + "/")),
    );

    if (retryOverlap.length === 0 && !retry.zero_diff_allowed) {
      halt({
        kind: "sdd_fidelity_empty_diff",
        task: task.id,
        expected: [...expected],
        observed: [...retryChanged],
        message:
          "Implementer reported DONE twice without on-disk evidence. Manual investigation required.",
      });
    }
  }
}
```

**Why a single retry, not unlimited:** two passes is enough signal for human review. A persistent empty-diff DONE is either a plan mis-spec (the task literally has nothing to do — opt into `zero_diff_allowed`) or a subagent bug worth surfacing.

**Why scan both `porcelain` and `git log`:** the implementer may have committed (clean working tree) or left uncommitted edits. Cover both. The `--since` window keeps the log scan bounded.

**Required schema field for `IMPLEMENTER_SCHEMA`:** `zero_diff_allowed: boolean` (default `false`). Without this opt-out, review-only tasks false-positive the gate.

---

## Gate 2 — spec-reviewer-PASS post-condition (CCE-94)

Symmetric variant. Insert **after** the spec-reviewer subagent returns `verdict: concur` and **before** marking the task complete (or proceeding to the code-quality-reviewer).

Same failure mode: a reviewer can return `concur` without actually reading any files.

```js
const reviewerDispatchTs = await bash("date -u +%Y-%m-%dT%H:%M:%SZ");

const reviewReport = await agent(specReviewerPrompt, {
  label: `spec-review:${task.id}`,
  schema: SPEC_REVIEWER_SCHEMA,
});

if (reviewReport.verdict === "concur") {
  // Mechanical post-condition: did the reviewer produce a structured findings array?
  // Empty array is fine (= explicit "no findings"); MISSING array is not (= silent no-op).
  if (!Array.isArray(reviewReport.findings)) {
    log(
      `SDD fidelity: spec-reviewer returned concur but findings array is missing. Re-dispatching.`,
    );

    const retryPrompt = `${specReviewerPrompt}\n\n---\n\nGATE-FEEDBACK: Your previous response returned verdict="concur" but did not include a structured "findings" array. Re-review and produce a response with findings: [] (if you have no concerns) or findings: [...] (if you do). An empty array is fine; a missing one is not.`;

    const retry = await agent(retryPrompt, {
      label: `spec-review-retry:${task.id}`,
      schema: SPEC_REVIEWER_SCHEMA,
    });

    if (!Array.isArray(retry.findings)) {
      halt({
        kind: "sdd_fidelity_reviewer_missing_findings",
        task: task.id,
        message:
          "Spec-reviewer returned concur twice without a structured findings array. Manual investigation required.",
      });
    }
  }

  // Optional heuristic: if task.review_targets is declared, confirm the reviewer
  // looked at them. Proxy signal: the reviewer's forensics show Read tool calls
  // against those paths in the dispatch window. Without forensics access in the
  // current orchestrator harness, fall back to an evidence field in the schema.
  if (task.review_targets && task.review_targets.length > 0) {
    const evidenceTargets = new Set(reviewReport.evidence?.files_read || []);
    const declaredTargets = new Set(task.review_targets);
    const reviewed = [...declaredTargets].filter((t) => evidenceTargets.has(t));

    if (reviewed.length === 0 && !reviewReport.low_confidence) {
      log(
        `SDD fidelity: spec-reviewer returned concur but evidence.files_read does not overlap with task.review_targets. Re-dispatching.`,
      );

      const retryPrompt = `${specReviewerPrompt}\n\n---\n\nGATE-FEEDBACK: Your previous response returned verdict="concur" but the evidence.files_read field does not show any of the declared review targets: ${[...declaredTargets].join(", ")}. Re-review by actually opening those files and produce a response with evidence.files_read listing the paths you read. If you genuinely cannot evaluate one or more targets, set low_confidence: true and explain in findings.`;

      const retry = await agent(retryPrompt, {
        label: `spec-review-retry-evidence:${task.id}`,
        schema: SPEC_REVIEWER_SCHEMA,
      });

      const retryEvidence = new Set(retry.evidence?.files_read || []);
      const retryReviewed = [...declaredTargets].filter((t) =>
        retryEvidence.has(t),
      );

      if (retryReviewed.length === 0 && !retry.low_confidence) {
        halt({
          kind: "sdd_fidelity_reviewer_no_evidence",
          task: task.id,
          declared: [...declaredTargets],
          observed: [...retryEvidence],
          message:
            "Spec-reviewer returned concur twice without evidence of reading review targets. Manual investigation required.",
        });
      }
    }
  }
}
```

**Required schema fields for `SPEC_REVIEWER_SCHEMA`:**

- `verdict: "concur" | "concerns" | "blocked"` — overall verdict.
- `findings: array` — empty if no concerns; entries with `{file, line, severity, message}` if so. Missing field is the silent-no-op signal.
- `evidence: { files_read: array }` — paths the reviewer actually opened. Empty array = "I evaluated without reading specific files" (valid for some review modes); missing = same silent-no-op signal.
- `low_confidence: boolean` (default `false`) — explicit opt-out for tasks where evidence cannot be gathered (e.g., reviewing a YAML config without an obvious primary file).

---

## Schema fragments

Add these JSON Schemas alongside your existing implementer/reviewer schemas.

```js
const IMPLEMENTER_SCHEMA = {
  type: "object",
  required: ["status"],
  properties: {
    status: {
      enum: ["DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED"],
    },
    summary: { type: "string" },
    changed_files: { type: "array", items: { type: "string" } },
    commit_sha: { type: "string" },
    test_cmd: { type: "string" },
    test_result: {
      type: "object",
      properties: { passed: { type: "integer" }, failed: { type: "integer" } },
    },
    zero_diff_allowed: { type: "boolean", default: false },
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
      properties: {
        files_read: { type: "array", items: { type: "string" } },
      },
    },
    low_confidence: { type: "boolean", default: false },
  },
};
```

Tighten or relax as your orchestrator's per-task contract requires. The gates above assume these field names.

---

## Anti-patterns

- **Trusting `status: DONE` without scanning the tree.** This is the original bug. Self-reports are advisory; on-disk state is authoritative.
- **Re-dispatching unlimited times on empty-diff.** Two passes max — a persistent fail is a plan or subagent bug, not a transient miss.
- **Treating missing `findings` as `findings: []`.** Missing means the reviewer didn't think about the field at all; explicit empty means they considered and found nothing. Different signals.
- **Skipping the gate "because the implementer always works."** It usually does. The gate fires on the rare path where it doesn't, and that's the one that costs you a green-CI-but-broken merge.
- **Skipping `zero_diff_allowed`.** Without it, review-only / question-to-human / TodoWrite-only tasks false-positive every time. Include the opt-out in your schema and your implementer prompts.

---

## Provenance

- **Incident:** 2026-06-04 B11 (CCE-77 ship-validator task execution). Forensic patch: `~/.claude/orchestrator/detached-changes/B11.patch`.
- **Meta-lesson:** captured in CCE-77 closing comment and CCE-83 plan closeout (PR #104).
- **Umbrella ticket:** CCE-92.
- **This file:** ships CCE-93 (implementer gate) + CCE-94 (reviewer gate) as a single atomic floor.
- **Upstream tracking:** CCE-95 — when the obra/superpowers PR lands, this template can either be deleted (if upstream's structured output makes it redundant) or kept as a porting guide.
