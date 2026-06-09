---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/106
synthesized_into: []
doc_kind: decision
---

# Decision: Plan-step verification must use the actual consumer tool

**Date:** 2026-06-04  
**Trigger:** ADIS PR #411 / engineering-docs-agent PR #106

## Context

A plan task that produces a published artifact — a docs page, a TypeScript module, a JSON Schema, an OpenAPI route — is not done when the artifact exists on disk. It is done when the artifact's real consumer accepts it.

This distinction collapsed in ADIS PR #411. Task δ.2 added a runbook and verified its existence with `test -f`. The check passed. The published link to the runbook from `docs/site-src/ops/runbooks.md` failed `mkdocs build --strict` because the path was outside `docs_dir`. The breakage reached docker-push before it was caught, costing three days of remediation (closed by ADIS PR #416).

The same class of bug is possible anywhere a plan author reaches for a filesystem check when the real question is "will the consumer accept this?"

## Decision

Every plan step that produces a published artifact must invoke the tool that consumes that artifact as its verification step. Filesystem checks (`test -f`, `ls`, path existence assertions) are not sufficient verification for published artifacts.

Concrete mapping:

| Artifact type | Consumer verification |
|---|---|
| MkDocs page or link | `mkdocs build --strict` |
| TypeScript import | `npx tsc --noEmit` |
| JSON Schema reference | `ajv validate` |
| OpenAPI route | your validator of record |

This convention was added to `CLAUDE.md` in PR #106 and applies to all plan authors working in this repo. The same rule landed simultaneously in the sibling repos ADIS and claude-code-self-assessment.

## Consequences

**Positive.** A consumer-tool check catches the failure class that `test -f` misses: the artifact exists but violates the consumer's validity contract. Running the real tool is a one-off cost at plan-step verification time.

**Negative / accepted trade-off.** Consumer tools are slower than filesystem checks and may require build environment setup. Accept this cost. A half-verified plan that reaches production is more expensive than a slower CI step.

## Relation to the fidelity ladder

This convention is the concrete, per-task expression of the fidelity ladder's Tier 1 rule (`task.verify_cmd` → run the real consumer tool). The ladder is the general mechanism; this decision record documents the specific incident that motivated requiring it in docs plans and the mapping from artifact type to verification command.

See `docs/superpowers/templates/sdd-fidelity-gate.md` for the full ladder specification.
