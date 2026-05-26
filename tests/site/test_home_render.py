from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import site_structure  # noqa: E402

SITE = {
    "docs_dir": "docs/site-src",
    "sections": [
        {"key": "home", "path": "index.md", "title": "Home"},
        {"key": "api", "path": "api/", "title": "API reference"},
        {"key": "operations", "path": "operations/", "title": "Operations"},
    ],
}


def test_home_uses_grid_cards_and_links_non_home_sections():
    home = site_structure.render_home(SITE)
    assert '<div class="grid cards" markdown>' in home
    assert "API reference" in home and "api/" in home
    assert "Operations" in home and "operations/" in home
    # the home section itself is not a card linking to itself
    assert home.count("](index.md)") == 0


def test_plan_scaffold_home_uses_grid_cards():
    files = {f.path: f for f in site_structure.plan_scaffold(SITE)}
    assert (
        '<div class="grid cards" markdown>' in files["docs/site-src/index.md"].content
    )


def test_home_links_resolve_to_md_targets():
    # Directory sections link to <dir>/index.md (mkdocs-validatable under
    # --strict); single-page sections link to their .md path directly.
    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "home", "path": "index.md", "title": "Home"},
            {"key": "api", "path": "api/", "title": "API reference"},
            {"key": "whats-new", "path": "whats-new.md", "title": "What's New"},
        ],
    }
    home = site_structure.render_home(site)
    assert "](api/index.md)" in home
    assert "](whats-new.md)" in home
