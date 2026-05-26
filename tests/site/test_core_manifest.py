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
    specs = tmp_path / "docs" / "superpowers" / "specs"
    specs.mkdir(parents=True)
    site = _site()
    site["sections"].append(
        {
            "key": "archive",
            "path": "archive/",
            "generator": "archive-index",
            "sources": ["docs/superpowers/specs", "docs/superpowers/plans"],
        }
    )
    assert cm._resolve_specs_dir(tmp_path, site, None) == specs


def test_resolve_specs_dir_none_when_absent(tmp_path):
    assert cm._resolve_specs_dir(tmp_path, _site(), None) is None
