---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/276
synthesized_into: []
doc_kind: decision
---

# CCE-178: A Forgiven Run Still Wasn't Merging

**Date:** 2026-09-22
**PR:** [#276](https://github.com/theoju/engineering-docs-agent/pull/276)
**Depends on:** CCE-175 (the stall clock this fixes), CCE-151 (the cursor-backed
watermark advance), CCE-140 (the deferral-skip hatch and its merge gate)

## The incident

CCE-175 shipped a wall-clock backstop for the CCE-140 deferral-skip hatch: a
PR that's been deferred long enough gets forgiven even if its own
consecutive-deferral counter never reaches the skip threshold. The reason that
counter can't reach the threshold on its own is structural — `state.json`
only reaches `main` when the docs-agent PR merges, and the PR doesn't merge
while the run is `partial` and not cursor-backed, which is exactly the
condition a stalled deferral creates. Every night recomputes the same count
into a branch that never lands.

The escape fired correctly on its first live run, `35609168489`
(2026-09-21T13:59Z), on `theoju/claude-code-self-assessment`:

```text
cursor: admitted=[235,236,238,240,243,246,250,249,251,252]
        deferred=[235,246,249] held_back=[none] skipped=[235,246,249]
        baseline_age=6.1d stall_window=4d
deferral_stall_escape: baseline has not advanced in 6.1d (window 4d);
                       forgiving 3 deferred PR(s) so state can reach main
```

And the PR still did not merge:

```text
docs-agent INFO: auto_merge_skipped: partial_run
```

Two defects, both introduced or left open by CCE-175, and neither visible
from the digest alone — the escape *looked* like it had worked.

## Defect 1: forgiveness didn't count as cursor-backed

Forgiving every deferred PR emptied `held_back`. An empty `held_back` routes
the watermark advance through the plain window-HEAD `else` branch in `run()`
(`scripts/orchestrator_runner.py:run`), and until this fix that branch set
`advance_cursor_backed = False` unconditionally — because before CCE-178, an
empty `held_back` only ever meant "nothing was deferred." CCE-140's merge
gate is `partial and not advance_cursor_backed`, and a forgiven run is still
`partial` (the escape reason doesn't clear that flag), so the gate kept
skipping the merge. The escape had moved the run from one blocked path to
another without touching the thing that actually blocks it.

The fix narrows what `advance_cursor_backed` means on that branch: it is now
`bool(skipped_numbers)` rather than a bare `False`. An empty `held_back` is
now read correctly as ambiguous between two different runs — nothing was ever
deferred, or everything deferred was explicitly forgiven — and only a run
that recorded a real, durable skip (in `skipped_prs`) counts as cursor-backed.
A clean run with nothing forgiven still reports `False`, unchanged from
before.

**Why the CCE-175 end-to-end test didn't catch this.** That test asserted
`orun._LAST_ADVANCE_CURSOR_BACKED is True` and passed, because its fixture
used a time-truncating clock (`time_budget_seconds=100`), which routes the
run through the cursor-*walk* branch, where the flag was already `True`.
Production ran with the default budget against a small window and never
truncated — it took the `else` branch, where the flag was `False`. The
assertion, the expected value, and the fixture were each individually
correct; the test still didn't exercise the code path production runs. Every
end-to-end case added for this fix, in
`tests/orchestrator/test_forgiven_run_merge_gate.py`, therefore sets
`time_budget_seconds=0` deliberately, and its module docstring says why.

## Defect 2: forgiving everything re-creates the deadlock it was meant to break

CCE-175's escape forgave *every* PR the stall window covered. In the
production run above, `#246` and `#249` were deferred for the first time —
blocked by an unrelated page — and abandoned immediately because a different,
older PR (`#235`) had stalled the baseline. The CCE-140 threshold promises
three consecutive deferrals before a PR is abandoned; the clock was deleting
that promise for PRs that had nothing to do with the stall.

The narrowing that looks obvious — forgive only PRs whose count is already
`>= 1` — reopens the same deadlock from a different angle. A PR deferred for
the *first* time at the oldest cursor position blocks the prefix at index 0,
so no cursor exists, so nothing merges, so its count can never reach 1, so it
can never qualify for forgiveness either. The counter can't be a
precondition for the escape from the counter — that's the same shape CCE-175
existed to fix in the first place, one layer down.
`test_the_deadlock_breaks_once_the_clock_is_consulted`
(`tests/orchestrator/test_deferral_stall_escape.py`) pins exactly this shape
and is what caught the count-gated draft before it shipped.

**The fix: forgive only the prefix blocker.** `partition_deferrals`
(`scripts/orchestrator_runner.py:partition_deferrals`) now takes an explicit
`forgive` set of PR numbers, replacing the CCE-175 boolean `stalled` flag.
The caller in `run()` scans the admitted PRs for the single oldest one that
is also deferred — the PR actually holding the cursor prefix — and forgives
only that one:

```python
_blocker = next(
    (p.get("number") for p in prs if p.get("number") in _deferred_numbers),
    None,
)
_forgive = {_blocker} if (_stalled and _blocker is not None) else frozenset()
```

One PR per stalled run is the minimum that restores progress. Everything
behind it keeps its full three chances, and once the baseline moves, the
clock resets and the ordinary counter governs again. `partition_deferrals`
stays order-independent — it just checks membership in `forgive` — and the
caller resolves window order, the same division of responsibility
`advance_cursor_list` already uses for the prefix-boundary invariant.

`tests/orchestrator/test_forgiven_run_merge_gate.py` pins the boundary
directly: a PR at zero deferrals is never forgiven on its own, a PR with
prior history is, and in a mixed window only the one with history is
abandoned while the other two keep waiting.

## What ships

- `advance_cursor_backed = bool(skipped_numbers)` on the non-truncated
  advance path, so a forgiven run is recognized as cursor-backed and reaches
  the CCE-140 merge gate instead of tripping `partial_run` a second time.
- `partition_deferrals(forgive=...)` replacing the CCE-175 `stalled` boolean,
  scoped by the caller to the single oldest deferred PR in window order.
- No change to the `deferral_stall_escape` reason's `info_only` status, to
  `baseline_stall_days` (`scripts/orchestrator_runner.py:baseline_stall_days`),
  or to `resolve_deferral_stall_days`
  (`scripts/orchestrator_runner.py:resolve_deferral_stall_days`) — the clock
  itself was correct; only what the run did with what the clock forgave was
  wrong.

## The transferable lesson

A test that reaches its assertion through a different code path than
production is not coverage, even when the reason string, the flag name, and
the expected value are all correct. The CCE-175 end-to-end test proved the
escape *fires*; it never proved the run that fired it could *merge*, because
its fixture never took the branch production actually runs. Whenever a flag
or a reason string is written at more than one call site, a regression test
needs to pin the site production reaches — not just the name it asserts —
and the fixture parameters that get it there belong in the test's own
docstring, not left implicit.

The narrower methodological point specific to this hatch: a release valve
gated on a counter must never let its own escape re-empty that counter's
preconditions for someone else. Forgiving the whole window looked like the
generous fix and was the one that broke first-time deferrals; forgiving
nothing until a PR earns its own count reopened the index-0 deadlock. The
fix that held is the narrowest one available — exactly the single PR
structurally responsible for the stall.
