from __future__ import annotations
import json as _json
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


def test_detect_code_only_single_system_overview(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    manifest = cm.detect_core_manifest(tmp_path, _site(), specs_dir=None)
    assert [p["key"] for p in manifest["pages"]] == ["system-overview"]
    p = manifest["pages"][0]
    assert p["page"] == "architecture/system-overview.md"
    assert p["source_files"] == ["pkg/**/*.py"]


def test_detect_empty_specs_dir_falls_back_to_overview(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "specs").mkdir()  # exists but contains no *.md
    manifest = cm.detect_core_manifest(tmp_path, _site(), specs_dir="specs")
    assert [p["key"] for p in manifest["pages"]] == ["system-overview"]


def test_detect_nothing_when_no_agent_authored_section(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    assert cm.detect_core_manifest(tmp_path, _site(generator="changelog")) is None


def test_detect_nothing_when_no_source_root_and_no_specs(tmp_path):
    # agent-authored section exists, but no Python source and no specs
    assert cm.detect_core_manifest(tmp_path, _site()) is None


def test_detect_none_when_section_path_blank(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    assert cm.detect_core_manifest(tmp_path, _site(path="/")) is None


def test_dedupe_and_sort_orders_by_key():
    pages = [
        {"key": "zebra", "title": "Z", "page": "arch/zebra.md", "source_files": []},
        {"key": "alpha", "title": "A", "page": "arch/alpha.md", "source_files": []},
    ]
    out = cm._dedupe_and_sort(pages, "arch")
    assert [p["key"] for p in out] == ["alpha", "zebra"]


def test_dedupe_and_sort_disambiguates_colliding_keys():
    pages = [
        {"key": "api", "title": "API", "page": "arch/api.md", "source_files": ["a"]},
        {"key": "api", "title": "API", "page": "arch/api.md", "source_files": ["b"]},
        {"key": "api", "title": "API", "page": "arch/api.md", "source_files": ["c"]},
    ]
    out = cm._dedupe_and_sort(pages, "arch")
    assert [p["key"] for p in out] == ["api", "api-2", "api-3"]
    assert [p["page"] for p in out] == [
        "arch/api.md",
        "arch/api-2.md",
        "arch/api-3.md",
    ]
    # disambiguation rewrites key + page but preserves the rest of the entry
    assert out[1]["source_files"] == ["b"]


def test_detect_collision_when_two_specs_slug_same_key(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "2026-01-01-api-design.md").write_text("`pkg/a.py`\n")
    (specs / "2026-02-02-api-design.md").write_text("`pkg/b.py`\n")
    manifest = cm.detect_core_manifest(tmp_path, _site(), specs_dir="specs")
    assert [p["key"] for p in manifest["pages"]] == ["api", "api-2"]


def test_write_drops_empty_glob_entries_and_writes_artifact(tmp_path):
    # Source tree (no git -> _resolve_tracked_files falls back to rglob).
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "payments.py").write_text("# pay\n")
    (tmp_path / "docs" / "site-src").mkdir(parents=True)
    specs = tmp_path / "specs"
    specs.mkdir()
    # payments.md -> matches a tracked file; ghost.md -> matches nothing (dropped)
    (specs / "2026-05-26-payments-design.md").write_text("`pkg/payments.py`\n")
    (specs / "2026-05-26-ghost-design.md").write_text("`pkg/does_not_exist.py`\n")

    ledger = cm.write_core_manifest(tmp_path, _site(), specs_dir="specs")
    assert ledger["written"] == ["docs/site-src/.doc-core-manifest.json"]
    assert ledger["pages"] == 1
    assert ledger["dropped"] == ["ghost"]

    art = _json.loads(
        (tmp_path / "docs" / "site-src" / ".doc-core-manifest.json").read_text()
    )
    assert art["version"] == 1
    assert [p["key"] for p in art["pages"]] == ["payments"]
    assert art["pages"][0]["source_files"] == ["pkg/payments.py"]


def test_write_no_manifest_when_detection_returns_none(tmp_path):
    (tmp_path / "docs" / "site-src").mkdir(parents=True)
    ledger = cm.write_core_manifest(tmp_path, _site())  # no source, no specs
    assert ledger == {"written": [], "pages": 0, "dropped": []}
    assert not (tmp_path / "docs" / "site-src" / ".doc-core-manifest.json").exists()


def test_write_no_manifest_when_all_entries_dropped(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "docs" / "site-src").mkdir(parents=True)
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "2026-05-26-ghost-design.md").write_text("`pkg/missing.py`\n")
    # Force the overview/per-spec glob to match nothing by removing the only .py
    (tmp_path / "pkg" / "__init__.py").unlink()
    ledger = cm.write_core_manifest(tmp_path, _site(), specs_dir="specs")
    assert ledger["written"] == []
    assert not (tmp_path / "docs" / "site-src" / ".doc-core-manifest.json").exists()


import subprocess


def test_setup_scaffold_main_writes_manifest(tmp_path):
    """End-to-end: running setup_scaffold against a host with an agent-authored
    section + Python source writes .doc-core-manifest.json and reports it."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "core.py").write_text("# core\n")
    cfg = tmp_path / "site.yaml"
    cfg.write_text(
        "docs_dir: docs/site-src\n"
        "theme: material\n"
        "sections:\n"
        "  - {key: home, path: index.md, title: Home}\n"
        "  - key: architecture\n"
        "    path: architecture/\n"
        "    title: Architecture\n"
        "    generator: agent-authored\n"
    )
    scaffold = Path(__file__).resolve().parents[2] / "scripts" / "setup_scaffold.py"
    r = subprocess.run(
        [
            sys.executable,
            str(scaffold),
            "--repo-root",
            str(tmp_path),
            "--config",
            str(cfg),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    out = _json.loads(r.stdout)
    assert out["core_manifest"]["written"] == ["docs/site-src/.doc-core-manifest.json"]
    art = _json.loads(
        (tmp_path / "docs" / "site-src" / ".doc-core-manifest.json").read_text()
    )
    assert [p["key"] for p in art["pages"]] == ["system-overview"]
    assert art["pages"][0]["source_files"] == ["pkg/**/*.py"]
