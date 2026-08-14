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
