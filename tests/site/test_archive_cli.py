from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI = _REPO_ROOT / "scripts" / "archive_indexes.py"
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "archive_indexes"

_CONFIG = """\
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths: {}
sources: { git: { host: github } }
lint: {}
publishing: { base_url: "https://x", build_workflow: "ci.yml", url_map_rule: "strip-ext" }
notifications: {}
site:
  docs_dir: docs/site-src
  sections:
    - { key: archive, path: archive/, title: Decision Archive,
        generator: archive-index, sources: [docs/superpowers/specs] }
"""


def test_cli_generates_and_reports_json(tmp_path):
    (tmp_path / "docs/superpowers").mkdir(parents=True)
    shutil.copytree(_FIXTURES / "specs", tmp_path / "docs/superpowers/specs")
    cfg = tmp_path / "config.yml"
    cfg.write_text(_CONFIG)

    proc = subprocess.run(
        [
            sys.executable,
            str(_CLI),
            "--repo-root",
            str(tmp_path),
            "--config",
            str(cfg),
            "--repo-url-base",
            "https://github.com/o/n/blob/main/",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert "docs/site-src/archive/specs.md" in result["written"]
    page = (tmp_path / "docs/site-src/archive/specs.md").read_text()
    assert "https://github.com/o/n/blob/main/docs/superpowers/specs/" in page


def test_cli_missing_config_errors(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(_CLI),
            "--repo-root",
            str(tmp_path),
            "--config",
            str(tmp_path / "nope.yml"),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "error" in proc.stderr.lower()


def test_cli_invalid_yaml_errors(tmp_path):
    # malformed config.yml surfaces a clean error, not a raw traceback
    cfg = tmp_path / "config.yml"
    cfg.write_text(": bad: yaml: {{{\n")
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--repo-root", str(tmp_path), "--config", str(cfg)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "error" in proc.stderr.lower()
    assert "Traceback" not in proc.stderr
