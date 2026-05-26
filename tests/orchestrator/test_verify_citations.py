from __future__ import annotations
import json as _json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import verify_citations as vc  # noqa: E402


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


# --- Task 1: parser ---------------------------------------------------------


def test_parse_finds_citation_with_pin():
    text = (
        "Defined at `backend/connectors/base.py:148` <!--pin:class BaseConnector-->.\n"
    )
    cits = vc._parse_page_citations(text)
    assert cits == [
        {
            "path": "backend/connectors/base.py",
            "line": 148,
            "token": "class BaseConnector",
        }
    ]


def test_parse_ignores_codespan_without_pin():
    # A path:line code span with no following pin is NOT a citation.
    text = "See `backend/connectors/base.py:148` for details.\n"
    assert vc._parse_page_citations(text) == []


def test_parse_trims_pin_whitespace_and_skips_empty():
    text = (
        "A `a.py:1` <!--pin:  foo  --> and "
        "B `b.py:2` <!--pin:  --> (empty pin skipped)\n"
    )
    assert vc._parse_page_citations(text) == [
        {"path": "a.py", "line": 1, "token": "foo"}
    ]


def test_parse_multiple_citations_one_page():
    text = "`x.py:10` <!--pin:def x--> then `y/z.py:20` <!--pin:class Z-->\n"
    assert vc._parse_page_citations(text) == [
        {"path": "x.py", "line": 10, "token": "def x"},
        {"path": "y/z.py", "line": 20, "token": "class Z"},
    ]


# --- Task 2: classifier -----------------------------------------------------


def test_classify_ok_when_token_at_line(tmp_path):
    _write(tmp_path / "src/a.py", "import os\nclass BaseConnector:\n    pass\n")
    cit = {"path": "src/a.py", "line": 2, "token": "class BaseConnector"}
    assert vc._classify_citation(tmp_path, cit)["status"] == "ok"


def test_classify_relocated_when_token_moved(tmp_path):
    # token is now on line 4, citation says line 2
    _write(tmp_path / "src/a.py", "# new\n# lines\nimport os\nclass BaseConnector:\n")
    cit = {"path": "src/a.py", "line": 2, "token": "class BaseConnector"}
    res = vc._classify_citation(tmp_path, cit)
    assert res["status"] == "relocated"
    assert res["new_line"] == 4


def test_classify_ambiguous_when_token_multiple_lines(tmp_path):
    _write(tmp_path / "src/a.py", "x = 1\nx = 1\n")
    cit = {"path": "src/a.py", "line": 5, "token": "x = 1"}
    res = vc._classify_citation(tmp_path, cit)
    assert res["status"] == "ambiguous"
    assert res["lines"] == [1, 2]


def test_classify_gone_when_token_absent(tmp_path):
    _write(tmp_path / "src/a.py", "totally different\n")
    cit = {"path": "src/a.py", "line": 1, "token": "class BaseConnector"}
    assert vc._classify_citation(tmp_path, cit)["status"] == "gone"


def test_classify_gone_when_file_missing(tmp_path):
    cit = {"path": "src/nope.py", "line": 1, "token": "anything"}
    assert vc._classify_citation(tmp_path, cit)["status"] == "gone"


# --- Task 3: scanner + ledger + --fix ---------------------------------------


def test_verify_citations_builds_ledger(tmp_path):
    repo = tmp_path
    _write(repo / "src/a.py", "class BaseConnector:\n")  # ok
    _write(repo / "src/b.py", "# pad\n# pad\ndef handler():\n")  # relocated -> 3
    _write(repo / "src/c.py", "gone now\n")  # gone
    docs = repo / "docs/site-src"
    _write(
        docs / "core/x.md",
        "A `src/a.py:1` <!--pin:class BaseConnector-->\n"
        "B `src/b.py:1` <!--pin:def handler-->\n"
        "C `src/c.py:1` <!--pin:class Missing-->\n",
    )
    ledger = vc.verify_citations(docs, repo, fix=False)
    assert ledger["checked"] == 3
    assert ledger["ok"] == 1
    assert ledger["relocated"] == [
        {"page": "core/x.md", "path": "src/b.py", "old": 1, "new": 3}
    ]
    assert ledger["gone"] == [
        {"page": "core/x.md", "path": "src/c.py", "token": "class Missing", "line": 1}
    ]
    assert ledger["pages_review_needed"] == ["core/x.md"]


def test_verify_citations_fix_rewrites_relocated(tmp_path):
    repo = tmp_path
    _write(repo / "src/b.py", "# pad\n# pad\ndef handler():\n")
    docs = repo / "docs/site-src"
    page = _write(docs / "core/x.md", "B `src/b.py:1` <!--pin:def handler-->\n")
    vc.verify_citations(docs, repo, fix=True)
    assert "`src/b.py:3`" in page.read_text()
    assert "`src/b.py:1`" not in page.read_text()


