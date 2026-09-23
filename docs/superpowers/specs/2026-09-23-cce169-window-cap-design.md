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

**Default 10, on by default.**

Every figure below is over a **pinned** window, `2026-06-25..2026-09-23` on
`origin/main`, so it is reproducible rather than drifting with `--since="90 days
ago"`. An earlier draft quoted a sliding window and the day counts moved between
readings.

```bash
git log origin/main --since=2026-06-25T00:00:00Z --until=2026-09-23T00:00:00Z \
    --pretty='%cI|%s' | grep -E '\(#[0-9]+\)$'
```

**64 merge commits.** `pr_branch_filter` (`scripts/orchestrator_runner.py`,
`["docs-agent/*"]`; `agents/source-collector.md` documents it as a list of globs to
**exclude**) drops 17 `docs(agent): run` merges before the window is built, so the
orchestrator's actual population is **47**. Both are given, because they diverge:

| Population      | Bucketing       | Active days | Median | Max   | p90 (nearest-rank) |
| --------------- | --------------- | ----------- | ------ | ----- | ------------------ |
| All 64          | nightly-aligned | 30          | 2      | 6     | 3                  |
| **Admitted 47** | nightly-aligned | 22          | 2      | **5** | **4**              |
| All 64          | UTC calendar    | 28          | 1.5    | 8     | 4                  |
| Admitted 47     | UTC calendar    | 22          | 1.5    | 7     | 4                  |

**The binding claim is the last column of a fifth one that is not in the table: on
every population × bucketing combination above, `days_over_10` is 0.** That is what
the default rests on. Three notes on the rest, because an earlier draft of this spec
got each of them wrong in a way that pointed somewhere:

- **Read the admitted-47 row, not the all-64 one.** The headroom argument has to be
  made on the population the orchestrator sees. It makes the cap _safer_: peak drops
  6 → 5.
- **p90 is 4 on the admitted population — not 5 (the first draft) and not 3 (the
  first correction).** The 3 is real but belongs to the all-64 row; the first
  correction switched population for the headline and left p90 behind, which is the
  same error in the opposite direction. Neither value changes the choice of 10,
  which rests on the observed maximum and on nothing exceeding the cap, not on p90.
- **Bucketing is a stated convention, not a fact.** This spec buckets by the 07:07
  UTC nightly boundary, because that is the boundary a nightly run actually sees.
  Plain UTC calendar days give a higher peak (8 on all-64, 7 on admitted) and are
  equally defensible; the choice is declared here so nobody re-derives a different
  number and assumes one of us is wrong.

**The cap will fire on the very first run after this lands.** The current window is
22 commits past the baseline: 21 PR merges, 2 of them `docs-agent`, so **19 admitted
PRs against a cap of 10**. `held_back_window_capped` is therefore the **routine**
path during a drain, not an exotic branch. Test it as the common case; the sub-cap
pass-through is the rarer one while a backlog exists.

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
`run` block is `additionalProperties: false`. Omit this key and every host that
**writes** it — at `0` for the advertised opt-out, at any other value to retune the
cap — **hard-fails config load with exit 2** (`jsonschema.validate` inside
`load_config_validated`, `scripts/state_io.py`, raising `ConfigError`, which `run`
turns into `return 2`).

**The bare host is the one case the omission spares, and that is what makes it
dangerous.** A host that configures nothing writes no `run.window_pr_cap` at all,
resolves to the default 10 exactly as `resolve_deferral_threshold` resolves an absent
key, and loads clean. So the gap stays invisible on every unconfigured host and
surfaces only on the night an operator reaches for the opt-out to disable a cap that
is misbehaving — the worst possible moment for a config file to stop loading. It
therefore needs its own test (test 7 below), not a passing mention.

Precedent that this is a live hazard rather than a hypothetical:
**`run.deferral_stall_days` is already missing from this schema in this tree**, and
the suite is green because its only test bypasses schema validation. Setting that key
in a host config today fails the load. Filed as **CCE-184**; noted here because it is
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

A cap of 10 drains the current 19-PR backlog in **two nights** (night 1 admits 10
and holds 9; night 2 admits the 9 plus whatever accrued). The accrual figure that
matters is per **calendar** day, because the nightly runs every day whether or not
anything merged: **0.71/day** across all 64 merges, **0.52/day** across the admitted 47. An earlier draft quoted "2.2 PRs/day," which is the mean over _active_ days — a
different denominator that overstates accrual roughly 3x. The conclusion is
unaffected and in fact strengthened: drain rate is `cap - accrual` per night, and
10 − 0.71 is not meaningfully different from 10 − 2.2 against a backlog of 19.

That is the property today's mechanism lacks: CCE-178's stall escape forgives exactly
one PR per stalled night, which does not converge against a window that keeps
filling.

