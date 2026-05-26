from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import verify_diagrams as vd  # noqa: E402


def test_main_skips_gracefully_when_playwright_absent(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(vd, "_PLAYWRIGHT_AVAILABLE", False)
    site = tmp_path / "site"
    site.mkdir()
    src = tmp_path / "src"
    src.mkdir()
    rc = vd.main(["--site-dir", str(site), "--source-dir", str(src)])
    assert rc == 0
    assert "diagram gate unavailable" in capsys.readouterr().out.lower()


def test_main_require_hard_fails_when_playwright_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(vd, "_PLAYWRIGHT_AVAILABLE", False)
    site = tmp_path / "site"
    site.mkdir()
    src = tmp_path / "src"
    src.mkdir()
    rc = vd.main(["--site-dir", str(site), "--source-dir", str(src), "--require"])
    assert rc != 0


def test_main_self_test_only_skips_when_playwright_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(vd, "_PLAYWRIGHT_AVAILABLE", False)
    rc = vd.main(
        ["--site-dir", str(tmp_path), "--source-dir", str(tmp_path), "--self-test-only"]
    )
    assert rc == 0
