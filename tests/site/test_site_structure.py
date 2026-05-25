from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import site_structure  # noqa: E402

SITE = {
    "docs_dir": "docs/site-src",
    "theme": "material",
    "sections": [
        {"key": "home", "path": "index.md", "title": "Home"},
        {
            "key": "api",
            "path": "api/",
            "title": "API reference",
            "generator": "api-extract",
        },
    ],
}


def test_plan_scaffold_emits_index_and_section_dirs():
    files = {f.path: f for f in site_structure.plan_scaffold(SITE)}
    # the home page
    assert "docs/site-src/index.md" in files
    # a directory section gets an index stub + a .pages
    assert "docs/site-src/api/index.md" in files
    assert "docs/site-src/api/.pages" in files
    # a root .pages orders the sections
    assert "docs/site-src/.pages" in files


def test_section_index_stub_has_title_and_draft_frontmatter():
    files = {f.path: f for f in site_structure.plan_scaffold(SITE)}
    stub = files["docs/site-src/api/index.md"].content
    assert "title: API reference" in stub
    assert "status: draft" in stub


def test_page_section_has_no_directory():
    # whats-new style single-page section (path ends in .md) → no dir/.pages
    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "whats-new", "path": "whats-new.md", "title": "What's New"}
        ],
    }
    paths = {f.path for f in site_structure.plan_scaffold(site)}
    assert "docs/site-src/whats-new.md" in paths
    assert "docs/site-src/whats-new.md/.pages" not in paths
