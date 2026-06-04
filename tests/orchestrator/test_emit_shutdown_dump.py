"""CCE-74: _emit_shutdown_dump unit tests.

Spec § 'Modified: scripts/orchestrator_runner.py' item 5:
  - Gated on state['current_run']['partial_reasons'] non-empty (NOT the
    partial flag — info_only reasons still warrant exit-time visibility).
  - Header: 'docs-agent: run exit summary (reasons=N):'
  - Per-reason: single prefix run-wide. PARTIAL when partial=True; INFO
    when partial=False (info_only-only run).
  - Implementation: uses print() directly, NOT emit_stderr/emit_log,
    so OSError propagates (last-resort signal must fail loudly).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402


def _orun():
    """Return the already-imported orchestrator_runner module."""
    return orun


def test_emit_shutdown_dump_no_op_when_state_lacks_current_run(capsys):
    _orun()._emit_shutdown_dump({})
    assert capsys.readouterr().err == ""


def test_emit_shutdown_dump_no_op_when_current_run_lacks_reasons(capsys):
    state = {"current_run": {"partial": False, "partial_reasons": []}}
    _orun()._emit_shutdown_dump(state)
    assert capsys.readouterr().err == ""


def test_emit_shutdown_dump_no_op_when_partial_reasons_missing_key(capsys):
    state = {"current_run": {"partial": False}}
    _orun()._emit_shutdown_dump(state)
    assert capsys.readouterr().err == ""


def test_emit_shutdown_dump_emits_partial_prefix_when_partial_true(capsys):
    """Common case: any non-info_only reason has flipped partial=True;
    all shutdown-dump lines use PARTIAL prefix (Option a, run-level)."""
    state = {
        "current_run": {
            "partial": True,
            "partial_reasons": [
                "lint_block: docs/foo.md line-length",
                "source_collector_partial: true",
                "source_map_failed: PermissionError",
            ],
        }
    }
    _orun()._emit_shutdown_dump(state)
    err = capsys.readouterr().err
    lines = err.strip().split("\n")
    assert lines[0] == "docs-agent: run exit summary (reasons=3):"
    assert lines[1] == "docs-agent PARTIAL: lint_block: docs/foo.md line-length"
    assert lines[2] == "docs-agent PARTIAL: source_collector_partial: true"
    assert lines[3] == "docs-agent PARTIAL: source_map_failed: PermissionError"


def test_emit_shutdown_dump_emits_info_prefix_when_partial_false(capsys):
    """Info_only-only run: partial=False, reasons non-empty. Single INFO
    prefix run-wide."""
    state = {
        "current_run": {
            "partial": False,
            "partial_reasons": [
                "source_map_failed: PermissionError",
                "core_drift_failed: timeout",
            ],
        }
    }
    _orun()._emit_shutdown_dump(state)
    err = capsys.readouterr().err
    lines = err.strip().split("\n")
    assert lines[0] == "docs-agent: run exit summary (reasons=2):"
    assert lines[1] == "docs-agent INFO: source_map_failed: PermissionError"
    assert lines[2] == "docs-agent INFO: core_drift_failed: timeout"


def test_emit_shutdown_dump_redacts_credentials_defense_in_depth(capsys):
    """Reasons stored in state.partial_reasons are ALREADY redacted by
    add_partial's redact-first invariant. But _emit_shutdown_dump applies
    _redact_credentials again as defense-in-depth — a future contributor
    bypassing add_partial cannot leak credentials via the shutdown dump."""
    state = {
        "current_run": {
            "partial": True,
            "partial_reasons": [
                # Pretend this somehow bypassed add_partial's redaction:
                "raw: https://x-access-token:ghs_LEAKED@github.com/r/r",
            ],
        }
    }
    _orun()._emit_shutdown_dump(state)
    err = capsys.readouterr().err
    assert "ghs_LEAKED" not in err
    assert "<redacted>" in err


def test_emit_shutdown_dump_does_NOT_swallow_oserror(monkeypatch):
    """Spec invariant: shutdown dump is last-resort observability; OSError
    must propagate to caller. Implementation uses print() directly, not
    emit_stderr/emit_log (which swallow OSError)."""

    class _BrokenStream:
        def write(self, _s):
            raise OSError("stream closed")

        def flush(self):
            raise OSError("stream closed")

    monkeypatch.setattr("sys.stderr", _BrokenStream())
    state = {
        "current_run": {
            "partial": True,
            "partial_reasons": ["X"],
        }
    }
    with pytest.raises(OSError):
        _orun()._emit_shutdown_dump(state)
