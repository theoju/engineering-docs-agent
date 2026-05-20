from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

RUNNER = Path(__file__).parent.parent.parent / "scripts" / "orchestrator_runner.py"
FAKES = Path(__file__).parent / "fakes"
FAKES_BLOCK = Path(__file__).parent / "fakes_block"

CONFIG_YAML = """
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
"""


def _init_host(tmp_path: Path, *, seed_files: dict[str, str] | None = None) -> Path:
    """Create a docs site skeleton, config, state, and initial git commit.

    `seed_files` is a mapping of repo-relative path → content for files that
    must exist in the initial commit (so they're in HEAD before the runner runs).
    """
    (tmp_path / "docs" / "site-src" / "core").mkdir(parents=True)
    (tmp_path / ".engineering-docs-agent").mkdir()
    (tmp_path / ".engineering-docs-agent" / "config.yml").write_text(CONFIG_YAML)
    state = tmp_path / ".engineering-docs-agent" / "state.json"
    state.write_text(
        json.dumps({"version": "1", "dismissed_gap_flags": {}, "cursors": {}})
    )
    for rel, body in (seed_files or {}).items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)

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
    return state


def _run(tmp_path: Path, fakes_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--repo-root",
            str(tmp_path),
            "--dry-run-subagents",
            str(fakes_dir),
            "--no-pr",
        ],
        capture_output=True,
        text=True,
    )


def test_pipeline_dry_run(tmp_path):
    state = _init_host(tmp_path)
    r = _run(tmp_path, FAKES)
    assert r.returncode == 0, r.stderr
    updated = json.loads(state.read_text())
    assert "current_run" in updated
    whats_new = tmp_path / "docs" / "site-src" / "whats-new.md"
    assert whats_new.exists(), "What's New file should be created"
    content = whats_new.read_text()
    assert "PR #1" in content
    assert "Gaps flagged" in content


def test_lint_block_unlinks_newly_created_file(tmp_path):
    """Create case: page-author writes a new file, validator blocks → unlink."""
    state = _init_host(tmp_path)
    target = tmp_path / "docs" / "site-src" / "core" / "connectors" / "foo.md"
    assert not target.exists(), "foo.md must not be in HEAD for the create-case"

    r = _run(tmp_path, FAKES_BLOCK)
    assert r.returncode == 0, r.stderr
    assert not target.exists(), "blocked create should be unlinked"

    updated = json.loads(state.read_text())
    reasons = updated["current_run"]["partial_reasons"]
    assert updated["current_run"]["partial"] is True
    assert any("lint_block" in reason for reason in reasons), reasons


def test_lint_block_restores_edited_file_from_head(tmp_path):
    """Edit case: file in HEAD with original content, working tree modified,
    validator blocks → git checkout HEAD -- restores original content."""
    rel = "docs/site-src/core/connectors/foo.md"
    original = "---\nstatus: published\n---\n# Original\n"
    state = _init_host(tmp_path, seed_files={rel: original})
    target = tmp_path / rel
    assert target.read_text() == original

    # Simulate page-author editing the file in the working tree.
    target.write_text("---\nstatus: draft\n---\n# Mutated by page-author\n")
    assert target.read_text() != original

    r = _run(tmp_path, FAKES_BLOCK)
    assert r.returncode == 0, r.stderr
    assert target.read_text() == original, "blocked edit should be restored from HEAD"

    updated = json.loads(state.read_text())
    assert updated["current_run"]["partial"] is True
    assert any(
        "lint_block" in reason for reason in updated["current_run"]["partial_reasons"]
    )
