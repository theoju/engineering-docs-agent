"""Guard: every third-party plugin declared in this repo's mkdocs.yml must be
installable from requirements-docs.txt, so `mkdocs build --strict` in CI
(docs.yml site-gate + docs-pages.yml deploy) never crashes on a missing plugin.

This class of bug is invisible to a local build when a separate mkdocs env
already has the plugins installed, so guard it deterministically here.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MKDOCS = ROOT / "mkdocs.yml"
REQS = ROOT / "requirements-docs.txt"


# mkdocs.yml uses `!!python/name:...` tags (superfences mermaid fence); ignore
# them when loading so safe_load doesn't choke.
class _Loader(yaml.SafeLoader):
    pass


_Loader.add_multi_constructor(
    "tag:yaml.org,2002:python/name:", lambda loader, suffix, node: None
)

# mkdocs core built-ins that need no pip package.
_BUILTIN = {"search", "tags"}
# plugin entry-point name -> pip distribution name.
_PKG = {
    "awesome-pages": "mkdocs-awesome-pages-plugin",
    "gen-files": "mkdocs-gen-files",
    "literate-nav": "mkdocs-literate-nav",
    "mkdocstrings": "mkdocstrings",
    "render-swagger": "mkdocs-render-swagger-plugin",
}


def _declared_plugins():
    data = yaml.load(MKDOCS.read_text(), Loader=_Loader)
    names = []
    for entry in data.get("plugins", []):
        names.append(entry if isinstance(entry, str) else next(iter(entry)))
    return names


def _req_packages():
    pkgs = set()
    for raw in REQS.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        # strip extras + version specifier: mkdocstrings[python]==0.30.1 -> mkdocstrings
        pkgs.add(re.split(r"[\[<>=!~ ]", line, maxsplit=1)[0].lower())
    return pkgs


def test_mkdocs_yml_exists():
    assert MKDOCS.exists()


def test_every_declared_plugin_is_installable():
    reqs = _req_packages()
    missing = []
    for name in _declared_plugins():
        if name in _BUILTIN:
            continue
        pkg = _PKG.get(name)
        assert pkg is not None, (
            f"unknown plugin '{name}' — add it to _PKG and requirements-docs.txt"
        )
        if pkg.lower() not in reqs:
            missing.append(f"{name} -> {pkg}")
    assert not missing, "mkdocs.yml plugins not in requirements-docs.txt: " + ", ".join(
        missing
    )
