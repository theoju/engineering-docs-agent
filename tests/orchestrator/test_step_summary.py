"""CCE-48: surface partial_reasons in $GITHUB_STEP_SUMMARY.

The runner's _write_step_summary helper:
- no-ops when $GITHUB_STEP_SUMMARY is unset (local runs, unit tests)
- appends a bulleted digest when env var is set + partial_reasons non-empty
- swallows OSError when the env-var-pointed path is unwritable
- runs from a try/finally in run() so hard-fail paths still flush
"""

from __future__ import annotations
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402


def test_helper_noop_when_env_var_unset(tmp_path: Path, monkeypatch):
    """When GITHUB_STEP_SUMMARY is unset, the helper returns silently
    with no side effects — local runs and unit tests behave as today."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    state = {
        "version": "1",
        "current_run": {
            "partial": True,
            "partial_reasons": ["source_collector_invalid: returned None"],
        },
    }
    # Should not raise; should not touch any file.
    orun._write_step_summary(state, tmp_path)
    # Nothing on disk (assertion implicit — helper has no path to write to).
    assert list(tmp_path.iterdir()) == []
