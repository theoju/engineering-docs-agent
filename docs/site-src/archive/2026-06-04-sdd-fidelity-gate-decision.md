---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/109
synthesized_into: []
doc_kind: decision
---

# Decision: SDD Fidelity Gate (2026-06-04)

**Tickets:** CCE-92 (umbrella), CCE-93 (implementer / Tier 0), CCE-94 (reviewer gate), CCE-95 (upstream PR, pending)
**Status:** in effect; upstream coordination pending CCE-95.

---

## The incident: B11, 2026-06-04

The CCE-77 ship-validator task completed with `status: DONE` from the implementer subagent. No edits landed on disk. The spec-reviewer was then dispatched against the unchanged tree, saw nothing wrong, and returned `verdict: concur`. The orchestrator marked the task complete.

The phantom work was caught only during post-run audit. The forensic patch is at `~/.claude/orchestrator/detached-changes/B11.patch`.

**Root cause.** The reviewer validated _intent_ — is the plan sound? — without validating _execution_ — did the plan run? LLM reviewers are tuned to judge semantic correctness, not process correctness. A spec that reads as valid earns `concur` even when no tool call ever touched the working tree. A prompt-level fix cannot close this: the check has to be mechanical and rooted in state the subagent cannot author.

---

## Decision: documentation over code, both gates together

### Rejected: `orchestrator_runner.py`

Early phase-1 investigation proposed routing the gate through `scripts/orchestrator_runner.py`. That runner is not the execution boundary for the superpowers SDD pattern. The SDD loop — implementer + spec-reviewer + code-quality-reviewer per task — is composed **inline by Workflow JS scripts**, not by the Python runner. A fix in the runner would never fire for inline compositions.

The durable fix is documentation + a copy-pasteable template the inline scripts can incorporate directly.

### Chosen: `docs/superpowers/templates/sdd-fidelity-gate.md`

PR #109 ships a canonical template at `docs/superpowers/templates/sdd-fidelity-gate.md` and a reference implementation at `docs/superpowers/templates/sdd-fidelity-gate.mjs` (dependency-injected, unit-tested, guarded against doc/impl drift by `tests/templates/test_sdd_fidelity_gate_template_sync.py`).

The template codifies two gates. They ship together because a partial gate produces false confidence: a gate that passes one condition while silently failing the other is worse than none — operators assume a passing gate is a complete gate.

**Gate 1 — implementer fidelity (CCE-93, Tier 0).** Inserts after the implementer returns `status: DONE`, before the spec-reviewer is dispatched. It diffs the working tree against a pre-dispatch baseline, checks the delta intersects `task.expected_touch_paths`, and cross-checks the implementer's `changed_files` claim against the actual git delta. One retry on empty diff, then `halt` with `kind: sdd_fidelity_empty_diff`. The baseline is attributed per-task so a tree already dirty from a prior task cannot mask a no-op.

**Gate 2 — reviewer fidelity (CCE-94).** Inserts after `verdict: concur`, before marking the task complete. It requires an explicit `findings` array (missing is not the same as empty), checks for a `concur` + `low_confidence` contradiction, and advisory-checks `evidence.files_read` against `task.review_targets`. One retry per check, then `halt`.

---

## The organizing principle

**Trust nothing the subagent authors about its own work.** A structured field is trustworthy only when it dereferences to external state:

- `changed_files` → verify against `git status --porcelain` + `git log --since`
- `commit_sha` → check it out; diff match
- `verify_cmd` → run it and inspect the exit code
- `summary`, `evidence.files_read` → advisory only; never the sole basis for passing a gate

Self-declared exemptions (`zero_diff_allowed`, `low_confidence`) count only when set in the plan, never when the implementer sets them on its own output. A subagent cannot exempt itself from the check that polices it.

---

## Tier coverage and layering

The gate layers tiers by host-requirement, not by failure mode:

| Tier | Trigger | Failure mode closed |
|------|---------|---------------------|
| **0** (always) | — | no-op, over-claim |
| **1** (optional) | `task.verify_cmd` | wrong-op |
| **2** (optional) | `task.red_green` | no-op + wrong-op + already-green |
| **reviewer** | after `verdict: concur` | lazy rubber-stamp |

Tier 0 uses only git; every host can run it. "Ship Tier 0 first" means "Tier 0 is the universal floor," not "Tier 0 is enough." The reviewer rubber-stamp mode stays open until the reviewer gate discharges. Wrong-op stays open until Tier 1 or 2 runs.

A bare host (no consumer tool, no tests) gets Tier 0 only. On a Tier-0-only host, the reviewer is the sole correctness check and must review at full rigor — the "judgment on already-verified work" reduction applies only when Tiers 1–2 actually discharged. A rich host lights up every tier automatically. No errors on the bare path: the plugin's degrade-gracefully mandate applies here the same as everywhere.

---

## Meta-lesson from CCE-77

The gate design reflects a single lesson: **declare-then-discharge, never trust-the-report.** Every plan declares per-task what "done" looks like externally. The gate discharges against that declaration mechanically. A `status: DONE` claim is advisory; an empty git delta is authoritative.

Subagent self-reports are improvable. A confident model emits plausible prose, plausible JSON, and a plausible "yes I did that." None of those signals come from external state. The only checks that close the execution-gap are the ones rooted in artifacts the subagent cannot author: git state, consumer-tool exit codes, eventually harness tool-call logs.

---

## Residual gaps

**`evidence.files_read` is advisory.** It catches the lazy reviewer, not the lying one. Closing the lying-reviewer case requires harness-level tool-call log exposure — tracked in the template's Known Limitations section; not yet wired.

**No durable PASS record.** The gate emits a record only on `halt`. Green task verifications are not yet persisted into the commit trailer or state file, making them non-auditable after the run completes.

---

## Upstream coordination

**CCE-95** tracks an upstream PR to `obra/superpowers`. Until that lands, every inline Workflow script composing the SDD pattern must copy the ladder from `docs/superpowers/templates/sdd-fidelity-gate.md` into its per-task loop directly. The template is the single source of truth in the interim; the sync test (`tests/templates/test_sdd_fidelity_gate_template_sync.py`) ensures the `.mjs` implementation and the markdown snippets do not drift.

An independent maintainer comment on `obra/superpowers#1701` (2026-06-07) reports the same pre-reviewer tree-delta gate in use elsewhere. Treat that as a see-also, not a verified production endorsement — the design's soundness rests on the git mechanics, not on a third-party report.
