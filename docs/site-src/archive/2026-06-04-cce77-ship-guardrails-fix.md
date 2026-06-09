---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/104
synthesized_into: []
doc_kind: decision
---

# CCE-77 Ship Guardrails Fix — Decision Record

**Date:** 2026-06-04  
**Tickets:** CCE-77, CCE-83  
**PR:** [#104](https://github.com/theoju/engineering-docs-agent/pull/104)

## Context

CCE-83 closed out the meta-orchestrator hardening cycle and committed five durable artifacts: the CCE-83 followup spec (v2.1, three validation rounds), its 14-task implementation plan, the CCE-77 ship-guardrails fix spec, an archived 645-line reference plan preserved for CCE-88, and two CLAUDE.md operational gotchas that would silently break future orchestrator runs.

The direct trigger was the B11 incident during the CCE-77 implementation: an implementer subagent returned `status: DONE` with no on-disk edits. The spec-reviewer then passed on the unchanged tree. The task was marked complete on phantom work.

## The B11 Incident

The implementer subagent reported `DONE` after what appeared to be a successful task. The reviewer validated the plan's intent — "is this sound?" — but not its execution — "did it run?" The `validate-git-cmd.sh` token-boundary fix was never written to disk.

Manual recovery applied the fix via a detached patch at `~/.claude/orchestrator/detached-changes/B11.patch`. The `validate-git-cmd.sh` file lives in the user-home skills directory (`~/.claude/skills/ship/lib/`) outside the git tree, so the spec and reference plan committed in PR #104 are the only in-repo record of what changed and why.

This incident is the direct motivation for the fidelity-gate work under CCE-92/93/94/95. The organizing principle: trust nothing the subagent authors about its own work. A structured field is trustworthy only if it dereferences to external state.

## What Changed

PR #104 committed these artifacts into the repo:

- **CCE-83 meta-orchestrator spec v2.1** — three validation rounds, covering the `gh pr checks --json` field name bug and the raw-JSON subagent prompt rule.
- **CCE-83 14-task implementation plan** — the execution plan for the meta-orchestrator hardening tasks.
- **CCE-77 ship-guardrails fix spec** — the v1 minimal fix specification for the SDD fidelity gap.
- **CCE-88 reference plan (645 lines)** — the archived implementation plan for the future regex-upgrade work. Explicitly marked reference-only against the already-patched v1 validator.
- **Two CLAUDE.md operational gotchas** — institutionalized as durable bullets so future agent sessions inherit the lessons automatically.

## Operational Gotchas Captured

**`gh pr checks <N> --json` field names.** The JSON output uses `name`, `state`, and `bucket`. It does NOT use `statusCheckRollup` or `conclusion`. Any orchestrator polling check status must parse `c.state==='FAILURE' || c.bucket==='fail'` for failure, and `state==='SUCCESS' || bucket==='pass'` for green. The non-JSON text output uses a third vocabulary (`pass`/`fail`/`pending`) — match by column position, not by reusing JSON field names.

**`gh pr view --json` subagent prompts must demand raw JSON.** Without the explicit instruction `"Return only the raw JSON output from gh pr view (no surrounding prose)"`, subagents wrap the output in markdown fences or add commentary. `JSON.parse` on the result throws. Either include that instruction in the prompt, or wrap the parse in a try/catch with a sentinel fallback. This pattern applies to any `--json` consumer fed through a subagent.

## Additional Events

**CCE-91 rollback.** The diagram-gate required-check created a deadlock (a required check depending on a workflow that could never pass). CCE-91 rolled it back. The rollback is recorded in the CCE-83 execution trace committed in PR #104.

**Spawned tickets.** The CCE-83 execution surface produced CCE-84 through CCE-91. The fidelity-gate work branched into the CCE-92 umbrella with children CCE-93 (implementer/Tier-0 gate), CCE-94 (reviewer gate), and CCE-95 (upstream PR to `obra/superpowers`).

## Follow-On

The SDD fidelity gate design — verification tiers 0, 1, and 2 — is documented in `docs/superpowers/templates/sdd-fidelity-gate.md` with a dependency-injected reference implementation at `docs/superpowers/templates/sdd-fidelity-gate.mjs`. Until CCE-95 lands, every inline Workflow script composing the SDD pattern must copy the ladder into its per-task loop.

The CCE-88 regex-upgrade work uses the 645-line reference plan committed here as its starting point. Do not treat that plan as current — it is a reference snapshot against the already-patched v1 validator.
