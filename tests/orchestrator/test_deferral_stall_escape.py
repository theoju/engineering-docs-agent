# tests/orchestrator/test_deferral_stall_escape.py
"""CCE-175: the deferral counter cannot ratchet, so the hatch needs a clock.

CCE-140 gave the pipeline a release valve: after `threshold` consecutive
deferrals a PR is abandoned so the cursor can walk past it. The valve counts
in `state.json:deferral_counts`.

`state.json` reaches `main` only when the docs-agent PR merges. The PR does
not merge while the run is partial and not cursor-backed (CCE-140's gate). The
run is partial *because* a page is deferred — the very condition the counter
exists to escape. So every night reads the same committed count, writes
count+1 into a branch that never lands, and the threshold is unreachable by
construction.

Observed 2026-09-20 on theoju/claude-code-self-assessment:

    origin/main   deferral_counts: {#235: 1, #236: 1}
    PR #248       deferral_counts: {#235: 2, #236: 2, #240: 1, #243: 1}

Five days, baseline pinned at 175162e1, counts pinned at 1.

The escape keys off `last_successful_run.completed_at`, which is ALREADY on
main and needs no new write — until CCE-175 it was written and never read.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as orun  # noqa: E402

REPO = {"owner": "o", "name": "r"}


def _pr(n: int, sha: str | None = None) -> dict:
    d = {"number": n, "title": f"PR {n}", "url": f"https://github.com/o/r/pull/{n}"}
    if sha:
        d["merge_sha"] = sha
    return d


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ---------------------------------------------------------------------------
# The bug, pinned as an executable statement of the deadlock.
# ---------------------------------------------------------------------------


def test_counter_never_reaches_threshold_while_the_run_pr_never_merges():
    """Ten nights, threshold 3, and the PR is never forgiven.

    `committed` is what `main` holds. A run reads it, computes the next map,
    and writes that into the docs PR branch. The PR does not merge, so
    `committed` never changes and every night recomputes 1 from 0.
    """
    committed: dict = {}
    threshold = 3
    written = []

    for _ in range(10):
        counts = dict(committed)  # each run reads main, not its own last write
        skipped, still = orun.partition_deferrals(
            [_pr(1, "a")], counts=counts, repo=REPO, threshold=threshold
        )
        assert skipped == [], "PR was forgiven — deadlock would be broken"
        nxt = orun.next_deferral_counts(
            counts,
            repo=REPO,
            window_pr_numbers={1},
            still_deferred_numbers={1},
        )
        written.append(nxt[orun.deferral_key(REPO, 1)])
        # The docs PR does not merge: `committed` is deliberately NOT updated.

    assert written == [1] * 10, "the written count is recomputed, never ratcheted"


# ---------------------------------------------------------------------------
# resolve_deferral_stall_days
# ---------------------------------------------------------------------------


def test_stall_window_defaults_to_threshold_plus_one_day():
    """A time-domain mirror of the counter, not a new arbitrary policy.

    Threshold 3 fires on the 4th consecutive run; on a nightly cadence that is
    4 days. Deriving the default keeps the two in step when a host raises one.
    """
    assert orun.resolve_deferral_stall_days({}) == 4
    assert (
        orun.resolve_deferral_stall_days({"run": {"deferral_skip_threshold": 6}}) == 7
    )


def test_stall_window_is_configurable_and_disabled_with_the_skip_hatch():
    assert orun.resolve_deferral_stall_days({"run": {"deferral_stall_days": 14}}) == 14
    # threshold <= 0 disables skipping entirely (CCE-140); the clock follows.
    assert (
        orun.resolve_deferral_stall_days({"run": {"deferral_skip_threshold": 0}}) == 0
    )


# ---------------------------------------------------------------------------
# baseline_stall_days
# ---------------------------------------------------------------------------


def test_baseline_stall_days_measures_from_last_successful_run():
    now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    state = {"last_successful_run": {"completed_at": _iso(now - timedelta(days=5))}}
    assert orun.baseline_stall_days(state, now=now) == 5.0


def test_baseline_stall_days_is_none_when_the_baseline_is_unknown():
    """A bootstrap host has no baseline; absence must not read as an infinite
    stall, which would forgive every PR on the first ever run."""
    now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    assert orun.baseline_stall_days({}, now=now) is None
    assert orun.baseline_stall_days({"last_successful_run": {}}, now=now) is None
    assert (
        orun.baseline_stall_days(
            {"last_successful_run": {"completed_at": "not-a-date"}}, now=now
        )
        is None
    )


def test_baseline_stall_days_tolerates_a_naive_timestamp():
    """Older hosts wrote a naive ISO string; it must not raise."""
    now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    state = {"last_successful_run": {"completed_at": "2026-09-18T12:00:00"}}
    assert orun.baseline_stall_days(state, now=now) == 2.0


def test_baseline_stall_days_never_returns_a_negative():
    """Clock skew between the host and the runner must not read as a stall in
    the future; it clamps to zero rather than going negative."""
    now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    state = {"last_successful_run": {"completed_at": _iso(now + timedelta(days=2))}}
    assert orun.baseline_stall_days(state, now=now) == 0.0


# ---------------------------------------------------------------------------
# partition_deferrals(stalled=...)
# ---------------------------------------------------------------------------


def test_a_stalled_baseline_forgives_a_pr_the_counter_never_could():
    """The fix. Count 1 forever, but the baseline has not moved in 5 days."""
    skipped, still = orun.partition_deferrals(
        [_pr(1, "a")],
        counts={orun.deferral_key(REPO, 1): 1},
        repo=REPO,
        threshold=3,
        forgive={1},
    )
    assert [p["number"] for p in skipped] == [1]
    assert still == []


def test_a_fresh_baseline_does_not_forgive_early():
    """The clock is a backstop, never a shortcut past the counter."""
    skipped, still = orun.partition_deferrals(
        [_pr(1, "a")],
        counts={orun.deferral_key(REPO, 1): 1},
        repo=REPO,
        threshold=3,
        forgive=frozenset(),
    )
    assert skipped == []
    assert [p["number"] for p in still] == [1]


def test_stalled_is_inert_when_skipping_is_disabled():
    """`threshold <= 0` disables the hatch; the clock must not reopen it."""
    skipped, still = orun.partition_deferrals(
        [_pr(1, "a")],
        counts={},
        repo=REPO,
        threshold=0,
        forgive={1},
    )
    assert skipped == []
    assert [p["number"] for p in still] == [1]


def test_stalled_defaults_to_false_for_every_existing_caller():
    """The parameter is keyword-only with a False default, so CCE-140's
    behaviour is byte-identical for any call that does not pass it."""
    skipped, still = orun.partition_deferrals(
        [_pr(1, "a")],
        counts={orun.deferral_key(REPO, 1): 2},
        repo=REPO,
        threshold=3,
    )
    assert skipped == []
    assert [p["number"] for p in still] == [1]


def test_the_deadlock_breaks_once_the_clock_is_consulted():
    """The first test's loop, with the stall clock wired in: forgiven on the
    night the baseline crosses the window, without the counter ever moving."""
    committed: dict = {}
    threshold = 3
    stall_days = threshold + 1
    baseline = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    state = {"last_successful_run": {"completed_at": _iso(baseline)}}

    forgiven_on = None
    for night in range(1, 11):
        now = baseline + timedelta(days=night)
        age = orun.baseline_stall_days(state, now=now)
        skipped, _ = orun.partition_deferrals(
            [_pr(1, "a")],
            counts=dict(committed),
            repo=REPO,
            threshold=threshold,
            forgive={1} if (age is not None and age >= stall_days) else frozenset(),
        )
        if skipped:
            forgiven_on = night
            break

    assert forgiven_on == 4, "expected forgiveness on the 4th night, not never"


# ---------------------------------------------------------------------------
# End-to-end through run(). The pure functions above prove the decision; these
# prove the wiring, which is where both defects in this change actually were.
# Helpers are duplicated from test_deferral_skip.py rather than imported — no
# test module in this tree imports another, and a `tests/` package would
# shadow the real `scripts` namespace package (CLAUDE.md, CCE-122).
# ---------------------------------------------------------------------------

FAKES_MULTI = Path(__file__).parent / "fakes_multi"
FAKES_BLOCK = Path(__file__).parent / "fakes_block"

ANCIENT = "2020-01-01T00:00:00+00:00"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _fake_clock(values):
    it = iter(values)
    last = values[-1]
    return lambda: next(it, last)


def _seed_window4(repo: Path, state_path: Path, completed_at: str) -> tuple[str, list]:
    base = _git(repo, "rev-parse", "HEAD")
    shas = []
    for i in range(1, 5):
        (repo / "f.txt").write_text(f"c{i}")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    state_path.write_text(
        json.dumps(
            {
                "version": "1",
                "last_successful_run": {"head_sha": base, "completed_at": completed_at},
            }
        )
    )
    return base, shas


def _lint_blocked_fakes(tmp_path: Path, prs: list[dict]) -> Path:
    dst = tmp_path.parent / f"fakes_cce175_{tmp_path.name}"
    dst.mkdir(parents=True, exist_ok=True)
    for f in FAKES_MULTI.iterdir():
        (dst / f.name).write_text(f.read_text())
    sc = json.loads((FAKES_MULTI / "fake_source_collector.json").read_text())
    sc["prs"] = prs
    (dst / "fake_source_collector.json").write_text(json.dumps(sc))
    summ = json.loads((dst / "fake_pr_summarizer.json").read_text())
    summ["doc_targets"] = [
        {"lens": "core", "action": "create", "page_hint": "connectors/foo.md"}
    ]
    (dst / "fake_pr_summarizer.json").write_text(json.dumps(summ))
    (dst / "fake_content_validator.json").write_text(
        (FAKES_BLOCK / "fake_content_validator.json").read_text()
    )
    return dst


def _reasons(state_path: Path) -> list[str]:
    cur = json.loads((state_path.parent / "current_run.json").read_text())[
        "current_run"
    ]
    return cur.get("partial_reasons", []) or []


def _partial(state_path: Path) -> bool:
    cur = json.loads((state_path.parent / "current_run.json").read_text())[
        "current_run"
    ]
    return bool(cur.get("partial"))


def test_a_clean_run_with_a_stalled_baseline_stays_clean(tmp_path, init_host):
    """The regression that matters most, and the defect this change shipped
    with until the prototype's walkthrough 4 exposed it.

    A stalled baseline with NOTHING deferred is a clean run — and it is the
    most important run in the cycle, because holding nothing back makes it
    cursor-backed, so it auto-merges, so it resets the very clock that is
    stalled. Emitting the escape reason on `_stalled` alone flipped this run
    to partial and blocked the merge that ends the stall, turning the escape
    hatch into a second deadlock.
    """
    state_path = init_host(
        {"version": "1", "last_successful_run": {"completed_at": ANCIENT}}
    )
    rc = orun.run(tmp_path, dry_run_dir=FAKES_MULTI, no_pr=True, time_budget_seconds=0)
    assert rc == 0
    assert not _partial(state_path), _reasons(state_path)
    assert not [r for r in _reasons(state_path) if "deferral_stall_escape" in r]
    written = json.loads(state_path.read_text())
    assert "skipped_prs" not in written
    assert "deferral_counts" not in written


def test_a_stalled_baseline_forgives_end_to_end_and_becomes_cursor_backed(
    tmp_path, init_host
):
    """The fix, through the real runner.

    Same lint-blocked window as
    test_deferral_skip.test_a_lint_blocked_pr_is_held_out_of_the_cursor, whose
    assertion is `advance == base` and `_LAST_ADVANCE_CURSOR_BACKED is False`
    — the frozen baseline. The only difference here is an ancient
    `completed_at`, and that alone has to flip both: the PRs are forgiven, the
    cursor walks, and the advance is cursor-backed, which is what authorises
    the merge that finally promotes state to main.
    """
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {}})
    base, (c1, c2, c3, c4) = _seed_window4(repo, state_path, ANCIENT)
    prs = [
        {**_pr(1, c1), "files": [], "labels": [], "jira_keys": []},
        {**_pr(2, c2), "files": [], "labels": [], "jira_keys": []},
        {**_pr(3, c3), "files": [], "labels": [], "jira_keys": []},
    ]
    rc = orun.run(
        repo,
        dry_run_dir=_lint_blocked_fakes(tmp_path, prs),
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 50, 150]),
    )
    assert rc == 0
    escape = [r for r in _reasons(state_path) if "deferral_stall_escape" in r]
    assert escape, _reasons(state_path)
    assert orun._LAST_ADVANCE_CURSOR_BACKED is True, (
        "forgiveness must leave the walk unobstructed — an advance that is not "
        "cursor-backed cannot merge, which is the deadlock this closes"
    )
    advance = json.loads(state_path.read_text())["last_successful_run"]["head_sha"]
    assert advance != base, "the baseline must finally move"


# ---------------------------------------------------------------------------
# CCE-185: the escape is inert when the budget admits nothing.
# ---------------------------------------------------------------------------


def test_the_admission_gate_never_truncates_at_index_zero(tmp_path, init_host):
    """`i > 0` in the admission gate is what keeps CCE-178's scan safe.

    CCE-178 selects the PR to forgive by scanning `prs`:

        _blocker = next(
            (p.get("number") for p in prs if p.get("number") in _deferred_numbers),
            None,
        )

    `prs` has had the admission-deferred tail removed at `prs = prs[:i]`, while
    `held_back` is built from
    `set(deferred_pages_by_pr) | {p.number for p in admission_deferred}`. If
    `prs` could ever be emptied by truncation, `_blocker` would be None, so
    `_forgive` would be empty, so nothing would be forgiven, so `held_back`
    would be the whole window and the cursor could not move — and because the
    reason is guarded on `if _forgive:`, nothing would say so. A silent,
    permanent freeze.

    That cannot happen, and the reason is one clause:

        if deadline is not None and i > 0 and clock() > deadline:

    The gate refuses to truncate before admitting anything, so `prs` always
    holds at least the oldest PR — which is exactly the prefix blocker the
    scan needs to find.

    This test pins that clause by behaviour. The clock here is exhausted at
    the very first check; the run must still admit PR #1, still forgive it,
    and still move the baseline. Delete the `i > 0` and this goes red.
    """
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {}})
    base, (c1, c2, c3, c4) = _seed_window4(repo, state_path, ANCIENT)
    prs = [
        {**_pr(1, c1), "files": [], "labels": [], "jira_keys": []},
        {**_pr(2, c2), "files": [], "labels": [], "jira_keys": []},
        {**_pr(3, c3), "files": [], "labels": [], "jira_keys": []},
    ]
    rc = orun.run(
        repo,
        dry_run_dir=_lint_blocked_fakes(tmp_path, prs),
        no_pr=True,
        time_budget_seconds=100,
        # exhausted at the FIRST admission check: nothing is ever admitted
        now_monotonic=_fake_clock([0, 150, 150, 150, 150, 150, 150]),
    )
    assert rc == 0
    admitted = [
        r
        for r in _reasons(state_path)
        if r.startswith("time_budget_exceeded: admitted")
    ]
    assert admitted and " 0/" not in admitted[0], (
        "the gate must admit the oldest PR even with the budget already gone; "
        f"got {admitted}"
    )
    escape = [r for r in _reasons(state_path) if "deferral_stall_escape" in r]
    assert escape, (
        "a maximally-truncated stalled run must still find a prefix blocker; "
        f"got reasons={_reasons(state_path)}"
    )
    advance = json.loads(state_path.read_text())["last_successful_run"]["head_sha"]
    assert advance != base, "the baseline must move, not freeze silently"
