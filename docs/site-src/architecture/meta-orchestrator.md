---
description: "The meta-orchestrator is the top-level Claude Code workflow that drives the nightly docs-PR pipeline."
source_files:
  - docs/superpowers/templates/sdd-fidelity-gate.md
  - docs/superpowers/templates/sdd-fidelity-gate.mjs
last_reviewed: '2026-06-09'
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/104
synthesized_into: []
---

# Meta-Orchestrator

The meta-orchestrator is the top-level Claude Code workflow that drives the nightly docs-PR pipeline. It dispatches subagent tasks in sequence, gates each task on a fidelity ladder, and opens a GitHub PR with the results. This page covers the architectural invariants hardened by CCE-83 and the B11 incident.

## GitHub CLI invariants

### `gh pr checks --json` field names

`gh pr checks <N> --json` returns objects with `name`, `state`, and `bucket`. It does **not** return `statusCheckRollup` or `conclusion`. Any orchestrator or skill polling check status must parse:

```javascript
c.state === 'FAILURE' || c.bucket === 'fail'   // red
c.state === 'SUCCESS' || c.bucket === 'pass'   // green
```

The non-JSON `gh pr checks` text output uses different vocabulary (`pass`/`fail`/`pending`) — match by column position, not by reusing JSON field names. Using the wrong field names produces silent always-undefined comparisons that pass all checks even when they fail.

Reference: CCE-83 iter-3 residuals (2026-06-03), Task 15 Step 2.

### Raw JSON output from subagents

When a subagent calls `gh pr view --json`, it wraps the output in markdown fences or prose unless you explicitly instruct otherwise. Include this sentence verbatim in the prompt:

> Return only the raw JSON output from gh pr view (no surrounding prose).

Alternatively, wrap the parse in `try/catch` with a sentinel fallback. The same rule applies to any `--json` CLI consumer fed through a subagent — never assume model output of a CLI tool is directly parseable as-is.

Reference: CCE-83 iter-3 residuals (2026-06-03), Tasks 16/17 Step 1.

## SDD fidelity model

### The B11 incident

On 2026-06-04, the B11 implementer subagent returned `status: DONE` for the CCE-77 ship-validator task with no on-disk edits. The spec-reviewer passed on the unchanged tree because it validated intent (is the plan sound?), not execution (did it run?). The task was marked complete on phantom work.

This is the direct motivation for the declare-then-discharge fidelity ladder. The manual recovery patch is at `~/.claude/orchestrator/detached-changes/B11.patch`. The in-repo spec is in `docs/superpowers/specs/`.

### Declare-then-discharge

Trust nothing a subagent authors about its own work — prose or structured JSON. A field is trustworthy only if it dereferences to external state:

- `changed_files` → diff against `git status --porcelain`
- `commit_sha` → check it out
- `verify_cmd` → run it
- `summary` → advisory only

The orchestrator verifies each task's post-conditions before proceeding to the next step. The canonical fidelity gate spec is at `docs/superpowers/templates/sdd-fidelity-gate.md`; the reference implementation is at `docs/superpowers/templates/sdd-fidelity-gate.mjs`.

### Fidelity tiers

Three tiers apply, selected by what the host provides:

**Tier 0 (always).** Pre-dispatch baseline `git status --porcelain` + `git log --since`, compared against `task.expected_touch_paths`. Catches the silent no-op. Baseline-attributed so a dirty tree from a prior task cannot mask new changes. Also cross-checks the implementer's claimed `changed_files` against the git delta — a cooperation-dependent over-claim check, not full forensic verification.

**Tier 1 (if `task.verify_cmd`).** Run the real consumer tool. Catches wrong-op. This is the "use the actual consumer tool, not `test -f`" invariant applied per task.

**Tier 2 (if `task.red_green`).** Assert the discriminating check fails pre-implementation and passes post. Catches no-op, wrong-op, and already-green.

Tier 0 ships first because it requires only git and runs on any host. It is the floor, not the ceiling — the reviewer rubber-stamp failure mode stays open until the reviewer gate runs, and wrong-op stays open until Tier 1 or 2.

### Reviewer gate

After each `concur` from the spec-reviewer subagent, the gate checks:

- `findings: []` must be explicit. A missing `findings` key is a silent no-op, not a pass.
- `evidence.files_read` vs `task.review_targets` is advisory only (self-authored, catches the lazy reviewer but not the lying one).
- A `concur` + `low_confidence` combination is a contradiction — halt and retry.
- `runFidelityLadder` signals a pass only via `concurred === true`. `halted === false` alone is not a pass.

### Graceful degradation

A bare host gets Tier 0 (pure git, universal). A host with `verify_cmd` and `red_green` declarations in its task specs lights up Tiers 1–2 automatically. No errors on the bare path — same generic-first mandate as the rest of the plugin.

## CCE-91 rollback: diagram-gate deadlock

The CCE-83 implementation plan wired a diagram-gate as a required GitHub check. That created a deadlock: the PR could not merge until the check passed, but the check's pass condition depended on the PR being in a merged state. CCE-91 rolled back the required-check flag. The diagram-gate remains in the workflow as an informational check only.

## Ticket map

| Ticket | Scope |
|--------|-------|
| CCE-83 | Meta-orchestrator spec v2.1 and 14-task plan |
| CCE-84–CCE-91 | Residuals and rollbacks from the CCE-83 execution trace |
| CCE-88 | Regex-upgrade reference plan (archived from CCE-77 v1 plan) |
| CCE-92 | Umbrella: SDD fidelity gap |
| CCE-93 | Implementer + Tier-0 gate |
| CCE-94 | Reviewer gate |
| CCE-95 | Upstream PR to `obra/superpowers` |

Until CCE-95 lands, every inline Workflow script that composes the SDD pattern must copy the fidelity ladder into its per-task loop.
