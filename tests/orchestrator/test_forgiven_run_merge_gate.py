# tests/orchestrator/test_forgiven_run_merge_gate.py
"""CCE-178: a forgiven run must reach the merge, and must not forgive at 0.

CCE-175 shipped the stall clock and it fired correctly on the first production
run that exercised it — run 35609168489, 2026-09-21T13:59Z:

    cursor: admitted=[235,236,238,240,243,246,250,249,251,252]
            deferred=[235,246,249] held_back=[none] skipped=[235,246,249]
            baseline_age=6.1d stall_window=4d
    deferral_stall_escape: baseline has not advanced in 6.1d (window 4d);
                           forgiving 3 deferred PR(s) so state can reach main

...and the PR still did not merge:

    docs-agent INFO: auto_merge_skipped: partial_run

Two defects, both introduced or left open by CCE-175.

DEFECT 1. Emptying `held_back` routes the run to the `else` branch, which sets
`advance_cursor_backed = False`. CCE-140's gate is `partial and not
advance_cursor_backed`, and a forgiven run is still partial, so the merge is
skipped. The escape moved the run from one blocked path to another.

The CCE-175 end-to-end test asserted `_LAST_ADVANCE_CURSOR_BACKED is True` and
PASSED, because it used a truncating clock and therefore reached the assertion
through the *walk* branch, where the flag is set True. Production had no time
truncation. A test that reaches its assertion by a different path than
production is not coverage — so every end-to-end case here runs with
`time_budget_seconds=0` (no truncation), which is the shape that actually ran.

DEFECT 2. The escape forgave every deferred PR regardless of count. #246 and
#249 were deferred for the FIRST time, blocked by an unrelated page, and
abandoned immediately because a different PR had stalled the baseline. The
threshold promises three chances; the clock was taking them away.

The obvious narrowing — forgive only PRs with count >= 1 — re-creates the
deadlock. A first-time deferral at the OLDEST position blocks the cursor
prefix at index 0, so no cursor exists, so nothing merges, so its count never
reaches 1. The counter cannot be a precondition for the escape from the
counter. `test_the_deadlock_breaks_once_the_clock_is_consulted` in
test_deferral_stall_escape.py catches exactly that, which is how this was
found before it shipped.

So the escape forgives the PREFIX BLOCKER: the single oldest deferred PR, one
per stalled run. `partition_deferrals` takes an explicit `forgive` set and
stays order-independent; the caller resolves window order.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as orun  # noqa: E402

FAKES_MULTI = Path(__file__).parent / "fakes_multi"
FAKES_BLOCK = Path(__file__).parent / "fakes_block"

REPO = {"owner": "o", "name": "r"}
ANCIENT = "2020-01-01T00:00:00+00:00"


def _pr(n: int, sha: str | None = None) -> dict:
    d = {"number": n, "title": f"PR {n}", "url": f"https://github.com/o/r/pull/{n}"}
    if sha:
        d["merge_sha"] = sha
    return d


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


# ---------------------------------------------------------------------------
# Defect 2 — the clock must not forgive a PR that has never been deferred
# ---------------------------------------------------------------------------


def test_a_stalled_baseline_does_not_forgive_a_pr_at_zero_deferrals():
    """#246 and #249 in production: deferred for the first time, blocked by an
    unrelated page, abandoned anyway because a different PR stalled the
    baseline. The threshold promises three chances."""
    skipped, still = orun.partition_deferrals(
        [_pr(1, "a")], counts={}, repo=REPO, threshold=3, forgive=frozenset()
    )
    assert skipped == []
    assert [p["number"] for p in still] == [1]


def test_a_stalled_baseline_forgives_a_pr_that_has_been_deferred_before():
    """Count 1 is the production shape for #235: deferred on an earlier run,
    pinned at 1 because state never reached main. That one IS forgiven."""
    skipped, still = orun.partition_deferrals(
        [_pr(1, "a")],
        counts={orun.deferral_key(REPO, 1): 1},
        repo=REPO,
        threshold=3,
        forgive={1},
    )
    assert [p["number"] for p in skipped] == [1]
    assert still == []


def test_a_stalled_run_forgives_only_the_previously_deferred_subset():
    """Mixed window, exactly as production saw it: one PR with history, two
    without. Only the one with history is abandoned."""
    skipped, still = orun.partition_deferrals(
        [_pr(235, "a"), _pr(246, "b"), _pr(249, "c")],
        counts={orun.deferral_key(REPO, 235): 1},
        repo=REPO,
        threshold=3,
        forgive={235},
    )
    assert [p["number"] for p in skipped] == [235]
    assert [p["number"] for p in still] == [246, 249]


def test_the_threshold_still_forgives_regardless_of_the_clock():
    """CCE-140's own path is untouched: at the threshold a PR is abandoned
    whether or not the baseline has stalled."""
    for forgive in (frozenset(), {1}):
        skipped, _ = orun.partition_deferrals(
            [_pr(1, "a")],
            counts={orun.deferral_key(REPO, 1): 3},
            repo=REPO,
            threshold=3,
            forgive=forgive,
        )
        assert [p["number"] for p in skipped] == [1], f"forgive={forgive}"


# ---------------------------------------------------------------------------
# Defect 1 — end-to-end, on the NON-TRUNCATED path production actually took
# ---------------------------------------------------------------------------


def _seed(repo: Path, state_path: Path, counts: dict) -> tuple[str, list]:
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
                "last_successful_run": {"head_sha": base, "completed_at": ANCIENT},
                "deferral_counts": counts,
            }
        )
    )
    return base, shas


def _lint_blocked_fakes(tmp_path: Path, prs: list[dict]) -> Path:
    dst = tmp_path.parent / f"fakes_cce178_{tmp_path.name}"
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


def test_a_forgiven_non_truncated_run_is_cursor_backed(tmp_path, init_host):
    """THE regression. No time truncation — `time_budget_seconds=0` — so the
    run takes the `else` branch, exactly as production did.

    Before this fix `_LAST_ADVANCE_CURSOR_BACKED` was False here and CCE-140's
    `partial and not advance_cursor_backed` gate skipped the merge with
    `auto_merge_skipped: partial_run`, leaving state.json stranded on the
    branch and the baseline frozen for a seventh day.
    """
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {}})
    base, (c1, c2, c3, c4) = _seed(repo, state_path, {})
    # Give every window PR prior deferral history, so defect 2's guard does not
    # mask defect 1: what is under test here is the merge gate, not the count.
    detected = orun.detect_repo(repo)
    state_path.write_text(
        json.dumps(
            {
                "version": "1",
                "last_successful_run": {"head_sha": base, "completed_at": ANCIENT},
                "deferral_counts": {
                    orun.deferral_key(detected, n): 1 for n in (1, 2, 3)
                },
            }
        )
    )
    prs = [
        {**_pr(1, c1), "files": [], "labels": [], "jira_keys": []},
        {**_pr(2, c2), "files": [], "labels": [], "jira_keys": []},
        {**_pr(3, c3), "files": [], "labels": [], "jira_keys": []},
    ]
    rc = orun.run(
        repo,
        dry_run_dir=_lint_blocked_fakes(tmp_path, prs),
        no_pr=True,
        time_budget_seconds=0,  # NOT truncated: the production shape
    )
    assert rc == 0
    reasons = _reasons(state_path)
    assert [r for r in reasons if "deferral_stall_escape" in r], reasons
    assert orun._LAST_ADVANCE_CURSOR_BACKED is True, (
        "a forgiven advance is an explicit, durably recorded decision -- every "
        "skip lands in skipped_prs. Reporting it as not cursor-backed is what "
        "kept auto_merge_skipped: partial_run firing in production"
    )
    assert base != json.loads(state_path.read_text())["last_successful_run"]["head_sha"]


def test_a_stalled_run_forgives_only_the_oldest_deferred_pr(tmp_path, init_host):
    """The blast-radius fix, end to end and at the call site.

    All three window PRs are deferred by the same lint block and none has any
    prior count — production's #246/#249 shape. Exactly one is abandoned: the
    oldest, which is the PR actually holding the cursor prefix. The other two
    keep their three chances, and because the baseline moves the clock resets
    and the ordinary counter governs the next run.

    CCE-175 skipped all three here.
    """
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {}})
    base, (c1, c2, c3, c4) = _seed(repo, state_path, {})
    prs = [
        {**_pr(1, c1), "files": [], "labels": [], "jira_keys": []},
        {**_pr(2, c2), "files": [], "labels": [], "jira_keys": []},
        {**_pr(3, c3), "files": [], "labels": [], "jira_keys": []},
    ]
    rc = orun.run(
        repo,
        dry_run_dir=_lint_blocked_fakes(tmp_path, prs),
        no_pr=True,
        time_budget_seconds=0,
    )
    assert rc == 0
    skips = [r for r in _reasons(state_path) if r.startswith("deferral_skip:")]
    assert len(skips) == 1, skips
    assert "#1 " in skips[0], skips[0]
    escape = [r for r in _reasons(state_path) if "deferral_stall_escape" in r]
    assert escape and "oldest deferred PR #1" in escape[0], escape
    # PRs 2 and 3 were NOT abandoned, so they still hold the cursor and the
    # baseline must not have run past them to window HEAD.
    advanced = json.loads(state_path.read_text())["last_successful_run"]["head_sha"]
    assert advanced != _git(repo, "rev-parse", "HEAD")


def test_a_clean_non_truncated_run_is_still_not_cursor_backed(tmp_path, init_host):
    """The narrowing that keeps CCE-151 intact. A clean run advances to window
    HEAD and reports NOT cursor-backed, exactly as before — the new True is
    conditioned on something actually having been forgiven, not on reaching
    the `else` branch."""
    state_path = init_host(
        {"version": "1", "last_successful_run": {"completed_at": ANCIENT}}
    )
    rc = orun.run(tmp_path, dry_run_dir=FAKES_MULTI, no_pr=True, time_budget_seconds=0)
    assert rc == 0
    assert not [r for r in _reasons(state_path) if "deferral_stall_escape" in r]
    assert orun._LAST_ADVANCE_CURSOR_BACKED is False
