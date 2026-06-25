---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/136
synthesized_into: []
doc_kind: architecture
---

# Nightly Run Partial Posture

When the orchestrator hits the CCE-109 soft deadline mid-run, it opens a PR with `partial: true` in the body rather than abandoning all work. This page explains what partial means, how to spot it, and what you should (and shouldn't) do.

## What triggers a partial run

The runner enforces a wall-clock soft deadline at three phases: page-author fan-out, fact-checker, and gap-detector. Before dispatching each authoring batch the runner checks whether the deadline has passed. If it has, remaining doc-target batches are deferred with a `time_budget_exceeded` reason and the run proceeds to lint and PR-open tail work. The fact-checker and gap-detector phases skip outright once the deadline is crossed at their entry point.

The page-author fan-out is the most expensive phase — up to 43 Opus dispatches per backlog window. Before PR #136, this loop never checked the deadline. Six consecutive scheduled nightlies (June 5–10, 2026) were killed by GitHub Actions' 60-minute job timeout instead, discarding an hour of work per run and advancing no state. Run 27263616736 confirmed that ~20 of 43 dispatches started after the 09:15:39 deadline and were orphaned on cancellation.

## How to recognize a partial run

A partial PR has `partial: true` in its body. The CCE-101 auto-merge gate rejects it — the PR stays open until a full run supersedes it.

The PR body also lists each deferred doc target with `time_budget_exceeded` next to it. Doc targets that completed authoring before the deadline land normally in the same PR; only targets not yet dispatched when the deadline fired are missing.

## What to do

**Do not merge a partial PR manually.** The next full nightly opens a new PR covering the deferred targets, and the D2 auto-close sweep removes the superseded partial PR once the new one merges.

**If partial runs repeat**, the backlog is outpacing the nightly window. Two levers:

- Narrow the `sources` window in `.engineering-docs-agent/config.yml` to reduce the per-run dispatch count.
- Reduce the number of agent-editable doc targets in `docs.agent_editable_paths` if some lenses are low priority.

**If the PR stays open for more than 24 hours**, trigger a manual nightly:

```bash
gh workflow run docs-agent-nightly.yml -f reason="manual re-run after partial"
gh run watch
```

The runner advances `state.json.last_successful_run` only after it completes without `partial: true`. A partial that never gets superseded leaves the clock frozen — new PRs in the sources window accumulate but are not picked up until the window advances.

## Relationship to auto-merge

Auto-merge (CCE-101) has three eligibility conditions: non-partial, zero fact-checker warnings, and no human commits on the PR. A partial run fails the first condition regardless of the other two. The PR stays open and `state.json.last_successful_run` does not advance until the partial is superseded by a full run that merges cleanly.

Hosts that set `merge: {policy: manual}` in config still see the same `partial: true` flag — the gate logic is shared; only the merge action differs.

See `docs/superpowers/specs/2026-06-10-cce101-merge-gate-design.md` for the full auto-merge gate spec. The enforcement design across all three phases — deadline check placement, monotonic clock, and TDD coverage — is covered in `docs/site-src/architecture/orchestrator-time-budget.md`.
