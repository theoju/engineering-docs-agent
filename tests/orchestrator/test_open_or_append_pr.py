"""CCE-21: open_or_append_pr must distinguish three push failure modes:
- push_refs_failed: commit didn't reach remote (fatal)
- push_tracking_setup_failed: commit on remote but `-u` tracking failed (info-only, continue)
- push_failed_unknown: couldn't verify remote state (fatal, conservative default)

It must also always log push.stderr and push.stdout when push.returncode != 0
so 'see logs' in the partial reason is actually backed by logs.
"""

from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402


def _make_subprocess_stub(*, push_rc: int, push_stderr: str, lsremote_sha: str | None):
    """Return a fake subprocess.run.

    - push (push -u origin <branch>): returns push_rc + push_stderr
    - ls-remote (git ls-remote origin <branch>): returns "<sha>\trefs/heads/<branch>" if lsremote_sha set, empty if not
    - checkout / add / commit / anything else: rc=0
    - rev-parse HEAD: returns "localsha" (the SHA we want push to have landed)
    """

    def _run(argv, **kwargs):
        if "push" in argv:
            return MagicMock(returncode=push_rc, stdout="", stderr=push_stderr)
        if "ls-remote" in argv:
            if lsremote_sha is None:
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(
                returncode=0,
                stdout=f"{lsremote_sha}\trefs/heads/branchname\n",
                stderr="",
            )
        if "rev-parse" in argv:
            return MagicMock(returncode=0, stdout="localsha\n", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    return _run


def _make_gh_client_stub(pr_number: int | None = 99):
    gh = MagicMock()
    gh.pr_list_for_branch.return_value = MagicMock(ok=True, value=None)
    gh.pr_create.return_value = MagicMock(ok=True, value=pr_number)
    return gh


def test_push_succeeds_tracking_setup_fails_returns_info_only_reason(tmp_path: Path):
    """Push refs succeed but tracking setup fails: info-only, PR still created."""
    gh = _make_gh_client_stub(pr_number=42)
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_make_subprocess_stub(
            push_rc=1,
            push_stderr="warning: failed to set up tracking; refs already pushed",
            lsremote_sha="localsha",  # remote DOES have local HEAD
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
    assert pr_number == 42
    info_only_reasons = [r for r, info_only in reasons if info_only]
    assert any("push_tracking_setup_failed" in r for r in info_only_reasons), (
        f"expected info-only push_tracking_setup_failed; got {reasons}"
    )


def test_push_refs_failed_no_remote_state_returns_fatal_reason(tmp_path: Path):
    """Push exits non-zero AND the remote does not have the commit. Fatal."""
    gh = _make_gh_client_stub()
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_make_subprocess_stub(
            push_rc=1,
            push_stderr="error: failed to push some refs to 'origin'",
            lsremote_sha=None,  # remote does NOT have the commit
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
    assert pr_number is None
    # exactly one fatal reason that includes push_refs_failed
    fatal = [r for r, info_only in reasons if not info_only]
    assert any("push_refs_failed" in r for r in fatal), (
        f"expected push_refs_failed fatal reason; got {reasons}"
    )


def test_push_failed_stderr_included_in_reason(tmp_path: Path):
    """When push fails, the partial reason must include push.stderr so
    'see logs' is actually backed by data."""
    gh = _make_gh_client_stub()
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_make_subprocess_stub(
            push_rc=128,
            push_stderr="fatal: unable to access 'https://github.com/...': ssl error",
            lsremote_sha=None,
        ),
    ):
        _, reasons = orun.open_or_append_pr(
            tmp_path,
            gh,
            branch="docs-agent/test",
            now_iso="2026-05-21T22:00:00+00:00",
            partial=False,
            partial_reasons=[],
        )
    # Some fatal reason must contain the actual stderr substring
    fatal_msgs = [r for r, info_only in reasons if not info_only]
    assert any("ssl error" in r for r in fatal_msgs), (
        f"expected stderr substring in fatal reason; got {reasons}"
    )


def test_push_succeeds_with_returncode_zero_no_reasons(tmp_path: Path):
    """Happy path: push returns 0; no reasons added; PR created."""
    gh = _make_gh_client_stub(pr_number=7)
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_make_subprocess_stub(
            push_rc=0,
            push_stderr="",
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
    assert pr_number == 7
    assert reasons == []
