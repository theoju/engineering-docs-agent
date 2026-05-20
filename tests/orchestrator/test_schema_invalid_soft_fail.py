# tests/orchestrator/test_schema_invalid_soft_fail.py
"""End-to-end: when source-collector returns a schema-invalid response,
the pipeline records a specific schema_invalid reason in partial_reasons,
falls through to the empty-prs path, exits 0, and does NOT also append the
generic source_collector_invalid: returned None reason."""

from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

ORCH_RUNNER = Path(__file__).parent.parent.parent / "scripts" / "orchestrator_runner.py"
FAKES_SCHEMA_INVALID = Path(__file__).parent / "fakes_schema_invalid"

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


def _init_host(tmp_path: Path) -> Path:
    (tmp_path / ".engineering-docs-agent").mkdir()
    (tmp_path / ".engineering-docs-agent" / "config.yml").write_text(CONFIG_YAML)
    state_path = tmp_path / ".engineering-docs-agent" / "state.json"
    state_path.write_text(json.dumps({"version": "1"}))
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


def test_schema_invalid_source_collector_yields_specific_reason(tmp_path):
    """Bad source-collector shape → schema_invalid reason, no generic redundancy."""
    state_path = _init_host(tmp_path)

    env = {**os.environ, "GITHUB_REPOSITORY": "owner/repo"}
    r = subprocess.run(
        [
            sys.executable,
            str(ORCH_RUNNER),
            "--repo-root",
            str(tmp_path),
            "--no-pr",
            "--dry-run-subagents",
            str(FAKES_SCHEMA_INVALID),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, (
        f"pipeline should exit 0 on schema-invalid soft-fail; "
        f"got rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}"
    )

    state = json.loads(state_path.read_text())
    reasons = state["current_run"]["partial_reasons"]

    schema_reasons = [
        reason
        for reason in reasons
        if reason.startswith("schema_invalid: source-collector: ")
    ]
    assert len(schema_reasons) == 1, (
        f"expected exactly one schema_invalid: source-collector: reason; got reasons={reasons}"
    )

    generic = [
        reason
        for reason in reasons
        if reason == "source_collector_invalid: returned None"
    ]
    assert generic == [], (
        f"specific schema reason should suppress the generic returned-None reason; got {reasons}"
    )

    assert state["current_run"]["partial"] is True
    assert state["current_run"]["pr_number"] is None
