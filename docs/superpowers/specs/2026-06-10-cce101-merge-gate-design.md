# CCE-101: docs-agent merge gate — auto-merge by default, setup-time opt-out

- **Status:** approved (brainstorm 2026-06-10)
- **Ticket:** CCE-101 (final deliverable of the CCE-89 stale-PR remediation; D1 PR-body enrichment and D2 auto-close-superseded shipped earlier)
- **Decision:** docs-agent PRs auto-merge when fully green and non-partial. The behavior defaults to **on** — including for existing hosts whose config predates this feature — and the setup skill asks every new host explicitly.

## Problem

docs-agent PRs do not merge themselves, and `state.json.last_successful_run` only advances when the PR lands in main. An operator who skips a day gets a competing snapshot of the same stale baseline the next night, not an incremental delta. Six stale PRs accumulated this way between 2026-05-30 and 2026-06-01 (CCE-89). D2's auto-close keeps the PR list clean but does not advance state; only a merge does. The durable fix is to make merging the default behavior and manual review the opt-in.

## Decision summary

| Question                       | Decision                                                                                                                                                                                                    |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Eligibility gate               | `partial == false` AND zero fact-checker contradiction warnings. Gap flags stay advisory and never block.                                                                                                   |
| Host CI checks                 | Wait for checks if any register; if none register within a grace window, merge on the strength of in-run validation.                                                                                        |
| Default when config key absent | Auto-merge ON. Existing hosts flip on at next tag pickup with zero config edits.                                                                                                                            |
| Merge method                   | Squash + delete branch. Not configurable.                                                                                                                                                                   |
| Mechanism                      | Runner-side poll-and-merge in `orchestrator_runner.py` (approach A). No GitHub native `--auto` (needs repo settings a default host lacks), no separate gate workflow (silently dead on no-App-token hosts). |

### Why fact warnings block auto-merge but nothing else does

Under manual review, the CCE-110 fact-checker is warn-only because an operator reads the PR body before merging. Under auto-merge nobody reads anything before the page publishes, so a contradiction warning must demote the run to manual review — otherwise the guard exists but protects nothing. This does not change CCE-110's in-run semantics: pages are still never dropped, `partial` is still never flipped by fact warnings. The warning only withholds the _merge_, not the _content_.

## Config

New top-level `merge:` block in `.engineering-docs-agent/config.yml`, codified in `templates/config.schema.json`:

```yaml
merge:
  policy: auto # auto | manual
  checks_grace_seconds: 120 # wait for host CI checks to register
  checks_timeout_seconds: 900 # max wait for registered checks to settle
```

- Absent block, or absent `policy`, resolves to `auto`.
- Schema: `merge` is an object with `additionalProperties: false`; `policy` is an enum (`auto`, `manual`); the two timing fields are integers with `minimum: 0` and the defaults above.
- The setup skill (`skills/engineering-docs-agent-setup/SKILL.md` step 3) gains an explicit question: "Should nightly docs PRs auto-merge when fully green and non-partial, or stay open for your review?" Default answer `auto`. Setup always writes the explicit value, so scaffolded hosts never rely on the implicit default.

## Runner flow

New helper `_maybe_auto_merge(...)` in `scripts/orchestrator_runner.py`, called after the PR number is known on **both** PR-handling paths: fresh `pr_create` and append-commit to an existing same-day PR.

### Eligibility (all must hold, checked cheapest-first)

