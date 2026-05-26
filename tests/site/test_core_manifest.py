from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import core_manifest as cm  # noqa: E402


def _site(generator="agent-authored", path="architecture/"):
    return {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "home", "path": "index.md", "title": "Home"},
            {
                "key": "arch",
                "path": path,
                "title": "Architecture",
                "generator": generator,
            },
        ],
    }


def test_agent_authored_section_found():
    s = cm._agent_authored_section(_site())
    assert s is not None and s["path"] == "architecture/"


def test_agent_authored_section_absent_returns_none():
    assert cm._agent_authored_section(_site(generator="changelog")) is None
    assert cm._agent_authored_section({}) is None
    assert cm._agent_authored_section("notadict") is None


def test_source_root_glob_python_package(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    assert cm._source_root_glob(tmp_path) == "pkg/**/*.py"


def test_source_root_glob_none_when_no_python(tmp_path):
    assert cm._source_root_glob(tmp_path) is None


def test_resolve_specs_dir_explicit_arg(tmp_path):
    d = tmp_path / "myspecs"
    d.mkdir()
    assert cm._resolve_specs_dir(tmp_path, _site(), "myspecs") == d


def test_resolve_specs_dir_from_archive_sources(tmp_path):
    # Non-default path so this exercises the archive-source branch, not the
    # docs/superpowers/specs default fallback.
    specs = tmp_path / "custom" / "spec-docs"
    specs.mkdir(parents=True)
    site = _site()
    site["sections"].append(
        {
            "key": "archive",
            "path": "archive/",
            "generator": "archive-index",
            "sources": ["custom/spec-docs", "docs/superpowers/plans"],
        }
    )
    assert cm._resolve_specs_dir(tmp_path, site, None) == specs


def test_resolve_specs_dir_none_when_absent(tmp_path):
    assert cm._resolve_specs_dir(tmp_path, _site(), None) is None


def test_spec_key_strips_date_and_suffix():
    assert cm._spec_key("2026-05-26-payments-api-design") == "payments-api"
    assert cm._spec_key("2026-01-02-foo-plan") == "foo"
    assert cm._spec_key("Storage Layer") == "storage-layer"


def test_title_from_key():
    assert cm._title_from_key("payments-api") == "Payments Api"
    assert cm._title_from_key("system-overview") == "System Overview"


def test_extract_source_globs_keeps_code_paths_drops_prose():
    text = (
        "See `backend/app/api/routes.py:12` and `scripts/x.py`.\n"
        "Glob `backend/**/*.py`. Prose `docs/superpowers/specs/foo` and "
        "a url `https://example.com/x` and a bare word `Connector`.\n"
    )
    assert cm._extract_source_globs(text) == [
        "backend/**/*.py",
        "backend/app/api/routes.py",
        "scripts/x.py",
    ]


def test_detect_specs_present_one_page_per_spec(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "2026-05-26-payments-design.md").write_text(
        "Payments live in `pkg/payments.py`.\n"
    )
    (specs / "2026-05-26-storage-design.md").write_text("No code refs here.\n")

    manifest = cm.detect_core_manifest(tmp_path, _site(), specs_dir="specs")
    assert manifest["version"] == 1
    pages = manifest["pages"]
    assert [p["key"] for p in pages] == ["payments", "storage"]
    payments = pages[0]
    assert payments["page"] == "architecture/payments.md"
    assert payments["title"] == "Payments"
    assert payments["source_files"] == ["pkg/payments.py"]
    # storage had no extractable refs -> falls back to the detected source root
    assert pages[1]["source_files"] == ["pkg/**/*.py"]
