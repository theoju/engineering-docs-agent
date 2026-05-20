from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

RUNNER = Path(__file__).parent.parent.parent / "scripts" / "orchestrator_runner.py"
FAKES = Path(__file__).parent / "fakes"


def test_pipeline_dry_run(tmp_path):
    (tmp_path / "docs" / "site-src" / "core").mkdir(parents=True)
    (tmp_path / ".engineering-docs-agent").mkdir()
    cfg = tmp_path / ".engineering-docs-agent" / "config.yml"
    cfg.write_text("""
docs:
  framework: mkdocs
  source_dir: docs/site-src
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths:
    core: docs/site-src/core
sources:
  git: { host: github }
trigger: { cron: "0 7 * * *", on_pr_merge: false }
gap_detection:
  allowlist_paths: ["backend/connectors/**"]
  size_filter: { min_loc: 50, min_files: 3 }
lint: { tier1: default, tier2: {}, tier3: {} }
publishing:
  base_url: https://example.com
  build_workflow: deploy.yml
  url_map_rule: standard
  verify_timeout_seconds: 60
notifications:
  slack: { enabled: false }
  email: { enabled: false }
""")
    state = tmp_path / ".engineering-docs-agent" / "state.json"
    state.write_text(
        json.dumps({"version": "1", "dismissed_gap_flags": {}, "cursors": {}})
    )

    # Initialize git in tmp_path so the runner can call `git rev-parse HEAD`.
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "init",
        ],
        check=True,
    )

    r = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--repo-root",
            str(tmp_path),
            "--dry-run-subagents",
            str(FAKES),
            "--no-pr",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    updated = json.loads(state.read_text())
    assert "current_run" in updated
    whats_new = tmp_path / "docs" / "site-src" / "whats-new.md"
    assert whats_new.exists(), "What's New file should be created"
    content = whats_new.read_text()
    assert "PR #1" in content
    assert "Gaps flagged" in content
