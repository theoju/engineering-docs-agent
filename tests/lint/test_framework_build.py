from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "lint" / "framework_build.py"


def test_skips_when_no_mkdocs(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("docs:\n  framework: mkdocs\n  source_dir: docs\n")
    fake = tmp_path / "fake.md"
    fake.write_text("# x")
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(cfg),
            "--paths",
            str(fake),
            "--json",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert "no mkdocs.yml" in out["results"][0]["message"].lower()


def test_unsupported_framework(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("docs:\n  framework: docusaurus\n  source_dir: docs\n")
    fake = tmp_path / "fake.md"
    fake.write_text("# x")
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(cfg),
            "--paths",
            str(fake),
            "--json",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert "docusaurus" in out["results"][0]["message"]
