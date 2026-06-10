# tests/orchestrator/test_time_budget.py
"""CCE-109: time-budget soft deadline — break the nightly doom loop."""

from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import orchestrator_runner as runner  # noqa: E402


def test_resolve_time_budget_precedence():
    # CLI override wins (including explicit 0 = unlimited).
    assert (
        runner.resolve_time_budget({"run": {"time_budget_seconds": 1200}}, 999) == 999
    )
    assert runner.resolve_time_budget({"run": {"time_budget_seconds": 1200}}, 0) == 0
    # No CLI override → config value.
    assert (
        runner.resolve_time_budget({"run": {"time_budget_seconds": 1200}}, None) == 1200
    )
    # No CLI, no config → default.
    assert runner.resolve_time_budget({}, None) == runner.DEFAULT_TIME_BUDGET_SECONDS
    assert (
        runner.resolve_time_budget({"run": {}}, None)
        == runner.DEFAULT_TIME_BUDGET_SECONDS
    )
    # Default is 2700.
    assert runner.DEFAULT_TIME_BUDGET_SECONDS == 2700


def _git(tmp: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(tmp), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _init_repo_with_commits(tmp: Path, n: int) -> list[str]:
    """Init a git repo with 1 base commit + n numbered commits.
    Returns [base_sha, c1, c2, ..., cn] (oldest-first)."""
    tmp.mkdir(parents=True, exist_ok=True)
    _git(tmp, "init", "-q")
    _git(tmp, "config", "user.email", "t@example.com")
    _git(tmp, "config", "user.name", "T")
    (tmp / "f.txt").write_text("base")
    _git(tmp, "add", ".")
    _git(tmp, "commit", "-q", "-m", "base")
    shas = [_git(tmp, "rev-parse", "HEAD")]
    for i in range(1, n + 1):
        (tmp / "f.txt").write_text(f"c{i}")
        _git(tmp, "add", ".")
        _git(tmp, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(tmp, "rev-parse", "HEAD"))
    return shas


def test_order_prs_oldest_first_reorders_with_real_window(tmp_path):
    shas = _init_repo_with_commits(tmp_path, 3)  # [base, c1, c2, c3]
    base, c1, c2, c3 = shas
    head = c3
    # PRs supplied newest-first; merge_sha = real commits.
    prs = [
        {"number": 3, "merge_sha": c3},
        {"number": 2, "merge_sha": c2},
        {"number": 1, "merge_sha": c1},
    ]
    ordered = runner._order_prs_oldest_first(
        prs, repo_root=tmp_path, last_sha=base, head_sha=head
    )
    assert [p["number"] for p in ordered] == [1, 2, 3]


def test_order_prs_oldest_first_passthrough_when_git_fails(tmp_path):
    # Bogus last_sha → git rev-list fails → return prs unchanged (graceful).
    prs = [{"number": 3, "merge_sha": "c"}, {"number": 1, "merge_sha": "a"}]
    ordered = runner._order_prs_oldest_first(
        prs, repo_root=tmp_path, last_sha="nope000", head_sha="nope999"
    )
    assert [p["number"] for p in ordered] == [3, 1]


FAKES_MULTI = Path(__file__).parent / "fakes_multi"


def _fake_clock(values):
    """Return a callable yielding the given monotonic values in order, then
    repeating the last value. First value is consumed by the deadline calc."""
    it = iter(values)
    last = values[-1]
    return lambda: next(it, last)


def test_unlimited_budget_processes_all_prs(tmp_path, init_host, read_current_run):
    # Empty baseline (first-run case) → clip + ordering take their documented
    # `if not last_sha: return prs` passthrough with NO partial reason emitted,
    # so a clean unlimited run is genuinely partial-free. (A *bogus* last_sha
    # would instead trip the pre-existing CCE-19 `out_of_window_filter_skipped`
    # clip partial, which is orthogonal to the time-budget gate under test.)
    # 3 PRs from fakes_multi; budget 0 = unlimited → no truncation.
    state_path = init_host(
        {"version": "1", "last_successful_run": {}},
    )
    rc = runner.run(
        tmp_path, dry_run_dir=FAKES_MULTI, no_pr=True, time_budget_seconds=0
    )  # 0 = unlimited
    assert rc == 0
    cr = read_current_run(state_path)
    assert cr["partial"] is False
    assert not any("time_budget_exceeded" in r for r in cr["partial_reasons"])
    # Non-truncated runs never carry the truncation-only window marker.
    written = json.loads(state_path.read_text())
    assert "window_head_sha" not in written["last_successful_run"]


def test_truncates_after_budget_and_records_partial(
    tmp_path, init_host, read_current_run
):
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "old_sha_000"}},
    )
    # deadline calc=0 → deadline=100; i=1 check=50 (admit PR2); i=2 check=150 (trip).
    clock = _fake_clock([0, 50, 150])
    rc = runner.run(
        tmp_path,
        dry_run_dir=FAKES_MULTI,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 0
    cr = read_current_run(state_path)
    assert cr["partial"] is True
    assert any(
        "time_budget_exceeded: admitted 2/3" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]


def test_always_admits_at_least_one_pr(tmp_path, init_host, read_current_run):
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "old_sha_000"}},
    )
    # Already past deadline at first gate (i=1), but i=0 is never gated → admit 1.
    clock = _fake_clock([0, 9999])
    rc = runner.run(
        tmp_path,
        dry_run_dir=FAKES_MULTI,
        no_pr=True,
        time_budget_seconds=1,
        now_monotonic=clock,
    )
    assert rc == 0
    cr = read_current_run(state_path)
    assert cr["partial"] is True
    assert any(
        "time_budget_exceeded: admitted 1/3" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]


