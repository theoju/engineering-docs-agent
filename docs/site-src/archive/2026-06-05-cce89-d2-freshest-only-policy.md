---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/113
synthesized_into: []
doc_kind: decision
---

# Decision: Freshest-Only Policy for docs-agent PRs (CCE-89 D2)

**Date:** 2026-06-05  
**Ticket:** CCE-89 D2  
**PR:** [#113](https://github.com/theoju/engineering-docs-agent/pull/113)

## Context

Between 2026-05-30 and 2026-06-01, six unmerged docs-agent PRs accumulated against this repo. `state.json` was pinned at `bdf0da1a` because `last_successful_run` only advances on merge-to-main. Each nightly run opened a new `docs-agent/YYYY-MM-DDTHH` branch from that same stale baseline. Nothing closed the predecessors.

The result was six competing snapshots of identical (stale) content, none of which an operator could safely merge without discarding the others. The situation required a manual sweep: head SHAs were archived under `.engineering-docs-agent/stale-prs-archive/pr-{85,86,90,92,94,95}.json` and branches were retained for cherry-pick reachability.

## Decision

After creating a new docs-agent PR, the orchestrator runner immediately closes all previously open `docs-agent/*` PRs whose commits are exclusively bot-authored. At most one open docs-agent PR survives any nightly run.

This is the **freshest-only policy**.

## What "bot-authored" means

The composer inspects each open `docs-agent/*` PR's commit list via `GhClient.pr_view_commits`. A PR is eligible for auto-close only if every commit on it was authored by the bot identity — no human-authored commits. PRs with any human-authored commit are left open unconditionally.

This guard exists to avoid discarding manual edits that an operator may have pushed onto a docs-agent branch (corrections, frontmatter fixes, content additions). The cost of a false negative (leaving a stale bot PR open) is operator confusion. The cost of a false positive (closing a PR with human work on it) is data loss. The policy errs toward preservation.

## Implementation

The feature lives in `scripts/orchestrator_runner.py` as `_auto_close_superseded_docs_agent_prs`. The orchestrator calls it once, immediately after the new PR URL is confirmed.

Three new `GhClient` methods support it:

- `pr_list_docs_agent_open` — lists all open PRs whose head branch matches `docs-agent/*`.
- `pr_view_commits` — fetches the commit list for a given PR number, including author identity.
- `pr_close` — closes a PR and posts a standardized comment referencing the superseding PR number.

`FakeGhClient` stubs for all three support the fixture-driven dry-run test path without hitting the GitHub API.

## Failure semantics

Every stage of the auto-close loop (list, per-PR commit lookup, per-PR close) captures failures as `info_only` partial reasons. A failure in the hygiene step cannot flip a nightly run to `partial: true`. The docs content itself is the primary artifact; stale-PR cleanup is a best-effort side effect.

If the list call fails entirely, the runner logs the error and continues. If a per-PR commit lookup fails, that PR is skipped (left open, not closed). If a close call fails, the error is recorded but does not halt the loop.

## What this does not do

The auto-close runs only after a new PR is successfully created. It does not run as a standalone cleanup job. If a nightly run fails before creating a PR, no auto-close occurs and stale predecessors remain open until the next successful run.

The cron remains paused at `workflow_dispatch`-only until CCE-89 D3 (merge-gate decision) lands. The auto-close behaviour will be exercised on the next manually dispatched nightly or when the operator unpauses the cron.

## Alternatives considered

**Rebase the latest stale PR.** Not viable. Each branch is a fresh snapshot from the pinned baseline; there is no incremental delta to rebase onto. The cadence policy is the only durable fix.

**Close all open docs-agent PRs unconditionally.** Rejected. Discards human edits without warning. The bot-identity check is the minimum necessary guard.

**Run cleanup as a separate scheduled job.** Adds operational surface area without meaningful benefit. Coupling cleanup to PR creation keeps the invariant simple: one open PR per run, enforced at the point of creation.
