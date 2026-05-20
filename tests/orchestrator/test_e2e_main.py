from __future__ import annotations
import json, shutil, subprocess, sys
from pathlib import Path

RUNNER = Path(__file__).parent.parent.parent / "scripts" / "orchestrator_runner.py"
FAKES = Path(__file__).parent / "fakes"
HOST = Path(__file__).parent.parent / "fixtures" / "e2e_host"


def test_full_main_pipeline_dry_run(tmp_path):
    target = tmp_path / "host"
    shutil.copytree(HOST, target)
    subprocess.run(["git", "-C", str(target), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(target), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(target),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "initial",
        ],
        check=True,
    )
    r = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--repo-root",
            str(target),
            "--dry-run-subagents",
            str(FAKES),
            "--no-pr",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    wn = (target / "docs" / "site-src" / "whats-new.md").read_text()
    assert "PR #1" in wn
    st = json.loads((target / ".engineering-docs-agent" / "state.json").read_text())
    assert "current_run" in st