1. `merge.policy == auto` (a `manual` host short-circuits before any gh call).
2. `partial == false`.
3. `current_run.fact_check_warnings` is empty.
4. Existing-PR path only: no non-bot commits on the PR — reuse the D2 human-edit guard pattern (`_auto_close_superseded_docs_agent_prs`'s commit-author check). An operator mid-review is never yanked out from under.
5. The CCE-109 time budget has at least `checks_grace_seconds` remaining. Otherwise skip with `auto_merge_skipped: time_budget`.

### Check wait

- Poll `gh pr checks <N> --json name,state,bucket` every ~15 seconds. Parse with the `state`/`bucket` vocabulary (`state == 'FAILURE' || bucket == 'fail'` is red; `state == 'SUCCESS' || bucket == 'pass'` is green) — never `statusCheckRollup`/`conclusion` (CLAUDE.md, CCE-83).
- **Zero checks after `checks_grace_seconds`:** merge anyway. On hosts without the GitHub App token, docs-agent PRs trigger no host CI at all (GitHub suppresses workflow runs for `GITHUB_TOKEN` commits), so waiting for green would wait forever. The in-run validation — content-validator lint, `mkdocs build --strict`, citation checks — is the gate on those hosts.
- **Checks registered:** poll until all settle or `checks_timeout_seconds` elapses, bounded also by the remaining CCE-109 budget (whichever is tighter). Any red check → skip with `auto_merge_skipped: checks_failed`. Timeout → skip with `auto_merge_skipped: checks_timeout`.

### Merge and post-merge

- `gh pr merge <N> --squash --delete-branch`.
- After a successful merge, when `publishing.build_workflow` is configured: `gh workflow run <build_workflow>` (no `--ref` — gh dispatches against the host's default branch, generic for `master`/`trunk` hosts). This closes the `GITHUB_TOKEN` landmine — a merge performed with the default token does not trigger the host's `on: push → main` workflows, so without the explicit dispatch the docs land in main but the site never redeploys. `workflow_dispatch` is exempt from GitHub's recursion suppression, so the dispatch fires even under `GITHUB_TOKEN`.
- On App-token hosts the push trigger _does_ fire, so the explicit dispatch produces a duplicate deploy. Coalesce it with a `concurrency` group in `templates/workflow-pages.yml` (verify at implementation time; add if missing). A duplicated deploy of identical content is harmless either way.
- Dispatch failure → `pages_dispatch_failed` info reason. On App-token hosts the publish-verifier remains the safety net for an unpublished site; on `GITHUB_TOKEN` hosts it is NOT — `templates/workflow-verify.yml` triggers on `pull_request: closed`, which a `GITHUB_TOKEN` merge does not fire (the same recursion suppression). There the digest reason is the only signal.

### Known limitations (post-review fast-follow)

- **Ambiguous `pr_merge` failure:** `gh pr merge` performs the remote merge and then local cleanup (checkout default branch, pull, delete local branch). A failure in the local phase exits non-zero after the remote merge already succeeded — the gate then reports `merge_failed` and skips the pages dispatch even though the PR merged. Fix: on merge failure, re-query PR state; if merged, continue to the dispatch and emit a cleanup-warning reason instead.
- **No publish-verifier backstop on `GITHUB_TOKEN` hosts** (see above): consider dispatching the verify workflow explicitly post-merge, the same way the build workflow is dispatched.

### Signaling

- **Every auto-merge reason is `info_only=True`.** Mirroring D2: merge automation is hygiene, and no auto-merge outcome ever flips `partial`. The authoring run already succeeded by the time merging starts.
- The notifier digest gains a merge-outcome line: `merged @ <sha>` or `left open: <reason>`.

## Error handling & degradation

The failure posture is uniform: any problem downgrades to today's behavior — the PR stays open for the operator — never to a worse state.

- Merge command fails (race with a human merge, branch protection, network) → `auto_merge_failed: <stderr>` info reason; PR open; run still successful.
- `state.json` promotion needs nothing new. The state file is already committed inside the PR; auto-merge just makes `last_successful_run` land in main minutes after the run instead of ~24h later. A skipped auto-merge behaves exactly like the current manual flow.
- D2 auto-close remains the backstop when a PR is left open and superseded the next night.

## Testing

pytest, fixture-driven dry-run path; the gh client is monkeypatched. `GhClient` gains `pr_checks`, `pr_merge`, and `workflow_run` methods, each mocked per-case.

- Eligible + zero checks registered → merges after grace window; pages workflow dispatched.
- Eligible + checks settle green → merges. Checks fail → skip `checks_failed`. Checks never settle → skip `checks_timeout`.
- Ineligible, one test each: `partial=true`; fact warnings present; `policy: manual`; human-edited existing PR; budget exhausted. Each skips with the right info reason and `pr_merge` is never called.
- Absent `merge:` block behaves as `auto` — the default-on contract gets its own test.
- Merge failure and dispatch failure → info-only reasons; `partial` stays `false`.
- Schema: new `merge` block validates; an unknown `policy` value is rejected.

## Rollout & docs

- **CHANGELOG / release notes:** loud behavior-change entry — "docs-agent PRs now auto-merge by default; set `merge.policy: manual` to opt out."
- **CLAUDE.md:** rewrite the "docs-agent PRs do NOT auto-merge by design" bullet into the CCE-101 decision record (auto by default, gates, opt-out, this spec as reference).
- **Ops docs:** update `docs/site-src/operations/docs-agent-nightly.md` and `nightly-cron-cadence.md`. The operator-promotion content shrinks to "what to do when a PR is left open, and the reasons one can be."
- **Setup skill:** step-3 question per the Config section.
- **Orchestrator skill:** extend the "PR handling" section of `skills/engineering-docs-agent/SKILL.md` with the auto-merge step (eligibility, check wait, squash-merge, pages dispatch) so the skill doc and runner stay in sync.
- PR title carries `CCE-101` so the Jira transition workflow closes the ticket on merge. This also retires the last open deliverable of CCE-89.

## Out of scope

- CircleCI check polling (CCE-63 owns non-GitHub CI).
- Making the merge method configurable.
- Auto-merge for any PR other than the docs-agent's own `docs-agent/*` branches.
