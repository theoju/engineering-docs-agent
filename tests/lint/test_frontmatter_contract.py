from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import frontmatter_contract as fc  # noqa: E402


def test_required_fields_default_for_none_and_unknown():
    assert fc.required_fields(None) == ("status", "sources", "synthesized_into")
    assert fc.required_fields("changelog") == ("status", "sources", "synthesized_into")
    assert fc.required_fields("archive-index") == (
        "status",
        "sources",
        "synthesized_into",
    )


def test_required_fields_agent_authored():
    assert fc.required_fields("agent-authored") == (
        "description",
        "source_files",
        "last_reviewed",
        "status",
    )


_CONFIG = {
    "site": {
        "docs_dir": "docs/site-src",
        "sections": [
            {
                "key": "core",
                "path": "core/",
                "title": "Core",
                "generator": "agent-authored",
            },
            {"key": "api", "path": "api/", "title": "API", "generator": "api-extract"},
            {
                "key": "whats-new",
                "path": "whats-new.md",
                "title": "WN",
                "generator": "changelog",
            },
            {"key": "ops", "path": "operations/", "title": "Ops"},
        ],
    }
}


def test_section_generator_for_dir_section():
    page = Path("/repo/docs/site-src/core/api.md")
    assert fc.section_generator_for(page, _CONFIG) == "agent-authored"


def test_section_generator_for_file_section():
    page = Path("/repo/docs/site-src/whats-new.md")
    assert fc.section_generator_for(page, _CONFIG) == "changelog"


def test_section_generator_for_section_without_generator_is_none():
    page = Path("/repo/docs/site-src/operations/runbook.md")
    assert fc.section_generator_for(page, _CONFIG) is None


def test_section_generator_for_no_match_is_none():
    page = Path("/repo/docs/site-src/elsewhere/x.md")
    assert fc.section_generator_for(page, _CONFIG) is None


def test_section_generator_for_no_site_block_is_none():
    assert fc.section_generator_for(Path("/repo/docs/site-src/core/api.md"), {}) is None


def test_section_generator_for_prefix_is_segment_bounded():
    cfg = {
        "site": {
            "docs_dir": "docs/site-src",
            "sections": [
                {
                    "key": "core-extra",
                    "path": "core-extra/",
                    "title": "X",
                    "generator": "changelog",
                },
                {
                    "key": "core",
                    "path": "core/",
                    "title": "Core",
                    "generator": "agent-authored",
                },
            ],
        }
    }
    assert (
        fc.section_generator_for(Path("/r/docs/site-src/core/a.md"), cfg)
        == "agent-authored"
    )
    assert (
        fc.section_generator_for(Path("/r/docs/site-src/core-extra/a.md"), cfg)
        == "changelog"
    )
