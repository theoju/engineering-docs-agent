from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import orchestrator_runner as runner  # noqa: E402


def test_progress_start_writes_initial_state(tmp_path):
    (tmp_path / ".engineering-docs-agent").mkdir()
    p = runner._BootstrapProgress(tmp_path, total=3)
    p.start()
    payload = json.loads(
        (tmp_path / ".engineering-docs-agent" / "bootstrap.progress.json").read_text()
    )
    assert payload["phase"] == "bootstrap"
    assert payload["total"] == 3
    assert payload["current_index"] == 0
    assert payload["current_page"] is None
    assert payload["completed"] == []
    assert payload["skipped_existing"] == []
    assert payload["failed"] == []


def test_progress_transitions_advance_current_and_record_completion(tmp_path):
    (tmp_path / ".engineering-docs-agent").mkdir()
    p = runner._BootstrapProgress(tmp_path, total=2)
    p.start()
    p.begin_page("core/api.md")
    p.mark_completed("core/api.md")
    p.begin_page("core/storage.md")
    p.mark_skipped("core/storage.md")
    payload = json.loads(
        (tmp_path / ".engineering-docs-agent" / "bootstrap.progress.json").read_text()
    )
    assert payload["current_index"] == 2
    assert payload["current_page"] == "core/storage.md"
    assert payload["completed"] == ["core/api.md"]
    assert payload["skipped_existing"] == ["core/storage.md"]


def test_progress_records_failure_reason(tmp_path):
    (tmp_path / ".engineering-docs-agent").mkdir()
    p = runner._BootstrapProgress(tmp_path, total=1)
    p.start()
    p.begin_page("core/bad.md")
    p.mark_failed(
        "core/bad.md", reason="frontmatter_parse_error: core/bad.md: ScannerError"
    )
    payload = json.loads(
        (tmp_path / ".engineering-docs-agent" / "bootstrap.progress.json").read_text()
    )
    assert payload["failed"] == [
        {
            "path": "core/bad.md",
            "reason": "frontmatter_parse_error: core/bad.md: ScannerError",
        }
    ]


def test_progress_finish_unlinks_file(tmp_path):
    (tmp_path / ".engineering-docs-agent").mkdir()
    p = runner._BootstrapProgress(tmp_path, total=0)
    p.start()
    assert (tmp_path / ".engineering-docs-agent" / "bootstrap.progress.json").exists()
    p.finish()
    assert not (
        tmp_path / ".engineering-docs-agent" / "bootstrap.progress.json"
    ).exists()


def test_progress_write_failures_are_swallowed(tmp_path, capsys):
    # Point the helper at a directory that doesn't exist; every write should
    # log to stderr but not raise.
    p = runner._BootstrapProgress(tmp_path / "does-not-exist", total=1)
    p.start()  # would fail to write the initial file
    p.begin_page("x.md")
    p.mark_completed("x.md")
    p.finish()
    err = capsys.readouterr().err
    # start + begin_page + mark_completed each fail to write — assert all
    # three were swallowed, not just the first.
    assert err.count("bootstrap.progress.json") >= 3