## Reporting

One reason, `degraded=True`:

```
held_back_window_capped: 9 of 19 PRs held for a later run (cap 10)
```

(19 is the admitted count for the current window — 21 PR merges past the baseline
less 2 `docs-agent` runs excluded by `pr_branch_filter`. The counts are `held` of
`admitted`, never of raw commits.)

`degraded`, not `blind`: the run **held back** what it did not process, which is
CCE-144's definition.

Deliberately **not** the `time_budget_*` family. An earlier draft of this spec
justified that with three claims that do not survive checking, corrected here so
nobody acts on them: `test_deferral_skip.py` asserts **no** `time_budget_*` reason
string at all (its only `time_budget` matches are the `time_budget_seconds=` kwarg);
the assertion sites are overwhelmingly Python `in` substring tests rather than exact
matches, so a prefix-sharing reason would not have broken them; and **no runbook
mentions `time_budget` at all** — `grep -rl time_budget docs/runbooks/` returns
nothing.

**Those three claims are not an artefact of this spec's drafting.** They are the
comment sitting immediately above `_rsn = "time_budget" if time_truncated else
"held_back"` in `scripts/orchestrator_runner.py`, and the same sentence is in
`CLAUDE.md`'s CCE-151 entry, which is where the draft copied it from. **Both must be
corrected in this change.** Measuring a justification false in a spec while leaving
it in the code is the same outcome by a shorter route: the next person weighing a
reason-string rename reads the comment, not this section. This is CCE-127's
`_TEMPLATE_ONLY_DIVERGENCES` lesson exactly — a written-down justification nobody
re-examines is worse than none, because it converts an unexamined gap into an
accepted one.

The strings genuinely must stay byte-identical, for two reasons the false ones
displaced: `tests/orchestrator/test_time_budget_authoring.py` and
`test_time_budget.py` pin five distinct `time_budget_exceeded:` prefixes including
their counts, and the family is quoted verbatim in five **published** pages
(`docs/site-src/architecture/orchestrator.md`, `whats-new.md`, and three archive
pages). A rename silently falsifies the published docs — which is a `citation_exists`
-shaped failure the linter cannot see, because these are prose strings, not paths.

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

## Stale justifications this change must correct

Two, not one. The second — the `_rsn` comment in `scripts/orchestrator_runner.py`
and the sentence it was copied from in `CLAUDE.md`'s CCE-151 entry — is under
**Reporting** above. The first follows.

### The `next_deferral_counts` docstring

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

| Risk                                          | Behaviour                                                                       | Why acceptable                                                                                                                                                                                                                                                                                                              |
| --------------------------------------------- | ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A host sustainably merges more than `cap`/day | Backlog never drains                                                            | Emits a `held_back_window_capped` reason every night; loud and trivially raised                                                                                                                                                                                                                                             |
| Default changes behaviour for existing hosts  | Fires on the first run here: 19 admitted PRs vs a cap of 10, ~2 nights to drain | The drain is the intended behaviour, not a regression — held PRs enter `held_back`, so the cursor stops at the cap boundary (CCE-151), no content is lost, and every held run says so via `held_back_window_capped`. Once drained the cap stops binding: no day in the pinned 90 exceeded 10 on any population or bucketing |
| A capped PR waits many nights                 | Documented later than it would have been                                        | Its content is never lost; the cursor cannot pass it                                                                                                                                                                                                                                                                        |
| Cap is set below a single PR's page group     | Run still cannot finish that group                                              | Out of scope — that is CCE-155 (see Scope)                                                                                                                                                                                                                                                                                  |

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
- **Default 25.** Never fires on a healthy day (max admitted 5) — identical to 10
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

1. **A capped run advances to the cap boundary, not to HEAD, and says so.** The
   CCE-151 regression guard, and the most important test here: assert the resulting
   `advance_sha` equals the cap-boundary PR's `merge_sha` and is **not** `head_sha`.

   **It must also assert the reason is PRESENT**, by list membership on the fully
   rendered line — token, both counts, and the cap — in the style of
   `tests/orchestrator/test_authoring_truncation_advance.py`, not the
   `any("..." in r for r in ...)` substring form, which would accept a line that
   misreported the counts. Nothing else in this plan distinguishes the right label
   from a wrong one or from no label at all, and **emitting nothing is the dangerous
   variant because it passes every other test**: on a healthy capped run CCE-151's
   walk takes its `if ok:` branch, which sets `advance_sha` and
   `advance_cursor_backed` without calling `add_partial`, so this site is the run's
   only signal that any PR was held. Without it the run is not `partial` at all, so
   test 6's gate (`if partial and not advance_cursor_backed`) holds vacuously,
   `test_classification_coverage.py` stays green on 46 instead of moving to 47, and
   the operator gets a green nightly whose baseline stopped short of HEAD with no
   explanation — the exact outcome the Accepted-risks table assumes away when it
   calls the cap "loud and trivially raised."

