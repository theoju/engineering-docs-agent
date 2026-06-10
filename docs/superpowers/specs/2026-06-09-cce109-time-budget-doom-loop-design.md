# CCE-109 — Time-budget soft deadline to break the nightly doom loop (design)

**Ticket:** CCE-109 (Bug)
**Date:** 2026-06-09
**Status:** Approved (brainstorm complete; "approve as-is"). Implementation plan next.

---

## Problem

The nightly docs-agent run processes the entire window
`last_successful_run.head_sha .. HEAD` in a single GitHub Actions job. When that
window is large, the run exceeds the job's hard wall-clock limit and is killed
**before** it reaches the state-advance and PR-open step — so nothing is
persisted, no PR opens, and the baseline never moves. The next nightly reads the
same stale baseline against an even larger window and dies the same way. The
failure is self-reinforcing: a **doom loop**.

This is not a hypothetical. Between 2026-05-30 and 2026-06-01 six unmerged
docs-agent PRs accumulated; `state.json` pinned at `bdf0da1a`, 39 commits stale;
every subsequent nightly was cancelled at the timeout (CCE-89, CCE-109). The loop
was broken **manually** on 2026-06-09 by advancing the baseline out-of-band
(PR #126, baseline → `68090590`). CCE-109 is the **durable** fix so the loop
cannot re-form on its own.

### Why the window grows (the feedback that drives the loop)

The baseline only reaches `main` when the docs-agent PR is **merged**
(`orchestrator_runner.py:1444` CCE-40: the on-disk advance lives on the
docs-agent branch until merge; CI's fresh `actions/checkout` discards an
un-pushed advance). docs-agent PRs do **not** auto-merge by design. So an
operator who skips merges for a few days lets the window grow one day at a time
— and once the window is big enough to blow the timeout, the run can no longer
even open the PR that would let the operator merge and reset it. The loop closes.

### Root cause (verified, exact)

The killer is **wall-clock**, not the advance logic. Grounding facts:

- The job runs with `timeout-minutes: 60` (`templates/workflow-run.yml:42`). The
  GitHub App token expires at ~1h, so the timeout is deliberately ≤60 min.
- `run()` processes **all** PRs in the window through a stage-major pipeline:
  source-collector → `for pr in prs:` pr-summarizer (`orchestrator_runner.py:1140`)
  → page-author batched per `(lens, page_hint)` → content-validator/lint →
  `for pr in prs:` gap-detector (`orchestrator_runner.py:1387`) → whats-new.
  Per-PR LLM dispatch cost scales with the number of PRs.
- The state advance and PR open happen **only after** the whole pipeline, at
  `orchestrator_runner.py:1449` (advance) and `:1460` (`open_or_append_pr`).
- A large window means the pipeline runs past 60 min and the job is **killed
  before line 1449** — so no advance, no PR, nothing on `main`.

> Important: the existing advance-on-partial contract is **not** the bug.
> CCE-62 (`tests/orchestrator/test_state_advancement_invariant.py`) and CCE-40 §7
> intentionally advance the baseline even on a _partial_ run, so the operator
> sees a "(partial)" PR and decides whether to merge. That contract is correct
> and stays. The doom loop is the distinct case where the run **never reaches**
> the advance step because it is killed first.

---

## Goal

Convert the all-or-nothing timeout into **bounded, incremental progress**: each
nightly processes as many PRs as fit within a soft time budget, then **always
finalizes cleanly** (advance the baseline to the last fully-processed PR, open or
append the PR) within the hard job limit. The window shrinks every night, so the
loop cannot persist.

### Non-goals (YAGNI — explicitly out of scope)

- **No second knob.** A single time-budget value is the only control. No
  max-PR-count cap, no per-stage sub-budgets, no adaptive per-PR cost estimation.
- **Not a guaranteed large-backlog drainer in one night.** CCE-109 prevents the
  loop from _re-forming_ in steady state. A massive accumulated backlog is still
  drained out-of-band by the operator (per `docs/runbooks/release-and-rollback.md`
  and the manual procedure used on 2026-06-09); CCE-109 then keeps it drained.
- **No change to the advance-on-partial semantics** (CCE-62 / CCE-40 §7) beyond
  _which SHA_ is chosen when the run is time-truncated.
- **No sub-PR granularity.** A PR is the atomic unit (see Known limitations).

---

## Locked decisions

1. **Stop condition = time-budget soft deadline.** Default **2700 s (45 min)**,
   configurable. "Soft" = checked only _between_ PRs, never interrupting an
   in-flight PR.
2. **Single admission gate** at the top of the pr-summarizer loop
   (`orchestrator_runner.py:1140`). When the deadline has passed and at least one
   PR is already admitted, stop admitting and truncate the PR set.
3. **Always admit ≥ 1 PR.** The deadline check is skipped for the first PR, so
   every run drains at least one PR. This _guarantees_ monotonic forward progress
   even if a prior stage already consumed the budget.
4. **On truncation, advance the baseline to the last fully-processed PR**, not to
   the window `HEAD`. When the whole window is processed, advance to `HEAD`
   exactly as today.

---

## Design

### Component 1 — Injectable monotonic clock

Add a monotonic time source the run captures once at start and a deadline derived
from it. Use `time.monotonic()` (immune to wall-clock skew), wrapped so tests
inject a fake.

- `run()` gains an optional `now_monotonic: Callable[[], float] | None = None`
  parameter, defaulting to `time.monotonic`. Tests pass a controllable stub.
- At run start: `budget = resolve_time_budget(config, cli)`; if `budget` is `None`
  or `<= 0`, the deadline is `None` (unlimited — today's behavior, fully
  backward-compatible). Otherwise `deadline = now_monotonic() + budget`.

Why monotonic, not `datetime.now`: the rest of `run()` uses UTC timestamps for
_recording_ (`now` at `:1041`); a _budget_ must measure elapsed wall-clock
immune to NTP steps, so it uses a separate monotonic source. The two do not mix.

### Component 2 — Deterministic oldest-first PR ordering (correctness requirement)

To advance to "the last fully-processed PR" without silently dropping work, PRs
must be processed **oldest-first** and admitted as a **contiguous prefix**.

Rationale: the baseline is a SHA cursor. If PRs were admitted out of order,
advancing to an admitted PR's `merge_sha` could move the cursor _past_ an
older, **un**admitted PR — whose `merge_sha` is then an ancestor of the new
baseline, so it falls outside the next window and is **lost forever**. Admitting
the oldest contiguous prefix guarantees every PR older than the cursor was
processed.

Implementation: compute the window's commit order once via
`git rev-list --reverse last_sha..head_sha` (oldest-first). Sort `prs` by the
index of each PR's `merge_sha` in that order. PRs missing `merge_sha`
(`merge_sha_missing`, already recorded by `_clip_prs_to_window`,
`orchestrator_runner.py:355`) sort **last** — they cannot serve as a cursor.
This ordering step runs after `_clip_prs_to_window` (`:1108`) and before the
summarizer loop (`:1140`). The single `rev-list` may be shared with the clip
helper (DRY) at the plan's discretion; the contract is "PRs are oldest-first
before admission."

### Component 3 — Admission gate + truncation propagation

At the top of the pr-summarizer loop, before dispatching PR _i_ (0-indexed):

```python
if deadline is not None and i > 0 and now_monotonic() > deadline:
    add_partial(
        state,
        f"time_budget_exceeded: admitted {i}/{len(prs)} PRs "
        f"(budget {budget}s); deferring PR #{prs[i]['number']} to next run",
    )
    prs = prs[:i]            # truncate so ALL downstream `for pr in prs` see it
    time_truncated = True
    break
```

`i > 0` enforces "always admit ≥ 1" (decision 3). Truncating the `prs` **list**
(not just `summaries`) is what makes the single gate sufficient: every downstream
per-PR stage reads from `prs` (gap-detector, `:1387`) or from `summaries`
(page-author batches, whats-new) which is built only from admitted PRs. No other
stage needs a gate.

`add_partial` marks the run partial (`current_run.partial = True`) and records a
human-readable reason — consistent with every other partial cause in `run()`.

### Component 4 — Advance-SHA selection

Replace the unconditional advance at `orchestrator_runner.py:1449`:

```python
if time_truncated:
    advance_sha = _last_processed_merge_sha(prs, repo_root, last_sha, head_sha)
else:
    advance_sha = state["current_run"]["head_sha"]   # full HEAD, unchanged
state["last_successful_run"] = {"head_sha": advance_sha, "completed_at": now}
```

`_last_processed_merge_sha` returns the `merge_sha` of the **newest admitted PR
that has a valid in-window `merge_sha`** (scan the admitted `prs` from the end).
Guards:

- If no admitted PR has a usable `merge_sha` (e.g., all `merge_sha_missing`), do
  **not** advance — keep the current baseline and record
  `time_budget_no_advance_no_cursor`. The window is retried next run; no
  regression, no loss.
- Assert the chosen SHA is within `last_sha..head_sha` (it is, by construction,
  since admitted PRs were clipped to the window). This is a cheap invariant
  guard, not a new behavior.

When **not** truncated, behavior is byte-for-byte today's: advance to `HEAD`.

### Component 5 — Configuration and CLI

- **Config:** a **new top-level optional `run:` block** holding run-execution
  settings, with `run.time_budget_seconds: 2700`. The config currently has no
  run-level settings block (top-level keys today: `docs`, `sources`, `trigger`,
  `gap_detection`, `voice`, `lint`, `publishing`, `notifications`, `site`), so
  `run:` is introduced here and left **out of `required`**. Absent block or key →
  built-in default (2700). Explicit `0` → unlimited (opt-out). Add `run` to
  `templates/config.schema.json` as an optional object with one optional integer
  property `time_budget_seconds` (≥ 0).
- **CLI:** `--time-budget-seconds INT` on `main()`
  (`orchestrator_runner.py:2342`), overriding config when supplied. `0` =
  unlimited. This lets the nightly workflow or an operator tune per invocation.
- **Default constant:** `DEFAULT_TIME_BUDGET_SECONDS = 2700` in
  `orchestrator_runner.py`, referenced by both resolvers so the number lives in
  exactly one place.
- **Generic-first:** the default applies to every host with no config change; the
  feature degrades to today's unlimited behavior when set to 0 or when `git
rev-list` is unavailable (same graceful-degradation path as
  `_clip_prs_to_window`).

### Component 6 — Observability

- The `time_budget_exceeded: admitted k/N …` partial reason flows through the
  existing `partial_reasons` → stderr (CCE-73/74) → PR-body partial banner
  (CCE-89 D1) plumbing. No new surface.
- The PR-body composer already renders "baseline X → current Y"; when truncated,
  `current Y` is the last-processed PR's `merge_sha`, so the operator sees the
  partial advance without opening `state.json`.

---

## Interaction with existing invariants

- **CCE-62 / CCE-40 §7 (advance on partial):** preserved. A time-truncated run is
  partial and still advances — only the _target SHA_ differs (last-processed PR
  instead of HEAD). The existing tests in
  `tests/orchestrator/test_state_advancement_invariant.py` must keep passing
  unchanged (their windows are small / single-PR, never truncated).
- **CCE-19 (`_clip_prs_to_window`):** unchanged. Ordering (Component 2) runs after
  clipping and consumes the same window definition.
- **No SHA regression:** advancing to an in-window `merge_sha` is always a
  descendant of `last_sha` and an ancestor of `head_sha` — the cursor only moves
  forward.

---

## Known limitations (documented, accepted)

1. **PR-level granularity.** The deadline is checked between PRs and never
   interrupts an in-flight PR, and decision 3 always admits ≥ 1. So a single
   pathological PR that alone exceeds the budget still runs to completion. This is
   the accepted residual; sub-PR splitting is out of scope.
2. **Single-gate wind-down is not separately budgeted.** The gate bounds _per-PR
   admission_ at the summarizer stage; the source-collector preamble and the
   page-author/gap-detector stages for the _admitted_ set then run unbudgeted.
   The soft (45 min) / hard (60 min) headroom absorbs steady-state wind-down
   (1–3 PRs author in minutes). A pathologically large admitted set on a first
   catch-up could still approach the hard limit — that scenario is handled
   out-of-band (Non-goals) and is a candidate for future multi-point gating (one
   knob, more check sites) if it ever bites in practice.
3. **Not a one-night backlog drainer.** Each run drains a contiguous oldest
   prefix; a large backlog drains over several nights. Guaranteed to _converge_
   (≥ 1 PR/run), not to finish in one run.

---

## Testing strategy (TDD)

All tests use the fixture-driven dry-run path with the production CLI dispatch
monkeypatched, and inject a **fake monotonic clock** so no test sleeps. New file:
`tests/orchestrator/test_time_budget.py`.

1. **Unlimited is unchanged.** Budget `0`/absent → no truncation; full window
   processed; advance to `HEAD`. (Pins backward compatibility.)
2. **Truncation advances to last-processed PR.** 5 in-window PRs, fake clock trips
   the deadline after 3 admissions → `prs` truncated to 3; baseline advances to
   PR #3's `merge_sha` (not HEAD); `partial == True`;
   `time_budget_exceeded: admitted 3/5` recorded; page-author/gap stages saw
   exactly 3 PRs.
3. **Always admit ≥ 1.** Clock already past deadline at the first PR → exactly 1
   PR admitted; baseline advances to PR #1's `merge_sha`. (Guarantees monotonic
   drain.)
4. **Oldest-first ordering.** PRs supplied newest-first → after ordering they are
   processed oldest-first; truncation cursor is the newest _admitted_ (not the
   newest in window). Assert no older PR is skipped.
5. **No usable cursor → no advance.** All admitted PRs `merge_sha_missing` under
   truncation → baseline unchanged; `time_budget_no_advance_no_cursor` recorded;
   no regression.
6. **Config/CLI resolution.** CLI `--time-budget-seconds` overrides config;
   config overrides default; `0` = unlimited; default = 2700. Unit-test
   `resolve_time_budget` directly.
7. **Graceful degradation.** `git rev-list` unavailable → ordering falls back
   (process in given order, no crash), mirroring `_clip_prs_to_window`'s
   git-missing path.

Existing `test_state_advancement_invariant.py` must remain green untouched
(regression guard on the preserved advance-on-partial contract).

## Verification ladder (per CLAUDE.md SDD fidelity gate)

Each implementation task declares post-conditions discharged externally:

- **Tier 0 (always):** `git status --porcelain` baseline diff vs
  `expected_touch_paths`; claimed-vs-observed cross-check.
- **Tier 1 (`verify_cmd`):** the new + existing pytest suites
  (`python3 -m pytest tests/orchestrator/test_time_budget.py
tests/orchestrator/test_state_advancement_invariant.py -q`).
- **Tier 2 (`red_green`):** each behavior test asserted **failing** before its
  implementation and **passing** after (TDD discriminator).

## Acceptance criteria

- [ ] Default run with a window larger than the budget finishes **under the 60-min
      hard limit**, opens/append the PR, and advances the baseline to the
      last-processed PR.
- [ ] Repeated runs monotonically drain the window (≥ 1 PR/run); the baseline
      never regresses.
- [ ] Budget `0`/absent reproduces today's behavior exactly (no truncation).
- [ ] All seven new tests pass; `test_state_advancement_invariant.py` unchanged
      and green; full `pytest` green.
- [ ] `mkdocs build --strict` unaffected (no docs-site change in this work).

## File-change map

- `scripts/orchestrator_runner.py` — clock param + deadline; `DEFAULT_TIME_BUDGET_SECONDS`;
  `resolve_time_budget`; oldest-first ordering; admission gate + truncation;
  `_last_processed_merge_sha` + advance-SHA selection; `--time-budget-seconds` CLI.
- `templates/config.schema.json` — new optional top-level `run` object with `time_budget_seconds` (integer ≥ 0).
- `tests/orchestrator/test_time_budget.py` — new suite (7 tests above).
- `docs/runbooks/release-and-rollback.md` _(or a docs follow-up)_ — one line noting
  the budget knob and that large backlogs still drain out-of-band.

## Rollout / rollback

- **Rollout:** ships with the default 2700 s active for every host immediately on
  release; no host config change required.
- **Rollback:** set `run.time_budget_seconds: 0` (config) or pass
  `--time-budget-seconds 0` to fully disable and revert to unlimited behavior,
  with no code change.
