---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/227
synthesized_into: []
doc_kind: decision
---

# CCE-152: cutting page authoring at a PR boundary

The CCE-109 soft time-budget check now cuts the page-authoring fan-out at a **PR boundary**, not at an arbitrary batch index. Before this fix, a host whose oldest PR in a window fanned out to more page batches than the time budget could author would truncate mid-PR on every single nightly — and never finish authoring it, so the baseline cursor could never advance past it.

## The symptom: a 20.6-day baseline stall

The ADIS host sat on one unmoved baseline for 20.6 days. Four consecutive nightlies authored only 1–5 of roughly 75 page batches, two of them re-authoring the identical four leading pages, and each one reported `time_budget_no_advance_no_cursor` in its `partial_reasons`.

That reason string is the CCE-140 cursor-backed advance refusing to move: `advance_cursor_list` (`scripts/orchestrator_runner.py:advance_cursor_list`) stops at the first PR still owing content, and `_last_processed_merge_sha([])` returns `None` when nothing qualifies. The stall wasn't a sizing problem — raising the time budget wouldn't have fixed it, because the run was cutting in the same place every night regardless of how much time it was given, for a structural reason described below.

## Root cause: a batch-level cut paired with a batch-level progress guarantee

CCE-114 added the authoring-loop time-budget check, but it fired at whatever batch index the clock happened to land on, guarded only by an `i > 0` at-least-one-progress escape scoped to **batches**.

That guarantee turned out to be the wrong unit. The authoring loop's `per_target` dict is built by walking the run's PRs oldest-first and calling `setdefault` per `(lens, page_hint)` doc target (`scripts/orchestrator_runner.py:run`) — `setdefault` never re-positions an existing key, so the resulting batch list is already grouped by the *oldest* PR that references each page: group(PR1), then group(PR2), and so on.

Cutting at an arbitrary batch index therefore splits whichever group the clock happens to land inside. When the window's oldest PR alone fans out to more pages than the budget can author, every run's cut lands inside group(PR1) — the same group, every night. PR1 never finishes, `advance_cursor_list` breaks at index 0 because PR1 is held back, and the baseline cannot move. `i > 0` guaranteed forward progress in units of *pages authored*, not in units of *PRs the cursor can advance past* — and the cursor is what CCE-140's auto-merge gate and the next window's lookback both depend on.

## The fix: PR-granularity cut, bounded by a hard cap

CCE-152 changes the unit of the progress guarantee from one batch to **one complete PR group**. The soft deadline may now only cut where the batch's owning PR changes:

```text
_at_boundary = _owner != _prev_owner
if _now > deadline and (_at_boundary or _past_hard):
    ...
    time_truncated = True
    break
```

A batch's owning PR is its oldest contributor — `batch_summaries[0]` in the grouped list above, since a page hint two PRs both touch yields a shared batch owned by whichever PR is older. `_prev_owner` still advances through `continue` paths (an `unknown_lens` or `unsafe_page_path` skip), not only through batches that actually author, so a skipped batch does not fabricate a false boundary inside the PR that follows it. The very first batch stays unconditional (`i > 0`), preserved from CCE-114.

This guarantees that whenever the deadline forces a stop, the run has authored a **complete prefix of PRs** — so the cursor is always non-empty and the baseline always has somewhere to advance to, unless the very first PR in the window is itself too large to finish (see the hard cap below).

Deferring to a PR boundary is unbounded on its own: one PR fanning out to twenty pages could run the authoring loop well past the GitHub App installation token's TTL. `resolve_authoring_hard_cap` (`scripts/orchestrator_runner.py:resolve_authoring_hard_cap`) bounds the overrun — `run.authoring_hard_cap_seconds` from config, or `time_budget_seconds * 1.15` by default — and clamps that value down against the token TTL ceiling (`GITHUB_APP_TOKEN_TTL_SECONDS` minus the merge-check poll minus a fixed post-run tail). Past the hard cap, the loop cuts inside the group rather than waiting for the boundary, and the run reports it cannot advance — the same standstill as before this fix, and never worse.

`authoring_hard_cap_seconds` is a new key in `run`'s block of `config.schema.json`, and `run` sets `additionalProperties: false` — the same schema strictness that makes a typo like `authoring_hardcap_seconds` fail loudly at config load rather than being silently ignored. That block also has no way to express "greater than a sibling field": the schema accepts any positive integer here and `resolve_authoring_hard_cap` is what actually rejects a cap at or below the budget, at startup, with exit 2. A host whose merge policy is `manual` never runs the merge-check poll, so its ceiling doesn't subtract that term (`test_a_manual_merge_host_is_not_charged_for_a_poll_it_never_runs`).

The resolver lands in one of three states, and the reason strings name which:

```text
time_budget_exceeded: authored 2/5 page batches (budget 2100s); deferring the rest
time_budget_exceeded: authored 2/5 page batches (hard cap 2415s over budget 2100s); cut inside PR #646, whose pages are now incomplete, so the baseline cannot advance to it
time_budget_exceeded: authored 2/5 page batches (hard cap held at budget 2700s by the App-token TTL); cut inside PR #646, whose pages are now incomplete, so the baseline cannot advance to it
```

The first two are the ordinary case (a clean boundary defer) and the bounded forced cut described above. The third is what a **stock-default host actually gets**: `DEFAULT_TIME_BUDGET_SECONDS` (2700s) plus the default 900s merge poll already fills the whole 3600s token with nothing left over, so the resolver holds the cap at the budget itself — a squeeze, not an error — and records an advisory `authoring_hard_cap_squeezed` reason rather than the ordinary "hard cap N over budget N" phrasing, which would read as a number over itself. Behavior on a squeezed host degrades to the pre-CCE-152 mid-group cut — never worse, never silent, and it does not flip `partial` beyond the ordinary time-budget reason. A cap that is merely narrowed by the TTL clamp (legal, not squeezed, but smaller than what it resolved to) gets its own advisory `authoring_hard_cap_clamped` reason naming the requested value, the resolved ceiling, and which config key or default ratio produced the original number — so an operator's config is never silently overridden without a trace.

An explicit `authoring_hard_cap_seconds` at or below the resolved budget is rejected as a config error (exit 2) rather than silently clamped up — equal collapses the hard deadline onto the soft one and quietly restores the pre-fix mid-group cut in exactly the place an operator was trying to configure it away.

## Verification

`tests/orchestrator/test_pr_boundary_authoring_cut.py` drives the fix end to end: a past-soft-deadline cut mid-group keeps running to the PR boundary and the baseline advances to it; a shared batch between two PRs is recognized as owned by the older one; a hard-cap cut still lands inside the group and reports that the baseline cannot advance; a skipped (`unknown_lens`) batch doesn't fabricate a spurious boundary; a squeezed stock-default host records its advisory without flipping `partial`; a merely-clamped cap is announced with all three numbers; a host-configured `authoring_hard_cap_seconds` loads through the real config schema and governs the cut; and the clamped (not the raw ratio) value is what actually bounds the runtime deadline. `tests/orchestrator/test_authoring_hard_cap_bounds.py` covers the cap resolver's clamping and squeeze arithmetic in isolation.

## See also

[Orchestrator](../architecture/orchestrator.md) documents the full soft-time-budget mechanism, including the other three checkpoints (PR admission, fact-checking, gap-detection) that this fix left unchanged.