def _write_fakes_with_prs(src: Path, dst: Path, prs: list[dict]) -> None:
    """Copy a fakes dir and overwrite its source-collector PRs."""
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        (dst / f.name).write_text(f.read_text())
    sc = json.loads((src / "fake_source_collector.json").read_text())
    sc["prs"] = prs
    (dst / "fake_source_collector.json").write_text(json.dumps(sc))


def test_truncated_run_advances_to_last_processed_pr(tmp_path, init_host):
    # Real window so the Component-4 in-window guard confirms the cursor.
    # PRs in window order #1(c1) #2(c2) #3(c3); truncate after 2 → cursor = c2.
    repo = tmp_path
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "seed"}}
    )
    base, (c1, c2, c3) = _seed_real_window(repo, state_path)
    fakes = tmp_path.parent / "fakes_cce109_advance"
    _write_fakes_with_prs(FAKES_MULTI, fakes, [_pr(1, c1), _pr(2, c2), _pr(3, c3)])
    clock = _fake_clock([0, 50, 150])  # admit 2 of 3 → cursor = c2
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == c2, written[
        "last_successful_run"
    ]


def test_truncation_with_out_of_window_cursor_does_not_advance(
    tmp_path, init_host, read_current_run
):
    # Prober edge / spec Component-4 guard: an uncomputable window (bogus baseline)
    # plus a cursor SHA that cannot be verified inside last_sha..head_sha must NOT
    # advance the baseline (no silent regression). The fake merge_sha 'b' is not a
    # real commit, so cursor normalization (rev-parse) fails and the guard refuses
    # the advance, recording time_budget_advance_out_of_window with a reason code
    # (review fix 6) so triage can tell infra failure from data corruption.
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "old_sha_000"}}
    )
    clock = _fake_clock([0, 50, 150])  # admit 2 of 3; cursor would be fake 'b'
    rc = runner.run(
        tmp_path,
        dry_run_dir=FAKES_MULTI,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    # Baseline must NOT regress to the unverifiable cursor 'b'.
    assert written["last_successful_run"]["head_sha"] == "old_sha_000", written[
        "last_successful_run"
    ]
    cr = read_current_run(state_path)
    assert any(
        "time_budget_advance_out_of_window" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    # Fix 6: the partial reason names the cause — an unresolvable cursor here —
    # not just a generic "not confirmed".
    assert any(
        "time_budget_advance_out_of_window" in r and "unresolvable" in r
        for r in cr["partial_reasons"]
    ), cr["partial_reasons"]


def test_gate_admits_on_deadline_equality_not_strict(
    tmp_path, init_host, read_current_run
):
    # The admission gate is strict `clock() > deadline`, so clock()==deadline
    # ADMITS. Pins `>` against a `>=` regression that would truncate one PR early.
    state_path = init_host({"version": "1", "last_successful_run": {}})
    clock = _fake_clock([0, 100])  # deadline=100; every gate check sees exactly 100
    rc = runner.run(
        tmp_path,
        dry_run_dir=FAKES_MULTI,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 0
    cr = read_current_run(state_path)
    assert not any("time_budget_exceeded" in r for r in cr["partial_reasons"]), cr[
        "partial_reasons"
    ]


def test_order_prs_oldest_first_matches_short_merge_sha(tmp_path):
    # A 7-char prefix merge_sha still resolves via the order_short branch.
    shas = _init_repo_with_commits(tmp_path, 3)  # [base, c1, c2, c3]
    base, c1, c2, c3 = shas
    prs = [
        {"number": 3, "merge_sha": c3[:7]},
        {"number": 2, "merge_sha": c2[:7]},
        {"number": 1, "merge_sha": c1[:7]},
    ]
    ordered = runner._order_prs_oldest_first(
        prs, repo_root=tmp_path, last_sha=base, head_sha=c3
    )
    assert [p["number"] for p in ordered] == [1, 2, 3]


def test_order_prs_oldest_first_empty_list(tmp_path):
    # Empty PR list (a no-merge nightly) → trivial passthrough, no git call.
    assert (
        runner._order_prs_oldest_first(
            [], repo_root=tmp_path, last_sha="anything", head_sha="anything"
        )
        == []
    )


def test_oldest_first_cursor_is_oldest_commit(tmp_path, init_host):
    # Real window; PRs given newest-first; truncate after 1 → must advance to OLDEST.
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "x"}})
    base, (c1, c2, c3) = _seed_real_window(repo, state_path)
    fakes = tmp_path.parent / "fakes_cce109_order"
    _write_fakes_with_prs(FAKES_MULTI, fakes, [_pr(3, c3), _pr(2, c2), _pr(1, c1)])
    clock = _fake_clock([0, 9999])  # admit exactly 1 (the oldest after ordering)
    rc = runner.run(
        repo, dry_run_dir=fakes, no_pr=True, time_budget_seconds=1, now_monotonic=clock
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    # Correct oldest-first ordering admits PR#1 → cursor c1 (oldest).
    # A broken passthrough would admit PR#3 → c3. Discriminating assertion:
    assert written["last_successful_run"]["head_sha"] == c1, written[
        "last_successful_run"
    ]


def test_truncation_with_no_usable_cursor_does_not_advance(
    tmp_path, init_host, read_current_run
):
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "old_sha_000"}}
    )
    fakes = tmp_path.parent / "fakes_cce109_nocursor"
    _write_fakes_with_prs(
        FAKES_MULTI,
        fakes,
        [
            # no merge_sha (cannot anchor cursor); url required by schema
            {"number": 1, "title": "x", "url": "https://github.com/o/r/pull/1"},
            {"number": 2, "title": "y", "url": "https://github.com/o/r/pull/2"},
            {"number": 3, "title": "z", "url": "https://github.com/o/r/pull/3"},
        ],
    )
    clock = _fake_clock([0, 50, 150])  # admit 2, both lack merge_sha
    rc = runner.run(
        tmp_path,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == "old_sha_000"
    cr = read_current_run(state_path)
    assert any(
        "time_budget_no_advance_no_cursor" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]


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


def _pr(n: int, sha: str | None = None) -> dict:
    d = {"number": n, "title": f"PR {n}", "url": f"https://github.com/o/r/pull/{n}"}
    if sha:
        d["merge_sha"] = sha
    return d


def test_first_run_truncation_advances_to_oldest_admitted(tmp_path, init_host):
    # Review fix 1: an EMPTY baseline (first run) must still order oldest-first
    # (rev-list --reverse over the full history) so a truncated first run
    # advances to the OLDEST admitted PR. With the pre-fix passthrough, the
    # collector's newest-first order is admitted as-is and the cursor lands
    # mid-window, permanently stranding every older PR behind it.
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {}})
    shas = []
    for i in range(1, 4):
        (repo / "f.txt").write_text(f"c{i}")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    c1, c2, c3 = shas
    fakes = tmp_path.parent / "fakes_cce109_firstrun"
    # Collector order is newest-first — the realistic gh default.
    _write_fakes_with_prs(FAKES_MULTI, fakes, [_pr(3, c3), _pr(2, c2), _pr(1, c1)])
    clock = _fake_clock([0, 9999])  # admit exactly 1
    rc = runner.run(
        repo, dry_run_dir=fakes, no_pr=True, time_budget_seconds=1, now_monotonic=clock
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == c1, written[
        "last_successful_run"
    ]


def test_truncation_refuses_advance_when_deferred_pr_unanchored(
    tmp_path, init_host, read_current_run
):
    # Review fix 2: merge_sha-less PRs sort last, so under truncation they sit
    # in the deferred tail; advancing the cursor past their merge time would
    # lose them forever (the next window never re-collects them). The advance
    # must be refused when any deferred PR is unanchored.
    repo = tmp_path
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "seed"}}
    )
    base, (c1, _c2, c3) = _seed_real_window(repo, state_path)
    fakes = tmp_path.parent / "fakes_cce109_unanchored"
    # PR2 has no merge_sha → orders [1, 3, 2]; truncation after 2 defers PR2.
    _write_fakes_with_prs(FAKES_MULTI, fakes, [_pr(1, c1), _pr(2), _pr(3, c3)])
    clock = _fake_clock([0, 50, 150])  # admit 2 of 3
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == base, written[
        "last_successful_run"
    ]
    cr = read_current_run(state_path)
    assert any(
        "time_budget_no_advance_unanchored_deferred" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]


