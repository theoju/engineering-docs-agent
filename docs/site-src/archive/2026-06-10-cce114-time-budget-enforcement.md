---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: decision
---

# CCE-114: end-to-end time budget enforcement for the nightly run

- **Status:** decided (2026-06-10)
- **Ticket:** CCE-114
- **PR:** [#136](https://github.com/theoju/engineering-docs-agent/pull/136)
- **Parent:** CCE-109 (soft deadline, PR-admission-only)

## Problem

Six consecutive nightly runs were killed by GitHub Actions' 60-minute hard timeout (earliest confirmed incident: run 27263616736, 2026-06-10 08:30 UTC).

CCE-109 introduced a soft deadline, but wired it only to PR admission. PR admission — deciding which PRs fall in the current window — completes within minutes of run start. The downstream work was never bounded.

The page-author fan-out dispatches up to approximately 43 Opus calls per backlog window, one per page in scope. The fact-checker and gap-detector loops each iterate over every authored page. None of these loops checked the soft deadline before starting work. The runner consistently overshot the deadline, causing GitHub Actions' scheduler to abort the job and discard all accumulated output.

## Decision

Extend the soft-deadline check to every major loop in the nightly pipeline. The check topology after CCE-114:

| Stage | Deadline check before starting? |
|---|---|
| PR admission | Yes (CCE-109) |
| Authoring batch loop (page-author fan-out) | Yes — per batch |
| Fact-checker loop | Yes — before starting the loop |
| Gap-detector loop | Yes — before starting the loop |

The authoring loop retains an **at-least-one-batch progress guarantee**: the runner always processes at least one batch even if the deadline is already soft-expired at loop entry. A tight budget that exhausted itself during PR admission still produces some authored output rather than a zero-page run.

The fact-checker and gap-detector loops do not carry this guarantee. If the budget is exhausted before either loop starts, the loop is skipped entirely.

## Why skipped verification flips `partial`, not a warning

When the fact-checker or gap-detector loop is skipped due to budget exhaustion, the run is marked `partial=true`.

This is load-bearing, not cosmetic. The CCE-101 auto-merge gate requires `partial == false` before it will squash-merge the docs PR. If fact-checking is skipped, the authored content has received no contradiction check — publishing it automatically removes the safety net that auto-merge depends on. Making the skip `partial=true` forces the PR into manual review, where a human can assess whether the content is safe to ship.

The same logic applies to the gap-detector: a run where gap flags were never assessed for this batch's new PRs cannot be represented as complete.

A warning-only approach would silently satisfy the `partial == false` gate and allow auto-merge to proceed on unverified content. That violates the invariant CCE-101 was built on.

## Relationship to CCE-101

CCE-101 specifies the full auto-merge eligibility contract:

> Eligible = `partial == false` AND zero fact-checker warnings AND no human commits on the PR.

CCE-114 ensures that a budget-exhausted run sets `partial=true`, which correctly gates this contract at the first condition. The fact-checker warning condition remains orthogonal: a fully-run fact-checker that finds contradictions withholds merge via the warning path; a skipped fact-checker withholds merge via the partial path.

## What did not change

The soft deadline value and the PR-admission check behavior from CCE-109 are unchanged. The CCE-101 auto-merge check-wait timing (`checks_grace_seconds: 120`, `checks_timeout_seconds: 900`) still bounds itself against the remaining CCE-109 budget, as specced.

Authoring pages that were completed before the budget expired are included in the PR normally. A partial run still opens the PR — it does not abort silently — so the work already done is visible and preservable by an operator who merges manually.
