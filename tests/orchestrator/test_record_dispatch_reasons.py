"""CCE-118: `_record_dispatch_reasons` records benign rescue reasons info_only
(no partial flip) and genuine-failure reasons as partial-flipping."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import orchestrator_runner as runner  # noqa: E402


def _fresh_state() -> dict:
    return {"current_run": {"partial": False, "partial_reasons": []}}


def test_ok_true_records_info_only_no_partial_flip():
    state = _fresh_state()
    runner._record_dispatch_reasons(
        state, ["prose_contamination_rescued: page-author"], ok=True
    )
    assert state["current_run"]["partial"] is False
    assert (
        "prose_contamination_rescued: page-author"
        in state["current_run"]["partial_reasons"]
    )


def test_ok_false_flips_partial():
    state = _fresh_state()
    runner._record_dispatch_reasons(
        state,
        ["schema_invalid: page-author: 'ok' is a required property"],
        ok=False,
    )
    assert state["current_run"]["partial"] is True


def test_empty_reasons_noop():
    state = _fresh_state()
    runner._record_dispatch_reasons(state, [], ok=True)
    assert state["current_run"]["partial"] is False
    assert state["current_run"]["partial_reasons"] == []
