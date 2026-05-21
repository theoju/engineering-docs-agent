"""Orchestrator clips source-collector output to last_sha..head_sha (CCE-19).

CCE-19: source-collector's agent prompt doesn't reliably apply an upper
bound on `gh pr list`, so in 3/5 CCE-16 baseline runs it returned PRs
merged after head_sha. `_clip_prs_to_window` is the orchestrator-side
safety net: it runs `git rev-list last_sha..head_sha` and drops PRs
whose merge_sha is not in the resulting set.
"""

from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402


def _fake_git_rev_list(in_window: list[str]):
    """Build a subprocess.run stub that returns `in_window` SHAs for any
    `git rev-list last_sha..head_sha` invocation."""

    def _run(argv, **kwargs):
        if "rev-list" in argv:
            return MagicMock(
                returncode=0,
                stdout="\n".join(in_window) + ("\n" if in_window else ""),
                stderr="",
            )
        return MagicMock(returncode=0, stdout="", stderr="")

    return _run


def test_in_window_prs_kept() -> None:
    prs = [
        {"number": 1, "url": "u1", "merge_sha": "aaaa1111"},
        {"number": 2, "url": "u2", "merge_sha": "bbbb2222"},
    ]
    reasons: list[str] = []
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_fake_git_rev_list(["aaaa1111", "bbbb2222"]),
    ):
        kept = orun._clip_prs_to_window(
            prs,
            last_sha="000000",
            head_sha="ffffff",
            repo_root=Path("."),
            out_reasons=reasons,
        )
    assert [p["number"] for p in kept] == [1, 2]
    assert reasons == []


def test_out_of_window_pr_dropped_with_reason() -> None:
    prs = [
        {"number": 1, "url": "u1", "merge_sha": "aaaa1111"},  # in window
        {"number": 9, "url": "u9", "merge_sha": "ffffffff"},  # past head_sha
    ]
    reasons: list[str] = []
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_fake_git_rev_list(["aaaa1111"]),
    ):
        kept = orun._clip_prs_to_window(
            prs,
            last_sha="000000",
            head_sha="ffffff",
            repo_root=Path("."),
            out_reasons=reasons,
        )
    assert [p["number"] for p in kept] == [1]
    assert any("out_of_window_dropped" in r for r in reasons), reasons
    assert any("9" in r for r in reasons), reasons


def test_pr_without_merge_sha_kept_with_warning() -> None:
    """If a PR doesn't carry merge_sha (older Mode-A fixtures), keep it but
    flag the gap — we can't clip without the SHA."""
    prs = [
        {"number": 1, "url": "u1"},  # no merge_sha
    ]
    reasons: list[str] = []
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_fake_git_rev_list([]),
    ):
        kept = orun._clip_prs_to_window(
            prs,
            last_sha="000000",
            head_sha="ffffff",
            repo_root=Path("."),
            out_reasons=reasons,
        )
    assert [p["number"] for p in kept] == [1]
    assert any("merge_sha_missing" in r for r in reasons), reasons


def test_empty_last_sha_skips_filtering() -> None:
    """When last_sha is empty (first run), the lower bound doesn't exist;
    git rev-list is not called; all PRs pass through."""
    prs = [
        {"number": 1, "url": "u1", "merge_sha": "aaaa1111"},
        {"number": 2, "url": "u2", "merge_sha": "ffffffff"},
    ]
    reasons: list[str] = []
    run_stub = MagicMock()
    with patch.object(orun.subprocess, "run", run_stub):
        kept = orun._clip_prs_to_window(
            prs,
            last_sha="",
            head_sha="ffffff",
            repo_root=Path("."),
            out_reasons=reasons,
        )
    assert [p["number"] for p in kept] == [1, 2]
    assert run_stub.call_count == 0, (
        "git rev-list should not run when last_sha is empty"
    )