def test_fix_two_relocated_same_path_do_not_collide(tmp_path):
    # Regression: A relocates 1->12, B relocates 12->20. A page-global replace
    # would rewrite A to :12, then the B-pass would catch BOTH :12 spans and
    # push them to :20, corrupting A. Offset-splicing must keep them distinct.
    repo = tmp_path
    lines = ["x"] * 20
    lines[11] = "def alpha():"  # line 12
    lines[19] = "def beta():"  # line 20
    _write(repo / "src/a.py", "\n".join(lines) + "\n")
    docs = repo / "docs/site-src"
    page = _write(
        docs / "core/x.md",
        "A `src/a.py:1` <!--pin:def alpha-->\nB `src/a.py:12` <!--pin:def beta-->\n",
    )
    vc.verify_citations(docs, repo, fix=True)
    out = page.read_text()
    assert out.count("`src/a.py:12`") == 1  # A landed at 12, not clobbered
    assert out.count("`src/a.py:20`") == 1  # B landed at 20
    assert "A `src/a.py:12` <!--pin:def alpha-->" in out


def test_fix_leaves_bare_reference_untouched(tmp_path):
    # Regression: a bare `path:line` prose reference (no pin) that duplicates a
    # pinned citation's span must not be rewritten by --fix.
    repo = tmp_path
    _write(repo / "src/b.py", "# pad\ndef handler():\n")  # def handler -> line 2
    docs = repo / "docs/site-src"
    page = _write(
        docs / "core/x.md",
        "Pinned `src/b.py:1` <!--pin:def handler--> and bare `src/b.py:1` here.\n",
    )
    vc.verify_citations(docs, repo, fix=True)
    out = page.read_text()
    assert "`src/b.py:2` <!--pin:def handler-->" in out  # pinned one relocated
    assert "bare `src/b.py:1` here" in out  # bare reference untouched


def test_verify_citations_empty_when_no_docs_dir(tmp_path):
    ledger = vc.verify_citations(tmp_path / "nope", tmp_path, fix=False)
    assert ledger == {
        "checked": 0,
        "ok": 0,
        "relocated": [],
        "ambiguous": [],
        "gone": [],
        "pages_review_needed": [],
    }


def test_verify_citations_scopes_to_pages_arg(tmp_path):
    repo = tmp_path
    _write(repo / "src/c.py", "gone now\n")
    docs = repo / "docs/site-src"
    _write(docs / "core/x.md", "C `src/c.py:1` <!--pin:class Missing-->\n")
    _write(docs / "core/y.md", "C `src/c.py:1` <!--pin:class Missing-->\n")
    # Only x.md is in scope; y.md must be untouched/unchecked.
    ledger = vc.verify_citations(docs, repo, fix=False, pages={"core/x.md"})
    assert ledger["checked"] == 1
    assert ledger["pages_review_needed"] == ["core/x.md"]


# --- Task 4: CLI ------------------------------------------------------------


def test_cli_json_output_and_exit_zero(tmp_path, capsys):
    repo = tmp_path
    _write(repo / "src/a.py", "class BaseConnector:\n")
    docs = repo / "docs/site-src"
    _write(docs / "core/x.md", "A `src/a.py:1` <!--pin:class BaseConnector-->\n")
    rc = vc.main(["--docs-dir", str(docs), "--repo-root", str(repo), "--json"])
    assert rc == 0
    out = _json.loads(capsys.readouterr().out)
    assert out["ok"] == 1 and out["checked"] == 1


def test_cli_strict_exits_nonzero_on_gone(tmp_path, capsys):
    repo = tmp_path
    _write(repo / "src/c.py", "gone\n")
    docs = repo / "docs/site-src"
    _write(docs / "core/x.md", "C `src/c.py:1` <!--pin:class Missing-->\n")
    rc = vc.main(
        ["--docs-dir", str(docs), "--repo-root", str(repo), "--json", "--strict"]
    )
    assert rc == 1
    capsys.readouterr()


def test_cli_fix_rewrites_and_exits_zero(tmp_path, capsys):
    repo = tmp_path
    _write(repo / "src/b.py", "# pad\ndef handler():\n")
    docs = repo / "docs/site-src"
    page = _write(docs / "core/x.md", "B `src/b.py:1` <!--pin:def handler-->\n")
    rc = vc.main(["--docs-dir", str(docs), "--repo-root", str(repo), "--fix", "--json"])
    assert rc == 0
    assert "`src/b.py:2`" in page.read_text()
