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


def test_home_links_resolve_to_md_targets(tmp_path):
    # The home section directory (now generated INTO the managed block by
    # generate_overviews) must resolve directory sections to <dir>/index.md
    # (mkdocs --strict-validatable) and single-page sections to their .md path
    # directly (NOT <page>.md/index.md). This coverage moved out of render_home
    # when the cards moved into the generator — it is verified here against the
    # real generator output.
    import managed_block as mb
    import section_overview

    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "home", "path": "index.md", "title": "Home"},
            {"key": "api", "path": "api/", "title": "API reference"},
            {"key": "whats-new", "path": "whats-new.md", "title": "What's New"},
        ],
    }
    home = tmp_path / "docs/site-src/index.md"
    home.parent.mkdir(parents=True, exist_ok=True)
    home.write_text(f"# Documentation\n\n{mb.START}\n{mb.END}\n", encoding="utf-8")
    section_overview.generate_overviews(tmp_path, site)
    out = home.read_text(encoding="utf-8")
    assert "](api/index.md)" in out  # directory section -> index.md
    assert "](whats-new.md)" in out  # single-page section -> direct .md
    assert "](whats-new.md/index.md)" not in out
