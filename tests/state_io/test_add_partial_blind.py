"""CCE-144: add_partial's blind/degraded semantics."""

from __future__ import annotations

import pytest

from scripts.state_io import add_partial


def _fresh() -> dict:
    return {}


def test_blocking_reason_is_blind_by_default():
    state = _fresh()
    add_partial(state, "source_collector_invalid: returned None")
    cr = state["current_run"]
    assert cr["partial"] is True
    assert cr["blind"] is True
    assert cr["partial_reasons"] == ["source_collector_invalid: returned None"]
    assert cr["blind_reasons"] == ["source_collector_invalid: returned None"]


def test_degraded_flips_partial_but_not_blind():
    state = _fresh()
    add_partial(state, "lint_block: page.md rule: msg", degraded=True)
    cr = state["current_run"]
    assert cr["partial"] is True
    assert cr.get("blind", False) is False
    assert cr["partial_reasons"] == ["lint_block: page.md rule: msg"]
    assert cr.get("blind_reasons", []) == []


def test_info_only_flips_neither():
    state = _fresh()
    add_partial(state, "gap_detector_unjudged: pr_id=7", info_only=True)
    cr = state["current_run"]
    assert cr["partial"] is False
    assert cr.get("blind", False) is False
    assert cr["partial_reasons"] == ["gap_detector_unjudged: pr_id=7"]
    assert cr.get("blind_reasons", []) == []


def test_info_only_wins_over_degraded():
    """Precedence: info_only is checked first and degraded is ignored."""
    state = _fresh()
    add_partial(state, "advisory thing", info_only=True, degraded=True)
    cr = state["current_run"]
    assert cr["partial"] is False
    assert cr.get("blind", False) is False


def test_blind_reasons_is_a_subset_of_partial_reasons():
    state = _fresh()
    add_partial(state, "blind one")
    add_partial(state, "degraded one", degraded=True)
    add_partial(state, "advisory one", info_only=True)
    cr = state["current_run"]
    assert set(cr["blind_reasons"]) <= set(cr["partial_reasons"])
    assert cr["blind_reasons"] == ["blind one"]
    assert len(cr["partial_reasons"]) == 3


def test_repeat_blind_reason_appends_once_to_each_list():
    state = _fresh()
    add_partial(state, "same reason")
    add_partial(state, "same reason")
    cr = state["current_run"]
    assert cr["partial_reasons"] == ["same reason"]
    assert cr["blind_reasons"] == ["same reason"]


def test_blind_reasons_are_redacted_identically():
    state = _fresh()
    add_partial(state, "clone failed: https://x-access-token:ghs_SECRET@github.com/o/r")
    cr = state["current_run"]
    assert "ghs_SECRET" not in cr["blind_reasons"][0]
    assert cr["blind_reasons"] == cr["partial_reasons"]


def test_a_degraded_run_that_later_goes_blind_stays_blind():
    """blind is monotonic within a run — one blind reason is enough."""
    state = _fresh()
    add_partial(state, "degraded first", degraded=True)
    add_partial(state, "blind second")
    add_partial(state, "degraded third", degraded=True)
    cr = state["current_run"]
    assert cr["blind"] is True
    assert cr["blind_reasons"] == ["blind second"]


def test_degraded_only_run_never_creates_the_blind_key_as_true():
    """A green-eligible run must not carry blind=True under any ordering."""
    state = _fresh()
    for i in range(3):
        add_partial(state, f"degraded {i}", degraded=True)
    assert state["current_run"].get("blind", False) is False


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"degraded": True}, {"info_only": True}],
    ids=["default", "degraded", "info_only"],
)
def test_seeded_current_run_is_not_clobbered(kwargs):
    """add_partial must preserve pre-existing current_run keys."""
    state = {
        "current_run": {"partial": False, "partial_reasons": [], "head_sha": "abc"}
    }
    add_partial(state, "reason", **kwargs)
    assert state["current_run"]["head_sha"] == "abc"
