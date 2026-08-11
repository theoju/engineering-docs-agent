# tests/orchestrator/test_deferral_skip.py
"""CCE-140: per-PR deferral counting, cursor narrowing, and the skip hatch.

The CCE-109 advance cursor is a PREFIX boundary: advancing the baseline to
PR k's merge sha declares every PR at index <= k done. So a PR this run did
not finish must stop the walk, and a PR the operator has decided to abandon
must not stop it. These tests pin both directions.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as orun  # noqa: E402


def _pr(n: int, sha: str | None = None) -> dict:
    d = {"number": n, "title": f"PR {n}", "url": f"https://github.com/o/r/pull/{n}"}
    if sha:
        d["merge_sha"] = sha
    return d


# ---------------------------------------------------------------------------
# advance_cursor_list
# ---------------------------------------------------------------------------


def test_cursor_list_is_whole_admitted_list_when_nothing_held_back():
    """Today's behaviour, pinned: no deferrals -> the cursor sees every
    admitted PR, exactly as _last_processed_merge_sha(prs) does now."""
    admitted = [_pr(1, "a"), _pr(2, "b"), _pr(3, "c")]
    out = orun.advance_cursor_list(admitted, [], held_back=set())
    assert [p["number"] for p in out] == [1, 2, 3]


def test_cursor_list_stops_at_first_held_back_pr():
    """PR 2 unfinished -> the cursor may only anchor on PR 1. Advancing to
    PR 3 would strand PR 2 outside every future window."""
    admitted = [_pr(1, "a"), _pr(2, "b"), _pr(3, "c")]
    out = orun.advance_cursor_list(admitted, [], held_back={2})
    assert [p["number"] for p in out] == [1]


def test_cursor_list_stops_at_the_first_held_back_pr_not_the_last():
    """Two held-back PRs: the boundary is the OLDEST, never the newest."""
    admitted = [_pr(1, "a"), _pr(2, "b"), _pr(3, "c"), _pr(4, "d")]
    out = orun.advance_cursor_list(admitted, [], held_back={2, 4})
    assert [p["number"] for p in out] == [1]


def test_cursor_list_refuses_everything_when_the_oldest_is_held_back():
    admitted = [_pr(1, "a"), _pr(2, "b")]
    assert orun.advance_cursor_list(admitted, [], held_back={1}) == []


def test_cursor_list_walks_into_the_deferred_tail_when_it_is_forgiven():
    """A PR the admission gate never reached is normally held back. When it
    has been forgiven (skipped), the walk continues into the tail so the
    baseline can finally move past it."""
    admitted = [_pr(1, "a"), _pr(2, "b")]
    tail = [_pr(3, "c"), _pr(4, "d")]
    out = orun.advance_cursor_list(admitted, tail, held_back={4})
    assert [p["number"] for p in out] == [1, 2, 3]


def test_cursor_list_does_not_walk_the_tail_when_an_admitted_pr_is_held_back():
    """Forgiveness of a tail PR must not leap over an unfinished admitted
    one — the boundary is still the oldest unfinished PR."""
    admitted = [_pr(1, "a"), _pr(2, "b")]
    tail = [_pr(3, "c")]
    out = orun.advance_cursor_list(admitted, tail, held_back={2})
    assert [p["number"] for p in out] == [1]


def test_cursor_list_empty_inputs():
    assert orun.advance_cursor_list([], [], held_back=set()) == []


# ---------------------------------------------------------------------------
# resolve_deferral_threshold
# ---------------------------------------------------------------------------


def test_threshold_defaults_to_three():
    assert orun.DEFAULT_DEFERRAL_SKIP_THRESHOLD == 3
    assert orun.resolve_deferral_threshold({}) == 3
    assert orun.resolve_deferral_threshold({"run": {}}) == 3


def test_threshold_reads_the_config_key():
    assert orun.resolve_deferral_threshold({"run": {"deferral_skip_threshold": 5}}) == 5


def test_threshold_zero_disables_skipping():
    assert orun.resolve_deferral_threshold({"run": {"deferral_skip_threshold": 0}}) == 0


def test_threshold_tolerates_a_malformed_run_block():
    """Same posture as resolve_merge_settings: a non-dict block falls back to
    the default rather than raising inside run()."""
    assert orun.resolve_deferral_threshold({"run": "nope"}) == 3
