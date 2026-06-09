from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import managed_block as mb  # noqa: E402
import section_overview as so  # noqa: E402
import setup_discover  # noqa: E402


def _dir_site():
    return {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "home", "path": "index.md", "title": "Home"},
            {"key": "architecture", "path": "architecture/", "title": "Architecture"},
        ],
    }


def _seed_landing(repo: Path, rel: str, text: str):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_render_directory_overview_lists_children_with_count():
    body = so.render_directory_overview(
        [("Routing", "How requests flow."), ("Storage", "Where state lives.")]
    )
    assert "**Routing** — How requests flow." in body
    assert "**Storage** — Where state lives." in body
    assert "2 pages" in body


def test_render_directory_overview_empty_is_no_pages():
    body = so.render_directory_overview([])
    assert body.strip() == "_No pages yet._"


def test_render_directory_overview_singular_page_grammar():
    body = so.render_directory_overview([("Routing", "x.")])
    assert "1 page" in body
    assert "1 pages" not in body


def test_render_api_overview_explicit_other_group_not_duplicated():
    # An operator-declared group literally named "Other" must not collide with
    # the implicit unmatched bucket into two lines / a double-counted total.
    groups = [{"name": "Other", "modules": ["pkg.calc"]}]
    body = so.render_api_overview(
        idents=["pkg.calc", "pkg.util"], groups=groups, contract_links=[]
    )
    assert body.count("**Other**") == 1


def test_generate_overviews_directory_section(tmp_path):
    site = _dir_site()
    _seed_landing(
        tmp_path,
        "docs/site-src/architecture/index.md",
        "---\ntitle: Architecture\n---\n\n# Architecture\n\nAuthor intro.\n",
    )
    _seed_landing(
        tmp_path,
        "docs/site-src/architecture/routing.md",
        "---\ntitle: Routing\n---\n\n# Routing\n\nHow requests flow.\n",
    )
    _seed_landing(
        tmp_path, "docs/site-src/architecture/_draft.md", "# Draft\n\nhidden.\n"
    )
    result = so.generate_overviews(tmp_path, site)
    assert "docs/site-src/architecture/index.md" in result["written"]
    out = (tmp_path / "docs/site-src/architecture/index.md").read_text()
    assert "Author intro." in out
    assert "**Routing** — How requests flow." in out
    assert "_draft" not in out and "hidden" not in out
    assert out.count(mb.START) == 1


def test_overview_false_section_is_skipped(tmp_path):
    site = _dir_site()
    site["sections"][1]["overview"] = False
    _seed_landing(tmp_path, "docs/site-src/architecture/index.md", "# Architecture\n")
    _seed_landing(
        tmp_path, "docs/site-src/architecture/routing.md", "# Routing\n\nx.\n"
    )
    result = so.generate_overviews(tmp_path, site)
    assert "docs/site-src/architecture/index.md" not in result["written"]
    assert (
        mb.START not in (tmp_path / "docs/site-src/architecture/index.md").read_text()
    )


def test_empty_directory_section_writes_no_pages_block(tmp_path):
    site = _dir_site()
    _seed_landing(tmp_path, "docs/site-src/architecture/index.md", "# Architecture\n")
    result = so.generate_overviews(tmp_path, site)
    out = (tmp_path / "docs/site-src/architecture/index.md").read_text()
    assert "_No pages yet._" in out
    assert "docs/site-src/architecture/index.md" in result["written"]


def test_malformed_landing_is_recorded_not_raised(tmp_path):
    site = _dir_site()
    bad = f"# A\n\n{mb.START}\nx\n{mb.START}\ny\n{mb.END}\n"
    _seed_landing(tmp_path, "docs/site-src/architecture/index.md", bad)
    _seed_landing(tmp_path, "docs/site-src/architecture/p.md", "# P\n\ns.\n")
    result = so.generate_overviews(tmp_path, site)
    assert "docs/site-src/architecture/index.md" in result["skipped"]


