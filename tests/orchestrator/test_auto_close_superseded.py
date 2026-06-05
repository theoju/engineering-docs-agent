"""CCE-89 D2: auto-close-stale policy tests.

Pure-function tests for `_auto_close_superseded_docs_agent_prs` — the
composer that closes prior open docs-agent/* PRs when a new nightly
opens, except those edited by a human.

Policy (per CCE-89 D2):
  - Every prior open docs-agent/* PR is superseded by definition because
    each nightly opens a fresh `docs-agent/YYYY-MM-DDTHH` branch, not an
    append-commit to an existing one.
  - Skip auto-close if any commit on the prior PR has an author that is
    not the bot (login / name / email match).
  - Close with the exact comment text the spec requires.
  - Each close (success / skip / failure) records a reason for caller's
    add_partial loop so the action shows up in state.json and CI logs.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402
from gh_client import FakeGhClient, GhResult  # noqa: E402


def _bot_author():
    return {
        "name": "engineering-docs-agent[bot]",
        "login": "engineering-docs-agent-bot",
        "email": "engineering-docs-agent@users.noreply.github.com",
    }


def _commits_with(authors_per_commit):
    """[[author_dict, ...], [author_dict, ...]] → gh-shape commits payload."""
    return [{"authors": authors} for authors in authors_per_commit]


def test_auto_close_no_prior_prs_returns_empty_reasons():
    gh = FakeGhClient(
        pr_list_docs_agent_open=GhResult(ok=True, value=[]),
    )
    reasons = orun._auto_close_superseded_docs_agent_prs(
        gh, new_pr_number=42, new_pr_branch="docs-agent/2026-06-04T18"
    )
    assert reasons == []
    # Confirm we asked but didn't try to close anything.
    listed = [c for c in gh.calls if c[0] == "pr_list_docs_agent_open"]
    closed = [c for c in gh.calls if c[0] == "pr_close"]
    assert len(listed) == 1
    assert closed == []


def test_auto_close_excludes_the_new_pr_itself():
    """The freshly-opened PR appears in the gh pr list result; the closer
    must not close itself."""
    gh = FakeGhClient(
        pr_list_docs_agent_open=GhResult(
            ok=True,
            value=[
                {"number": 42, "headRefName": "docs-agent/2026-06-04T18"},
            ],
        ),
    )
    reasons = orun._auto_close_superseded_docs_agent_prs(
        gh, new_pr_number=42, new_pr_branch="docs-agent/2026-06-04T18"
    )
    assert reasons == []
    closed = [c for c in gh.calls if c[0] == "pr_close"]
    assert closed == [], "must not auto-close the freshly-opened PR"


def test_auto_close_succeeds_when_only_bot_commits():
    """All commits authored by the bot → close prior PR with the spec comment."""
    gh = FakeGhClient(
        pr_list_docs_agent_open=GhResult(
            ok=True,
            value=[
                {"number": 30, "headRefName": "docs-agent/2026-06-03T07"},
                {"number": 42, "headRefName": "docs-agent/2026-06-04T18"},
            ],
        ),
        pr_view_commits=GhResult(
            ok=True,
            value=_commits_with([[_bot_author()], [_bot_author()]]),
        ),
        pr_close=GhResult(ok=True, value=30),
    )
    reasons = orun._auto_close_superseded_docs_agent_prs(
        gh, new_pr_number=42, new_pr_branch="docs-agent/2026-06-04T18"
    )
    # Reason recorded for the close.
    assert any("auto_close_succeeded:30" in r for r, _ in reasons)
    # The close call was made with the exact spec comment.
    close_calls = [c for c in gh.calls if c[0] == "pr_close"]
    assert len(close_calls) == 1
    _, (prior_num, comment) = close_calls[0]
    assert prior_num == 30
    assert comment == (
        "Auto-closing: superseded by #42 (docs-agent freshest-only policy)"
    )


def test_auto_close_skips_when_any_commit_is_human():
    """One commit has a non-bot author → leave the PR open for human review."""
    human = {
        "name": "Theo Jungeblut",
        "login": "theoju",
        "email": "theo@example.com",
    }
    gh = FakeGhClient(
        pr_list_docs_agent_open=GhResult(
            ok=True,
            value=[{"number": 30, "headRefName": "docs-agent/2026-06-03T07"}],
        ),
        pr_view_commits=GhResult(
            ok=True,
            value=_commits_with([[_bot_author()], [human]]),  # bot then human
        ),
    )
    reasons = orun._auto_close_superseded_docs_agent_prs(
        gh, new_pr_number=42, new_pr_branch="docs-agent/2026-06-04T18"
    )
    # Skip reason recorded.
    assert any("auto_close_skipped:30:human_edited" in r for r, _ in reasons)
    # No close call.
    closed = [c for c in gh.calls if c[0] == "pr_close"]
    assert closed == [], "human-edited PR must not be auto-closed"


def test_auto_close_skips_when_commits_lookup_fails():
    """gh pr view commits errors → fail-safe SKIP (don't close on partial signal)."""
    gh = FakeGhClient(
        pr_list_docs_agent_open=GhResult(
            ok=True,
            value=[{"number": 30, "headRefName": "docs-agent/2026-06-03T07"}],
        ),
        pr_view_commits=GhResult(ok=False, error="gh_failed: rate limit"),
    )
    reasons = orun._auto_close_superseded_docs_agent_prs(
        gh, new_pr_number=42, new_pr_branch="docs-agent/2026-06-04T18"
    )
    assert any("auto_close_skipped:30:commits_lookup_failed" in r for r, _ in reasons)
    closed = [c for c in gh.calls if c[0] == "pr_close"]
    assert closed == [], "must not auto-close when commit author info is unknown"


def test_auto_close_skips_when_list_fails_and_records_info_reason():
    """Top-level list call fails → record info reason, no close attempts."""
    gh = FakeGhClient(
        pr_list_docs_agent_open=GhResult(ok=False, error="gh_failed: 403"),
    )
    reasons = orun._auto_close_superseded_docs_agent_prs(
        gh, new_pr_number=42, new_pr_branch="docs-agent/2026-06-04T18"
    )
    assert reasons, "list failure must surface at least one reason"
    reason_str, info_only = reasons[0]
    assert "auto_close_list_failed" in reason_str
    assert info_only is True, (
        "list-failure must not flip the run to partial — D2 is best-effort"
    )
    closed = [c for c in gh.calls if c[0] == "pr_close"]
    assert closed == []


def test_auto_close_records_failure_when_close_call_errors():
    """Close attempt fails → record info reason, continue to next prior PR."""
    gh = FakeGhClient(
        pr_list_docs_agent_open=GhResult(
            ok=True,
            value=[
                {"number": 30, "headRefName": "docs-agent/2026-06-03T07"},
                {"number": 31, "headRefName": "docs-agent/2026-06-02T07"},
            ],
        ),
        pr_view_commits=GhResult(
            ok=True,
            value=_commits_with([[_bot_author()]]),
        ),
        pr_close=GhResult(ok=False, error="gh_failed: not found"),
    )
    reasons = orun._auto_close_superseded_docs_agent_prs(
        gh, new_pr_number=42, new_pr_branch="docs-agent/2026-06-04T18"
    )
    fail_reasons = [r for r, _ in reasons if "auto_close_failed:30" in r]
    assert len(fail_reasons) == 1
    # Both prior PRs were attempted — failure on one didn't short-circuit.
    close_calls = [c for c in gh.calls if c[0] == "pr_close"]
    assert len(close_calls) == 2


def test_auto_close_reasons_are_all_info_only_so_run_stays_non_partial():
    """D2 is cosmetic hygiene; its failures must NOT mark the docs-agent run
    partial. Caller's add_partial loop expects info_only=True for all D2
    reasons so the partial flag stays driven by authoring-pipeline errors."""
    gh = FakeGhClient(
        pr_list_docs_agent_open=GhResult(
            ok=True,
            value=[{"number": 30, "headRefName": "docs-agent/2026-06-03T07"}],
        ),
        pr_view_commits=GhResult(
            ok=True,
            value=_commits_with([[_bot_author()]]),
        ),
        pr_close=GhResult(ok=True, value=30),
    )
    reasons = orun._auto_close_superseded_docs_agent_prs(
        gh, new_pr_number=42, new_pr_branch="docs-agent/2026-06-04T18"
    )
    assert reasons, "expected at least one reason recorded"
    assert all(info_only for _, info_only in reasons), (
        "every D2 reason must be info_only — auto-close hygiene cannot "
        "flip the run to partial"
    )
