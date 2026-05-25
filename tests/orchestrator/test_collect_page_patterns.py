from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from source_map import _collect_page_patterns, _page_globs  # noqa: E402


def _page(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


def test_collects_list_valued_source_files(tmp_path):
    docs = tmp_path / "site-src"
    _page(
        docs / "architecture/auth.md",
        "---\nsource_files:\n  - scripts/auth/**/*.py\n  - scripts/login.py\n---\n# Auth\n",
    )
    _page(docs / "operations/index.md", "---\ntitle: Ops\n---\n# Ops\n")  # opts out
    patterns = _collect_page_patterns(docs)
    assert patterns == {
        "architecture/auth.md": ["scripts/auth/**/*.py", "scripts/login.py"]
    }


def test_missing_docs_dir_returns_empty(tmp_path):
    assert _collect_page_patterns(tmp_path / "nope") == {}


def test_page_globs_reports_skip_reasons(tmp_path):
    bad = _page(tmp_path / "a.md", "---\nsource_files: not-a-list\n---\n# A\n")
    globs, reason = _page_globs(bad)
    assert globs == [] and reason == "source_files is not a list"

    malformed = _page(tmp_path / "b.md", "---\n: : bad yaml :\n---\n# B\n")
    globs2, reason2 = _page_globs(malformed)
    assert globs2 == [] and reason2 == "malformed frontmatter"

    opted_out = _page(tmp_path / "c.md", "---\ntitle: C\n---\n# C\n")
    assert _page_globs(opted_out) == ([], None)


def test_non_string_glob_entries_are_dropped(tmp_path):
    p = _page(
        tmp_path / "d.md",
        "---\nsource_files:\n  - scripts/a.py\n  - 42\n  - ''\n---\n# D\n",
    )
    globs, reason = _page_globs(p)
    assert globs == ["scripts/a.py"] and reason is None
