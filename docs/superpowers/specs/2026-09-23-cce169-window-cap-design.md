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

**Default 10, on by default.** Measured over 90 days on this host: **67 merge
commits** across 30 active days, median 2/day, max 6 under nightly-aligned day
bucketing. No day exceeded 10.

Three corrections to that measurement, because an earlier draft of this spec
overstated it and the overstatement pointed the wrong way:

- **The relevant population is 50, not 67.** `pr_branch_filter`
  (`scripts/orchestrator_runner.py`) excludes 17 of those 67 before the window is
  built, so the headroom argument must be made on 50. This makes the cap _safer_,
  not less safe.
- **p90 is 3, not 5.** Nearest-rank p90 over the 30 buckets is 3 (interpolated
  3.2); the values 5, 5, 6 sit at ranks 28–30, around p93. The earlier figure
  overstated routine load, which argues for a _larger_ cap than the evidence
  supports — so the error was in the unsafe direction for the wrong reason.
- **"Max 6" depends on a bucketing convention that was never stated.** Under plain
  UTC calendar days the same data gives 29 active days and **max 8** (2026-08-08
  carried 8 merges). Both figures are defensible; this spec uses nightly-aligned
  bucketing, because that is the boundary a nightly run actually sees.

**The cap will fire on the very first run after this lands** — roughly 20 admitted
PRs against a cap of 10 — and would have fired on 2 of the 18 historical windows.
`held_back_window_capped` is therefore the **routine** path during a drain, not an
exotic branch. Test it as the common case; the sub-cap pass-through is the rarer
one while a backlog exists.

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

**The schema edit is load-bearing, not bookkeeping.** `templates/config.schema.json`'s
`run` block is `additionalProperties: false`. Omit this key and a host that writes
`window_pr_cap: 0` — the advertised opt-out, the entire bare-host degradation story,
and an operator's only way to disable a cap that is misbehaving — **hard-fails config
load with exit 2**. It therefore needs its own test (test 7 below), not a passing
mention.

Precedent that this is a live hazard rather than a hypothetical:
**`run.deferral_stall_days` is already missing from this schema in this tree**, and
the suite is green because its only test bypasses schema validation. Setting that key
in a host config today fails the load. Worth its own ticket; noted here because it is
the same defect this spec is one careless step away from repeating.

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

**`window_prs` — including it would ERASE a capped PR's deferral history.**
Note the direction: the danger is deletion, not over-counting. `next_deferral_counts`
increments only when a PR is in the window **and** in `still_deferred_numbers`; the
else branch is `out.pop(k, None)`, which **deletes the stored count**.

A capped PR cannot reach `still_deferred_numbers`. That set comes from
`partition_deferrals(_deferred_all, ...)`, and `_deferred_all` draws from exactly two
writers — `admission_deferred` (written only at the time-budget break) and
`deferred_pages_by_pr` (written only by the CCE-140 complement writer, which walks
`per_target`, built from `summaries`). The cut lands **before** the summarize loop,
so a capped PR is never summarized, is owed no pages, and reaches neither.

So including capped PRs in `window_prs` takes the **else** branch every night they
wait, wiping any genuine deferral history they had accrued earlier and permanently
disarming the CCE-140 skip hatch for them. That is a stall-prolonging bug of the
same class CCE-175/CCE-178 exist to fix — not an over-eager abandonment.

**These three rows are not independent, and an earlier draft of this spec claimed
they were.** Row 2's original rationale ("the skip hatch would abandon it") is only
reachable if row 3 is _also_ violated, because `partition_deferrals` never receives a
PR that row 3 keeps out of `_deferred_all`. Measured directly:
`next_deferral_counts(window={11,12}, still_deferred=set())` turns `{#11:2,#12:2}`
into `{}`, and `partition_deferrals([], counts={#11:3}, threshold=3)` returns
`([], [])` — an at-threshold PR absent from the deferred list is never skipped. An
implementer who concludes "including capped PRs in `window_prs` is harmless so long
as we keep them out of `_deferred_all`" — which the original rationale invites —
ships the erasure bug with every test green.

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
CCE-144's definition.

