"""CCE-21: open_or_append_pr must distinguish three push failure modes:
- push_refs_failed: commit didn't reach remote (fatal)
- push_tracking_setup_failed: commit on remote but `-u` tracking failed (info-only, continue)
- push_failed_unknown: couldn't verify remote state (fatal, conservative default)

It must also always log push.stderr and push.stdout when push.returncode != 0
so 'see logs' in the partial reason is actually backed by logs.
"""

from __future__ import annotations
import json
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


# CCE-42: append-commit on same-hour reruns. The orchestrator must fetch
# the remote branch before checkout so the local branch tracks the
# existing remote tip; otherwise `checkout -B` resets to HEAD (main) and
# the subsequent push is rejected non-fast-forward.


def _capturing_subprocess_stub(
    *,
    fetch_rc: int,
    calls_out: list[list[str]],
    push_rc: int = 0,
    push_stderr: str = "",
):
    """Record argv of every subprocess.run call into calls_out.

    fetch (origin <branch>) returns fetch_rc; everything else rc=0 by default.
    """

    def _run(argv, **kwargs):
        calls_out.append(list(argv))
        if "fetch" in argv:
            return MagicMock(returncode=fetch_rc, stdout="", stderr="")
        if "push" in argv:
            return MagicMock(returncode=push_rc, stdout="", stderr=push_stderr)
        if "ls-remote" in argv:
            return MagicMock(returncode=0, stdout="localsha\trefs/heads/x\n", stderr="")
        if "rev-parse" in argv:
            return MagicMock(returncode=0, stdout="localsha\n", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    return _run


def test_fetches_remote_branch_before_checkout_when_remote_exists(tmp_path: Path):
    """When remote branch exists (fetch rc=0), code must:
    1. Call `git fetch origin <branch>` BEFORE checkout
    2. Call `git checkout -B <branch> origin/<branch>` (start-point is remote tip)
    so the subsequent push is fast-forward, not non-fast-forward.
    Repros CCE-42 same-hour rerun branch collision.
    """
    gh = _make_gh_client_stub(pr_number=42)
    calls: list[list[str]] = []
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_capturing_subprocess_stub(fetch_rc=0, calls_out=calls),
    ):
        orun.open_or_append_pr(
            tmp_path,
            gh,
            branch="docs-agent/2026-05-28T22",
            now_iso="2026-05-28T22:47:45+00:00",
            partial=False,
            partial_reasons=[],
        )

    fetch_idx = next(
        (
            i
            for i, argv in enumerate(calls)
            if "fetch" in argv and "docs-agent/2026-05-28T22" in argv
        ),
        None,
    )
    checkout_idx = next(
        (i for i, argv in enumerate(calls) if "checkout" in argv and "-B" in argv),
        None,
    )
    assert fetch_idx is not None, (
        f"expected `git fetch origin <branch>` to be called; argv calls: {calls}"
    )
    assert checkout_idx is not None, f"expected a checkout call; got: {calls}"
    assert fetch_idx < checkout_idx, (
        f"fetch (idx={fetch_idx}) must come before checkout (idx={checkout_idx}); "
        f"calls: {calls}"
    )
    checkout_argv = calls[checkout_idx]
    assert "origin/docs-agent/2026-05-28T22" in checkout_argv, (
        f"expected `checkout -B <branch> origin/<branch>` when remote exists; "
        f"got argv: {checkout_argv}"
    )


def test_falls_back_to_head_checkout_when_remote_branch_absent(tmp_path: Path):
    """When fetch fails (rc!=0; remote branch doesn't exist), code falls back
    to `git checkout -B <branch>` off HEAD — first-of-hour behavior."""
    gh = _make_gh_client_stub(pr_number=43)
    calls: list[list[str]] = []
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_capturing_subprocess_stub(fetch_rc=128, calls_out=calls),
    ):
        orun.open_or_append_pr(
            tmp_path,
            gh,
            branch="docs-agent/2026-05-28T23",
            now_iso="2026-05-28T23:01:00+00:00",
            partial=False,
            partial_reasons=[],
        )

    checkout_argv = next(argv for argv in calls if "checkout" in argv and "-B" in argv)
    assert "origin/docs-agent/2026-05-28T23" not in checkout_argv, (
        f"expected fallback `checkout -B <branch>` off HEAD when fetch fails; "
        f"got argv with remote ref: {checkout_argv}"
    )


# CCE-43: skip same-hour reruns that already processed this window. The
# orchestrator must detect that origin/<branch> already advanced its
# committed state.json to our HEAD and exit 0 before dispatching
# subagents, avoiding the working-tree collision documented in CCE-42's
# smoke-test 2/2 failure (run 26608024227).


def _skip_predicate_subprocess_stub(
    *,
    fetch_rc: int,
    show_rc: int = 0,
    remote_head_sha: str | None = None,
    show_stdout_override: str | None = None,
):
    """Stub git fetch + git show for _remote_already_processed_window tests.

    - fetch (`git fetch origin <branch>`): returns fetch_rc
    - show (`git show origin/<branch>:.engineering-docs-agent/state.json`):
      returns show_rc; if remote_head_sha is provided, stdout is a valid
      state.json with that head_sha; show_stdout_override forces raw stdout.
    """
    if show_stdout_override is not None:
        show_stdout = show_stdout_override
    elif remote_head_sha is not None:
        show_stdout = json.dumps(
            {
                "version": "1",
                "last_successful_run": {
                    "head_sha": remote_head_sha,
                    "completed_at": "2026-05-28T23:00:00+00:00",
                },
            }
        )
    else:
        show_stdout = ""

    def _run(argv, **kwargs):
        if "fetch" in argv:
            return MagicMock(returncode=fetch_rc, stdout="", stderr="")
        if "show" in argv:
            return MagicMock(returncode=show_rc, stdout=show_stdout, stderr="")
        raise AssertionError(f"unexpected argv: {argv!r}")

    return _run


