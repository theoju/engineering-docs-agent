from __future__ import annotations

import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import archive_indexes  # noqa: E402

_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "archive_indexes"

SITE = {
    "docs_dir": "docs/site-src",
    "sections": [
        {"key": "home", "path": "index.md", "title": "Home"},
        {
            "key": "archive",
            "path": "archive/",
            "title": "Decision Archive",
            "generator": "archive-index",
            "sources": [
                "docs/superpowers/specs",
                "docs/superpowers/plans",
                "docs/superpowers/measurements",  # absent -> skipped
            ],
        },
    ],
}


def _seed_sources(repo: Path):
    (repo / "docs/superpowers").mkdir(parents=True)
    shutil.copytree(_FIXTURES / "specs", repo / "docs/superpowers/specs")
    shutil.copytree(_FIXTURES / "plans", repo / "docs/superpowers/plans")


def test_generate_writes_present_skips_absent(tmp_path):
    _seed_sources(tmp_path)
    # No git remote in tmp_path -> link_base resolves to None -> plain text.
    result = archive_indexes.generate_archive(tmp_path, SITE)
    assert (tmp_path / "docs/site-src/archive/specs.md").exists()
    assert (tmp_path / "docs/site-src/archive/plans.md").exists()
    assert "docs/site-src/archive/specs.md" in result["written"]
    assert "docs/site-src/archive/plans.md" in result["written"]
    assert "docs/site-src/archive/measurements.md" in result["skipped"]
    assert not (tmp_path / "docs/site-src/archive/measurements.md").exists()
    page = (tmp_path / "docs/site-src/archive/specs.md").read_text()
    assert "Structured Docs Site" in page and "## 2026-05" in page


def test_generate_overwrites_stale_but_leaves_section_index(tmp_path):
    _seed_sources(tmp_path)
    archive_dir = tmp_path / "docs/site-src/archive"
    archive_dir.mkdir(parents=True)
    # S's section landing stub — D must not touch it.
    (archive_dir / "index.md").write_text("# Decision Archive\n\nLanding.\n")
    # a stale generated page — D must overwrite it.
    (archive_dir / "specs.md").write_text("STALE\n")
    archive_indexes.generate_archive(tmp_path, SITE)
    assert (archive_dir / "index.md").read_text() == "# Decision Archive\n\nLanding.\n"
    assert "STALE" not in (archive_dir / "specs.md").read_text()


def test_generate_noop_when_no_archive_section(tmp_path):
    site = {
        "docs_dir": "docs/site-src",
        "sections": [{"key": "home", "path": "index.md", "title": "Home"}],
    }
    assert archive_indexes.generate_archive(tmp_path, site) == {
        "written": [],
        "skipped": [],
    }


def test_generate_uses_explicit_repo_url_base(tmp_path):
    _seed_sources(tmp_path)
    archive_indexes.generate_archive(
        tmp_path, SITE, repo_url_base="https://github.com/o/n/blob/main/"
    )
    page = (tmp_path / "docs/site-src/archive/specs.md").read_text()
    assert "https://github.com/o/n/blob/main/docs/superpowers/specs/" in page
