from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("playwright")  # browser layer — skipped where Chromium is absent

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import verify_diagrams as vd  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "diagrams" / "render"


def test_self_test_handshake_holds():
    st = vd.run_self_test(FIX)
    assert st == {"good": "pass", "broken": "fail", "ok": True}


def test_verify_site_passes_for_good_only(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "good.html").write_text((FIX / "good.html").read_text())
    (site / "mermaid.min.js").write_text((FIX / "mermaid.min.js").read_text())
    src = tmp_path / "src"
    src.mkdir()
    (src / "good.md").write_text((FIX / "src" / "good.md").read_text())
    ledger = vd.verify_site(site, src, FIX)
    assert ledger["failures"] == []
    assert vd.ledger_ok(ledger) is True


def test_verify_site_flags_count_mismatch(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "count2.html").write_text((FIX / "count2.html").read_text())
    (site / "mermaid.min.js").write_text((FIX / "mermaid.min.js").read_text())
    src = tmp_path / "src"
    src.mkdir()
    (src / "count2.md").write_text((FIX / "src" / "count2.md").read_text())
    ledger = vd.verify_site(site, src, FIX)
    reasons = [f["reason"] for f in ledger["failures"]]
    assert "count_mismatch" in reasons


def test_assert_page_detects_error_box():
    result = vd._render_one(FIX, "broken.html")
    assert result["error_boxes"], "broken mermaid must surface an error box"


def test_assert_page_asset404_flags_asset_error():
    result = vd._render_one(FIX, "asset404.html")
    assert any("missing.css" in a for a in result["asset_errors"])


def test_assert_page_blank_renders_nothing():
    result = vd._render_one(FIX, "blank.html")
    assert result["http_status"] == 200
    assert result["rendered_ok"] == 0
    assert result["error_boxes"] == []
