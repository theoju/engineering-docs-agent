# tests/orchestrator/test_state_carry_forward.py
"""CCE-5: partial_reasons from a prior run must NOT carry forward into the
next run's current_run. Persistent root causes will re-accumulate on their
own when the next run also fails; transient reasons must not survive."""

from __future__ import annotations
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
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


def _read_current_run(state_path: Path) -> dict:
    """CCE-40: current_run lives in a sibling file, not state.json."""
    sibling = state_path.parent / "current_run.json"
    return json.loads(sibling.read_text())["current_run"]


def _init_host(tmp_path: Path, seeded_state: dict) -> Path:
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
    return state_path


def _run_orchestrator(tmp_path: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "GITHUB_REPOSITORY": "owner/repo"}
    return subprocess.run(
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
        env=env,
    )


def test_prior_run_partial_reasons_do_not_carry_forward(tmp_path):
    """A non-stale prior current_run with transient reasons must NOT leak
    those reasons into the new current_run."""
    seeded = {
        "version": "1",
        "current_run": {
            "started_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "head_sha": "priorrunsha",
            "partial": True,
            "partial_reasons": [
                "schema_invalid: source-collector: 'prs' is a required property",
                "source_collector_invalid: returned None",
            ],
        },
    }
    state_path = _init_host(tmp_path, seeded)

    r = _run_orchestrator(tmp_path)
    assert r.returncode == 0, (
        f"orchestrator should exit 0 on a clean dry-run; "
        f"rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}"
    )

    cr = _read_current_run(state_path)
    reasons = cr.get("partial_reasons", [])
    assert reasons == [], (
        f"prior-run transient reasons must not carry forward; got {reasons}"
    )


def test_fresh_run_after_failed_run_starts_with_empty_reasons(tmp_path):
    """Acceptance criterion #5: after a prior failed run, the new run's
    current_run starts with partial: false and partial_reasons: []."""
    seeded = {
        "version": "1",
        "current_run": {
            "started_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "head_sha": "priorrunsha",
            "partial": True,
            "partial_reasons": ["push_failed: simulated network error"],
        },
    }
    state_path = _init_host(tmp_path, seeded)

    r = _run_orchestrator(tmp_path)
    assert r.returncode == 0, r.stderr

    cr = _read_current_run(state_path)
    assert cr.get("partial") is False, (
        f"clean run after failed run should have partial=false; got {cr}"
    )
    assert cr.get("partial_reasons") == [], (
        f"clean run after failed run should have empty partial_reasons; got {cr.get('partial_reasons')!r}"
    )


def test_stale_clear_signal_still_emitted_against_fresh_reasons(tmp_path):
    """Acceptance criterion #6 + interaction with the existing stale-clear
    contract: a stale prior current_run must still emit
    'stale_current_run_cleared' — and that must be the ONLY reason
    present (no leakage of the stale run's prior reasons)."""
    stale_iso = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    seeded = {
        "version": "1",
        "current_run": {
            "started_at": stale_iso,
            "head_sha": "stalesha",
            "partial": True,
            "partial_reasons": ["push_failed: ancient", "lint_block: tier1: rule_x"],
        },
    }
    state_path = _init_host(tmp_path, seeded)

    r = _run_orchestrator(tmp_path)
    assert r.returncode == 0, r.stderr

    cr = _read_current_run(state_path)
    reasons = cr["partial_reasons"]
    assert "stale_current_run_cleared" in reasons, (
        f"stale-clear signal must still fire; got {reasons}"
    )
    leaked = [
        reason
        for reason in reasons
        if "push_failed" in reason or "lint_block" in reason
    ]
    assert leaked == [], (
        f"stale prior reasons must not leak into fresh current_run; got {reasons}"
    )


def test_stale_current_run_cleared_is_info_only(tmp_path):
    """Stale current_run is cleared as info-only: partial stays False, signal is recorded, prior reasons do not leak."""
    stale_iso = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    seeded = {
        "version": "1",
        "current_run": {
            "started_at": stale_iso,
            "head_sha": "stalesha",
            "partial": True,
            "partial_reasons": ["push_failed: simulated"],
        },
    }
    state_path = _init_host(tmp_path, seeded)

    r = _run_orchestrator(tmp_path)
    assert r.returncode == 0, r.stderr

    cr = _read_current_run(state_path)
    assert cr.get("partial") is False, (
        f"info-only stale_current_run_cleared must not flip partial=True; got {cr}"
    )
    assert "stale_current_run_cleared" in cr.get("partial_reasons", []), (
        f"staleness annotation must still be visible; got {cr}"
    )
    leaked = [
        reason for reason in cr.get("partial_reasons", []) if "push_failed" in reason
    ]
    assert leaked == [], (
        f"prior run's partial_reasons must NOT carry forward; leaked={leaked}"
    )
