from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import verify_diagrams as vd  # noqa: E402


def test_scan_counts_mermaid_fences(tmp_path):
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "api.md").write_text(
        "# API\n\n```mermaid\ngraph TD\nA-->B\n```\n\ntext\n\n```mermaid\nflowchart LR\n```\n"
    )
    (tmp_path / "plain.md").write_text("# Plain\n\n```python\nx = 1\n```\n")
    assert vd.scan_mermaid_sources(tmp_path) == {"core/api.md": 2}


def test_scan_ignores_indented_and_nonmermaid(tmp_path):
    (tmp_path / "a.md").write_text("```mermaid\ngraph TD\n```\n")
    (tmp_path / "b.md").write_text(
        "    ```mermaid\n    graph TD\n    ```\n"
    )  # indented code, not a fence
    assert vd.scan_mermaid_sources(tmp_path) == {"a.md": 1}


def test_scan_empty_dir_is_empty(tmp_path):
    assert vd.scan_mermaid_sources(tmp_path) == {}


def test_scan_missing_dir_is_empty(tmp_path):
    assert vd.scan_mermaid_sources(tmp_path / "nope") == {}


def test_source_to_built_urls_directory_and_flat():
    assert vd.source_to_built_urls("core/api.md") == [
        "core/api/index.html",
        "core/api.html",
    ]


def test_source_to_built_urls_index_page():
    assert vd.source_to_built_urls("index.md") == ["index.html"]
    assert vd.source_to_built_urls("core/index.md") == ["core/index.html"]


def _result(http=200, rendered=1, errors=None, assets=None):
    return {
        "http_status": http,
        "rendered_ok": rendered,
        "error_boxes": errors or [],
        "asset_errors": assets or [],
    }


def test_page_failure_ok_returns_none():
    assert vd._page_failure("core/api/", 1, _result(rendered=1)) is None


def test_page_failure_page_missing():
    f = vd._page_failure("core/gone/", 1, _result(http=404, rendered=0))
    assert f == {"page": "core/gone/", "reason": "page_missing", "http": 404}


def test_page_failure_error_box_beats_count():
    f = vd._page_failure(
        "core/api/", 2, _result(rendered=1, errors=["Syntax error in text"])
    )
    assert f["reason"] == "error_box"
    assert f["detail"] == "Syntax error in text"


def test_page_failure_asset_error():
    f = vd._page_failure("g/setup/", 1, _result(rendered=1, assets=["main.css 404"]))
    assert f["reason"] == "asset_error"
    assert f["detail"] == "main.css 404"


def test_page_failure_count_mismatch():
    f = vd._page_failure("core/api/", 2, _result(rendered=1))
    assert f == {
        "page": "core/api/",
        "reason": "count_mismatch",
        "expected": 2,
        "rendered": 1,
    }


def test_build_ledger_and_ok():
    ledger = vd.build_ledger(
        {"good": "pass", "broken": "fail", "ok": True},
        [
            {"page": "core/api/", "expected": 2, "rendered_ok": 2, "failure": None},
            {
                "page": "g/x/",
                "expected": 1,
                "rendered_ok": 0,
                "failure": {
                    "page": "g/x/",
                    "reason": "count_mismatch",
                    "expected": 1,
                    "rendered": 0,
                },
            },
        ],
    )
    assert ledger["checked_pages"] == 2
    assert ledger["expected_diagrams"] == 3
    assert ledger["rendered_diagrams"] == 2
    assert len(ledger["failures"]) == 1
    assert vd.ledger_ok(ledger) is False


def test_ledger_ok_true_when_clean_and_selftest_ok():
    ledger = vd.build_ledger({"good": "pass", "broken": "fail", "ok": True}, [])
    assert vd.ledger_ok(ledger) is True


def test_ledger_not_ok_when_selftest_failed():
    ledger = vd.build_ledger({"good": "pass", "broken": "pass", "ok": False}, [])
    assert vd.ledger_ok(ledger) is False
