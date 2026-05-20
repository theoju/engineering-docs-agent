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
    assert (target / "archive" / "adrs" / "index.md").exists()
    assert (target / "archive" / "specs" / "index.md").exists()
