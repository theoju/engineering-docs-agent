---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/126
synthesized_into: []
doc_kind: decision
---

# CCE-109 Doom Loop Resolution: Backlog Catch-Up Run (2026-06-10)

## Context

Since 2026-05-29, the nightly docs-agent had been stuck in a doom loop. Each CI run re-processed the full ~35-PR backlog window, hit the 60-minute job timeout, and exited without advancing `last_successful_run`. The next run would pick up the same window and repeat the cycle.

The root cause is a missing window budget: the runner has no mechanism to bound per-run scope to fit within a CI timeout. The durable fix is tracked under CCE-109.

## What happened on 2026-06-10

A one-off local run was executed without a CI timeout constraint to unblock the backlog. The run:

- Processed the full ~35-PR window accumulated since `bdf0da1a`.
- Published 32 documentation pages across the `archive` and `architecture` sections.
- Advanced `last_successful_run` baseline from `bdf0da1a` to `68090590`.
- Produced a `.doc-source-map.json` drift-tracking artifact.

## Dropped pages

Approximately 19 candidate architecture pages and 3 broken-link pages were rejected by the Tier-1 linter and not published. The linter requires `last_reviewed` in the frontmatter for architecture pages; the page-author agent was not emitting it. These pages will not auto-regenerate — the baseline has advanced past the source PRs that would trigger them.

The page-author frontmatter gap is a separate follow-up, not addressed in PR #126.

## Decision

The immediate unblock was a manual local run. This is not a repeatable operational procedure — it bypasses the CI timeout guard that exists for a reason (resource protection and predictable run duration).

The durable fix under CCE-109 introduces window budgeting: the runner will stop processing new PRs once a configurable time budget is consumed, emit a `partial: true` PR, and leave the remaining window for the next nightly run. This prevents both the doom loop (no timeout → unbounded run) and the inverse problem (timeout → no progress).

## Operator follow-ups required

**Two items flagged in PR #126 need human review:**

1. `docs/site-src/operations/release-and-rollback.md` — an agent-authored ops page that may overlap the intentionally-unpublished runbook at `docs/runbooks/release-and-rollback.md`. Decide whether to keep, trim, or drop the published version.

2. `docs/site-src/operations/jira-auto-transition.md` — carries a cosmetic `doc_kind: architecture` mislabel. The content is correct; the frontmatter field needs a manual fix to `doc_kind: operations` or equivalent.

## Affected baseline

| Field | Before | After |
|---|---|---|
| `last_successful_run.head_sha` | `bdf0da1a` | `68090590` |
| Pages published | — | 32 |
| Pages dropped (lint) | — | ~22 |

## See also

- CCE-109: window budgeting (durable fix, open)
- `docs/superpowers/specs/2026-06-10-cce101-merge-gate-design.md`: auto-merge gate spec
- `.engineering-docs-agent/state.json`: current baseline
