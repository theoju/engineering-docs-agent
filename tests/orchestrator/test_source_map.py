from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
import source_map  # noqa: E402

SCRIPT = _ROOT / "scripts" / "source_map.py"

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


def _make_host(tmp_path: Path) -> Path:
    (tmp_path / "scripts/auth").mkdir(parents=True)
    (tmp_path / "scripts/auth/session.py").write_text("x = 1\n")
    (tmp_path / "scripts/auth/token.py").write_text("y = 2\n")
    page = tmp_path / "docs/site-src/architecture/auth.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nsource_files:\n  - scripts/auth/**/*.py\n---\n# Auth\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    return tmp_path


def test_generate_writes_dual_view_artifact(tmp_path):
    host = _make_host(tmp_path)
    ledger = source_map.generate_source_map(host, "docs/site-src")
    artifact = json.loads((host / "docs/site-src/.doc-source-map.json").read_text())
    assert artifact["version"] == 1
    assert artifact["map"] == {
        "scripts/auth/session.py": ["architecture/auth.md"],
        "scripts/auth/token.py": ["architecture/auth.md"],
    }
    assert artifact["patterns"] == {"architecture/auth.md": ["scripts/auth/**/*.py"]}
    assert ledger["written"] == ["docs/site-src/.doc-source-map.json"]
    assert ledger["mapped_sources"] == 2


def test_skip_clean_when_no_source_files(tmp_path):
    docs = tmp_path / "docs/site-src"
    docs.mkdir(parents=True)
    (docs / "index.md").write_text("---\ntitle: Home\n---\n# Home\n")
    ledger = source_map.generate_source_map(tmp_path, "docs/site-src")
    assert ledger["written"] == []
    assert not (docs / ".doc-source-map.json").exists()


def test_malformed_frontmatter_recorded_not_aborted(tmp_path):
    docs = tmp_path / "docs/site-src"
    docs.mkdir(parents=True)
    (docs / "bad.md").write_text("---\nsource_files: not-a-list\n---\n# Bad\n")
    ledger = source_map.generate_source_map(tmp_path, "docs/site-src")
    assert {"page": "bad.md", "reason": "source_files is not a list"} in ledger[
        "skipped"
    ]


def test_non_git_repo_falls_back_to_rglob(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("z = 3\n")
    page = tmp_path / "docs/site-src/api.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nsource_files:\n  - src/*.py\n---\n# API\n")
    source_map.generate_source_map(tmp_path, "docs/site-src")  # not a git repo
    artifact = json.loads((tmp_path / "docs/site-src/.doc-source-map.json").read_text())
    assert artifact["map"] == {"src/app.py": ["api.md"]}


def test_cli_reads_config_and_prints_ledger(tmp_path):
    host = _make_host(tmp_path)
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
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "error" not in proc.stderr.lower()
    ledger = json.loads(proc.stdout)
    assert ledger["written"] == ["docs/site-src/.doc-source-map.json"]


def test_cli_invalid_config_exits_1_no_traceback(tmp_path):
    (tmp_path / "config.yml").write_text(": bad: yaml: {{{\n")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--config",
            str(tmp_path / "config.yml"),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "error" in proc.stderr.lower()
    assert "Traceback" not in proc.stderr