def test_truncated_cursor_persisted_as_full_sha(tmp_path, init_host):
    # Review fix 3: the source-collector contract permits abbreviated
    # merge_shas (its own example is 8-char). The persisted baseline must be
    # normalized to the full 40-hex commit id, never a prefix.
    repo = tmp_path
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "seed"}}
    )
    base, (c1, c2, c3) = _seed_real_window(repo, state_path)
    fakes = tmp_path.parent / "fakes_cce109_shortsha"
    _write_fakes_with_prs(
        FAKES_MULTI, fakes, [_pr(1, c1[:8]), _pr(2, c2[:8]), _pr(3, c3[:8])]
    )
    clock = _fake_clock([0, 50, 150])  # admit 2 of 3 → cursor = c2
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    got = written["last_successful_run"]["head_sha"]
    assert got == c2 and len(got) == 40, written["last_successful_run"]


def test_truncated_run_records_window_head_for_rerun_guard(tmp_path, init_host):
    # Review fix 4: a truncated run persists window_head_sha = the run's real
    # HEAD so the CCE-43 same-hour guard recognizes the window as already
    # processed (the cursor alone never equals HEAD).
    repo = tmp_path
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "seed"}}
    )
    base, (c1, c2, c3) = _seed_real_window(repo, state_path)
    fakes = tmp_path.parent / "fakes_cce109_windowhead"
    _write_fakes_with_prs(FAKES_MULTI, fakes, [_pr(1, c1), _pr(2, c2), _pr(3, c3)])
    clock = _fake_clock([0, 50, 150])  # admit 2 of 3
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    head = _git(repo, "rev-parse", "HEAD")
    assert written["last_successful_run"].get("window_head_sha") == head, written[
        "last_successful_run"
    ]
    # Guard matcher: truncated state covers the window…
    assert runner._remote_state_covers_window(written, head) is True
    # …a full-run state (head_sha == HEAD, no window field) still matches…
    assert (
        runner._remote_state_covers_window(
            {"last_successful_run": {"head_sha": head}}, head
        )
        is True
    )
    # …and unrelated or empty state never does.
    assert (
        runner._remote_state_covers_window(
            {"last_successful_run": {"head_sha": "other"}}, head
        )
        is False
    )
    assert runner._remote_state_covers_window({}, head) is False


