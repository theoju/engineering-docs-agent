from __future__ import annotations

import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import site_structure  # noqa: E402

SITE = {"docs_dir": "docs/site-src", "theme": "material", "sections": []}


def test_mkdocs_yaml_has_material_and_awesome_pages():
    out = site_structure.render_mkdocs_yaml(
        SITE, site_name="Demo", python_detected=False
    )
    assert "name: material" in out
    assert "navigation.sections" in out
    assert "awesome-pages" in out
    assert "docs_dir: docs/site-src" in out
    # the mermaid custom fence python tag must be present verbatim
    assert "!!python/name:pymdownx.superfences.fence_code_format" in out
    # no mkdocstrings when python not detected
    assert "mkdocstrings" not in out


def test_mkdocs_yaml_adds_mkdocstrings_when_python():
    out = site_structure.render_mkdocs_yaml(
        SITE, site_name="Demo", python_detected=True
    )
    assert "mkdocstrings" in out


def test_mkdocs_yaml_is_parseable_yaml():
    # The !!python/name: tag can't be safe_load'd, and unsafe_load would try to
    # *import* pymdownx (a doc-build dep we don't install in the unit venv). Use
    # a SafeLoader with a no-op constructor for that tag so this test is
    # deterministic regardless of what's installed.
    class _Loader(yaml.SafeLoader):
        pass

    _Loader.add_multi_constructor(
        "tag:yaml.org,2002:python/name:", lambda loader, suffix, node: None
    )
    out = site_structure.render_mkdocs_yaml(
        SITE, site_name="Demo", python_detected=False
    )
    loaded = yaml.load(out, Loader=_Loader)
    assert loaded["theme"]["name"] == "material"
    assert loaded["docs_dir"] == "docs/site-src"