2. **Capped PRs do not accrue deferral counts.** `deferral_counts` for a capped
   PR is byte-identical before and after the run.
3. **A capped PR already at threshold is not abandoned.** It must not appear in
   `skipped_prs`, because the run never attempted it.
4. **`window_pr_cap: 0` is a true no-op.** Byte-identical tree and identical
   reasons against a >cap window.
5. **A sub-cap window is untouched.** No `held_back_window_capped` reason, and
   the advance reaches HEAD exactly as today.
6. **A capped run still auto-merges.** Assert `pr_merge` appears in the fake `gh`
   call log. Nothing weaker distinguishes "the gate opened" from "the gate opened and
   something downstream closed it": `_maybe_auto_merge` returns
   `skip("merge_vetoed", veto)` and then `skip("blind_run")` **before** it ever
   reaches `skip("partial_run")`, so "did not return `partial_run`" is equally true
   of a run vetoed by a `held_back_window_capped` entry mistakenly added to
   `_MERGE_VETO_REASON_PREFIXES`, and of one misclassified `blind` — neither merges,
   and both leave the cap inert. Pin the preconditions beside the merge assertion, as
   `tests/orchestrator/test_cursor_backed_merge.py::test_cursor_backed_partial_run_actually_merges_end_to_end`
   does: the run is partial, carries `held_back_window_capped`, and is cursor-backed.
   Otherwise the merge can pass for the wrong reason, since a run that is not partial
   at all also reaches the merge path under today's rules.
7. **The key survives schema validation.** A host config carrying
   `run: {window_pr_cap: 0}` loads without raising. This is not ceremony: the
   `run` block is `additionalProperties: false` in `templates/config.schema.json`,
   so a key absent from the schema is a **hard load failure with exit 2**, not an
   ignored field. Test 4's no-op assertion is unreachable until this passes. Goes
   beside the existing cases in `tests/schemas/test_config_schema.py`; assert on a
   successful load, never on a `ValidationError` count.
8. **The default is 10.** A direct unit assertion: `resolve_window_cap({}) == 10`
   **and** `resolve_window_cap({"run": {}}) == 10`, mirroring
   `test_deferral_skip.py::test_threshold_defaults_to_three` and
   `test_deferral_stall_escape.py::test_stall_window_defaults_to_threshold_plus_one_day`.

   **Without this test the whole suite is blind to the default value.** The largest
   window any existing fixture builds is **3 PRs** — every `fake_source_collector.json`
   in the tree tops out at 3, and each helper that rewrites them
   (`test_time_budget.py:_write_fakes_with_prs`, `test_deferral_skip.py:_window_prs`,
   the four-commit helper in `test_cursor_backed_merge.py`) keeps 3. So
   `len(prs) > cap` is False for any default ≥ 3 and no end-to-end test can observe
   it: tests 4 and 7 set the key to `0`, test 5 passes under any default including
   `0`, and tests 1–3 and 6 need a >cap window, which against these fixtures means
   setting the key explicitly. An implementer who writes
   `int(run_cfg.get("window_pr_cap") or 0)` — the shape the rejected "off by default"
   alternative takes — therefore ships that alternative with **every test green**.

Tests 1 and 6 are the pair that prove convergence; either failing means the cap
is inert or actively harmful. Tests 7 and 8 are the two that fail first if a piece
of the wiring is skipped, and both fail in ways that do not look like the cap: 7
looks like a config typo (see the Config section), and 8 does not fail at all
without being written, because no fixture is large enough to catch it.

## Scope

CCE-169's title covers two failures with one shape. This spec closes **only the
window-growth half**:

- **Closed here:** the window grows without bound, so recovery cost compounds
  nightly.
- **NOT closed here:** a single PR whose page group cannot finish within the
  budget. ADIS's quoted run authored `3/152` batches and reported
  `time_budget_no_advance_no_cursor` — it could not finish even the first PR's
  group. When that holds, the cap cannot manufacture a cursor: `advance_cursor_list`
  breaks at index 0 on the first `held_back` PR, `cursor is None`, and the baseline
  is unchanged — the capped PRs sit behind that break, so the walk never reaches
  them. **The _advance_ is what is identical capped or not; the run is not.** It
  emits an extra `held_back_window_capped` reason, and its shorter `window_prs`
  writes different `deferral_counts` and `pr_summaries` into `state.json`. Per the
  correction below it also returns the held PRs' `pr-summarizer` dispatches to the
  authoring loop, so it may author strictly more of the first group's batches — what
  it cannot do is _finish_ that group, which is what producing a cursor requires.
  That case is **CCE-155** (resumable page groups), still in Backlog.

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
