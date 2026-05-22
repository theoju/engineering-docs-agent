"""CCE-20: add_partial gains an info_only flag.

When info_only=True, the reason is appended to partial_reasons but
current_run.partial is NOT flipped to True. The default (info_only=False)
preserves the existing behavior so call sites that don't opt in keep
flipping partial.
"""

from __future__ import annotations

from scripts.state_io import add_partial


def _fresh_state() -> dict:
    return {
        "current_run": {
            "started_at": "2026-05-21T22:00:00+00:00",
            "head_sha": "abc",
            "partial": False,
            "partial_reasons": [],
        }
    }


def test_add_partial_default_flips_partial_true():
    state = _fresh_state()
    add_partial(state, "source_collector_error: boom")
    assert state["current_run"]["partial"] is True
    assert state["current_run"]["partial_reasons"] == ["source_collector_error: boom"]


def test_add_partial_info_only_does_not_flip_partial():
    state = _fresh_state()
    add_partial(state, "stale_current_run_cleared", info_only=True)
    assert state["current_run"]["partial"] is False
    assert state["current_run"]["partial_reasons"] == ["stale_current_run_cleared"]


def test_add_partial_info_only_appends_to_existing_reasons():
    state = _fresh_state()
    state["current_run"]["partial"] = True
    state["current_run"]["partial_reasons"] = ["prior_failure"]
    add_partial(state, "stale_current_run_cleared", info_only=True)
    assert state["current_run"]["partial"] is True  # not lowered by info-only
    assert state["current_run"]["partial_reasons"] == [
        "prior_failure",
        "stale_current_run_cleared",
    ]


def test_add_partial_non_info_after_info_flips_partial():
    state = _fresh_state()
    add_partial(state, "stale_current_run_cleared", info_only=True)
    add_partial(state, "source_collector_error: real")
    assert state["current_run"]["partial"] is True
    assert state["current_run"]["partial_reasons"] == [
        "stale_current_run_cleared",
        "source_collector_error: real",
    ]
