from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SETUP_CLI = _REPO_ROOT / "scripts" / "setup_scaffold.py"
_ARCHIVE_CLI = _REPO_ROOT / "scripts" / "archive_indexes.py"
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "archive_indexes"

pytestmark = pytest.mark.skipif(
    shutil.which("mkdocs") is None, reason="mkdocs not installed (doc-build dep)"
)

_SITE = {
    "docs_dir": "docs/site-src",
    "theme": "material",
    "sections": [
        {"key": "home", "path": "index.md", "title": "Home"},
        {
            "key": "archive",
            "path": "archive/",
            "title": "Decision Archive",
            "generator": "archive-index",
            "sources": ["docs/superpowers/specs"],
        },
    ],
}

_CONFIG = {
    "docs": {
        "framework": "mkdocs",
        "source_dir": "docs",
        "whats_new_file": "docs/site-src/whats-new.md",
        "agent_editable_paths": ["docs/site-src/**"],
        "lens_paths": {},
    },
    "sources": {"git": {"host": "github"}},
    "lint": {},
    "publishing": {
        "base_url": "https://x",
        "build_workflow": "ci.yml",
        "url_map_rule": "strip-ext",
    },
    "notifications": {},
    "site": _SITE,
}


def test_scaffold_plus_archive_builds_strict(tmp_path: Path):
    # source content for the archive
    (tmp_path / "docs/superpowers").mkdir(parents=True)
    shutil.copytree(_FIXTURES / "specs", tmp_path / "docs/superpowers/specs")

    site_yaml = tmp_path / "site.yaml"
    site_yaml.write_text(yaml.safe_dump(_SITE))
    config_yaml = tmp_path / "config.yml"
    config_yaml.write_text(yaml.safe_dump(_CONFIG))

    # S: scaffold
    subprocess.run(
        [
            sys.executable,
            str(_SETUP_CLI),
            "--repo-root",
            str(tmp_path),
            "--site-name",
            "Demo",
            "--config",
            str(site_yaml),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    # D: generate archive pages
    subprocess.run(
        [
            sys.executable,
            str(_ARCHIVE_CLI),
            "--repo-root",
            str(tmp_path),
            "--config",
            str(config_yaml),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert (tmp_path / "docs/site-src/archive/specs.md").exists()

    # build gate
    proc = subprocess.run(
        ["mkdocs", "build", "--strict"], cwd=tmp_path, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
