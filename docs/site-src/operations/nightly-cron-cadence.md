---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/114
synthesized_into: []
---

# Nightly Cron Cadence

The docs-agent runs automatically once per day at **07:07 UTC** via `.github/workflows/docs-agent-nightly.yml`. Each run opens a new `docs-agent/YYYY-MM-DDTHH` branch and PR against the host repo's docs site. The runner never appends commits to a prior PR — each nightly is a fresh snapshot.

## Current status

The cron is **active** as of 2026-06-09 (PR #114). It was paused on 2026-06-04 (PR #108) and held until CCE-89 deliverables D1 and D2 landed.

## CCE-89 deliverables

Three deliverables were required before safely resuming the schedule.

**D1 — PR-body enrichment (PR #112, merged).** Each nightly PR body now surfaces the top-N changed pages, a file count by lens, and any `partial_reasons` inline. You can decide whether to merge in under 60 seconds without opening any individual file.

**D2 — Auto-close-stale (PR #113, merged).** Only the freshest docs-agent run stays open. When a new run completes, the runner closes any prior open docs-agent PR automatically. This structurally prevents the stale-PR pileup that triggered the original pause.

**D3 — Merge-gate decision (open, CCE-89).** D3 will decide between auto-merging a fully-green non-partial PR and publishing an operator-promotion runbook. D3 is still open. Until it lands, you promote each morning's PR manually after reviewing the enriched body.

## Operator procedure (D3 pending)

Each morning after 07:07 UTC:

1. Open the docs-agent PR. The body lists which pages changed and why.
2. If the run is not partial and checks are green, merge it.
3. After merging, run `scripts/prune_merged_branches.py --apply` to clean up the local branch reference.

Do not rebase or amend the docs-agent branch. Each branch has no rebase target — `state.json.last_successful_run` advances only on merge-to-main.

## Observation window

The cron resumed with D1 and D2 in place. The two-week window starting 2026-06-09 measures actual operator merge latency before the team commits to the D3 auto-merge vs promotion-runbook choice. If you merge promptly each morning, the data supports auto-merge in D3. If latency consistently exceeds 24 hours, D3 should instead produce a runbook.

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
- CCE-89 — umbrella ticket for D1/D2/D3
- `docs/runbooks/release-and-rollback.md` — release and rollback ops
