from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import site_structure  # noqa: E402

SITE = {"docs_dir": "docs/site-src", "theme": "material", "sections": []}


def test_python_wiring_emits_full_recipe():
    y = site_structure.render_mkdocs_yaml(
        SITE,
        site_name="X",
        python_detected=True,
        python_path_root="scripts",
        openapi_enabled=False,
    )
    assert "gen-files" in y
    assert "literate-nav" in y
    assert "mkdocstrings" in y
    assert 'paths: ["scripts"]' in y


def test_no_python_omits_recipe():
    y = site_structure.render_mkdocs_yaml(SITE, site_name="X", python_detected=False)
    assert "mkdocstrings" not in y
    assert "gen-files" not in y


def test_openapi_enabled_emits_swagger_plugin():
    y = site_structure.render_mkdocs_yaml(
        SITE,
        site_name="X",
        python_detected=False,
        openapi_enabled=True,
    )
    assert "render_swagger" in y


def test_backward_compatible_defaults():
    # S's original 3-arg call still works (new args default safely).
    y = site_structure.render_mkdocs_yaml(SITE, site_name="X", python_detected=True)
    assert "mkdocstrings" in y
    assert 'paths: ["."]' in y  # default path_root when none supplied
