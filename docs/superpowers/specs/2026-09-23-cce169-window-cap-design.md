# CCE-169 — bound the review window so a stall drains instead of compounding

**Status:** design approved, not yet implemented
**Date:** 2026-09-23
**Ticket:** CCE-169 (narrowed — see Scope)
**Measured on:** `theoju/engineering-docs-agent` @ `13511b6`, 2026-09-22

## The problem

The review window has no upper bound. `orchestrator_runner.run` takes whatever
`source-collector` returns since `last_successful_run.head_sha`:

```python
prs = sources.get("prs", [])          # scripts/orchestrator_runner.py
prs = _order_prs_oldest_first(prs, ...)
window_prs = list(prs)
```

The only truncation is the time-based cut inside the admission loop, which fires
_after_ the run has already begun failing to keep up. Nothing bounds the input.

That makes a stall self-reinforcing, and the structure is always the same
whatever the proximate cause:

> baseline frozen → window widens by one day → next run finishes an even smaller
> fraction → still no cursor prefix → PR auto-closed → baseline frozen.

The cost of recovery grows every night the stall persists, so an incident that
starts as "slow" ends as "unrecoverable by any means except a hand write-off."

### Measured, this host

|                                |                                                                              |
| ------------------------------ | ---------------------------------------------------------------------------- |
| `last_successful_run.head_sha` | `37f2885` — 2026-08-13                                                       |
| Commits on `main` past it      | 22                                                                           |
| `deferral_counts`              | 18 PRs, every one pinned at 1                                                |
| Advisory agents, run #280      | `fact-checked 0/4`, `gap-checked 0/19`, both `time_budget_exceeded` at 2100s |

### Measured, ADIS (the originating incident)

Window reached **113 merged PRs / 152 page batches** over sixteen consecutive
green runs. Resolved only by advancing `last_successful_run.head_sha` by hand and
writing the skipped PRs off as a documented gap. Host ticket ADIS-583.

### Why it cannot be tuned out

Three different budget values appear in the evidence above and below, so they are
disambiguated here once: **2700** is the plugin's schema default
(`run.time_budget_seconds`), **2100** is what this host ran at in run #280, and
**2340** is the value ADIS had already reached — its documented ceiling, being
the largest for which `2340 + 900 + 300 + 60 = 3600` still fits the App token's
one-hour TTL.

The point is the ceiling, not any one host's setting: ADIS was already at the
maximum the token TTL permits and still authored 3 of 152 batches. Authoring time
can only be bought back by shortening the merge-check poll, and no plausible
amount of that closes a 152-batch gap while the window grows every day. A larger
budget is not a lever that exists.

## Decisions

**Bound the window by PR count, before admission.** The alternatives were days
since baseline and page batches. Days is a poor cost proxy — measured on this
host, a quiet day is 2 PRs and the busiest in 90 days was 6, a 3x spread, and
ADIS accrued ~7.5/day during its stall. Page batches is the truest cost unit but
is not known until after `pr-summarizer` runs, so it can only be applied mid-run,
which is approximately where `time_budget_seconds` already cuts — and that
mechanism is the one this ticket exists because it fails.

A PR's page group is already the unit that must complete atomically (CCE-152 cuts
the authoring loop on PR boundaries), so PR count matches the thing that actually
has to finish.

**Default 10, on by default.** Measured over 90 days on this host: 67 PRs across
30 active days, median 2/day, p90 5, max 6. **No day in that window exceeded 10**,
so a healthy night is byte-identical to today with roughly 2x headroom over the
observed peak.

On-by-default breaks this repo's usual "empty by default keeps today's exact
behavior" precedent (`citation_source_roots`, `lint.external_repos`), and that is
deliberate. Every CCE-169 incident happened on a host that had configured
nothing; an opt-in guard against an unrecoverable failure is discovered by having
the failure. The precedent is right for features that add capability and wrong
for a guard against a silent, compounding loss.

**The error modes are asymmetric, so err low.** A cap set too tight emits a
`held_back_window_capped` reason every night — visible, mildly annoying,
trivially raised by an operator. A cap set too loose produces a silent stall,
which is the failure that cost 113 PRs of documentation. Given that asymmetry,
prefer the value that fails loudly.

## Config

```yaml
run:
  window_pr_cap: 10 # 0 disables
```

`templates/config.schema.json`, under `run`:

```json
"window_pr_cap": {
  "type": "integer",
  "minimum": 0,
  "description": "CCE-169: maximum merged PRs a single run admits, oldest-first. PRs beyond the cap are held for a later run: they are excluded from the advance cursor so the baseline stops at the cap boundary, and they do NOT accrue deferral counts, because they were never attempted. Default 10. 0 = unlimited, restoring the pre-CCE-169 unbounded window."
}
```

