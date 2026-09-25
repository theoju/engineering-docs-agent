---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/274
synthesized_into: []
doc_kind: decision
---

# CCE-175 / CCE-178: the deferral-skip stall clock

## Context

CCE-140 gave the orchestrator an escape hatch: a PR that keeps blocking the
authoring pipeline gets abandoned after `threshold` (default 3) consecutive
nightly deferrals, so the cursor can walk past it instead of freezing the
baseline forever. The counter lives in `state.json:deferral_counts`.

`state.json` only reaches `main` when the docs-agent PR merges. And the PR
does not merge while the run is `partial` and not cursor-backed — CCE-140's
own merge gate. A run is `partial` *precisely because* something is
deferred, which is the exact condition the counter exists to escape. Every
night, the run reads the same committed count from `main`, computes
`count + 1`, and writes it into a branch that never lands. The threshold is
unreachable by construction: a counter cannot be a precondition for the
escape from that counter.

This was observed on `theoju/claude-code-self-assessment`: the baseline
pinned at `175162e1` for five consecutive nights, with `deferral_counts` for
PR #235 and PR #236 recomputed to the same value every run because the write
never reached `main`.

## The fix: a wall-clock backstop

CCE-175 adds a stall clock keyed on a signal that was already on `main` and
had simply never been read: `last_successful_run.completed_at`.

`baseline_stall_days(state, now=)` (`scripts/orchestrator_runner.py:baseline_stall_days`)
returns the baseline's age in days, or `None` when it can't be determined — a
bootstrap host with no `last_successful_run`, a missing `completed_at`, or an
unparseable timestamp. Absence must never read as an infinite stall, or a
bootstrap host's very first run would forgive every PR in its window. A
`completed_at` in the future (clock skew) clamps to `0.0` instead of going
negative.

`resolve_deferral_stall_days(config)`
(`scripts/orchestrator_runner.py:resolve_deferral_stall_days`) derives the
stall window as `resolve_deferral_threshold(config) + 1` — not a separately
tunable constant. That keeps the clock strictly slower than the counter it
backs up: raise the threshold and the window follows for free. A host can
still override with `run.deferral_stall_days`, and a threshold `<= 0` (the
CCE-140 opt-out that disables skipping entirely) resolves the stall window
to `0` too, so turning the hatch off can't be quietly reopened by the clock.

When the baseline is older than the stall window, `partition_deferrals`
(`scripts/orchestrator_runner.py:partition_deferrals`) takes an explicit
`forgive` set of PR numbers and abandons them regardless of their own
consecutive-deferral count.

## Only the prefix blocker, not the whole window

The first version of the fix forgave every PR the stall window covered, and
it broke on its first live run — `35609168489`, 2026-09-21T13:59Z. The
cursor had admitted PRs `235, 236, 238, 240, 243, 246, 250, 249, 251, 252`
and deferred `235, 246, 249`; the escape forgave all three, including #246
and #249, which had been deferred for the *first time* that night, blocked
by an unrelated page, and had nothing to do with the stalled baseline. That
deleted the three chances the threshold is supposed to guarantee.

The narrower fix people reach for next — forgive only PRs whose count is
already nonzero — reopens the same deadlock from a different angle: a
first-time deferral sitting at the oldest cursor position blocks the prefix
at index 0, so nothing merges, so its own count can never reach 1, so it can
never qualify for forgiveness either.
`test_the_deadlock_breaks_once_the_clock_is_consulted`
(`tests/orchestrator/test_deferral_stall_escape.py`) pins exactly this shape,
walking ten simulated nights and asserting the run is forgiven on the fourth
— it caught the count-gated draft before it shipped.

What holds: forgive only the single oldest deferred PR — the actual cursor
prefix blocker — one per stalled run, nothing else. A forgiven run records
an info-only `deferral_stall_escape: baseline has not advanced in Nd
(window Md); forgiving the oldest deferred PR #k so state can reach main`
reason, because forgiveness here is a deliberate, self-documenting choice,
not a malfunction.

