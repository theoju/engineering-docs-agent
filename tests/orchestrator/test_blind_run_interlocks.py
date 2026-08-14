"""CCE-144: the three consumers of the blind flag — exit code (Task 4),
watermark advance (Task 5), auto-merge gate (Task 6)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402


# --------------------------------------------------------------------------
# Task 4 — exit code
# --------------------------------------------------------------------------


def test_exit_code_is_1_when_blind():
    assert orun._exit_code({"current_run": {"partial": True, "blind": True}}) == 1


def test_exit_code_is_0_when_degraded_only():
    assert orun._exit_code({"current_run": {"partial": True}}) == 0


def test_exit_code_is_0_on_a_clean_run():
    assert orun._exit_code({"current_run": {"partial": False}}) == 0


def test_exit_code_is_0_when_current_run_is_absent():
    """Defensive: an early return before current_run exists must not crash."""
    assert orun._exit_code({}) == 0


def test_exit_code_treats_explicit_false_as_not_blind():
    assert orun._exit_code({"current_run": {"blind": False}}) == 0


# --------------------------------------------------------------------------
# Task 5 — watermark interlock
# --------------------------------------------------------------------------


def _advance(state: dict, *, advance_sha: str, now: str, time_truncated: bool):
    """Mirror of the guarded advance in run(), exercised directly.

    run() is a ~1000-line function whose advance sits behind a full fixture
    dispatch; this pins the guard's logic in isolation.
    """
    if orun._should_advance_watermark(state):
        state["last_successful_run"] = {"head_sha": advance_sha, "completed_at": now}
        if time_truncated:
            state["last_successful_run"]["window_head_sha"] = state["current_run"][
                "head_sha"
            ]


def test_blind_run_does_not_advance_the_watermark():
    state = {
        "last_successful_run": {"head_sha": "old", "completed_at": "t0"},
        "current_run": {"partial": True, "blind": True, "head_sha": "new"},
    }
    _advance(state, advance_sha="new", now="t1", time_truncated=False)
    assert state["last_successful_run"] == {"head_sha": "old", "completed_at": "t0"}


def test_blind_truncated_run_does_not_write_window_head_sha_into_the_old_cursor():
    """The time_truncated block mutates last_successful_run in place. If it
    escapes the guard, a blind run corrupts the cursor it must not touch."""
    state = {
        "last_successful_run": {"head_sha": "old", "completed_at": "t0"},
        "current_run": {"partial": True, "blind": True, "head_sha": "new"},
    }
    _advance(state, advance_sha="new", now="t1", time_truncated=True)
    assert "window_head_sha" not in state["last_successful_run"]
    assert state["last_successful_run"]["head_sha"] == "old"


def test_degraded_run_still_advances():
    state = {
        "last_successful_run": {"head_sha": "old", "completed_at": "t0"},
        "current_run": {"partial": True, "head_sha": "new"},
    }
    _advance(state, advance_sha="new", now="t1", time_truncated=False)
    assert state["last_successful_run"]["head_sha"] == "new"


def test_degraded_truncated_run_still_records_window_head_sha():
    state = {
        "last_successful_run": {"head_sha": "old", "completed_at": "t0"},
        "current_run": {"partial": True, "head_sha": "new"},
    }
    _advance(state, advance_sha="cursor", now="t1", time_truncated=True)
    assert state["last_successful_run"]["window_head_sha"] == "new"


def test_clean_run_advances():
    state = {
        "last_successful_run": {"head_sha": "old", "completed_at": "t0"},
        "current_run": {"partial": False, "head_sha": "new"},
    }
    _advance(state, advance_sha="new", now="t1", time_truncated=False)
    assert state["last_successful_run"]["head_sha"] == "new"


def test_should_advance_is_true_when_current_run_is_absent():
    assert orun._should_advance_watermark({}) is True