Resolved by `resolve_window_cap(config) -> int`, mirroring the existing
`resolve_deferral_threshold`.

## The cut

Applied after `_order_prs_oldest_first` and before `window_prs = list(prs)`.
Capped PRs go into a **new list**, not into `admission_deferred`:

```python
cap = resolve_window_cap(config)
window_capped: list[dict] = []
if cap and len(prs) > cap:
    window_capped = prs[cap:]
    prs = prs[:cap]
```

### The third category is the design

`admission_deferred` means _the run tried and ran out of time_. `window_capped`
means _the run deliberately did not try_. They have the same shape and different
causes, and per CCE-144 classification follows the **call site**, never the
resemblance. Routing them identically is the error this spec exists to avoid.

| Consumer                                | `admission_deferred` | `window_capped` | Why                                                            |
| --------------------------------------- | -------------------- | --------------- | -------------------------------------------------------------- |
| `held_back`                             | yes                  | **yes**         | The cursor must stop at the cap boundary                       |
| `window_prs` → `next_deferral_counts`   | yes                  | **no**          | Out of window → count carries forward unchanged                |
| `_deferred_all` → `partition_deferrals` | yes                  | **no**          | The skip hatch must never abandon a PR the run did not attempt |

Each row is load-bearing:

**`held_back` — omitting it silently destroys content.** `held_back` is composed
as `set(deferred_pages_by_pr) | {admission_deferred numbers}` minus skips. A bare
`prs = prs[:cap]` puts capped PRs in neither set, so `held_back` is empty,
`time_truncated` is False, CCE-151's walk is never entered, and control reaches
the `else` branch where `advance_sha = current_run.head_sha` — **full window
HEAD**. The run would document 10 PRs and advance the baseline past all 22,
losing 12 PRs' content permanently and silently. That is the CCE-151 incident
reproduced inside a change meant to prevent stalls.

**`window_prs` — including it would abandon PRs for being scheduled.**
`next_deferral_counts` increments any PR that is in the window and still
deferred. A capped PR is "deferred" in the loosest sense, so including it would
tick its counter every night it waits, and after `deferral_skip_threshold` nights
the skip hatch would abandon it — for the sole offence of being eleventh.
Excluding it takes the `not in this window at all → carried forward unchanged`
branch, which is already correct.

**`_deferred_all` — including it exposes untried PRs to the skip hatch.**
`_deferred_all = list(admission_deferred) + [page-deferred PRs]` feeds
`partition_deferrals`. A capped PR carrying a count at threshold from earlier
genuine deferrals would be abandoned without this run ever attempting it.

## Why this converges

`held_back` non-empty → CCE-151's cursor walk runs → the cursor stops at the cap
boundary → `advance_cursor_backed=True` → CCE-140's carve-out
(`if partial and not advance_cursor_backed`) permits the auto-merge →
`state.json` is promoted to the default branch → the baseline advances → the next
run takes the next `cap` PRs.

Against this host's measured 2.2 PRs/day accrual, a cap of 10 drains the current
22-PR backlog in roughly three nights. That is the property today's mechanism
lacks: CCE-178's stall escape forgives exactly one PR per stalled night, which
does not converge against a window that keeps filling.

## Reporting

One reason, `degraded=True`:

```
held_back_window_capped: 12 of 22 PRs held for a later run (cap 10)
```

`degraded`, not `blind`: the run **held back** what it did not process, which is
CCE-144's definition. Deliberately **not** the `time_budget_*` family —
`tests/orchestrator/test_time_budget.py` and `test_deferral_skip.py` assert those
strings exactly, and the CCE-109/CCE-140 runbooks tell operators to grep for
them.

Not in `_MERGE_VETO_REASON_PREFIXES`: a capped run is the healthy case and must
merge, or the cap accomplishes nothing.

## The docstring this invalidates

`next_deferral_counts` justifies its carry-forward branch with:

> "Growth is bounded because a PR leaves the window only once the baseline passes
> it, which requires it to be in the cursor prefix, which requires it not to be
> deferred."

Under a cap a PR leaves the window without the baseline passing it. The
**behaviour** stays correct — carry-forward is exactly right for a PR that was
never attempted — but the **stated reason** becomes false, and growth is now
bounded by the cap instead. Corrected in the same change. Per CCE-127's
`_TEMPLATE_ONLY_DIVERGENCES` lesson, a written-down justification that nobody
re-examines is worse than none, because it converts an unexamined gap into an
accepted one.

