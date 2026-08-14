"""CCE-144: the three consumers of the blind flag — exit code (Task 4),
watermark advance (Task 5), auto-merge gate (Task 6)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402


# --------------------------------------------------------------------------
# Task 4 — exit code
# --------------------------------------------------------------------------


def test_exit_code_is_1_when_blind():
    assert orun._exit_code({"current_run": {"partial": True, "blind": True}}) == 1


def test_exit_code_is_0_when_degraded_only():
    assert orun._exit_code({"current_run": {"partial": True}}) == 0


def test_exit_code_is_0_on_a_clean_run():
    assert orun._exit_code({"current_run": {"partial": False}}) == 0


def test_exit_code_is_0_when_current_run_is_absent():
    """Defensive: an early return before current_run exists must not crash."""
    assert orun._exit_code({}) == 0


def test_exit_code_treats_explicit_false_as_not_blind():
    assert orun._exit_code({"current_run": {"blind": False}}) == 0


# --------------------------------------------------------------------------
# Task 5 — watermark interlock
# --------------------------------------------------------------------------


def _advance(state: dict, *, advance_sha: str, now: str, time_truncated: bool):
    """Mirror of the guarded advance in run(), exercised directly.

    run() is a ~1000-line function whose advance sits behind a full fixture
    dispatch; this pins the guard's logic in isolation.
    """
    if orun._should_advance_watermark(state):
        state["last_successful_run"] = {"head_sha": advance_sha, "completed_at": now}
        if time_truncated:
            state["last_successful_run"]["window_head_sha"] = state["current_run"][
                "head_sha"
            ]


def test_blind_run_does_not_advance_the_watermark():
    state = {
        "last_successful_run": {"head_sha": "old", "completed_at": "t0"},
        "current_run": {"partial": True, "blind": True, "head_sha": "new"},
    }
    _advance(state, advance_sha="new", now="t1", time_truncated=False)
    assert state["last_successful_run"] == {"head_sha": "old", "completed_at": "t0"}


def test_blind_truncated_run_does_not_write_window_head_sha_into_the_old_cursor():
    """The time_truncated block mutates last_successful_run in place. If it
    escapes the guard, a blind run corrupts the cursor it must not touch."""
    state = {
        "last_successful_run": {"head_sha": "old", "completed_at": "t0"},
        "current_run": {"partial": True, "blind": True, "head_sha": "new"},
    }
    _advance(state, advance_sha="new", now="t1", time_truncated=True)
    assert "window_head_sha" not in state["last_successful_run"]
    assert state["last_successful_run"]["head_sha"] == "old"


def test_degraded_run_still_advances():
    state = {
        "last_successful_run": {"head_sha": "old", "completed_at": "t0"},
        "current_run": {"partial": True, "head_sha": "new"},
    }
    _advance(state, advance_sha="new", now="t1", time_truncated=False)
    assert state["last_successful_run"]["head_sha"] == "new"


def test_degraded_truncated_run_still_records_window_head_sha():
    state = {
        "last_successful_run": {"head_sha": "old", "completed_at": "t0"},
        "current_run": {"partial": True, "head_sha": "new"},
    }
    _advance(state, advance_sha="cursor", now="t1", time_truncated=True)
    assert state["last_successful_run"]["window_head_sha"] == "new"


def test_clean_run_advances():
    state = {
        "last_successful_run": {"head_sha": "old", "completed_at": "t0"},
        "current_run": {"partial": False, "head_sha": "new"},
    }
    _advance(state, advance_sha="new", now="t1", time_truncated=False)
    assert state["last_successful_run"]["head_sha"] == "new"


def test_should_advance_is_true_when_current_run_is_absent():
    assert orun._should_advance_watermark({}) is True


# --------------------------------------------------------------------------
# Task 5 fix round 1 — the guard proven against the real code path
#
# `_advance()` above is a hand-copied mirror of the guard in `run()`: it
# proves the copy is right, not that `run()` still calls it. This drives a
# blind reason (source-collector error) AND a truncated window (time-budget
# admission cutoff) through the real `orun.run()` in one invocation, so a
# regression that moves the `if time_truncated:` block back outside the
# guard in production is caught here even though `_advance()` would stay
# green forever.
#
# source_collector_error does not short-circuit the pipeline: the
# post-dispatch branch in `run()` records the reason via `add_partial(...,
# degraded=False)` (blind) and then falls through to `sources.get("prs",
# [])` unconditionally, so it composes cleanly with an admission-loop
# truncation driven by the same fake clock pattern as
# tests/orchestrator/test_time_budget.py.
# --------------------------------------------------------------------------

FAKES_MULTI = Path(__file__).parent / "fakes_multi"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _fake_clock(values):
    """Monotonic values in order, then repeating the last (same helper as
    test_time_budget.py and test_authoring_truncation_advance.py)."""
    it = iter(values)
    last = values[-1]
    return lambda: next(it, last)


def _seed_real_window(
    repo: Path, state_path: Path, n: int = 3
) -> tuple[str, list[str]]:
    """Add n commits on top of the host's init commit and pin the baseline at
    that init commit, so last_sha..HEAD is a real n-commit window.
    Returns (base_sha, [c1..cn] oldest-first)."""
    base = _git(repo, "rev-parse", "HEAD")
    shas = []
    for i in range(1, n + 1):
        (repo / "f.txt").write_text(f"c{i}")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    state_path.write_text(
        json.dumps({"version": "1", "last_successful_run": {"head_sha": base}})
    )
    return base, shas


def _pr(n: int, sha: str) -> dict:
    return {
        "number": n,
        "title": f"PR {n}",
        "url": f"https://github.com/o/r/pull/{n}",
        "merge_sha": sha,
    }


def _write_fakes_errored_and_truncatable(
    src: Path, dst: Path, prs: list[dict], error: str
) -> Path:
    """Copy a fakes dir, override its source-collector PRs with real
    merge_shas, and mark the collector run as errored — composes a blind
    reason with whatever admission-loop truncation the caller's fake clock
    drives."""
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        (dst / f.name).write_text(f.read_text())
    sc = json.loads((src / "fake_source_collector.json").read_text())
    sc["prs"] = prs
    sc["error"] = error
    (dst / "fake_source_collector.json").write_text(json.dumps(sc))
    return dst


def test_blind_and_truncated_run_through_real_run_does_not_advance_or_write_window_head(
    tmp_path, init_host, read_current_run
):
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {}})
    base, (c1, c2, c3) = _seed_real_window(repo, state_path)
    fakes = tmp_path.parent / "fakes_blind_truncated"
    _write_fakes_errored_and_truncatable(
        FAKES_MULTI,
        fakes,
        [_pr(1, c1), _pr(2, c2), _pr(3, c3)],
        error="git_unrecoverable: api timeout after 3 retries",
    )
    # deadline=100; i=1 sees 50 (admit PR#2), i=2 sees 150 (defer PR#3) — the
    # same admission-truncation clock as test_time_budget.py.
    clock = _fake_clock([0, 50, 150])
    rc = orun.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 1, "source_collector_error is blind; run must exit 1"

    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == base, written[
        "last_successful_run"
    ]
    assert "window_head_sha" not in written["last_successful_run"], written[
        "last_successful_run"
    ]

    cr = read_current_run(state_path)
    assert cr.get("blind") is True, cr
    assert any("source_collector_error" in r for r in cr.get("blind_reasons", [])), cr


# --------------------------------------------------------------------------
# Task 6 — auto-merge interlock
# --------------------------------------------------------------------------


class _ExplodingGh:
    """Any gh access means the gate let the run through when it should not.

    __getattr__ rather than a single stub method: the gate must be proven to
    return BEFORE it touches the client at all, and hard-coding one method
    name would silently pass if the implementation reached for a different
    one first.
    """

    def __getattr__(self, name):  # pragma: no cover - must not run
        raise AssertionError(f"reached gh.{name}; the blind gate did not skip")


_MERGE_SETTINGS = {
    "policy": "auto",
    "checks_grace_seconds": 1,
    "checks_timeout_seconds": 1,
}


def _call(*, blind, partial, cursor_backed, gh=None, reasons=()):
    return orun._maybe_auto_merge(
        gh if gh is not None else _ExplodingGh(),
        pr_number=1,
        partial=partial,
        blind=blind,
        fact_warnings=[],
        merge_settings=dict(_MERGE_SETTINGS),
        build_workflow=None,
        deadline=None,
        clock=lambda: 0.0,
        sleep=lambda _s: None,
        advance_cursor_backed=cursor_backed,
        partial_reasons=tuple(reasons),
    )


def test_blind_and_cursor_backed_does_not_merge():
    """The case current code merges. This is the regression test for CCE-144's
    auto-merge interlock: blind + time-truncated + cursor-backed passes the
    CCE-140 gate and reaches the merge path today."""
    outcome, reasons = _call(blind=True, partial=True, cursor_backed=True)
    assert outcome["merged"] is False
    assert outcome["reason"] == "blind_run"
    assert any("auto_merge_skipped: blind_run" in r for r, _info in reasons)


def test_blind_without_cursor_backing_skips_as_blind_not_partial():
    """Both gates would stop this run. Asserting the REASON is the point: if
    the blind gate is removed, partial_run silently covers for it and a
    weaker assertion would still pass."""
    outcome, _reasons = _call(blind=True, partial=True, cursor_backed=False)
    assert outcome["reason"] == "blind_run"


def test_blind_gate_precedes_the_cce140_carve_out():
    """A blind run that is somehow not marked partial must still be stopped."""
    outcome, _reasons = _call(blind=True, partial=False, cursor_backed=True)
    assert outcome["reason"] == "blind_run"


def test_degraded_and_cursor_backed_still_reaches_the_merge_path():
    """CCE-140 must survive CCE-144. If the blind classification over-reaches
    into the time-budget reasons, this fails — which is the alarm-fatigue
    guard expressed as a test."""
    with pytest.raises(AssertionError, match="the blind gate did not skip"):
        _call(blind=False, partial=True, cursor_backed=True)
    # Sanity: the same call with blind=True must NOT raise, or the assertion
    # above would pass for the wrong reason (e.g. a stub that always throws).
    outcome, _ = _call(blind=True, partial=True, cursor_backed=True)
    assert outcome["reason"] == "blind_run"


def test_veto_still_wins_for_a_non_blind_run():
    outcome, _reasons = _call(
        blind=False,
        partial=True,
        cursor_backed=True,
        reasons=("app_token_unavailable: mint failed",),
    )
    assert outcome["reason"] == "merge_vetoed"


def test_manual_policy_is_unchanged_by_blind():
    outcome, reasons = orun._maybe_auto_merge(
        _ExplodingGh(),
        pr_number=1,
        partial=True,
        blind=True,
        fact_warnings=[],
        merge_settings={"policy": "manual"},
        build_workflow=None,
        deadline=None,
        clock=lambda: 0.0,
        advance_cursor_backed=True,
        partial_reasons=(),
    )
    assert outcome["reason"] == "policy_manual"
    assert reasons == []