def test_truncated_pr_body_current_sha_is_cursor(tmp_path, monkeypatch, init_host):
    # Review fix 5 (spec Component 6): the PR body's "baseline X → current Y"
    # must show the truncated cursor as Y, not the full window HEAD — otherwise
    # the operator reads a coverage claim the run did not deliver.
    repo = tmp_path
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "seed"}}
    )
    base, (c1, c2, c3) = _seed_real_window(repo, state_path)
    fakes = tmp_path.parent / "fakes_cce109_prbody"
    _write_fakes_with_prs(FAKES_MULTI, fakes, [_pr(1, c1), _pr(2, c2), _pr(3, c3)])

    captured: dict = {}

    def fake_open_or_append_pr(
        repo_root, gh, *, branch, now_iso, partial, partial_reasons, **kw
    ):
        captured.update(kw)
        return None, [("forced_failure: pr_open simulated", False)]

    monkeypatch.setattr(runner, "open_or_append_pr", fake_open_or_append_pr)
    clock = _fake_clock([0, 50, 150])  # admit 2 of 3 → cursor = c2
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=False,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 1  # PR-open failure hard-fails per spec §8 row 7
    assert captured.get("current_sha") == c2, captured
    assert captured.get("baseline_sha") == base, captured


def test_ordering_degrades_when_window_uncomputable(
    tmp_path, init_host, read_current_run
):
    # Spec test 7 (graceful degradation): a *bogus* last_sha makes
    # `git rev-list bogus_000..HEAD` exit rc=128, so BOTH `_clip_prs_to_window`
    # and `_order_prs_oldest_first` hit their documented git-failure fallback and
    # pass the PRs through in their given order — no crash. The run still
    # finalizes cleanly (rc == 0) and the time-budget gate never trips (the fake
    # clock stays under deadline=100).
    #
    # NOTE on assertions (CCE-109 plan-vs-code drift, resolved per the sibling
    # `test_unlimited_budget_processes_all_prs`): a bogus last_sha deliberately
    # exercises the rev-list-FAILURE path, but that same failure makes
    # `_clip_prs_to_window` record the pre-existing CCE-19
    # `out_of_window_filter_skipped` partial — orthogonal to the time-budget gate
    # under test. So this test asserts the time-budget-specific contract (no
    # `time_budget_exceeded` reason, clean rc) and that the ONLY partial cause is
    # that orthogonal clip fallback — never a `cr["partial"] is False` that the
    # CCE-19 net makes impossible whenever the window is uncomputable.
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "bogus_000"}},
    )
    clock = _fake_clock([0, 1, 2, 3])  # always under deadline=100
    rc = runner.run(
        tmp_path,
        dry_run_dir=FAKES_MULTI,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 0
    cr = read_current_run(state_path)
    # The time-budget gate must NOT have fired (window degraded, not truncated).
    assert not any("time_budget_exceeded" in r for r in cr["partial_reasons"]), cr[
        "partial_reasons"
    ]
    # Any partial state is solely the orthogonal CCE-19 clip fallback, never the
    # time-budget feature.
    assert all("time_budget" not in r for r in cr["partial_reasons"]), cr[
        "partial_reasons"
    ]