def test_overview_replaces_block_preserves_author_prose(tmp_path):
    site = _dir_site()
    landing = _seed_landing(
        tmp_path,
        "docs/site-src/architecture/index.md",
        "# Architecture\n\nHAND-WRITTEN INTRO.\n\n"
        f"{mb.START}\nSTALE GENERATED\n{mb.END}\n\nHAND-WRITTEN FOOTER.\n",
    )
    _seed_landing(tmp_path, "docs/site-src/architecture/r.md", "# R\n\nrouting.\n")
    so.generate_overviews(tmp_path, site)
    out = landing.read_text()
    assert "HAND-WRITTEN INTRO." in out
    assert "HAND-WRITTEN FOOTER." in out
    assert "STALE GENERATED" not in out
    assert "**R** — routing." in out


def test_render_api_overview_groups_with_counts():
    groups = [{"name": "Math", "modules": ["pkg.calc"]}]
    body = so.render_api_overview(
        idents=["pkg.calc", "pkg.util"],
        groups=groups,
        contract_links=[("Widget", "contracts/widget.md")],
    )
    assert "**Math** — 1 module" in body
    assert "**Other** — 1 module" in body
    assert "[Widget](contracts/widget.md)" in body


def test_render_api_overview_flat_when_no_groups():
    body = so.render_api_overview(idents=["a", "b", "c"], groups=[], contract_links=[])
    assert "3 modules" in body


def test_generate_overviews_api_section(tmp_path, monkeypatch):
    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {
                "key": "api",
                "path": "api/",
                "title": "API reference",
                "generator": "api-extract",
                "groups": [{"name": "Math", "modules": ["pkg.calc"]}],
            },
        ],
    }
    _seed_landing(tmp_path, "docs/site-src/api/index.md", "# API reference\n")
    _seed_landing(
        tmp_path, "docs/site-src/api/contracts/widget.md", "# Widget\n\nA widget.\n"
    )
    _seed_landing(tmp_path, "pkg/calc.py", "def add(a, b):\n    return a + b\n")
    _seed_landing(tmp_path, "pkg/util.py", "def slug(s):\n    return s\n")
    monkeypatch.setattr(
        setup_discover,
        "detect_python",
        lambda root: {"detected": True, "scan_dir": "pkg", "path_root": "."},
    )
    result = so.generate_overviews(tmp_path, site)
    out = (tmp_path / "docs/site-src/api/index.md").read_text()
    assert "docs/site-src/api/index.md" in result["written"]
    assert "**Math** — 1 module" in out
    assert "**Other** — 1 module" in out
    assert "[Widget](contracts/widget.md)" in out


def test_generate_overviews_fills_home_block(tmp_path):
    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "home", "path": "index.md", "title": "Home"},
            {"key": "architecture", "path": "architecture/", "title": "Architecture"},
            {"key": "ops", "path": "operations/", "title": "Operations"},
        ],
    }
    _seed_landing(
        tmp_path,
        "docs/site-src/index.md",
        "---\ntitle: Home\n---\n\n# Documentation\n\nWELCOME INTRO.\n\n"
        f"{mb.START}\n{mb.END}\n",
    )
    _seed_landing(tmp_path, "docs/site-src/architecture/index.md", "# Architecture\n")
    _seed_landing(tmp_path, "docs/site-src/operations/index.md", "# Operations\n")
    result = so.generate_overviews(tmp_path, site)
    out = (tmp_path / "docs/site-src/index.md").read_text()
    assert "WELCOME INTRO." in out
    assert "docs/site-src/index.md" in result["written"]
    assert "Architecture" in out and "Operations" in out
    assert "architecture/index.md" in out


