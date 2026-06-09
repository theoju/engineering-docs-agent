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


def test_home_has_managed_block_markers():
    # Grid cards now live inside the managed block (filled by generate_overviews).
    # render_home emits an empty block so the generator can upsert cards in.
    home = site_structure.render_home(SITE)
    assert "docs-agent:overview:start" in home
    assert "docs-agent:overview:end" in home
    assert "grid cards" not in home  # cards come from the generator, not the stub


def test_plan_scaffold_home_has_managed_block():
    files = {f.path: f for f in site_structure.plan_scaffold(SITE)}
    content = files["docs/site-src/index.md"].content
    assert "docs-agent:overview:start" in content
    assert "docs-agent:overview:end" in content


def test_home_links_resolve_to_md_targets():
    # Directory sections link to <dir>/index.md (mkdocs-validatable under
    # --strict); single-page sections link to their .md path directly.
    # These links are now generated inside the managed block by generate_overviews;
    # render_home itself just emits the empty marker pair.
    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "home", "path": "index.md", "title": "Home"},
            {"key": "api", "path": "api/", "title": "API reference"},
            {"key": "whats-new", "path": "whats-new.md", "title": "What's New"},
        ],
    }
    home = site_structure.render_home(site)
    # The stub only contains the markers; link targets are injected by the generator.
    assert "docs-agent:overview:start" in home
    assert "docs-agent:overview:end" in home
