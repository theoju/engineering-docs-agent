from __future__ import annotations
import subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "archive_indexes.py"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "archive_indexes"


def test_generates_indexes(tmp_path):
    import shutil

    target = tmp_path / "archive_indexes"
    shutil.copytree(FIXTURES, target)
    subprocess.run(
        [sys.executable, str(SCRIPT), "--archive-root", str(target / "archive")],
        check=True,
    )
    adrs_index = (target / "archive" / "adrs" / "index.md").read_text()
    specs_index = (target / "archive" / "specs" / "index.md").read_text()
    assert "2026-01-01-foo" in adrs_index
    assert "accepted" in adrs_index
    assert "2026-01-02-bar" in specs_index
    assert "draft" in specs_index
