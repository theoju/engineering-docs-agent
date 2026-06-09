---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/108
synthesized_into: []
doc_kind: decision
---

# Decision: Docs-Agent Cadence Invariant and Cron Pause (2026-06-05)

**Date:** 2026-06-05  
**Ticket:** CCE-89  
**PR:** [#108](https://github.com/theoju/engineering-docs-agent/pull/108)  
**Status:** Cron paused; re-enable gated on CCE-89 deliverables D1–D3.

---

## What happened

The docs-agent state cursor (`state.json.last_successful_run`) pinned at commit `bdf0da1a` on 2026-05-29 and did not advance for six-plus days. No docs-agent PR merged during that window.

Because the design has no auto-merge and PR bodies did not surface enough context for operators to confidently approve, each nightly run opened a new branch (`docs-agent/YYYY-MM-DDTHH`) covering the same May-29-to-HEAD window rather than an incremental delta. Six redundant open PRs accumulated: #85, #86, #90, #92, #94, #95.

## Why each run opens a fresh branch — not an incremental delta

The docs-agent is a snapshot system. Each run reads `state.json.last_successful_run.head_sha`, collects everything merged since that SHA, authors pages, and opens a PR. The cursor only advances when that PR merges to `main`.

No run appends commits to a prior docs-agent PR. Each branch is independent. Rebasing a stale PR onto a newer branch is wrong: there is no rebase target, and even if there were, the content was authored against the stale baseline, not the current one. The only correct remediation is to merge or close existing PRs so the cursor can advance, then let the next nightly produce an accurate snapshot.

## What PR #108 did

PR #108 stopped the accumulation of competing snapshots by:

1. **Pausing the 07:07 UTC cron** in `.github/workflows/docs-agent-nightly.yml`. Manual `workflow_dispatch` runs remain available. The cron entry is commented out with a reference to CCE-89.
2. **Archiving the six stale PRs.** Head SHAs and metadata for #85, #86, #90, #92, #94, and #95 were written to `.engineering-docs-agent/stale-prs-archive/pr-{85,86,90,92,94,95}.json`. The branches were retained for cherry-pick reachability; the PRs were closed.
3. **Codifying the invariant in CLAUDE.md.** A plugin-conventions bullet now explains the merge-cadence design, why rebasing stale PRs is wrong, and what the re-enable gates are.

## Re-enable gates (CCE-89)

The cron resumes when all three CCE-89 deliverables land:

**D1 — PR-body enrichment.**  
The docs-agent PR body must surface enough context for an operator to make a confident merge decision without inspecting individual file diffs. This means: top-N changed pages, file count by lens, and any `partial_reasons` inline in the body.

**D2 — Auto-close-stale policy.**  
Only the freshest docs-agent run stays open. When a new nightly run completes, any prior open docs-agent PR is automatically closed with a note pointing to the replacement. This eliminates the competing-snapshot accumulation regardless of merge cadence.

**D3 — Merge-gate decision.**  
Define the promotion path explicitly: either auto-merge when the run is fully green and non-partial, or produce an operator runbook that makes the promotion decision deterministic. "No context, no merge" must not be the default outcome.

## What operators must not do

Do not propose rebasing the latest stale PR onto current `main`. Each docs-agent branch is a self-contained snapshot with no rebase target. Rebasing produces a PR whose content was authored against an old baseline while claiming to cover current changes — it is worse than closing the PR and waiting for the next nightly.

Do not re-enable the cron manually before D1, D2, and D3 are merged. Without D2 in particular, the next failure to merge within ~24h restarts the accumulation.

## Stale-PR archive location

The archived metadata lives under `.engineering-docs-agent/stale-prs-archive/`. Each file records the PR number, head SHA, branch name, and close date. The branches themselves (`docs-agent/2026-05-*`, `docs-agent/2026-06-0*`) are retained on origin for cherry-pick reachability.

## Invariant (canonical form)

> The docs-agent cursor advances only on merge-to-main. Each nightly opens a fresh branch covering everything since the last merged cursor. No run appends commits to a prior open PR. The only durable fix for accumulation is cadence policy (D2), not rebase.

This invariant is now in `CLAUDE.md` under "Plugin conventions" and is the authoritative written policy for this design decision.