Deliberately **not** the `time_budget_*` family. An earlier draft of this spec
justified that with three claims that do not survive checking, corrected here so
nobody acts on them: `test_deferral_skip.py` asserts **no** `time_budget_*` string
at all; 24 of the 25 assertion sites are Python `in` substring tests rather than
exact matches, so a prefix-sharing reason would not have broken them; and there is
no CCE-109/CCE-140 runbook telling operators to grep for those strings. The real
exact-match assertion lives in `tests/orchestrator/test_authoring_truncation_advance.py`,
which the earlier draft did not name.

The decision stands on a different and better reason: a `time_budget_*` name would
be **factually wrong**. The cap is not a budget outcome — it fires before any clock
is consulted — so labelling it that way misreports the cause to the operator reading
the digest, which is the CCE-127 `outcome`-vs-`conclusion` failure in another costume.

**Do not route the new reason through `_rsn`.** CCE-151's `_rsn` helper generates the
existing `held_back_*` strings by selecting between the `time_budget_*` and
`held_back_*` families based on cause. The cap is neither of the conditions `_rsn`
discriminates, so passing it through produces `time_budget_window_capped` on a
truncated run — exactly the mislabel this section exists to prevent.
`held_back_window_capped` must be a plain literal.

**`tests/orchestrator/test_classification_coverage.py` will go red.** It pins an exact
count of `add_partial` call sites; this change adds one, so the expected count moves
46 → 47. That file's convention also requires an audit paragraph accompanying the
bump. Neither is optional, and neither was in the earlier test plan.

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
7. **The key survives schema validation.** A host config carrying
   `run: {window_pr_cap: 0}` loads without raising. This is not ceremony: the
   `run` block is `additionalProperties: false` in `templates/config.schema.json`,
   so a key absent from the schema is a **hard load failure with exit 2**, not an
   ignored field. Test 4's no-op assertion is unreachable until this passes. Goes
   beside the existing cases in `tests/schemas/test_config_schema.py`; assert on a
   successful load, never on a `ValidationError` count.

Tests 1 and 6 are the pair that prove convergence; either failing means the cap
is inert or actively harmful. Test 7 is the one that fails first if the schema
edit is skipped, and it fails in a way that looks like a config typo rather than a
missing feature — see the Config section.

## Scope

CCE-169's title covers two failures with one shape. This spec closes **only the
window-growth half**:

- **Closed here:** the window grows without bound, so recovery cost compounds
  nightly.
- **NOT closed here:** a single PR whose page group cannot finish within the
  budget. ADIS's quoted run authored `3/152` batches and reported
  `time_budget_no_advance_no_cursor` — it could not finish even the first PR's
  group. When that holds, the cap cannot manufacture a cursor:
  `advance_cursor_list` breaks at index 0, `cursor is None`, the baseline is
  unchanged, and the capped PRs' `held_back` membership is never even consulted.
  Byte-identical outcome, capped or not. That case is **CCE-155** (resumable page
  groups), still in Backlog.

**Correcting an earlier draft:** it justified the above with "a cap of 10 PRs would
not have changed that by one batch," which is false and misleading in a way that
matters. There is **one shared deadline for the whole run**, and the pr-summarizer
fan-out is charged against it before a single page is authored. Dropping 103 PRs
from the window returns 103 dispatches' worth of wall clock to the authoring loop,
so the cap can move `3/152` materially — it simply cannot guarantee the _first_
group completes, which is what producing a cursor requires.

The consequence is that **the cut's position is load-bearing**: it must land after
`_order_prs_oldest_first` and before the summarize loop, so that capped PRs cost no
`pr-summarizer` dispatch at all. An implementer who believes "the cap does nothing
when PR #1 is the problem" may cap later — on `summaries` or `per_target` — which
looks identical in every sub-cap test and throws away most of the benefit in exactly
the regime the cap was built for.

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