def test_helper_returns_true_when_remote_head_sha_matches_ours(tmp_path: Path):
    """When origin/<branch>'s state.json has last_successful_run.head_sha
    equal to our_head_sha, the predicate returns True (this window is
    already processed; the runner should skip)."""
    our_head_sha = "abc123def456abc123def456abc123def456abcd"
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_skip_predicate_subprocess_stub(
            fetch_rc=0,
            show_rc=0,
            remote_head_sha=our_head_sha,
        ),
    ):
        result = orun._remote_already_processed_window(
            tmp_path, "docs-agent/2026-05-28T23", our_head_sha
        )
    assert result is True, (
        f"expected helper to return True when remote head_sha matches; got {result}"
    )


def test_helper_returns_false_when_remote_head_sha_differs(tmp_path: Path):
    """When origin/<branch>'s state.json has a DIFFERENT head_sha (S3
    retry-after-partial or S4 window-grew scenario), the predicate returns
    False so the runner proceeds and hits the existing checkout_failed
    handling if the collision occurs."""
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_skip_predicate_subprocess_stub(
            fetch_rc=0,
            show_rc=0,
            remote_head_sha="oldsha000000000000000000000000000000000",
        ),
    ):
        result = orun._remote_already_processed_window(
            tmp_path,
            "docs-agent/2026-05-28T23",
            "newsha111111111111111111111111111111111",
        )
    assert result is False, f"expected False on differing remote head_sha; got {result}"


def test_helper_returns_false_when_remote_branch_absent(tmp_path: Path):
    """When `git fetch origin <branch>` fails (rc != 0; branch doesn't
    exist remotely OR network failure), the predicate returns False so
    the runner proceeds normally — first-run-of-hour case."""
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_skip_predicate_subprocess_stub(fetch_rc=128),
    ):
        result = orun._remote_already_processed_window(
            tmp_path,
            "docs-agent/2026-05-28T23",
            "somehead00000000000000000000000000000000",
        )
    assert result is False, f"expected False when fetch fails; got {result}"


def test_helper_returns_false_when_remote_state_json_missing(tmp_path: Path):
    """When fetch succeeds but `git show origin/<branch>:.engineering-docs-agent/state.json`
    fails (rc != 0; e.g. a pre-CCE-40 docs-agent branch that doesn't track
    state.json, or any branch lacking the file), the predicate returns False
    so the runner proceeds. Covers spec §Failure modes row "Remote branch
    exists, no state.json"."""
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_skip_predicate_subprocess_stub(
            fetch_rc=0,
            show_rc=128,
        ),
    ):
        result = orun._remote_already_processed_window(
            tmp_path,
            "docs-agent/2026-05-28T23",
            "somehead00000000000000000000000000000000",
        )
    assert result is False, (
        f"expected False when state.json missing on remote; got {result}"
    )


def test_helper_returns_false_when_remote_state_json_corrupted(tmp_path: Path):
    """When origin/<branch>'s state.json exists but is not valid JSON
    (corrupted file, schema drift, partial write), the predicate returns
    False so the runner proceeds. Never false-skip on parse errors."""
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_skip_predicate_subprocess_stub(
            fetch_rc=0,
            show_rc=0,
            show_stdout_override="{not valid json at all",
        ),
    ):
        result = orun._remote_already_processed_window(
            tmp_path,
            "docs-agent/2026-05-28T23",
            "somehead00000000000000000000000000000000",
        )
    assert result is False, f"expected False on corrupted JSON; got {result}"


# CCE-48: PR body switches from "; ".join() to a bulleted list using
# the shared _format_partial_digest formatter so the step summary and
# PR body stay format-aligned.


def test_partial_pr_body_uses_bulleted_format(tmp_path: Path):
    """Partial-run PR body is a bulleted list, not '; '-joined."""
    gh = _make_gh_client_stub(pr_number=42)
    captured_body = {}

    def capture_create(branch, commit_msg, body):
        captured_body["body"] = body
        return MagicMock(ok=True, value=42)

    gh.pr_create.side_effect = capture_create

    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_make_subprocess_stub(
            push_rc=0,
            push_stderr="",
            lsremote_sha="localsha",
        ),
    ):
        orun.open_or_append_pr(
            tmp_path,
            gh,
            branch="docs-agent/test",
            now_iso="2026-05-28T22:00:00+00:00",
            partial=True,
            partial_reasons=["reason_one", "reason_two"],
        )

    body = captured_body["body"]
    # Heading must be present.
    assert "WARNING — Partial run" in body
    # Each reason is a bullet, not joined by '; '.
    assert "- reason_one" in body
    assert "- reason_two" in body
    # Confirm the old "; "-join shape is GONE.
    assert "reason_one; reason_two" not in body


def test_clean_pr_body_unchanged(tmp_path: Path):
    """Clean-run PR body remains exactly 'docs-agent run'."""
    gh = _make_gh_client_stub(pr_number=42)
    captured_body = {}

    def capture_create(branch, commit_msg, body):
        captured_body["body"] = body
        return MagicMock(ok=True, value=42)

    gh.pr_create.side_effect = capture_create

    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_make_subprocess_stub(
            push_rc=0,
            push_stderr="",
            lsremote_sha="localsha",
        ),
    ):
        orun.open_or_append_pr(
            tmp_path,
            gh,
            branch="docs-agent/test",
            now_iso="2026-05-28T22:00:00+00:00",
            partial=False,
            partial_reasons=[],
        )

    assert captured_body["body"] == "docs-agent run"
