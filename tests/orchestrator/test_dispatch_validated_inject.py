"""CCE-120: dispatch_validated(..., inject={...}) stamps orchestrator-owned
fields onto the raw agent output BEFORE schema validation, so a value the
orchestrator already owns (e.g. gap-detector's pr_id) is never sourced from
the LLM's echo. inject wins over the agent's own value.

These tests use the dry-run fixture path: dispatch_subagent returns the
fake_<name>.json contents verbatim, so the real inject merge runs unmocked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import orchestrator_runner as runner  # noqa: E402


def _write_gap_fixture(dry_run_dir: Path, payload: dict) -> None:
    dry_run_dir.mkdir(parents=True, exist_ok=True)
    (dry_run_dir / "fake_gap_detector.json").write_text(json.dumps(payload))


def test_inject_fills_missing_prid(tmp_path):
    # Agent output omits pr_id (the CCE-120 failure). Schema requires it.
    _write_gap_fixture(tmp_path, {"needs_spec": True, "reasoning": "why"})
    out, reasons = runner.dispatch_validated(
        "gap-detector",
        {},
        dry_run_dir=tmp_path,
        inject={"pr_id": "owner/repo#7"},
    )
    assert reasons == []
    assert out is not None
    assert out["pr_id"] == "owner/repo#7"
    assert out["needs_spec"] is True


def test_inject_overrides_wrong_prid(tmp_path):
    # Agent echoes a DIFFERENT pr_id; the injected value must win.
    _write_gap_fixture(
        tmp_path, {"pr_id": "WRONG#1", "needs_spec": False, "reasoning": "x"}
    )
    out, reasons = runner.dispatch_validated(
        "gap-detector",
        {},
        dry_run_dir=tmp_path,
        inject={"pr_id": "owner/repo#7"},
    )
    assert reasons == []
    assert out["pr_id"] == "owner/repo#7"


def test_inject_none_is_unchanged_behavior(tmp_path):
    # Regression for the 7 other callers: no inject => today's behavior.
    # A valid verdict passes through untouched...
    _write_gap_fixture(
        tmp_path, {"pr_id": "owner/repo#7", "needs_spec": True, "reasoning": "x"}
    )
    out, reasons = runner.dispatch_validated("gap-detector", {}, dry_run_dir=tmp_path)
    assert reasons == []
    assert out["pr_id"] == "owner/repo#7"


def test_inject_none_still_rejects_missing_prid(tmp_path):
    # ...and a verdict missing pr_id with NO inject still fails schema
    # validation exactly as before (inject didn't secretly fix anything).
    _write_gap_fixture(tmp_path, {"needs_spec": True, "reasoning": "x"})
    out, reasons = runner.dispatch_validated("gap-detector", {}, dry_run_dir=tmp_path)
    assert out is None
    assert any(r.startswith("schema_invalid: gap-detector") for r in reasons), reasons
