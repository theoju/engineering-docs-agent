"""CCE-101: auto-merge gate tests.

`resolve_merge_settings` + `_maybe_auto_merge` — the runner-side
poll-and-merge that lands fully-green non-partial docs-agent PRs
without an operator. All auto-merge reasons are info_only=True;
every failure degrades to leaving the PR open (pre-CCE-101 behavior).
"""

from __future__ import annotations

import json
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
    ci_provider=None,
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
        ci_provider=ci_provider,
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


# ---------------------------------------------------------------------------
# Task 7: _maybe_auto_merge — check poll, merge, pages dispatch
# ---------------------------------------------------------------------------


def _eligible_gh(**kw):
    kw.setdefault(
        "pr_view_commits", GhResult(ok=True, value=[{"authors": [_bot_author()]}])
    )
    return FakeGhClient(**kw)


def _green(name="ci"):
    return {"name": name, "state": "SUCCESS", "bucket": "pass"}


def _pending(name="ci"):
    return {"name": name, "state": "PENDING", "bucket": "pending"}


def _red(name="ci"):
    return {"name": name, "state": "FAILURE", "bucket": "fail"}


def test_zero_checks_merges_after_grace_window():
    """No-App-token host: no checks ever register; in-run validation is
    the gate. Merge fires once the grace window elapses."""
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[]))
    clock = FakeClock()
    outcome, reasons = _run(gh, clock=clock)
    assert outcome == {"merged": True, "reason": None}
    assert ("pr_merge", (7,)) in gh.calls
    assert clock.t >= 120  # waited out the grace window
    assert ("auto_merge_succeeded: pr=7", True) in reasons


def test_checks_green_merges_without_waiting_full_grace():
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green()]))
    clock = FakeClock()
    outcome, _ = _run(gh, clock=clock)
    assert outcome["merged"] is True
    assert clock.t < 120  # settled checks short-circuit the grace wait


def test_pending_then_green_polls_until_settled():
    gh = _eligible_gh(
        pr_checks=[
            GhResult(ok=True, value=[_pending()]),
            GhResult(ok=True, value=[_pending()]),
            GhResult(ok=True, value=[_green()]),
        ]
    )
    outcome, _ = _run(gh)
    assert outcome["merged"] is True
    assert [c for c in gh.calls if c[0] == "pr_checks"]


def test_any_red_check_skips_immediately():
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green("a"), _red("b")]))
    outcome, reasons = _run(gh)
    assert outcome["reason"] == "checks_failed"
    assert "b" in reasons[0][0]
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_checks_never_settle_times_out():
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_pending()]))
    outcome, reasons = _run(gh, settings=_settings(checks_timeout_seconds=60))
    assert outcome["reason"] == "checks_timeout"
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_checks_query_failure_skips_conservatively():
    gh = _eligible_gh(pr_checks=GhResult(ok=False, error="gh_failed: 500"))
    outcome, reasons = _run(gh)
    assert outcome["reason"] == "checks_query_failed"
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_merge_failure_leaves_pr_open_with_info_reason():
    gh = _eligible_gh(
        pr_checks=GhResult(ok=True, value=[_green()]),
        pr_merge=GhResult(ok=False, error="gh_pr_merge_failed: protected"),
    )
    outcome, reasons = _run(gh)
    assert outcome == {"merged": False, "reason": "merge_failed"}
    assert reasons == [("auto_merge_failed: gh_pr_merge_failed: protected", True)]


def test_successful_merge_dispatches_pages_workflow():
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green()]))
    outcome, reasons = _run(gh, build_workflow="docs-agent-pages.yml")
    assert outcome["merged"] is True
    assert ("workflow_run", ("docs-agent-pages.yml",)) in gh.calls
    assert ("pages_dispatch_succeeded: docs-agent-pages.yml", True) in reasons


def test_no_build_workflow_skips_dispatch():
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green()]))
    outcome, _ = _run(gh, build_workflow=None)
    assert outcome["merged"] is True
    assert not [c for c in gh.calls if c[0] == "workflow_run"]


def test_circleci_provider_skips_dispatch_with_info_reason():
    """CCE-123: a circleci host merges but does NOT fire a GH Actions dispatch;
    it records one info_only pages_dispatch_skipped reason instead."""
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green()]))
    outcome, reasons = _run(gh, ci_provider="circleci")
    assert outcome["merged"] is True
    assert not [c for c in gh.calls if c[0] == "workflow_run"]
    assert (
        "pages_dispatch_skipped: circleci_trigger_modeled_but_unvalidated",
        True,
    ) in reasons


