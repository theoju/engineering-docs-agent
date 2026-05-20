from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "setup_discover.py"
FIX = Path(__file__).parent.parent / "fixtures" / "setup_repos"


def test_mkdocs_lensy_detected():
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        cwd=FIX / "mkdocs_lensy",
        capture_output=True,
        text=True,
    )
    out = json.loads(r.stdout)
    assert out["framework"] == "mkdocs"
    assert "core" in out["lens_paths"]
    assert "archive" in out["lens_paths"]


def test_bare_repo_minimal():
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        cwd=FIX / "bare",
        capture_output=True,
        text=True,
    )
    out = json.loads(r.stdout)
    assert out["framework"] is None
