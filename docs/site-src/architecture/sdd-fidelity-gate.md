---
description: "The SDD fidelity gate closes the phantom-work failure mode in the superpowers SDD pattern."
source_files:
  - docs/superpowers/templates/sdd-fidelity-gate.md
  - docs/superpowers/templates/sdd-fidelity-gate.mjs
  - tests/templates/test_sdd_fidelity_gate_node.py
  - tests/templates/test_sdd_fidelity_gate_template_sync.py
  - scripts/orchestrator_runner.py
last_reviewed: '2026-06-09'
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/116
  - https://github.com/theoju/engineering-docs-agent/pull/109
synthesized_into: []
---

# SDD Fidelity Gate

The SDD fidelity gate closes the phantom-work failure mode in the superpowers SDD pattern. Without it, an implementer subagent can return `status: DONE` with zero on-disk edits; the spec-reviewer then operates on the unchanged tree, passes, and the orchestrator marks the task complete on work that never happened.

The gate embodies one organizing principle: **declare-then-discharge**. Every task declares its post-conditions up front; the gate discharges those post-conditions against external authority — git, the real consumer tool — before any self-report is trusted.

## Canonical files

- **Template walkthrough:** `docs/superpowers/templates/sdd-fidelity-gate.md`
- **Reference implementation:** `docs/superpowers/templates/sdd-fidelity-gate.mjs` (dependency-injected, 53-case node:test suite)
- **Pytest wrapper:** `tests/templates/test_sdd_fidelity_gate_node.py`
- **Drift guard:** `tests/templates/test_sdd_fidelity_gate_template_sync.py`

Until CCE-95 lands an upstream port to `obra/superpowers`, every inline Workflow script that composes the SDD pattern must copy the ladder from the template into its per-task loop.

## Failure modes closed

The gate targets four distinct ways a task can appear complete without being complete:

| Mode | Description |
|---|---|
| **No-op** | Implementer returned `DONE`; no files changed. |
| **Wrong-op** | Implementer changed files, but the artifact is invalid under its consumer. |
| **Already-green** | The discriminating check passed before implementation ran. |
| **Rubber-stamp** | Reviewer concurred without reading the relevant files. |

Each tier closes a subset of these modes. Tiers are layered, not atomic — a bare host runs Tier 0 only, a rich host lights up Tiers 1–2 automatically with no errors on the bare path.

## Tier 0 — git baseline (always active)

Tier 0 runs unconditionally. It needs only git, making it universal across hosts.

**Step 1 — baseline diff.** Before dispatching the implementer, record `git status --porcelain` and `git log --since=<dispatch_time>`. After the implementer returns, re-run both. Intersect the observed changed paths against `task.expected_touch_paths`. If the intersection is empty, the task is a no-op: retry once, then halt with `kind: sdd_fidelity_empty_diff`.

The baseline is attributed per-task, not per-session. A tree already dirty from a prior task cannot mask a missing delta in the current one.

**Step 2 — claimed-vs-observed cross-check.** The implementer's `changed_files` list must appear in the git delta. This is cooperation-dependent (a lying subagent can omit files from its claim), but it catches accidental over-claim and provides a fast signal when claims are honest. It is not a forensic check.

Tier 0 independently closes the **no-op** mode. It does not close wrong-op (the files changed, but are they correct?) or rubber-stamp (the reviewer may have concurred without reading).

## Tier 1 — real consumer tool (if `task.verify_cmd`)

When a task declares `task.verify_cmd`, run that command after Tier 0 passes. A non-zero exit code halts the gate regardless of what the implementer reported.

This is the per-task application of the broader plugin invariant: verification must use the actual consumer tool, not `test -f`. A markdown link can resolve on disk while `mkdocs build --strict` rejects it. A TypeScript import can compile locally while `npx tsc --noEmit` fails against the published types.

Tier 1 closes the **wrong-op** mode. It is optional because not every task has a cheap, deterministic consumer-tool invocation. Declare `verify_cmd` whenever one exists.

## Tier 2 — red→green differential (if `task.red_green`)

When a task declares `task.red_green`, run the discriminating check twice: once before the implementer is dispatched (must fail — confirms the check is meaningful) and once after (must pass). If the pre-check already passes, halt: the task's acceptance criterion was already satisfied, meaning either the spec is wrong or the implementer did nothing novel.

Tier 2 closes **no-op**, **wrong-op**, and **already-green** together. It is the strongest single-tier signal, and also the costliest to declare correctly — the pre-check must be cheap and idempotent, and the criterion must be tight enough that a wrong-op implementation can't accidentally satisfy it.

## Reviewer gate

After the implementer tiers pass, the spec-reviewer subagent runs. The gate checks three things on every `concur` response:

1. **Explicit `findings` array.** `findings: []` (explicit empty) is valid. A missing `findings` key is a silent no-op concurrence — reject it.
2. **Evidence overlap (advisory).** `evidence.files_read` vs `task.review_targets`. This is self-reported by the reviewer subagent, so it catches the lazy reviewer, not the lying one. It is advisory: flag it, but do not halt on it alone.
3. **`concur` + `low_confidence` contradiction.** If a reviewer concurs and flags `low_confidence: true`, halt and re-prompt. A reviewer uncertain enough to flag low confidence is not qualified to concur. Re-check this condition on every retry — a retry that still returns `concur` + `low_confidence` halts again.

The `runFidelityLadder` compositor signals a task pass **only via `concurred === true`**. `halted === false` alone is not a pass.

The reviewer gate closes the **rubber-stamp** mode. The known residual gap: confirming the reviewer *actually read* the target files requires per-subagent tool-call logs, which the harness does not currently expose. `evidence.files_read` is the advisory interim. See the template's **Known limitations** section.

## Graceful degradation

Tier 0 is the universal floor. It ships first because it needs only git and is available on every host.

When `task.verify_cmd` is absent, Tier 1 is skipped without error. When `task.red_green` is absent, Tier 2 is skipped without error. A bare host that declares neither gets Tier 0 plus the reviewer gate. A rich host with both declarations gets all four tiers.

This is the same generic-first mandate as the rest of the plugin: behavior is driven by what the task declares, not by what the host provides.

## Short-circuit on blocked implementer

If the implementer returns `status: BLOCKED` or `status: NEEDS_CONTEXT`, the ladder short-circuits immediately. There is no point running git-diff checks on a task that never started. Surface the block to the operator and wait for resolution before retrying.

## Provenance

The 2026-06-04 B11 incident (CCE-77 ship-validator task) exposed the phantom-work gap. The implementer returned `DONE` with no edits; the spec-reviewer passed on the unchanged tree; the orchestrator marked the task complete. The patch is at `~/.claude/orchestrator/detached-changes/B11.patch`.

CCE-92 is the umbrella ticket. CCE-93 covers the implementer/Tier-0 gate, CCE-94 covers the reviewer gate, and CCE-95 tracks the upstream port to `obra/superpowers`. Tiers 1–2 are convention-only extensions with no separate ticket.

An earlier plan (CCE-89) proposed fixing this in `scripts/orchestrator_runner.py`. Phase-1 investigation confirmed the SDD pattern is composed inline by Workflow JS scripts, not by that runner, making the durable fix documentation and a copy-pasteable template rather than code. PR #109 and PR #116 deliver both.
