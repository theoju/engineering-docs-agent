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


def test_framework_build_no_mkdocs_yml_skipped(tmp_path, monkeypatch):
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "lint"))
    import framework_build

    monkeypatch.chdir(tmp_path)
    ok, skipped, reason = framework_build.run_mkdocs(tmp_path)
    assert ok
    assert skipped is True
    assert "mkdocs.yml" in reason


def test_framework_build_result_distinguishes_skip(tmp_path, monkeypatch, capsys):
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "lint"))
    import framework_build

    monkeypatch.chdir(tmp_path)
    # No mkdocs.yml => skipped path
    cfg = tmp_path / "config.yml"
    cfg.write_text("docs:\n  framework: mkdocs\n")
    foo = tmp_path / "foo.md"
    foo.write_text("# foo")

    # Run main() with args
    monkeypatch.setattr(
        sys,
        "argv",
        ["framework_build", "--config", str(cfg), "--paths", str(foo), "--json"],
    )
    rc = framework_build.main()
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    result = out["results"][0]
    assert result["ok"] is True
    assert result.get("skipped") is True
    assert "mkdocs.yml" in result.get("reason", "")
