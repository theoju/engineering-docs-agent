from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import contracts_doc  # noqa: E402
import site_structure  # noqa: E402

_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "api" / "host"

pytestmark = pytest.mark.skipif(
    shutil.which("mkdocs") is None, reason="mkdocs not installed (doc-build dep)"
)

_SITE = {
    "docs_dir": "docs/site-src",
    "theme": "material",
    "sections": [
        {"key": "home", "path": "index.md", "title": "Home"},
        {
            "key": "api",
            "path": "api/",
            "title": "API reference",
            "generator": "api-extract",
            "extractors": ["python-mkdocstrings", "json-schema", "openapi"],
            "sources": ["schemas"],
            "openapi": "openapi.json",
        },
    ],
}


def _build(tmp_path):
    proc = subprocess.run(
        ["mkdocs", "build", "--strict"], cwd=tmp_path, capture_output=True, text=True
    )
    if (
        proc.returncode != 0
        and "plugin" in proc.stderr.lower()
        and (
            "not installed" in proc.stderr.lower() or "no module" in proc.stderr.lower()
        )
    ):
        pytest.skip(f"mkdocs plugins not in tool env: {proc.stderr[:200]}")
    return proc


def test_api_site_builds_strict(tmp_path):
    shutil.copytree(_FIXTURE, tmp_path, dirs_exist_ok=True)
    site_structure.apply_scaffold(
        tmp_path,
        _SITE,
        site_name="Fixture",
        python_detected=True,
        python_scan_dir="pkg",
        python_path_root=".",
        openapi_path="openapi.json",
    )
    result = contracts_doc.generate_contracts(tmp_path, _SITE)
    assert "docs/site-src/api/contracts/widget.md" in result["written"]

    proc = _build(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    built = tmp_path / "site"
    # python reference (ident "pkg.calc" -> api/reference/pkg/calc/)
    assert (built / "api" / "reference" / "pkg" / "calc" / "index.html").exists()
    assert (built / "api" / "contracts" / "widget" / "index.html").exists()
    assert (built / "api" / "http" / "index.html").exists()


_SITE_GROUPED = {
    "docs_dir": "docs/site-src",
    "theme": "material",
    "sections": [
        {"key": "home", "path": "index.md", "title": "Home"},
        {
            "key": "api",
            "path": "api/",
            "title": "API reference",
            "generator": "api-extract",
            "extractors": ["python-mkdocstrings"],
            "groups": [{"name": "Math", "modules": ["pkg.calc"]}],
        },
    ],
}


def test_api_site_builds_strict_with_groups(tmp_path):
    """Real-consumer guard (CCE-105): a grouped config must build under
    mkdocs --strict and still generate every reference page. The fake-mkdocs
    unit test proves the grouped nav-key tuples; this proves the grouped
    literate-nav SUMMARY survives the real build pipeline (e.g. a group name
    is not markdown-significant in a way that aborts strict mode). `pkg.calc`
    matches the "Math" group; `pkg.util` falls through to "Other".

    Note: surfacing the reference subtree (grouped or flat) in the rendered
    *nav* is a separate, pre-existing wiring concern (literate-nav does not
    currently consume api/reference/SUMMARY.md) tracked under CCE-106; this
    guard deliberately asserts only what CCE-105 owns — that the grouped
    SUMMARY builds strict and the pages generate."""
    shutil.copytree(_FIXTURE, tmp_path, dirs_exist_ok=True)
    site_structure.apply_scaffold(
        tmp_path,
        _SITE_GROUPED,
        site_name="Fixture",
        python_detected=True,
        python_scan_dir="pkg",
        python_path_root=".",
    )
    proc = _build(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    built = tmp_path / "site"
    # grouping only changes nav keys, not the doc paths — both modules build
    assert (built / "api" / "reference" / "pkg" / "calc" / "index.html").exists()
    assert (built / "api" / "reference" / "pkg" / "util" / "index.html").exists()


def test_no_convention_host_skips_cleanly(tmp_path):
    site = {
        "docs_dir": "docs/site-src",
        "theme": "material",
        "sections": [
            {"key": "home", "path": "index.md", "title": "Home"},
            {
                "key": "api",
                "path": "api/",
                "title": "API",
                "generator": "api-extract",
                "extractors": ["json-schema"],
                "sources": ["schemas"],
            },
        ],
    }
    site_structure.apply_scaffold(
        tmp_path, site, site_name="Bare", python_detected=False
    )
    result = contracts_doc.generate_contracts(tmp_path, site)
    assert result["written"] == []
    assert not (tmp_path / "gen_ref_pages.py").exists()
    proc = _build(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
