"""Integration: source-collector returns one out-of-window PR; orchestrator
drops it and records out_of_window_dropped (CCE-19).

Exercises dispatch_validated → _clip_prs_to_window end-to-end via the
dry-run fixture path with a patched git rev-list. The real orchestrator
call site at scripts/orchestrator_runner.py uses the same plumbing; this
test pins the contract for callers that combine the two.
"""

from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "cce19"


def _fake_git_rev_list(in_window: list[str]):
    def _run(argv, **kwargs):
        if "rev-list" in argv:
            return MagicMock(
                returncode=0,
                stdout="\n".join(in_window) + "\n",
                stderr="",
            )
        return MagicMock(returncode=0, stdout="", stderr="")

    return _run


def test_orchestrator_drops_out_of_window_pr(tmp_path: Path) -> None:
    """End-to-end: dispatch_validated loads the 3-PR fixture, then
    _clip_prs_to_window drops PR #9 (whose merge_sha ffffffff is not in
    the stubbed git rev-list output)."""
    reasons: list[str] = []
    result, dispatch_reasons = orun.dispatch_validated(
        "source-collector",
        {
            "last_sha": "000000",
            "head_sha": "ffffff",
            "repo": {"owner": "x", "name": "y"},
        },
        dry_run_dir=FIXTURE,
        cwd=tmp_path,
    )
    assert result is not None, (
        f"Fixture should load; dispatch reasons={dispatch_reasons}"
    )
    assert len(result["prs"]) == 3, "Sanity: fixture has 3 PRs before clipping"

    # Now apply the clip with patched git rev-list (mirrors orchestrator wiring).
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_fake_git_rev_list(["aaaa1111", "bbbb2222"]),
    ):
        result["prs"] = orun._clip_prs_to_window(
            result["prs"],
            last_sha="000000",
            head_sha="ffffff",
            repo_root=tmp_path,
            out_reasons=reasons,
        )

    kept_numbers = [p["number"] for p in result["prs"]]
    assert kept_numbers == [1, 2], f"PR #9 should have been dropped; got {kept_numbers}"
    assert any("out_of_window_dropped" in r and "9" in r for r in reasons), reasons
