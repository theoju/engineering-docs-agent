from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import managed_block as mb  # noqa: E402
import section_overview as so  # noqa: E402


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
