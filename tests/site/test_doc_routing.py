from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import doc_routing as dr  # noqa: E402


def _site(archive_path="archive/"):
    return {
        "docs_dir": "docs/site-src",
        "sections": [
            {
                "key": "architecture",
                "path": "architecture/",
                "generator": "agent-authored",
            },
            {"key": "archive", "path": archive_path, "generator": "archive-index"},
        ],
    }


def test_archive_section_leaf_finds_generator_marker():
    assert dr.archive_section_leaf(_site()) == "archive"


def test_archive_section_leaf_honors_custom_name():
    assert dr.archive_section_leaf(_site("decisions/")) == "decisions"


def test_archive_section_leaf_none_when_absent():
    assert dr.archive_section_leaf({"sections": [{"key": "x", "path": "x/"}]}) is None
    assert dr.archive_section_leaf({}) is None
    assert dr.archive_section_leaf(None) is None  # the `site_config or {}` guard


def test_route_decision_rewrites_to_archive():
    assert (
        dr.route_create_hint(
            "architecture/foo.md", "decision", "archive", ["architecture", "archive"]
        )
        == "archive/foo.md"
    )


def test_route_decision_honors_custom_archive_name():
    assert (
        dr.route_create_hint(
            "architecture/foo.md",
            "decision",
            "decisions",
            ["architecture", "decisions"],
        )
        == "decisions/foo.md"
    )


def test_route_architecture_unchanged():
    assert (
        dr.route_create_hint(
            "architecture/foo.md",
            "architecture",
            "archive",
            ["architecture", "archive"],
        )
        == "architecture/foo.md"
    )


def test_route_absent_doc_kind_unchanged():
    assert (
        dr.route_create_hint(
            "architecture/foo.md", None, "archive", ["architecture", "archive"]
        )
        == "architecture/foo.md"
    )


def test_route_no_archive_section_unchanged():
    assert (
        dr.route_create_hint("architecture/foo.md", "decision", None, ["architecture"])
        == "architecture/foo.md"
    )


def test_route_archive_not_available_unchanged():
    # generic-first: archive declared in config but its dir not yet on disk
    assert (
        dr.route_create_hint(
            "architecture/foo.md", "decision", "archive", ["architecture"]
        )
        == "architecture/foo.md"
    )


def test_route_preserves_filename_only():
    assert (
        dr.route_create_hint(
            "architecture/sub/bar.md",
            "decision",
            "archive",
            ["architecture", "archive"],
        )
        == "archive/bar.md"
    )


def test_route_slashless_hint_to_archive():
    # a flat-slug hint (no section prefix) still routes cleanly to the archive
    assert (
        dr.route_create_hint(
            "foo.md", "decision", "archive", ["architecture", "archive"]
        )
        == "archive/foo.md"
    )
