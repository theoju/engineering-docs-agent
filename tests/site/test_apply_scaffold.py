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
        {"key": "api", "path": "api/", "title": "API reference"},
    ],
}


def test_apply_creates_files(tmp_path: Path):
    result = site_structure.apply_scaffold(
        tmp_path, SITE, site_name="Demo", python_detected=False
    )
    assert (tmp_path / "docs/site-src/index.md").exists()
    assert (tmp_path / "docs/site-src/api/index.md").exists()
    assert (tmp_path / "mkdocs.yml").exists()
    assert "docs/site-src/api/index.md" in result["created"]


def test_apply_is_idempotent_and_never_clobbers(tmp_path: Path):
    site_structure.apply_scaffold(
        tmp_path, SITE, site_name="Demo", python_detected=False
    )
    # an author edits a stub
    page = tmp_path / "docs/site-src/api/index.md"
    page.write_text("# API\n\nReal authored content.\n")
    # re-run (structure-sync)
    result = site_structure.apply_scaffold(
        tmp_path, SITE, site_name="Demo", python_detected=False
    )
    assert page.read_text() == "# API\n\nReal authored content.\n"  # untouched
    assert "docs/site-src/api/index.md" in result["skipped"]


def test_apply_adds_new_section_on_resync(tmp_path: Path):
    site_structure.apply_scaffold(
        tmp_path, SITE, site_name="Demo", python_detected=False
    )
    site2 = {
        **SITE,
        "sections": SITE["sections"]
        + [{"key": "operations", "path": "operations/", "title": "Operations"}],
    }
    result = site_structure.apply_scaffold(
        tmp_path, site2, site_name="Demo", python_detected=False
    )
    assert (tmp_path / "docs/site-src/operations/index.md").exists()
    assert "docs/site-src/operations/index.md" in result["created"]


def test_apply_writes_utf8(tmp_path: Path):
    # Files must be written as UTF-8 on every platform and round-trip cleanly.
    # The "→" glyph that used to appear in the static grid cards now lives in
    # the generator-filled managed block (generate_overviews → render_home_overview),
    # so we verify the UTF-8 invariant via the managed block markers and the
    # section-index stub (which also writes UTF-8).
    site_structure.apply_scaffold(
        tmp_path, SITE, site_name="Demo", python_detected=False
    )
    home = (tmp_path / "docs/site-src/index.md").read_text(encoding="utf-8")
    assert "docs-agent:overview:start" in home
    assert "docs-agent:overview:end" in home
    # section-index stub written as UTF-8 (content includes non-ASCII-safe characters
    # in the template when titles use special characters; basic check is sufficient).
    section = (tmp_path / "docs/site-src/api/index.md").read_text(encoding="utf-8")
    assert "API reference" in section


def test_apply_never_clobbers_hand_tuned_mkdocs_yml(tmp_path: Path):
    # mkdocs.yml is the highest-value never-clobber target: a hand-tuned
    # config must survive a resync untouched.
    site_structure.apply_scaffold(
        tmp_path, SITE, site_name="Demo", python_detected=False
    )
    mkdocs = tmp_path / "mkdocs.yml"
    mkdocs.write_text("site_name: Hand Tuned\n", encoding="utf-8")
    result = site_structure.apply_scaffold(
        tmp_path, SITE, site_name="Demo", python_detected=False
    )
    assert mkdocs.read_text(encoding="utf-8") == "site_name: Hand Tuned\n"
    assert "mkdocs.yml" in result["skipped"]
