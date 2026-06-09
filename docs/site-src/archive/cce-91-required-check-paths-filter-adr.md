---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/110
synthesized_into: []
doc_kind: decision
---

# ADR: Required Status Checks Must Not Carry a Workflow-Level `paths:` Filter

**CCE-91 — 2026-06-09**

## Status

Accepted. Implemented in PR #110.

## Context

GitHub Actions supports a `paths:` filter on the `pull_request` trigger. When you add this filter, GitHub **skips the workflow entirely** on PRs that touch no matching paths. GitHub does not post a `skipped` status check — it posts nothing at all.

If that workflow contains a job that is configured as a **required status check** in branch protection, every PR that misses the `paths:` filter ends up with `mergeStateStatus: BLOCKED`. The required check never arrives. The PR cannot merge.

This exact failure hit `docs.yml` (the `diagram-gate` job) in this repo. Non-docs PRs — the majority of merges — triggered the `paths:` skip. The `diagram-gate` required check never posted a passing status, so those PRs were permanently blocked.

CCE-91 stage-1 was an **emergency rollback**: it removed `diagram-gate` from required checks so existing PRs could land. The same root cause had appeared earlier in `actionlint.yml` (CCE-59), but the lesson wasn't yet generalised.

## Decision

**Required status checks must never carry a workflow-level `paths:` filter.**

Instead, use an **in-job filter step**:

1. Add a `filter` step early in the job. Run `git diff --name-only ${{ github.event.pull_request.base.sha }}...HEAD` and set a step output (`changes_detected: true/false`) based on whether any diagram-relevant paths appear in the diff.
2. Gate all expensive steps (Playwright, Chromium install, mkdocs build, render gate) on `if: steps.filter.outputs.changes_detected == 'true'`.
3. Add a no-op success step with `if: steps.filter.outputs.changes_detected != 'true'` so the job always exits green on non-relevant PRs.

This keeps the workflow in scope on every PR — so the job always runs and always posts a conclusive status — while skipping the expensive work when nothing diagram-related changed.

PR #110 implements this pattern for `docs.yml` and encodes two regression tests:

- `test_docs_workflow_has_no_pull_request_paths_filter` — asserts the `paths:` key is absent from the top-level `on.pull_request` trigger.
- `test_docs_workflow_gates_heavy_steps_on_in_job_filter` — asserts the expensive steps carry an `if:` condition gated on the filter output.

## Consequences

- `diagram-gate` can be restored as a required status check after this PR lands without reintroducing the deadlock. The restore is an operator action against branch protection, not a code change.
- Any workflow that previously relied on a `paths:` filter for performance must migrate to the in-job filter pattern before being added to required checks. This is a higher cost per workflow than a top-level filter, but it is the only pattern compatible with GitHub's required-check semantics.
- The invariant is also recorded in `CLAUDE.md` as a plugin convention so it applies to any workflow the agent scaffolds onto host repos.

## Invariant

> Required status checks must **never** carry a workflow-level `paths:` filter. Use an in-job filter step instead.

See `docs/site-src/core/operations/diagram-gate-ci-workflow.md` for how to structure the in-job filter pattern step-by-step.
