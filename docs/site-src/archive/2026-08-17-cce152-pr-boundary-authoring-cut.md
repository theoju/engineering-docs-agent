---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/227
synthesized_into: []
doc_kind: decision
---

# CCE-152: Authoring Cuts at a PR Boundary, Not a Batch Index

The ADIS host sat on one baseline for 20.6 days because the CCE-114 authoring-loop time-budget cut guaranteed progress in the wrong unit — one batch, not one PR — so a run whose oldest admitted PR fanned out to more page batches than the budget allowed split that PR's group on every single nightly and never advanced past it. CCE-152 moves the guarantee to one complete PR group and adds a bounded hard cap so the fix can't turn into an unbounded overrun of its own.

## The failure mode

`resolve_time_budget` (`scripts/orchestrator_runner.py`) computes one deadline for the whole run, and CCE-114 wired that deadline into the page-authoring fan-out with an `i > 0` at-least-one-progress escape — the loop always finishes the batch it's on before checking the clock, so it can never cut at index zero. That guarantee was scoped to **batches**, not to the PRs that own them.

`per_target`, the structure the authoring loop walks, is built by iterating admitted PRs oldest-first and `setdefault`-ing each `doc_targets` entry into it, so its batches already arrive grouped by the oldest PR that references each page: group(PR1), then group(PR2), and so on. Cutting at an arbitrary batch index therefore splits whichever group the clock happens to land inside. `advance_cursor_list` — the CCE-140 cursor that decides how far the baseline is safe to move — stops at the oldest PR with an incomplete page batch. When the split group belongs to the OLDEST admitted PR, that PR is incomplete every night, the cursor breaks at index 0, and the baseline cannot move at all. On the ADIS host this reproduced for four consecutive nightlies, each reporting `no_advance_no_cursor` and re-authoring the same leading pages it had already started the night before.

## Why the batch-level fix wasn't enough

CCE-114 closed the class of failure where authoring ran unbounded past the deadline entirely (six nightlies died at the workflow's hard kill with all work discarded). It did not distinguish between a cut that lands *between* two PRs' groups — harmless, the cursor advances cleanly — and a cut that lands *inside* one — the group is split and, if it's the oldest PR, the cursor can't move past it. Both looked identical to the loop: an index where the clock ran out.

## The decision: cut at PR boundaries

CCE-152 changes the unit of the at-least-one-progress guarantee from one batch to one complete PR group. The authoring loop now tracks the owning PR of the current and previous batch and only allows a soft-deadline cut where those differ — a PR boundary:

```python
if deadline is not None and i > 0:
    _now = clock()
    _past_hard = (
        authoring_hard_deadline is not None and _now > authoring_hard_deadline
    )
    _at_boundary = _owner != _prev_owner
    if _now > deadline and (_at_boundary or _past_hard):
        time_truncated = True
        break
```

A cut at a PR boundary always leaves a complete prefix of PRs behind it, so the cursor is non-empty and the baseline moves. `i > 0` still guards only the very first batch, preserving the original unconditional-progress escape.

Deferring the cut to the next boundary is unbounded on its own — a PR with an unusually large page fan-out could push the cut arbitrarily far past the soft deadline. `resolve_authoring_hard_cap` (`scripts/orchestrator_runner.py:resolve_authoring_hard_cap`) bounds that overrun. It resolves an explicit `run.authoring_hard_cap_seconds`, else defaults to `budget * 1.15`, then clamps the result against a ceiling: the GitHub App installation token's TTL (`GITHUB_APP_TOKEN_TTL_SECONDS`) minus the merge-check poll term this host will actually run, minus a fixed 285-second post-run tail. 285 was chosen as the largest reserve that still leaves a 2100-second budget its full 1.15× overrun; it has to cover more than a margin's worth of work, because the cut is checked at the top of each authoring iteration, before that iteration dispatches — the last admitted batch runs entirely past the hard deadline, on top of the site generators, the push, and the PR create that follow.

## Four resolver outcomes

`resolve_authoring_hard_cap` has four outcomes, each pinned by `tests/orchestrator/test_authoring_hard_cap_bounds.py`:

- **REJECTED** — an explicit `run.authoring_hard_cap_seconds` at or below the resolved budget raises a config error rather than silently collapsing the hard deadline onto the soft one (which would restore the exact mid-group cut this decision exists to prevent).
- **NORMAL** — the resolved cap fits under the TTL ceiling and is returned unchanged.
- **CLAMPED** — the resolved cap is narrowed to the ceiling; records an advisory `authoring_hard_cap_clamped` reason.
- **SQUEEZED** — the ceiling itself is at or below the budget, so the cap is held at the budget with no overrun at all; records an advisory `authoring_hard_cap_squeezed` reason. The stock `DEFAULT_TIME_BUDGET_SECONDS` default (2700s) lands here — a host that hasn't sized `run.authoring_hard_cap_seconds` gets no authoring overrun and the pre-CCE-152 cut behavior, never worse and never silent.

CLAMPED and SQUEEZED are both `info_only` and never flip `partial`; only REJECTED is a hard failure, and it fails at config load rather than mid-run. `run.authoring_hard_cap_seconds` is now a declared field in `templates/config.schema.json` — before CCE-152 the `run` block's `additionalProperties: false` silently rejected the key at load, so a host that had already discovered and set it from documentation aborted its nightly before the resolver ever ran.

## What this does not fix

CCE-152 makes the prefix-boundary invariant CCE-109 and CCE-140 already require actually reachable in the case that was breaking it — an oversized *leading* PR. It does not remove the underlying ceiling: a single PR whose own page group exceeds the authoring hard cap still stalls the cursor at that PR, because there is no smaller unit than "one PR" left to defer to. That residual case is tracked separately as ADIS-515 and is out of scope here.

## References

- PR #227.
- `scripts/orchestrator_runner.py:resolve_authoring_hard_cap` and the authoring-loop cut in `scripts/orchestrator_runner.py`.
- `templates/config.schema.json` — declares `run.authoring_hard_cap_seconds`.
- `tests/orchestrator/test_authoring_hard_cap_bounds.py` — pins the four resolver outcomes.
- `tests/orchestrator/test_pr_boundary_authoring_cut.py` — pins the PR-boundary cut behavior.
- `CHANGELOG.md` — CCE-152 entry with the full arithmetic derivation.
- Architecture reference: `docs/site-src/architecture/orchestrator.md`.