def test_github_provider_still_dispatches():
    """CCE-123 backward-compat: explicit ci_provider=github behaves identically
    to the pre-CCE-123 unconditional dispatch."""
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green()]))
    outcome, reasons = _run(gh, ci_provider="github")
    assert ("workflow_run", ("docs-agent-pages.yml",)) in gh.calls
    assert ("pages_dispatch_succeeded: docs-agent-pages.yml", True) in reasons


def test_dispatch_failure_is_info_only_after_merge():
    gh = _eligible_gh(
        pr_checks=GhResult(ok=True, value=[_green()]),
        workflow_run=GhResult(ok=False, error="gh_workflow_run_failed: 404"),
    )
    outcome, reasons = _run(gh)
    assert outcome["merged"] is True  # merge succeeded; dispatch is best-effort
    assert ("pages_dispatch_failed: gh_workflow_run_failed: 404", True) in reasons


def test_all_reasons_are_info_only():
    """No auto-merge outcome may ever flip the run to partial."""
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_red()]))
    _, reasons = _run(gh)
    assert all(info for _, info in reasons)


def test_skipping_bucket_counts_as_settled():
    """Path-filtered/conditional jobs report bucket=skipping; they must
    count as settled-non-blocking, not poll until timeout."""
    gh = _eligible_gh(
        pr_checks=GhResult(
            ok=True,
            value=[
                _green(),
                {"name": "cond", "state": "SKIPPED", "bucket": "skipping"},
            ],
        )
    )
    clock = FakeClock()
    outcome, _ = _run(gh, clock=clock)
    assert outcome["merged"] is True
    assert clock.t < 120  # settled immediately, no grace wait


# ---------------------------------------------------------------------------
# Task 8: run_pipeline wiring — auto-merge gate + digest merge_outcome
# ---------------------------------------------------------------------------

_FAKES = Path(__file__).parent / "fakes"


def test_run_pipeline_wires_auto_merge_and_digest(tmp_path, monkeypatch, init_host):
    """End-to-end wiring: a green non-partial dry-run pipeline merges its
    PR, records auto_merge_succeeded, and partial stays false (info-only).
    Asserts against current_run.json and the FakeGhClient call log."""
    init_host({"version": "1", "dismissed_gap_flags": {}, "cursors": {}})

    # Zero grace window: the wired _maybe_auto_merge uses the REAL
    # time.sleep (bound as a default arg — monkeypatching time.sleep
    # after import does NOT reach it). With grace 0 the zero-checks
    # path breaks out of the poll loop on the first iteration, so the
    # test never sleeps.
    config_path = tmp_path / ".engineering-docs-agent" / "config.yml"
    config_path.write_text(
        config_path.read_text()
        + "\nmerge:\n  policy: auto\n  checks_grace_seconds: 0\n"
        + "  checks_timeout_seconds: 0\n"
    )

    fake = None

    def _fake_factory(repo_root):
        nonlocal fake
        fake = FakeGhClient(
            pr_create=GhResult(ok=True, value=11),
            pr_view_commits=GhResult(ok=True, value=[{"authors": [_bot_author()]}]),
            pr_checks=GhResult(ok=True, value=[]),
        )
        return fake

    monkeypatch.setattr(orun, "GhClient", _fake_factory)

    # The tmp host repo has no `origin` remote; stub ONLY `git push` to
    # succeed so open_or_append_pr proceeds to pr_create (inverse of
    # test_pipeline_integration.test_git_push_failure_adds_partial).
    real_run = orun.subprocess.run

    def selective(cmd, *a, **kw):
        if isinstance(cmd, list) and cmd[:2] == ["git", "-C"] and "push" in cmd:
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(orun.subprocess, "run", selective)

    rc = orun.run(tmp_path, dry_run_dir=_FAKES, no_pr=False)
    assert rc == 0
    assert ("pr_merge", (11,)) in fake.calls
    current_run = json.loads(
        (tmp_path / ".engineering-docs-agent" / "current_run.json").read_text()
    )["current_run"]
    assert any(
        r.startswith("auto_merge_succeeded") for r in current_run["partial_reasons"]
    )
    assert current_run["partial"] is False  # info-only reasons never flip it


def test_cancelled_check_fails_fast_as_red():
    """bucket=cancel is terminal-non-green: skip immediately as
    checks_failed instead of burning the timeout as pending."""
    gh = _eligible_gh(
        pr_checks=GhResult(
            ok=True,
            value=[{"name": "ci", "state": "CANCELLED", "bucket": "cancel"}],
        )
    )
    outcome, reasons = _run(gh)
    assert outcome["reason"] == "checks_failed"
    assert "ci" in reasons[0][0]
    assert not [c for c in gh.calls if c[0] == "pr_merge"]
