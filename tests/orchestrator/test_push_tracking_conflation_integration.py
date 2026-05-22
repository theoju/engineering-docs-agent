"""Integration: orchestrator continues to PR creation when push refs land
but `git push -u` upstream-tracking-setup fails.

Patches subprocess so push exits non-zero while git ls-remote returns
local HEAD. Asserts pr_number is set, current_run.partial stays False,
and push_tracking_setup_failed appears as an info-only partial reason.
"""

from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402


def _stub_subprocess(*, push_rc, push_stderr, lsremote_sha):
    def _run(argv, **kwargs):
        if "push" in argv:
            return MagicMock(returncode=push_rc, stdout="", stderr=push_stderr)
        if "ls-remote" in argv:
            return MagicMock(
                returncode=0,
                stdout=f"{lsremote_sha}\trefs/heads/x\n" if lsremote_sha else "",
                stderr="",
            )
        if "rev-parse" in argv:
            return MagicMock(returncode=0, stdout="localsha\n", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    return _run


def test_orchestrator_continues_when_push_refs_succeed_but_tracking_fails(
    tmp_path: Path,
):
    """Push -u returns non-zero but refs reached remote: PR opens, run stays clean."""
    gh = MagicMock()
    gh.pr_list_for_branch.return_value = MagicMock(ok=True, value=None)
    gh.pr_create.return_value = MagicMock(ok=True, value=123)

    state = {
        "current_run": {
            "started_at": "x",
            "head_sha": "y",
            "partial": False,
            "partial_reasons": [],
        }
    }

    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_stub_subprocess(
            push_rc=1,
            push_stderr="warning: ref pushed but tracking setup failed",
            lsremote_sha="localsha",
        ),
    ):
        pr_number, reasons = orun.open_or_append_pr(
            tmp_path,
            gh,
            branch="docs-agent/test",
            now_iso="2026-05-21T22:00:00+00:00",
            partial=False,
            partial_reasons=[],
        )
        for reason, info_only in reasons:
            orun.add_partial(state, reason, info_only=info_only)

    assert pr_number == 123, "PR should be opened despite push -u returncode != 0"
    assert state["current_run"]["partial"] is False, (
        f"info-only reason must not flip partial; state={state}"
    )
    assert any(
        "push_tracking_setup_failed" in r
        for r in state["current_run"]["partial_reasons"]
    ), state["current_run"]["partial_reasons"]