## Guards and degradation

**Bare-host / opt-out.** `window_pr_cap: 0` restores the unbounded window and the
tree is byte-identical. A host whose window never exceeds the cap takes the same
code path as today — `window_capped` stays empty and nothing is added to
`held_back`.

**The cap cannot advance past what it documented.** The advance is cursor-backed
on every path (CCE-151), and capped PRs are in `held_back`, so the cursor
physically cannot walk past the cap boundary.

## Accepted risks

| Risk                                          | Behaviour                                | Why acceptable                                                                  |
| --------------------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------- |
| A host sustainably merges more than `cap`/day | Backlog never drains                     | Emits a `held_back_window_capped` reason every night; loud and trivially raised |
| Default changes behaviour for existing hosts  | A >10-PR night takes two runs            | Measured: 0 of 30 active days over 90 days exceeded 10 on this host             |
| A capped PR waits many nights                 | Documented later than it would have been | Its content is never lost; the cursor cannot pass it                            |
| Cap is set below a single PR's page group     | Run still cannot finish that group       | Out of scope — that is CCE-155 (see Scope)                                      |

## Rejected

- **Days since baseline.** Matches how operators describe the stall and how the
  alarm already measures it, but a terrible cost proxy: the same M gives a 3x
  spread on this host and far worse on a release-heavy one.
- **Page-batch cap.** Truest cost unit, but only knowable after summarization, so
  it cuts mid-run — approximately where `time_budget_seconds` already cuts, and
  that is the mechanism this ticket exists because it fails.
- **Off by default (`0`).** Zero regression risk and consistent with
  `citation_source_roots`, but it ships a fix for a bug it then does not fix:
  every incident hit an unconfigured host.
- **Default 25.** Never fires on a healthy day (max observed 6) — identical to 10
  there — but admits enough PRs on a stalled host to blow the budget and truncate
  anyway, leaving the cap inert in precisely the case it exists for. It buys the
  regression risk of on-by-default and returns none of the benefit.
- **Resetting `deferral_counts` to protect at-threshold PRs.** Explicitly named
  as an anti-pattern by CCE-169. `state.json`'s history records a prior manual
  reset of eleven entries; it buys "no doc loss" by removing the one mechanism
  that advances the cursor, and re-arms the same stall.
- **Putting capped PRs into `admission_deferred`.** The obvious reuse, and wrong
  for two of its three consumers — see "The third category is the design."

## Test plan

Red/green on the load-bearing claims, each of which must fail before the change:

1. **A capped run advances to the cap boundary, not to HEAD.** The CCE-151
   regression guard, and the most important test here: assert the resulting
   `advance_sha` equals the cap-boundary PR's `merge_sha` and is **not**
   `head_sha`.
2. **Capped PRs do not accrue deferral counts.** `deferral_counts` for a capped
   PR is byte-identical before and after the run.
3. **A capped PR already at threshold is not abandoned.** It must not appear in
   `skipped_prs`, because the run never attempted it.
4. **`window_pr_cap: 0` is a true no-op.** Byte-identical tree and identical
   reasons against a >cap window.
5. **A sub-cap window is untouched.** No `held_back_window_capped` reason, and
   the advance reaches HEAD exactly as today.
6. **A capped run still auto-merges.** `_maybe_auto_merge` is reached and does
   not return `skip("partial_run")`, since it is partial but cursor-backed.

Tests 1 and 6 are the pair that prove convergence; either failing means the cap
is inert or actively harmful.

## Scope

CCE-169's title covers two failures with one shape. This spec closes **only the
window-growth half**:

- **Closed here:** the window grows without bound, so recovery cost compounds
  nightly.
- **NOT closed here:** a single PR whose page group cannot finish within the
  budget. ADIS's quoted run authored `3/152` batches and reported
  `time_budget_no_advance_no_cursor` — it could not finish even the first PR's
  group, and a cap of 10 PRs would not have changed that by one batch. That case
  is **CCE-155** (resumable page groups), still in Backlog.

CCE-169 must be narrowed rather than closed outright, so CCE-155 is not quietly
buried under a "fixed" label.

## References

- CCE-140 — cursor-backed advance
- CCE-144 — blind vs degraded classification by call site
- CCE-151 — the cursor walk is entered on every path, not just the truncated one
- CCE-152 — the authoring cut lands on a PR-group boundary
- CCE-155 — resumable page groups (the other half; still Backlog)
- CCE-175 / CCE-178 — the deferral stall escape, one PR per stalled night
- CCE-109 — window exceeds job timeout, the first instance of this shape
- ADIS-583 — the originating host incident, resolved by write-off
