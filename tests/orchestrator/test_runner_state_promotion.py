# tests/orchestrator/test_runner_state_promotion.py
"""CCE-40: the runner must advance last_successful_run.head_sha and write
only persistent fields to state.json on disk, so the docs-agent PR's
commit carries an advanced state."""

from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

ORCH_RUNNER = Path(__file__).parent.parent.parent / "scripts" / "orchestrator_runner.py"
FAKES_OK = Path(__file__).parent / "fakes"

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
lint: { tier1: default }
publishing:
  base_url: https://example.com
  build_workflow: deploy.yml
  url_map_rule: standard
  verify_timeout_seconds: 60
notifications:
  slack: { enabled: false }
  email: { enabled: false }
"""


def _init_host(tmp_path: Path, seeded_state: dict) -> tuple[Path, str]:
    """Returns (state_path, head_sha_after_init)."""
    (tmp_path / ".engineering-docs-agent").mkdir()
    (tmp_path / ".engineering-docs-agent" / "config.yml").write_text(CONFIG_YAML)
    state_path = tmp_path / ".engineering-docs-agent" / "state.json"
    state_path.write_text(json.dumps(seeded_state))
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True
    )
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True
    )
    head_sha = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return state_path, head_sha


def test_runner_advances_last_successful_run_to_head(tmp_path):
    """After a dry-run, state.json on disk has last_successful_run.head_sha
    set to the repo's HEAD at run start."""
    seeded = {"version": "1", "last_successful_run": {"head_sha": "old_sha_000"}}
    state_path, head_sha = _init_host(tmp_path, seeded)

    result = subprocess.run(
        [
            sys.executable,
            str(ORCH_RUNNER),
            "--repo-root",
            str(tmp_path),
            "--no-pr",
            "--dry-run-subagents",
            str(FAKES_OK),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"runner failed: {result.stderr}"

    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == head_sha, (
        f"expected head_sha to advance to {head_sha}, got "
        f"{written['last_successful_run']['head_sha']}"
    )


def test_runner_does_not_write_current_run_to_state_json(tmp_path):
    """state.json on disk must not contain current_run. The ephemeral
    state goes to the sibling current_run.json (CCE-40)."""
    seeded = {"version": "1", "last_successful_run": {"head_sha": "old_sha_000"}}
    state_path, _ = _init_host(tmp_path, seeded)

    result = subprocess.run(
        [
            sys.executable,
            str(ORCH_RUNNER),
            "--repo-root",
            str(tmp_path),
            "--no-pr",
            "--dry-run-subagents",
            str(FAKES_OK),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"runner failed: {result.stderr}"

    written = json.loads(state_path.read_text())
    assert "current_run" not in written, (
        f"current_run leaked into state.json: {written}"
    )

    # The sibling current_run.json should exist instead.
    sibling = state_path.parent / "current_run.json"
    assert sibling.exists(), "current_run.json sibling should exist after a run"
    cr_data = json.loads(sibling.read_text())
    assert "current_run" in cr_data
