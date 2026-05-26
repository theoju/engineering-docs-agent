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


def test_section_generator_for_malformed_config_never_raises():
    # Each malformed shape must return None, not raise.
    assert (
        fc.section_generator_for(Path("/r/docs/site-src/core/a.md"), {"site": "nope"})
        is None
    )
    assert (
        fc.section_generator_for(
            Path("/r/docs/site-src/core/a.md"),
            {"site": {"docs_dir": "docs/site-src", "sections": "notalist"}},
        )
        is None
    )
    assert (
        fc.section_generator_for(
            Path("/r/docs/site-src/core/a.md"),
            {
                "site": {
                    "docs_dir": "docs/site-src",
                    "sections": [
                        "core/",
                        {"path": "core/", "generator": "agent-authored"},
                    ],
                }
            },
        )
        == "agent-authored"
    )  # a junk string element is skipped, the valid dict still matches
    assert (
        fc.section_generator_for(
            Path("/r/docs/site-src/core/a.md"),
            {
                "site": {
                    "docs_dir": 123,
                    "sections": [{"path": "core/", "generator": "agent-authored"}],
                }
            },
        )
        is None
    )  # non-str docs_dir -> no match


def test_section_generator_for_page_none_returns_none():
    assert fc.section_generator_for(None, _CONFIG) is None


def test_section_generator_for_accepts_str_page():
    assert (
        fc.section_generator_for("/r/docs/site-src/core/a.md", _CONFIG)
        == "agent-authored"
    )


def test_default_frontmatter_dict_shape():
    d = fc.default_frontmatter_dict(["https://pr/1"])
    assert d == {"status": "draft", "sources": ["https://pr/1"], "synthesized_into": []}
    assert set(fc.DEFAULT_REQUIRED) <= set(d)


def test_default_frontmatter_dict_empty_sources():
    assert fc.default_frontmatter_dict() == {
        "status": "draft",
        "sources": [],
        "synthesized_into": [],
    }


def test_default_frontmatter_text_is_valid_and_complete():
    import yaml as _yaml

    text = fc.default_frontmatter_text()
    assert text.startswith("---\n") and text.endswith("---\n")
    body = _yaml.safe_load(text.split("---", 2)[1])
    assert set(fc.DEFAULT_REQUIRED) <= set(body)
    assert body["status"] == "draft"


def test_section_generator_for_docs_dir_relative_page():
    # docs_dir absent from the page path -> resolves via the section path alone.
    assert fc.section_generator_for("core/api.md", _CONFIG) == "agent-authored"
    assert fc.section_generator_for(Path("core/api.md"), _CONFIG) == "agent-authored"


def test_section_generator_for_bare_file_section_page():
    assert fc.section_generator_for("whats-new.md", _CONFIG) == "changelog"


def test_section_generator_for_docs_dir_relative_no_section_is_none():
    assert fc.section_generator_for("elsewhere/x.md", _CONFIG) is None


def test_section_generator_for_under_docs_dir_no_section_stays_none():
    # docs_dir IS present but no section contains the page -> None (no fallback).
    assert fc.section_generator_for("/r/docs/site-src/elsewhere/x.md", _CONFIG) is None


def test_section_generator_for_docs_dir_relative_longest_match_wins():
    cfg = {
        "site": {
            "docs_dir": "docs/site-src",
            "sections": [
                {
                    "key": "arch",
                    "path": "architecture/",
                    "title": "A",
                    "generator": "agent-authored",
                },
                {"key": "home", "path": "index.md", "title": "H"},
            ],
        }
    }
    # bare-frame page under architecture/ still resolves agent-authored
    assert fc.section_generator_for("architecture/index.md", cfg) == "agent-authored"


def test_agent_authored_frontmatter_dict_shape():
    d = fc.agent_authored_frontmatter_dict(
        description="API layer",
        source_files=["a/b.py", "a/c.py"],
        last_reviewed="2026-05-26",
    )
    assert d == {
        "description": "API layer",
        "source_files": ["a/b.py", "a/c.py"],
        "last_reviewed": "2026-05-26",
        "status": "draft",
    }
    assert set(fc.AGENT_AUTHORED_REQUIRED) <= set(d)


def test_agent_authored_frontmatter_dict_copies_source_files():
    src = ["a/b.py"]
    d = fc.agent_authored_frontmatter_dict(
        description="x", source_files=src, last_reviewed="2026-05-26"
    )
    src.append("mutated")
    assert d["source_files"] == ["a/b.py"]  # not aliased to caller's list


def test_agent_authored_frontmatter_text_valid_and_complete():
    import yaml as _yaml

    text = fc.agent_authored_frontmatter_text(
        description="API layer",
        source_files=["a/b.py", "a/c.py"],
        last_reviewed="2026-05-26",
    )
    assert text.startswith("---\n") and text.endswith("---\n")
    body = _yaml.safe_load(text.split("---", 2)[1])
    assert set(fc.AGENT_AUTHORED_REQUIRED) <= set(body)
    assert body["description"] == "API layer"
    assert body["source_files"] == ["a/b.py", "a/c.py"]
    assert body["last_reviewed"] == "2026-05-26"
    assert body["status"] == "draft"


def test_agent_authored_frontmatter_text_empty_source_files():
    import yaml as _yaml

    text = fc.agent_authored_frontmatter_text(
        description="x", source_files=[], last_reviewed="2026-05-26"
    )
    body = _yaml.safe_load(text.split("---", 2)[1])
    assert body["source_files"] == []


def test_agent_authored_frontmatter_text_custom_status():
    import yaml as _yaml

    text = fc.agent_authored_frontmatter_text(
        description="x",
        source_files=["a.py"],
        last_reviewed="2026-05-26",
        status="reviewed",
    )
    body = _yaml.safe_load(text.split("---", 2)[1])
    assert body["status"] == "reviewed"