def test_generate_overviews_home_without_markers_appends(tmp_path):
    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "home", "path": "index.md", "title": "Home"},
            {"key": "ops", "path": "operations/", "title": "Operations"},
        ],
    }
    _seed_landing(
        tmp_path,
        "docs/site-src/index.md",
        "---\ntitle: Home\n---\n\n# Documentation\n\nOld cards.\n",
    )
    _seed_landing(tmp_path, "docs/site-src/operations/index.md", "# Operations\n")
    so.generate_overviews(tmp_path, site)
    out = (tmp_path / "docs/site-src/index.md").read_text()
    assert "Old cards." in out
    assert mb.START in out and "Operations" in out


import datetime


def test_freshness_key_prefers_last_reviewed():
    assert so._freshness_key({"last_reviewed": "2026-05-01"}, "foo.md") == "2026-05-01"


def test_freshness_key_coerces_date_object():
    # YAML parses an unquoted `last_reviewed: 2026-05-01` to a datetime.date;
    # comparing that against the "" fallback during sort would raise TypeError.
    assert (
        so._freshness_key({"last_reviewed": datetime.date(2026, 5, 1)}, "foo.md")
        == "2026-05-01"
    )


def test_freshness_key_falls_back_to_filename_date():
    assert so._freshness_key({}, "2026-03-15-foo.md") == "2026-03-15"


def test_freshness_key_empty_when_no_date():
    assert so._freshness_key({}, "foo.md") == ""


def test_overview_orders_by_last_reviewed_desc(tmp_path):
    site = _dir_site()  # home + architecture (directory section)
    _seed_landing(tmp_path, "docs/site-src/architecture/index.md", "# Architecture\n")
    _seed_landing(
        tmp_path,
        "docs/site-src/architecture/old.md",
        "---\nlast_reviewed: '2026-01-01'\n---\n\n# Old Page\n\nold.\n",
    )
    _seed_landing(
        tmp_path,
        "docs/site-src/architecture/new.md",
        "---\nlast_reviewed: '2026-05-01'\n---\n\n# New Page\n\nnew.\n",
    )
    so.generate_overviews(tmp_path, site)
    out = (tmp_path / "docs/site-src/architecture/index.md").read_text()
    assert out.index("New Page") < out.index("Old Page")


def test_overview_undated_page_sinks_last(tmp_path):
    site = _dir_site()
    _seed_landing(tmp_path, "docs/site-src/architecture/index.md", "# Architecture\n")
    _seed_landing(
        tmp_path,
        "docs/site-src/architecture/dated.md",
        "---\nlast_reviewed: '2026-05-01'\n---\n\n# Dated Page\n\nd.\n",
    )
    _seed_landing(
        tmp_path, "docs/site-src/architecture/undated.md", "# Undated Page\n\nu.\n"
    )
    so.generate_overviews(tmp_path, site)
    out = (tmp_path / "docs/site-src/architecture/index.md").read_text()
    assert out.index("Dated Page") < out.index("Undated Page")


def test_overview_title_tiebreak_when_equal_freshness(tmp_path):
    site = _dir_site()
    _seed_landing(tmp_path, "docs/site-src/architecture/index.md", "# Architecture\n")
    _seed_landing(tmp_path, "docs/site-src/architecture/b.md", "# Banana\n\nb.\n")
    _seed_landing(tmp_path, "docs/site-src/architecture/a.md", "# Apple\n\na.\n")
    so.generate_overviews(tmp_path, site)
    out = (tmp_path / "docs/site-src/architecture/index.md").read_text()
    assert out.index("Apple") < out.index("Banana")  # both undated -> title asc


def test_generate_overviews_api_no_python_degrades(tmp_path, monkeypatch):
    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "api", "path": "api/", "title": "API", "generator": "api-extract"},
        ],
    }
    _seed_landing(tmp_path, "docs/site-src/api/index.md", "# API\n")
    monkeypatch.setattr(
        setup_discover,
        "detect_python",
        lambda root: {"detected": False, "scan_dir": None, "path_root": None},
    )
    result = so.generate_overviews(tmp_path, site)
    out = (tmp_path / "docs/site-src/api/index.md").read_text()
    assert mb.START in out
    assert "_No pages yet._" in out or "modules" in out
