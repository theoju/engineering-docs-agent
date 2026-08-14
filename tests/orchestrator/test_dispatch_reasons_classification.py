"""CCE-144: _record_dispatch_reasons carries the blind/degraded classification."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402

_record_dispatch_reasons = orun._record_dispatch_reasons


def test_failed_dispatch_is_blind_by_default():
    state: dict = {}
    _record_dispatch_reasons(state, ["dispatch exploded"], ok=False)
    cr = state["current_run"]
    assert cr["partial"] is True
    assert cr["blind"] is True
    assert cr["blind_reasons"] == ["dispatch exploded"]


def test_failed_dispatch_marked_degraded_is_not_blind():
    state: dict = {}
    _record_dispatch_reasons(state, ["author gave up"], ok=False, degraded=True)
    cr = state["current_run"]
    assert cr["partial"] is True
    assert cr.get("blind", False) is False
    assert cr.get("blind_reasons", []) == []


def test_successful_dispatch_stays_advisory_even_when_degraded_is_set():
    """ok=True means info_only=True, which outranks degraded."""
    state: dict = {}
    _record_dispatch_reasons(state, ["retry 1 of 3"], ok=True, degraded=True)
    cr = state["current_run"]
    assert cr["partial"] is False
    assert cr.get("blind", False) is False


def test_empty_reasons_touches_nothing():
    state: dict = {}
    _record_dispatch_reasons(state, [], ok=False)
    assert state.get("current_run", {}).get("blind", False) is False
