from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
import source_drift  # noqa: E402

SCRIPT = _ROOT / "scripts" / "source_drift.py"

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
    - { key: home, path: index.md, title: Home }
"""


def _host(tmp_path: Path) -> Path:
    page = tmp_path / "docs/site-src/architecture/auth.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nsource_files:\n  - scripts/auth/**/*.py\n---\n# Auth\n")
    return tmp_path


def test_modified_mapped_file_drifts_its_page(tmp_path):
    host = _host(tmp_path)
    result = source_drift.detect_drift(
        host / "docs/site-src", ["scripts/auth/session.py"]
    )
    assert result == {
        "drifted": [
            {
                "page": "architecture/auth.md",
                "changed_sources": ["scripts/auth/session.py"],
            }
        ],
        "changed_files_seen": 1,
    }


def test_newly_added_file_matching_glob_drifts(tmp_path):
    host = _host(tmp_path)
    result = source_drift.detect_drift(
        host / "docs/site-src", ["scripts/auth/brand_new.py"]
    )
    assert result["drifted"] == [
        {
            "page": "architecture/auth.md",
            "changed_sources": ["scripts/auth/brand_new.py"],
        }
    ]


def test_unrelated_change_is_no_op(tmp_path):
    host = _host(tmp_path)
    result = source_drift.detect_drift(
        host / "docs/site-src", ["README.md", "scripts/other/x.py"]
    )
    assert result == {"drifted": [], "changed_files_seen": 2}


def test_missing_docs_dir_no_op(tmp_path):
    result = source_drift.detect_drift(tmp_path / "nope", ["scripts/auth/a.py"])
    assert result == {"drifted": [], "changed_files_seen": 1}


def test_cli_reads_changed_files_from_stdin(tmp_path):
    host = _host(tmp_path)
    (host / "config.yml").write_text(_CONFIG)
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(host),
            "--config",
            str(host / "config.yml"),
        ],
        input=json.dumps(["scripts/auth/session.py"]),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["drifted"][0]["page"] == "architecture/auth.md"


def test_cli_empty_stdin_is_no_op(tmp_path):
    host = _host(tmp_path)
    (host / "config.yml").write_text(_CONFIG)
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(host),
            "--config",
            str(host / "config.yml"),
        ],
        input="",
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"drifted": [], "changed_files_seen": 0}
