---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/116
synthesized_into: []
doc_kind: decision
---

# Decision: SDD Fidelity Verification Ladder (CCE-92)

**Date:** 2026-06-08  
**Tickets:** CCE-92 (umbrella), CCE-93 (implementer/Tier-0 gate), CCE-94 (reviewer gate), CCE-95 (upstream port)  
**PR:** [#116](https://github.com/theoju/engineering-docs-agent/pull/116)

## Incident

On 2026-06-04, the B11 incident (CCE-77 ship-validator task) exposed a phantom-work failure mode in the superpowers SDD orchestration pattern.

An implementer subagent returned `status: DONE` with no on-disk edits. The spec-reviewer then operated on the unchanged tree and passed. The orchestrator marked the task complete.

Nothing was built. Nothing was verified. The task was done on paper only.

Root cause: the reviewer validated *intent* (is the plan sound?), not *execution* (did it run?). A structured self-report field is not external authority. The system had no mechanism to distinguish a completed task from a fabricated one.

## Principle: declare-then-discharge

Trust nothing the subagent authors about its own work — prose or JSON. A structured field is trustworthy only if it dereferences to external state:

- `changed_files` → diff against git
- `commit_sha` → check it out
- `verify_cmd` → run it
- `summary` → advisory only

The plan declares per-task post-conditions up front. The gate discharges them against external authority before the next step runs. That is the declare-then-discharge contract.

## Decision

Introduce a four-tier fidelity verification ladder. The ladder runs after each implementer dispatch, before the reviewer sees the result, and again after each reviewer `concur`. The orchestrator gates task completion on `concurred === true` — not on `halted === false` alone.

The canonical doc and reference implementation live at `docs/superpowers/templates/sdd-fidelity-gate.md` and `docs/superpowers/templates/sdd-fidelity-gate.mjs`.

## Tiers

**Tier 0 — always active.**  
Pre-dispatch baseline diff of `git status --porcelain` + `git log --since` against `task.expected_touch_paths`. Catches the no-op case. The baseline is attributed to the current task so a tree already dirty from a prior step cannot mask the absence of new edits. A claimed-vs-observed cross-check additionally requires that every path in the implementer's `changed_files` appears in the git delta — a cooperation-dependent over-claim check, but it uses git as the authority, not the model's self-report.

Tier 0 needs only git. Ship it first for universality. It independently closes the no-op failure mode but is not sufficient alone: the rubber-stamp reviewer and wrong-op modes stay open until the higher tiers.

**Tier 1 — if `task.verify_cmd` is declared.**  
Run the real consumer tool and assert exit 0. Catches wrong-op (the implementer did something, but not the right thing). This is the "actual consumer tool, not `test -f`" invariant applied per-task — the same rule that closed the ADIS PR #411 incident.

**Tier 2 — if `task.red_green` is declared.**  
Assert the discriminating check fails before implementation and passes after. Catches no-op, wrong-op, and already-green. The most expensive tier; declare it on tasks where a binary pass/fail check is feasible.

**Reviewer gate.**  
After each `concur`, the gate checks:
- `findings: []` (explicit empty) vs missing `findings` (silent no-op — rejected)
- Advisory `evidence.files_read` vs `task.review_targets` (self-authored, catches the lazy reviewer not the lying one)
- `concur` + `low_confidence` contradiction — halted and re-queued on every retry path

## Layering

The tiers are layered, not atomic. Each tier closes one failure mode independently:

| Mode | Closed by |
|---|---|
| No on-disk edits | Tier 0 |
| Wrong operation | Tier 1 / Tier 2 |
| Rubber-stamp reviewer | Reviewer gate |
| Didn't actually read the file | Residual gap (see below) |

A bare host gets Tier 0 only — pure git, no external tools required. A richer host lights up Tiers 1 and 2 when tasks declare `verify_cmd` or `red_green`. No errors on the bare path.

## Deliverables landed in PR #116

- `docs/superpowers/templates/sdd-fidelity-gate.md` — Markdown walkthrough
- `docs/superpowers/templates/sdd-fidelity-gate.mjs` — dependency-injected reference implementation
- 53-case `node:test` suite
- `tests/templates/test_sdd_fidelity_gate_node.py` — pytest wrapper for the JS suite
- `tests/templates/test_sdd_fidelity_gate_template_sync.py` — doc/impl drift guard
- `CLAUDE.md` — full convention bullet + `TIER1_DEFAULT` 7→9 miscount fix

## Residual gap

The reviewer "did you actually read it" mode requires the harness to expose per-subagent tool-call logs. That capability is not available today. `evidence.files_read` is the advisory interim. Tracked in the template's **Known limitations** section.

## Until CCE-95 lands

CCE-95 tracks the upstream port to `obra/superpowers`. Until that PR merges, every inline Workflow script that composes the SDD pattern must copy the ladder into its per-task loop manually. Do not rely on an imported shared module — it does not exist in the upstream yet.
