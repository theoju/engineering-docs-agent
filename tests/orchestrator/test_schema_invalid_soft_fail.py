# tests/orchestrator/test_schema_invalid_soft_fail.py
"""End-to-end: when source-collector returns a schema-invalid response,
the pipeline records a specific schema_invalid reason in partial_reasons,
falls through to the empty-prs path, exits 1 (schema_invalid is a blind
blocking reason — CCE-144), and does NOT also append the generic
source_collector_invalid: returned None reason."""

from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

ORCH_RUNNER = Path(__file__).parent.parent.parent / "scripts" / "orchestrator_runner.py"
FAKES_SCHEMA_INVALID = Path(__file__).parent / "fakes_schema_invalid"


def test_schema_invalid_source_collector_yields_specific_reason(tmp_path, init_host):
    """Bad source-collector shape → schema_invalid reason, no generic redundancy."""
    state_path = init_host({"version": "1"})

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
    assert r.returncode == 1, (  # schema_invalid is blind (blocking reason)
        f"pipeline should exit 1 on schema-invalid soft-fail; "
        f"got rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}"
    )

    cr_path = state_path.parent / "current_run.json"
    cr = json.loads(cr_path.read_text())["current_run"]
    reasons = cr["partial_reasons"]

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

    assert cr["partial"] is True
    assert cr["pr_number"] is None
