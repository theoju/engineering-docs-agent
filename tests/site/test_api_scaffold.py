from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import site_structure  # noqa: E402

API_SITE = {
    "docs_dir": "docs/site-src",
    "theme": "material",
    "sections": [
        {"key": "home", "path": "index.md", "title": "Home"},
        {
            "key": "api",
            "path": "api/",
            "title": "API",
            "generator": "api-extract",
            "extractors": ["python-mkdocstrings", "openapi"],
            "openapi": "openapi.json",
        },
    ],
}


def test_apply_scaffold_writes_gen_script_when_python(tmp_path):
    site_structure.apply_scaffold(
        tmp_path,
        API_SITE,
        site_name="X",
        python_detected=True,
        python_scan_dir="scripts",
        python_path_root="scripts",
        openapi_path="openapi.json",
    )
    gen = tmp_path / "gen_ref_pages.py"
    assert gen.exists()
    body = gen.read_text()
    assert 'SCAN_DIR = "scripts"' in body
    assert 'PATH_ROOT = "scripts"' in body
    assert "mkdocs_gen_files" in body


def test_apply_scaffold_writes_openapi_stub(tmp_path):
    site_structure.apply_scaffold(
        tmp_path,
        API_SITE,
        site_name="X",
        python_detected=True,
        python_scan_dir="scripts",
        python_path_root="scripts",
        openapi_path="openapi.json",
    )
    http = tmp_path / "docs/site-src/api/http.md"
    assert http.exists()
    assert "openapi.json" in http.read_text()


def test_no_gen_script_without_python(tmp_path):
    site = {
        "docs_dir": "docs/site-src",
        "theme": "material",
        "sections": [{"key": "home", "path": "index.md", "title": "Home"}],
    }
    site_structure.apply_scaffold(tmp_path, site, site_name="X", python_detected=False)
    assert not (tmp_path / "gen_ref_pages.py").exists()
