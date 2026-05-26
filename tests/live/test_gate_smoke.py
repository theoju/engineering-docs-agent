"""Verify the @pytest.mark.live gate works. These do NOT call the LLM —
they're sanity checks that default-skip and `-m live` opt-in behave."""

import pytest


@pytest.mark.live
def test_live_marker_runs_when_opted_in():
    """Sanity: when this test runs, the gate opt-in worked."""
    assert True
