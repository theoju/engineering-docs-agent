from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI = _REPO_ROOT / "scripts" / "contracts_doc.py"

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
    - { key: api, path: api/, title: API reference, generator: api-extract,
        extractors: [json-schema], sources: [schemas] }
"""


def test_cli_generates_and_reports_json(tmp_path):
    d = tmp_path / "schemas"
    d.mkdir()
    (d / "thing.json").write_text(json.dumps({"title": "Thing", "type": "object"}))
    cfg = tmp_path / "config.yml"
    cfg.write_text(_CONFIG)
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--repo-root", str(tmp_path), "--config", str(cfg)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "error" not in proc.stderr.lower()  # no silent config-validation failure
    result = json.loads(proc.stdout)
    assert "docs/site-src/api/contracts/thing.md" in result["written"]


def test_cli_invalid_yaml_errors_cleanly(tmp_path):
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