## CCE-178: forgiving still wasn't enough to merge

The narrowed escape fired correctly on `35609168489` and the PR *still* did
not merge — `auto_merge_skipped: partial_run`. Two defects surfaced, both
introduced or left open by CCE-175:

**Defect 1.** Forgiving the blocker empties `held_back`, which routes the
watermark advance through the plain window-HEAD `else` branch
(see the cursor-backed advance section of `docs/site-src/architecture/orchestrator.md`).
That branch set `advance_cursor_backed = False` unconditionally, on the
assumption that an empty `held_back` only ever meant "nothing was deferred."
CCE-140's merge gate is `partial and not advance_cursor_backed`; a forgiven
run is still `partial` (the escape reason doesn't clear that), so the gate
kept skipping the merge. The escape had moved the run from one blocked path
to another without touching the thing that actually blocks it. The fix
narrows what `advance_cursor_backed` means on that branch to
`bool(skipped_numbers)`: an empty `held_back` is ambiguous between "nothing
was ever deferred" and "everything deferred was explicitly forgiven," and
only a run with a real, auditable skip counts as cursor-backed.

**Defect 2, and the test-fidelity lesson.** CCE-175's own end-to-end test
asserted `orun._LAST_ADVANCE_CURSOR_BACKED is True` and passed — but only
because it drove the run with `time_budget_seconds=100` against a small
window, which time-truncates and routes the run through the cursor-*walk*
branch, where the flag was already `True`. A stock nightly against a normal
window never time-truncates; production takes the `else` branch, where the
flag was `False`. The assertion was correct, the expected value was
correct, and the fixture was green — the defect shipped anyway, because the
test reached its assertion by a different code path than production runs.
Every end-to-end case added for this fix
(`tests/orchestrator/test_forgiven_run_merge_gate.py`) therefore runs with
`time_budget_seconds=0`, the shape that actually ran in production, and
says so in its docstring.

## The regression that mattered most

A stalled baseline with *nothing* deferred has to stay a clean run. It's the
single most important run in the cycle: holding nothing back makes it
cursor-backed, so it auto-merges, so it resets the very clock that was
stalled. An early draft emitted the stall-escape reason whenever the
baseline was old, independent of whether anything was actually being
forgiven — which flipped that clean run to `partial` and blocked the merge
that would have ended the stall, turning the escape hatch into a second
deadlock. The shipped version guards the reason on `_forgive` being
non-empty (the clock is stalled *and* a prefix blocker exists to forgive),
never on staleness alone.

## Verification

`tests/orchestrator/test_classification_coverage.py` enforces that every
blocking `add_partial` call site in `scripts/orchestrator_runner.py` and
`scripts/verify_runner.py` is explicitly classified `info_only` or
`degraded` — a bare call inherits the fail-safe blind default by accident.
The stall-escape reason is `info_only=True`; this test is the guard against
a future refactor silently dropping that classification and turning a
self-documented forgiveness back into a run-flipping failure.

## Consequences

- A host's deferral-skip hatch (CCE-140) now has two independent paths to
  arm: the original consecutive-deferral counter (works once `state.json`
  is actually landing on `main`), and the CCE-175 wall-clock backstop (works
  even while it isn't).
- The stall window is derived, not configured, by default — `threshold + 1`
  days — so raising `run.deferral_skip_threshold` on a host automatically
  widens the backstop window too.
- The fix addresses the orchestrator's *response* to a stalled baseline, not
  the underlying cause. The incident that motivated it was two genuine
  Tier-1 lint blocks (a frontmatter-less page and a cross-repo citation
  failure); a nightly that needs the stall escape every night is reporting a
  content bug, not a cursor bug.

## References

CCE-175 (2026-09-20), CCE-178 (2026-09-21). See also the "Deferral-skip
stall clock" and "A forgiven run must still count as cursor-backed
(CCE-178)" sections of `docs/site-src/architecture/orchestrator.md`.
