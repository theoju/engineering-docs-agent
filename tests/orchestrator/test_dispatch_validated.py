# tests/orchestrator/test_dispatch_validated.py
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import orchestrator_runner  # noqa: E402


CANONICAL_SOURCE_COLLECTOR = {
    "prs": [
        {
            "number": 1,
            "url": "https://github.com/owner/repo/pull/1",
        }
    ],
    "jira_issues": [],
}


WRONG_SHAPE_SOURCE_COLLECTOR = {
    "status": "success",
    "modifications": [],
    "summary": "no work",
    "head_sha": "abc",
    "branches_scanned": [],
    "events_processed": 0,
    "verification": {},
}


def test_dispatch_validated_returns_raw_dict_on_schema_valid(monkeypatch, tmp_path):
    """Schema-valid response: returns (raw_dict, [])."""
    monkeypatch.setattr(
        orchestrator_runner,
        "dispatch_subagent",
        lambda name, inputs, *, dry_run_dir, cwd=None: dict(CANONICAL_SOURCE_COLLECTOR),
    )

    raw, reasons = orchestrator_runner.dispatch_validated(
        "source-collector", {}, dry_run_dir=None, cwd=tmp_path
    )

    assert raw == CANONICAL_SOURCE_COLLECTOR
    assert reasons == []


def test_dispatch_validated_returns_reason_on_schema_invalid(monkeypatch, tmp_path):
    """Schema-invalid response: returns (None, ['schema_invalid: <name>: ...'])."""
    monkeypatch.setattr(
        orchestrator_runner,
        "dispatch_subagent",
        lambda name, inputs, *, dry_run_dir, cwd=None: dict(
            WRONG_SHAPE_SOURCE_COLLECTOR
        ),
    )

    raw, reasons = orchestrator_runner.dispatch_validated(
        "source-collector", {}, dry_run_dir=None, cwd=tmp_path
    )

    assert raw is None
    assert len(reasons) == 1
    assert reasons[0].startswith("schema_invalid: source-collector: "), reasons


def test_dispatch_validated_returns_empty_reasons_on_dispatch_none(
    monkeypatch, tmp_path
):
    """Dispatch returned None (binary missing, nonzero rc, etc.): returns (None, [])."""
    monkeypatch.setattr(
        orchestrator_runner,
        "dispatch_subagent",
        lambda name, inputs, *, dry_run_dir, cwd=None: None,
    )

    raw, reasons = orchestrator_runner.dispatch_validated(
        "source-collector", {}, dry_run_dir=None, cwd=tmp_path
    )

    assert raw is None
    assert reasons == []


def test_dispatch_validated_returns_schema_missing_reason(monkeypatch, tmp_path):
    """Unknown agent name (schema file missing): returns (None, ['schema_missing: ...'])."""
    monkeypatch.setattr(
        orchestrator_runner,
        "dispatch_subagent",
        lambda name, inputs, *, dry_run_dir, cwd=None: {"anything": "valid"},
    )

    raw, reasons = orchestrator_runner.dispatch_validated(
        "no-such-agent", {}, dry_run_dir=None, cwd=tmp_path
    )

    assert raw is None
    assert reasons == ["schema_missing: no-such-agent"]
