# tests/orchestrator/test_time_budget.py
"""CCE-109: time-budget soft deadline — break the nightly doom loop."""

from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import orchestrator_runner as runner  # noqa: E402


def test_resolve_time_budget_precedence():
    # CLI override wins (including explicit 0 = unlimited).
    assert (
        runner.resolve_time_budget({"run": {"time_budget_seconds": 1200}}, 999) == 999
    )
    assert runner.resolve_time_budget({"run": {"time_budget_seconds": 1200}}, 0) == 0
    # No CLI override → config value.
    assert (
        runner.resolve_time_budget({"run": {"time_budget_seconds": 1200}}, None) == 1200
    )
    # No CLI, no config → default.
    assert runner.resolve_time_budget({}, None) == runner.DEFAULT_TIME_BUDGET_SECONDS
    assert (
        runner.resolve_time_budget({"run": {}}, None)
        == runner.DEFAULT_TIME_BUDGET_SECONDS
    )
    # Default is 2700.
    assert runner.DEFAULT_TIME_BUDGET_SECONDS == 2700
