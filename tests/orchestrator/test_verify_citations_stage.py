from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import orchestrator_runner as orun  # noqa: E402


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_compute_citation_drift_flags_gone(tmp_path):
    _write(tmp_path / "scripts/auth.py", "def login():\n    pass\n")
    _write(
        tmp_path / "docs/site-src/core/auth.md",
        "Login `scripts/auth.py:1` <!--pin:class Missing-->\n",
    )
    config = {"site": {"docs_dir": "docs/site-src"}}
    prs = [{"number": 1, "files": [{"path": "scripts/auth.py"}]}]
    ledger = orun.compute_citation_drift(tmp_path, config, prs)
    assert ledger["pages_review_needed"] == ["core/auth.md"]
    assert ledger["gone"][0]["path"] == "scripts/auth.py"


def test_compute_citation_drift_autofixes_relocated(tmp_path):
    _write(tmp_path / "scripts/auth.py", "# pad\ndef login():\n    pass\n")
    page = _write(
        tmp_path / "docs/site-src/core/auth.md",
        "Login `scripts/auth.py:1` <!--pin:def login-->\n",
    )
    config = {"site": {"docs_dir": "docs/site-src"}}
    prs = [{"number": 1, "files": [{"path": "scripts/auth.py"}]}]
    ledger = orun.compute_citation_drift(tmp_path, config, prs)
    assert ledger["relocated"][0]["new"] == 2
    assert "`scripts/auth.py:2`" in page.read_text()  # rewritten in place


def test_compute_citation_drift_no_site_is_empty(tmp_path):
    ledger = orun.compute_citation_drift(tmp_path, {}, [])
    assert ledger["checked"] == 0 and ledger["pages_review_needed"] == []


def test_citation_drift_whats_new_lines():
    empty = {
        "checked": 0,
        "ok": 0,
        "relocated": [],
        "ambiguous": [],
        "gone": [],
        "pages_review_needed": [],
    }
    assert orun._citation_drift_whats_new_lines(empty) == []
    lines = orun._citation_drift_whats_new_lines(
        {
            "gone": [
                {"page": "core/a.md", "path": "x.py", "token": "class X", "line": 5}
            ],
            "ambiguous": [
                {"page": "core/b.md", "path": "y.py", "token": "t", "lines": [1, 2]}
            ],
            "pages_review_needed": ["core/a.md", "core/b.md"],
        }
    )
    assert lines[0] == "### Pages to review (citation drift)"
    assert "- core/a.md — citation gone: x.py (class X)" in lines
    assert "- core/b.md — ambiguous: y.py (t)" in lines


def test_changed_pages_from_map_scopes_via_map(tmp_path):
    docs_rel = "docs/site-src"
    mp = tmp_path / docs_rel / ".doc-source-map.json"
    mp.parent.mkdir(parents=True)
    mp.write_text(
        '{"version":1,"map":{"scripts/auth.py":["core/auth.md"],'
        '"scripts/other.py":["core/other.md"]},"patterns":{}}'
    )
    prs = [{"number": 1, "files": [{"path": "scripts/auth.py"}]}]
    pages = orun._changed_pages_from_map(tmp_path, docs_rel, prs)
    assert pages == {"core/auth.md"}


def test_changed_pages_from_map_none_when_no_map(tmp_path):
    assert orun._changed_pages_from_map(tmp_path, "docs/site-src", []) is None
