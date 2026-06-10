from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPTS_LINT = Path(__file__).parent.parent.parent / "scripts" / "lint"
sys.path.insert(0, str(SCRIPTS_LINT))
import citation_exists  # noqa: E402

SCRIPT = SCRIPTS_LINT / "citation_exists.py"


# ---------- extraction (pure) ----------


def test_extracts_repo_path_and_test_id():
    text = "See `scripts/foo.py` and `test_bar_baz` for details."
    cites = citation_exists.extract_citations(text)
    assert cites["paths"] == ["scripts/foo.py"]
    assert cites["tests"] == ["test_bar_baz"]


def test_line_suffix_stripped():
    assert citation_exists.extract_citations("`scripts/foo.py:123`")["paths"] == [
        "scripts/foo.py"
    ]
    assert citation_exists.extract_citations("`scripts/foo.py:10-20`")["paths"] == [
        "scripts/foo.py"
    ]


def test_duplicates_collapse():
    text = "`scripts/foo.py` twice `scripts/foo.py`, `test_x` twice `test_x`"
    cites = citation_exists.extract_citations(text)
    assert cites["paths"] == ["scripts/foo.py"]
    assert cites["tests"] == ["test_x"]


def test_placeholders_urls_and_env_refs_skipped():
    text = (
        "`docs/specs/YYYY-MM-DD-x.md` `<path>` `glob/*.md` `{owner}/file.py` "
        "`https://x.test/a.py` `~/conf/a.yml` `$HOME/a.sh` `dir/.../file.py`"
    )
    assert citation_exists.extract_citations(text) == {"paths": [], "tests": []}


def test_fenced_blocks_ignored():
    text = (
        "intro prose\n"
        "```python\n"
        'x = load("`scripts/fake_in_fence.py`")\n'
        "```\n"
        "outro cites `test_real_one`\n"
    )
    cites = citation_exists.extract_citations(text)
    assert cites["paths"] == []
    assert cites["tests"] == ["test_real_one"]


def test_vocabulary_tokens_skipped():
    # No slash and not a test identifier -> not a citation.
    text = "`partial_reasons` `run.time_budget_seconds` `frontmatter_contract.py`"
    assert citation_exists.extract_citations(text) == {"paths": [], "tests": []}
