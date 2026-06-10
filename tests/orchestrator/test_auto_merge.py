"""CCE-101: auto-merge gate tests.

`resolve_merge_settings` + `_maybe_auto_merge` — the runner-side
poll-and-merge that lands fully-green non-partial docs-agent PRs
without an operator. All auto-merge reasons are info_only=True;
every failure degrades to leaving the PR open (pre-CCE-101 behavior).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402
from gh_client import FakeGhClient, GhResult  # noqa: E402


def test_resolve_merge_settings_absent_block_defaults_to_auto():
    """CCE-101 contract: absent key = auto-merge ON."""
    s = orun.resolve_merge_settings({})
    assert s == {
        "policy": "auto",
        "checks_grace_seconds": 120,
        "checks_timeout_seconds": 900,
    }


def test_resolve_merge_settings_absent_policy_defaults_to_auto():
    s = orun.resolve_merge_settings({"merge": {"checks_grace_seconds": 5}})
    assert s["policy"] == "auto"
    assert s["checks_grace_seconds"] == 5
    assert s["checks_timeout_seconds"] == 900


def test_resolve_merge_settings_manual_respected():
    s = orun.resolve_merge_settings({"merge": {"policy": "manual"}})
    assert s["policy"] == "manual"


def test_resolve_merge_settings_non_dict_block_falls_back():
    s = orun.resolve_merge_settings({"merge": "auto"})
    assert s["policy"] == "auto"
    assert s["checks_grace_seconds"] == 120


# ---------------------------------------------------------------------------
# Task 6: _maybe_auto_merge — eligibility short-circuits
# ---------------------------------------------------------------------------


class FakeClock:
    """Injectable monotonic clock; sleep() advances it so poll loops
    terminate instantly in tests."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def _settings(**over):
    s = {"policy": "auto", "checks_grace_seconds": 120, "checks_timeout_seconds": 900}
    s.update(over)
    return s


def _bot_author():
    return {
        "name": "engineering-docs-agent[bot]",
        "login": "engineering-docs-agent-bot",
        "email": "engineering-docs-agent@users.noreply.github.com",
    }


def _run(
    gh,
    *,
    partial=False,
    fact_warnings=None,
    settings=None,
    build_workflow="docs-agent-pages.yml",
    deadline=None,
    clock=None,
):
    clock = clock or FakeClock()
    return orun._maybe_auto_merge(
        gh,
        pr_number=7,
        partial=partial,
        fact_warnings=fact_warnings or [],
        merge_settings=settings or _settings(),
        build_workflow=build_workflow,
        deadline=deadline,
        clock=clock,
        sleep=clock.sleep,
    )


def test_policy_manual_short_circuits_without_gh_calls():
    gh = FakeGhClient()
    outcome, reasons = _run(gh, settings=_settings(policy="manual"))
    assert outcome == {"merged": False, "reason": "policy_manual"}
    assert reasons == []
    assert gh.calls == []


def test_partial_run_skips_with_info_reason():
    gh = FakeGhClient()
    outcome, reasons = _run(gh, partial=True)
    assert outcome == {"merged": False, "reason": "partial_run"}
    assert reasons == [("auto_merge_skipped: partial_run", True)]
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_fact_warnings_demote_to_manual_review():
    """CCE-110 guard: under auto-merge nobody reads the PR, so a
    contradiction warning must withhold the merge (not the content)."""
    gh = FakeGhClient()
    outcome, reasons = _run(gh, fact_warnings=["page.md: contradicts source"])
    assert outcome["reason"] == "fact_check_warnings"
    assert reasons[0][0].startswith("auto_merge_skipped: fact_check_warnings")
    assert reasons[0][1] is True
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_human_edited_pr_is_never_merged():
    gh = FakeGhClient(
        pr_view_commits=GhResult(
            ok=True,
            value=[
                {"authors": [_bot_author()]},
                {"authors": [{"name": "Theo", "login": "theoju", "email": "t@x.com"}]},
            ],
        ),
    )
    outcome, reasons = _run(gh)
    assert outcome["reason"] == "human_edited"
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_commits_lookup_failure_skips_conservatively():
    gh = FakeGhClient(pr_view_commits=GhResult(ok=False, error="gh_failed: 500"))
    outcome, reasons = _run(gh)
    assert outcome["reason"] == "commits_lookup_failed"
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_exhausted_time_budget_skips_before_polling():
    gh = FakeGhClient(
        pr_view_commits=GhResult(ok=True, value=[{"authors": [_bot_author()]}])
    )
    clock = FakeClock(t=1000.0)
    # deadline already closer than the grace window
    outcome, reasons = _run(gh, deadline=1060.0, clock=clock)
    assert outcome["reason"] == "time_budget"
    assert not [c for c in gh.calls if c[0] == "pr_checks"]
