---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/114
  - https://github.com/theoju/engineering-docs-agent/pull/133
synthesized_into: []
---

# Nightly Cron Cadence

The docs-agent runs automatically once per day at **07:07 UTC** via `.github/workflows/docs-agent-nightly.yml`. Each run opens a new `docs-agent/YYYY-MM-DDTHH` branch and PR against the host repo's docs site. The runner never appends commits to a prior PR — each nightly is a fresh snapshot.

## Current status

The cron is **active** as of 2026-06-09 (PR #114). It was paused on 2026-06-04 (PR #108) and held until CCE-89 deliverables D1 and D2 landed. Since CCE-101 (2026-06-10), auto-merge is the default closure mechanism for nightly PRs — manual merging is the exception, not the routine.

## CCE-89 deliverables

Three deliverables were required before safely resuming the schedule.

**D1 — PR-body enrichment (PR #112, merged).** Each nightly PR body now surfaces the top-N changed pages, a file count by lens, and any `partial_reasons` inline. You can decide whether to merge in under 60 seconds without opening any individual file.

**D2 — Auto-close-stale (PR #113, merged).** Only the freshest docs-agent run stays open. When a new run completes, the runner closes any prior open docs-agent PR automatically. This structurally prevents the stale-PR pileup that triggered the original pause.

**D3 — Merge-gate decision (shipped, CCE-101, PR #133).** D3 weighed auto-merging a fully-green non-partial PR against publishing an operator-promotion runbook. The decision landed as the CCE-101 merge gate on 2026-06-10: auto-merge won. A nightly PR now merges itself when the run earned it; a defined set of left-open reasons replaces the runbook. PR #133 is the implementation: 41 new tests (TDD red-first), 1059 passed in the full suite.

## Operator procedure (since CCE-101)

Auto-merge is the default closure mechanism. A fully-green, non-partial, untouched-by-humans nightly PR merges itself and dispatches the Pages workflow — no morning ritual required.

### Eligibility and polling

The merge gate squash-merges a PR only when all of the following hold:

- `merge.policy` is `auto` (the default when no `merge:` block is present in config) or unset.
- `partial: false` — the run completed without gaps.
- Zero fact-checker warnings.
- No human commits on the PR branch.
- Sufficient CCE-109 budget remaining to cover the polling window.

Check polling uses `gh pr checks --json name,state,bucket` (the CCE-83 vocabulary). The gate waits up to 120 seconds for checks to register, then up to 900 seconds for them to settle. Both windows are bounded by the CCE-109 nightly-job budget so polling never blocks or overruns the workflow timeout.

After a successful squash-merge the orchestrator deletes the branch and explicitly dispatches the `publishing.build_workflow` configured in the host's `config.yml`. A `GITHUB_TOKEN` merge cannot fire `on: push` triggers — without the dispatch the site never redeploys.

The run digest gains a `merge_outcome` field describing what happened: `merged`, `skipped`, or the specific skip reason.

### Config

The `merge:` block in `config.schema.json` controls the policy. Absent config defaults to auto. To opt out:

```yaml
merge:
  policy: manual
```

The setup skill (`/engineering-docs-agent-setup`) asks for an explicit choice at scaffold time so new hosts are not silently enrolled in auto-merge.

### When a PR is left open

Every failure mode is info-only. The PR stays open, and the reason is recorded in the run digest and `current_run.partial_reasons`. The full reason table and per-reason operator actions live in the [merge-gate section of the nightly runbook](docs-agent-nightly.md#merge-gate-cce-101). In short: `policy_manual` means the host opted out, `fact_check_warnings` means verify the flagged page first, `human_edited` means finish the review you started, and the CI/infrastructure reasons mean fix the underlying problem and merge by hand.

After any manual merge, run `scripts/prune_merged_branches.py --apply` to clean up the local branch reference. Do not rebase or amend the docs-agent branch. Each branch has no rebase target — the `state.json.last_successful_run` baseline on main advances only when a docs-agent PR merges (each run writes the advance to its own branch; merge promotes it).

## Observation window (historical)

The cron resumed with D1 and D2 in place. A two-week window starting 2026-06-09 was planned to measure actual operator merge latency before committing to the D3 auto-merge vs promotion-runbook choice. CCE-101 superseded the window on 2026-06-10 by shipping auto-merge directly — the latency question is moot when the green path needs no operator at all.

## Re-pause procedure

If stale PRs accumulate again — multiple open `docs-agent/*` branches with `state.json` pinned at the same baseline SHA — pause the cron immediately:

1. Comment out the `schedule:` trigger in `.github/workflows/docs-agent-nightly.yml` and open a PR.
2. Sweep stale open docs-agent PRs: close them and archive their head SHAs under `.engineering-docs-agent/stale-prs-archive/pr-<N>.json`.
3. Identify and fix the structural cause before resuming. PR #108 is the canonical reference for this pattern.

Do not reopen the cron until the structural cause is resolved. "Just rebase the latest stale PR" is not a fix — each branch is a fresh snapshot with no shared rebase target.

## Manual trigger

To fire a run outside the schedule:

```bash
gh workflow run docs-agent-nightly.yml -f reason="<your reason>"
gh run watch
```

The `reason` field is a free-text label surfaced in the run summary. Auth uses the `CLAUDE_CODE_OAUTH_TOKEN` repo secret. Concurrent invocations queue rather than race.

## Related

- PR #108 — original cron pause
- PR #112 — D1 PR-body enrichment
- PR #113 — D2 auto-close-stale
- PR #114 — cron resume
- PR #133 — D3 merge gate implementation (CCE-101)
- CCE-89 — umbrella ticket for D1/D2/D3
- CCE-101 — the merge gate that closed D3 ([reason table](docs-agent-nightly.md#merge-gate-cce-101))
- CCE-109 — budget-awareness wired into the polling gate
- `docs/superpowers/specs/2026-06-10-cce101-merge-gate-design.md` — full design spec
- `docs/runbooks/release-and-rollback.md` — release and rollback ops
