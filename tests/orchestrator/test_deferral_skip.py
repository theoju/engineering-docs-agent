# tests/orchestrator/test_deferral_skip.py
"""CCE-140: per-PR deferral counting, cursor narrowing, and the skip hatch.

The CCE-109 advance cursor is a PREFIX boundary: advancing the baseline to
PR k's merge sha declares every PR at index <= k done. So a PR this run did
not finish must stop the walk, and a PR the operator has decided to abandon
must not stop it. These tests pin both directions.
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


def _pr(n: int, sha: str | None = None) -> dict:
    d = {"number": n, "title": f"PR {n}", "url": f"https://github.com/o/r/pull/{n}"}
    if sha:
        d["merge_sha"] = sha
    return d


# ---------------------------------------------------------------------------
# advance_cursor_list
# ---------------------------------------------------------------------------


def test_cursor_list_is_whole_admitted_list_when_nothing_held_back():
    """Today's behaviour, pinned: no deferrals -> the cursor sees every
    admitted PR, exactly as _last_processed_merge_sha(prs) does now."""
    admitted = [_pr(1, "a"), _pr(2, "b"), _pr(3, "c")]
    out = orun.advance_cursor_list(admitted, [], held_back=set())
    assert [p["number"] for p in out] == [1, 2, 3]


def test_cursor_list_stops_at_first_held_back_pr():
    """PR 2 unfinished -> the cursor may only anchor on PR 1. Advancing to
    PR 3 would strand PR 2 outside every future window."""
    admitted = [_pr(1, "a"), _pr(2, "b"), _pr(3, "c")]
    out = orun.advance_cursor_list(admitted, [], held_back={2})
    assert [p["number"] for p in out] == [1]


def test_cursor_list_stops_at_the_first_held_back_pr_not_the_last():
    """Two held-back PRs: the boundary is the OLDEST, never the newest."""
    admitted = [_pr(1, "a"), _pr(2, "b"), _pr(3, "c"), _pr(4, "d")]
    out = orun.advance_cursor_list(admitted, [], held_back={2, 4})
    assert [p["number"] for p in out] == [1]


def test_cursor_list_refuses_everything_when_the_oldest_is_held_back():
    admitted = [_pr(1, "a"), _pr(2, "b")]
    assert orun.advance_cursor_list(admitted, [], held_back={1}) == []


def test_cursor_list_walks_into_the_deferred_tail_when_it_is_forgiven():
    """A PR the admission gate never reached is normally held back. When it
    has been forgiven (skipped), the walk continues into the tail so the
    baseline can finally move past it."""
    admitted = [_pr(1, "a"), _pr(2, "b")]
    tail = [_pr(3, "c"), _pr(4, "d")]
    out = orun.advance_cursor_list(admitted, tail, held_back={4})
    assert [p["number"] for p in out] == [1, 2, 3]


def test_cursor_list_does_not_walk_the_tail_when_an_admitted_pr_is_held_back():
    """Forgiveness of a tail PR must not leap over an unfinished admitted
    one — the boundary is still the oldest unfinished PR."""
    admitted = [_pr(1, "a"), _pr(2, "b")]
    tail = [_pr(3, "c")]
    out = orun.advance_cursor_list(admitted, tail, held_back={2})
    assert [p["number"] for p in out] == [1]


def test_cursor_list_empty_inputs():
    assert orun.advance_cursor_list([], [], held_back=set()) == []


# ---------------------------------------------------------------------------
# resolve_deferral_threshold
# ---------------------------------------------------------------------------


def test_threshold_defaults_to_three():
    assert orun.DEFAULT_DEFERRAL_SKIP_THRESHOLD == 3
    assert orun.resolve_deferral_threshold({}) == 3
    assert orun.resolve_deferral_threshold({"run": {}}) == 3


def test_threshold_reads_the_config_key():
    assert orun.resolve_deferral_threshold({"run": {"deferral_skip_threshold": 5}}) == 5


def test_threshold_zero_disables_skipping():
    assert orun.resolve_deferral_threshold({"run": {"deferral_skip_threshold": 0}}) == 0


def test_threshold_tolerates_a_malformed_run_block():
    """Same posture as resolve_merge_settings: a non-dict block falls back to
    the default rather than raising inside run()."""
    assert orun.resolve_deferral_threshold({"run": "nope"}) == 3


# ---------------------------------------------------------------------------
# deferral_key / partition_deferrals / next_deferral_counts
# ---------------------------------------------------------------------------

_REPO = {"owner": "o", "name": "r"}


def test_deferral_key_matches_the_dismissed_gap_flags_shape():
    """One key shape across the whole state file. The runner already builds
    this string for gap-detector pr_ids at orchestrator_runner.py:1901."""
    assert orun.deferral_key(_REPO, 5) == "o/r#5"


def test_partition_leaves_an_under_threshold_pr_deferred():
    skipped, still = orun.partition_deferrals(
        [_pr(5, "e")], counts={"o/r#5": 2}, repo=_REPO, threshold=3
    )
    assert skipped == []
    assert [p["number"] for p in still] == [5]


def test_partition_skips_a_pr_that_has_already_hit_the_threshold():
    """'3 consecutive deferrals -> skipped on the 4th': the count reaching 3
    is what THIS run reads, so this run is the fourth."""
    skipped, still = orun.partition_deferrals(
        [_pr(5, "e")], counts={"o/r#5": 3}, repo=_REPO, threshold=3
    )
    assert [p["number"] for p in skipped] == [5]
    assert still == []


def test_partition_skips_above_the_threshold_too():
    skipped, _ = orun.partition_deferrals(
        [_pr(5, "e")], counts={"o/r#5": 9}, repo=_REPO, threshold=3
    )
    assert [p["number"] for p in skipped] == [5]


def test_partition_treats_an_unseen_pr_as_count_zero():
    skipped, still = orun.partition_deferrals(
        [_pr(5, "e")], counts={}, repo=_REPO, threshold=3
    )
    assert skipped == []
    assert [p["number"] for p in still] == [5]


def test_threshold_zero_never_skips():
    skipped, still = orun.partition_deferrals(
        [_pr(5, "e")], counts={"o/r#5": 99}, repo=_REPO, threshold=0
    )
    assert skipped == []
    assert [p["number"] for p in still] == [5]


def test_counts_increment_for_a_still_deferred_pr():
    out = orun.next_deferral_counts(
        {"o/r#5": 1},
        repo=_REPO,
        window_pr_numbers={5, 6},
        still_deferred_numbers={5},
    )
    assert out["o/r#5"] == 2


def test_counts_reset_when_a_pr_is_processed():
    """'Consecutive' means consecutive: a PR that got processed this run
    loses its history, so an intermittently-slow PR is never skipped."""
    out = orun.next_deferral_counts(
        {"o/r#5": 2},
        repo=_REPO,
        window_pr_numbers={5},
        still_deferred_numbers=set(),
    )
    assert "o/r#5" not in out


def test_counts_drop_a_skipped_pr():
    """A skipped PR is in the window and not still-deferred, so the same
    reset rule drops it — and it never returns to any window."""
    out = orun.next_deferral_counts(
        {"o/r#4": 3},
        repo=_REPO,
        window_pr_numbers={4},
        still_deferred_numbers=set(),
    )
    assert "o/r#4" not in out


def test_counts_carry_forward_a_pr_absent_from_this_window():
    """A window can shrink transiently when the source-collector degrades.
    Absence is not evidence the PR was processed, so its history survives."""
    out = orun.next_deferral_counts(
        {"o/r#9": 2},
        repo=_REPO,
        window_pr_numbers={5},
        still_deferred_numbers=set(),
    )
    assert out["o/r#9"] == 2


def test_counts_do_not_mutate_the_input():
    counts = {"o/r#5": 1}
    orun.next_deferral_counts(
        counts, repo=_REPO, window_pr_numbers={5}, still_deferred_numbers={5}
    )
    assert counts == {"o/r#5": 1}


# ---------------------------------------------------------------------------
# End-to-end: counting, the skip on run 4, and the quiescent-host invariant
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _fake_clock(values):
    it = iter(values)
    last = values[-1]
    return lambda: next(it, last)


def _fakes_with_prs(src: Path, dst: Path, prs: list[dict]) -> Path:
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        (dst / f.name).write_text(f.read_text())
    sc = json.loads((src / "fake_source_collector.json").read_text())
    sc["prs"] = prs
    (dst / "fake_source_collector.json").write_text(json.dumps(sc))
    return dst


def _seed_window(repo: Path, state_path: Path, n: int = 3) -> tuple[str, list[str]]:
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


def _window_prs(c1: str, c2: str, c3: str) -> list[dict]:
    return [
        {**_pr(1, c1), "files": [], "labels": [], "jira_keys": []},
        {**_pr(2, c2), "files": [], "labels": [], "jira_keys": []},
        {**_pr(3, c3), "files": [], "labels": [], "jira_keys": []},
    ]


def _read_current_run(state_path: Path) -> dict:
    return json.loads((state_path.parent / "current_run.json").read_text())[
        "current_run"
    ]


def test_a_deferred_pr_accumulates_a_count(tmp_path, init_host):
    """One truncated run: PR 3 is deferred, so its count goes 0 -> 1 and it
    is NOT skipped."""
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    _base, (c1, c2, c3) = _seed_window(repo, state_path)
    fakes = _fakes_with_prs(
        FAKES_MULTI,
        tmp_path.parent / f"fakes_cce140_count_{tmp_path.name}",
        _window_prs(c1, c2, c3),
    )
    rc = orun.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 50, 150]),  # admit 2 of 3
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    assert written["deferral_counts"] == {"unknown/unknown#3": 1}, written
    assert "skipped_prs" not in written
    assert written["last_successful_run"]["head_sha"] == c2


def test_a_pr_at_the_threshold_is_skipped_and_recorded(
    tmp_path, init_host, monkeypatch
):
    """Seed the count at 3, so THIS run is the fourth. The cursor walks past
    PR 3, a skipped_prs entry lands, and a NON-info_only partial reason names
    the PR.

    The window carries a fourth, non-PR commit so that walking to c3 is a
    statement about the cursor rather than about HEAD: with only three
    commits, `advance == c3` and `advance == head` are the same assertion and
    would hold even if forgiveness never ran.
    """
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    _base, (c1, c2, c3, c4) = _seed_window(repo, state_path, 4)
    state_path.write_text(
        json.dumps(
            {
                "version": "1",
                "last_successful_run": {"head_sha": _base},
                "deferral_counts": {"unknown/unknown#3": 3},
            }
        )
    )
    fakes = _fakes_with_prs(
        FAKES_MULTI,
        tmp_path.parent / f"fakes_cce140_skip_{tmp_path.name}",
        _window_prs(c1, c2, c3),
    )
    # Spy on the kwarg, because neither surface downstream of it can carry the
    # claim: `current_run.partial` was already flipped True by the admission
    # truncation several steps earlier, and the run's exit summary re-prints
    # every reason under a PARTIAL prefix regardless of how it was recorded.
    # Both read identical whether the skip is info_only or not (verified by
    # mutation -- forcing info_only=True left both green).
    _real_add_partial = orun.add_partial
    seen: list[tuple[str, bool]] = []

    def _spy(state, reason, *, info_only=False, degraded=False):
        # CCE-144 widened add_partial's signature; the spy must accept the new
        # kwarg and forward it, or every callsite that classifies a reason
        # raises TypeError through this monkeypatch.
        seen.append((reason, info_only))
        return _real_add_partial(state, reason, info_only=info_only, degraded=degraded)

    monkeypatch.setattr(orun, "add_partial", _spy)
    rc = orun.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 50, 150]),  # admit 2 of 3, defer PR 3
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    # The cursor forgives PR 3 and walks into the deferred tail -- but only as
    # far as PR 3's merge, never to HEAD.
    assert written["last_successful_run"]["head_sha"] == c3, written
    assert written["last_successful_run"]["head_sha"] != c4, written
    entries = written["skipped_prs"]
    assert [e["pr"] for e in entries] == ["unknown/unknown#3"]
    assert entries[0]["deferrals"] == 3
    assert entries[0]["skipped_at"]
    # The count is cleared: a skipped PR never returns.
    assert "unknown/unknown#3" not in written.get("deferral_counts", {})
    cr = _read_current_run(state_path)
    reason = [r for r in cr["partial_reasons"] if r.startswith("deferral_skip:")]
    assert len(reason) == 1, cr["partial_reasons"]
    assert "unknown/unknown#3" in reason[0]
    recorded = [(r, i) for r, i in seen if r.startswith("deferral_skip:")]
    assert len(recorded) == 1, seen
    assert recorded[0][1] is False, (
        "the skip reason must NOT be info_only -- it is a recorded content "
        f"loss and it has to reach the notifier digest: {recorded[0]}"
    )


def test_a_skipped_pr_names_the_page_it_owed(tmp_path, init_host):
    """Authoring-truncation skip: the reason and the record name the pages.
    All three PRs share every page batch (the summarizer fixture is a single
    static file), so all three are over threshold and all three are skipped."""
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    _base, (c1, c2, c3) = _seed_window(repo, state_path)
    fakes = _fakes_with_prs(
        FAKES_MULTI,
        tmp_path.parent / f"fakes_cce140_pages_{tmp_path.name}",
        _window_prs(c1, c2, c3),
    )
    summ = json.loads((fakes / "fake_pr_summarizer.json").read_text())
    summ["doc_targets"] = [
        {"lens": "core", "action": "create", "page_hint": f"connectors/{n}.md"}
        for n in ("alpha", "beta", "gamma")
    ]
    (fakes / "fake_pr_summarizer.json").write_text(json.dumps(summ))
    state_path.write_text(
        json.dumps(
            {
                "version": "1",
                "last_successful_run": {"head_sha": _base},
                "deferral_counts": {
                    "unknown/unknown#1": 3,
                    "unknown/unknown#2": 3,
                    "unknown/unknown#3": 3,
                },
            }
        )
    )
    rc = orun.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        # admission 10,20 (all 3 admitted); authoring batch-1 gate at 150.
        now_monotonic=_fake_clock([0, 10, 20, 150]),
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    entries = {e["pr"]: e for e in written["skipped_prs"]}
    assert set(entries) == {
        "unknown/unknown#1",
        "unknown/unknown#2",
        "unknown/unknown#3",
    }
    assert entries["unknown/unknown#1"]["pages"] == [
        "core/connectors/beta.md",
        "core/connectors/gamma.md",
    ]
    cr = _read_current_run(state_path)
    assert any(
        r.startswith("deferral_skip:") and "core/connectors/beta.md" in r
        for r in cr["partial_reasons"]
    ), cr["partial_reasons"]


def test_threshold_zero_never_skips_end_to_end(tmp_path, init_host):
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    config_path = tmp_path / ".engineering-docs-agent" / "config.yml"
    config_path.write_text(
        config_path.read_text() + "\nrun:\n  deferral_skip_threshold: 0\n"
    )
    _base, (c1, c2, c3) = _seed_window(repo, state_path)
    state_path.write_text(
        json.dumps(
            {
                "version": "1",
                "last_successful_run": {"head_sha": _base},
                "deferral_counts": {"unknown/unknown#3": 99},
            }
        )
    )
    fakes = _fakes_with_prs(
        FAKES_MULTI,
        tmp_path.parent / f"fakes_cce140_zero_{tmp_path.name}",
        _window_prs(c1, c2, c3),
    )
    rc = orun.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 50, 150]),
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    assert "skipped_prs" not in written
    assert written["last_successful_run"]["head_sha"] == c2


def test_a_clean_run_writes_neither_new_key(tmp_path, init_host):
    """The quiescent-host invariant: nothing deferred, nothing skipped, so
    state.json gains neither key and a host that never truncates sees no
    change at all."""
    state_path = init_host({"version": "1", "last_successful_run": {}})
    rc = orun.run(tmp_path, dry_run_dir=FAKES_MULTI, no_pr=True, time_budget_seconds=0)
    assert rc == 0
    written = json.loads(state_path.read_text())
    assert "skipped_prs" not in written
    assert "deferral_counts" not in written


# ---------------------------------------------------------------------------
# Regressions found by independent review of the CCE-140 implementation
# ---------------------------------------------------------------------------


def _seed_window4(repo: Path, state_path: Path) -> tuple[str, list[str]]:
    """Four commits: three PR merges plus a trailing non-PR commit, so the
    newest PR sha is NEVER equal to HEAD. Without c4, `advance == c3` and
    `advance == head` are the same statement and a cursor assertion passes
    vacuously even if the cursor machinery were bypassed entirely."""
    return _seed_window(repo, state_path, 4)


def test_a_lint_blocked_pr_is_held_out_of_the_cursor(tmp_path, init_host):
    """A page that lint reverted did NOT land, so its PRs are still owed a
    page and the baseline must not advance past them.

    Before this fix `held_back` was built only from the two TIME-truncation
    sources, so any other way a batch could fail — a reverted lint block, a
    failed page-author dispatch, an unknown lens, an unsafe path — left the PR
    out of `held_back` entirely. The cursor then walked straight past it and
    reported the advance as cursor-backed, which under CCE-140 is a merge.
    That is the silent-loss bug the whole track exists to close, narrowed to
    the failure modes nobody enumerated.

    Admission truncation (not authoring truncation) is what makes this test
    discriminating: it puts the run on the cursor path while leaving the
    authoring loop free to run to completion and fail on its own terms.
    """
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (c1, c2, _c3, c4) = _seed_window4(repo, state_path)
    fakes = _fakes_with_prs(
        FAKES_MULTI,
        tmp_path.parent / f"fakes_cce140_lintblock_{tmp_path.name}",
        _window_prs(c1, c2, _c3),
    )
    # One doc_target, so the authoring loop never trips its own i > 0 gate.
    summ = json.loads((fakes / "fake_pr_summarizer.json").read_text())
    summ["doc_targets"] = [
        {"lens": "core", "action": "create", "page_hint": "connectors/foo.md"}
    ]
    (fakes / "fake_pr_summarizer.json").write_text(json.dumps(summ))
    # ...and that one page is lint-blocked, so the batch never lands.
    (fakes / "fake_content_validator.json").write_text(
        (FAKES_BLOCK / "fake_content_validator.json").read_text()
    )
    rc = orun.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 50, 150]),  # admit 2 of 3, defer PR 3
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    head = _git(repo, "rev-parse", "HEAD")
    assert head == c4
    assert advance != head, written["last_successful_run"]
    # PR 1 and PR 2 were admitted, but their page was reverted by lint, so
    # they are NOT done. The walk must stop at the oldest of them, leaving the
    # baseline untouched. Before the fix this asserted c2 — an advance past
    # two PRs whose page had just been deleted.
    assert advance == base, written["last_successful_run"]
    assert orun._LAST_ADVANCE_CURSOR_BACKED is False, (
        "an advance that crosses a lint-reverted PR must never be reported as "
        "cursor-backed -- that flag is what authorises the merge"
    )


def test_a_clean_run_clears_a_prior_deferral_count(tmp_path, init_host):
    """'Consecutive' means consecutive, and the run that PROCESSES a PR is
    usually the clean one.

    The prune was gated on `time_truncated`, so a clean run never reset
    anything: a truncated/clean/truncated alternation accumulated toward a
    skip for a PR the pipeline handled successfully every other night, and
    counts for PRs long past the baseline stayed in state.json forever. The
    pure helper `next_deferral_counts` always had the right rule -- the
    WIRING is what broke the promise, which is why its own unit test passed
    throughout.
    """
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (c1, c2, c3) = _seed_window(repo, state_path)
    state_path.write_text(
        json.dumps(
            {
                "version": "1",
                "last_successful_run": {"head_sha": base},
                # PR 3 was deferred on an earlier run, and a stale entry for a
                # PR that has long since left the window.
                "deferral_counts": {"unknown/unknown#3": 2, "unknown/unknown#99": 1},
            }
        )
    )
    fakes = _fakes_with_prs(
        FAKES_MULTI,
        tmp_path.parent / f"fakes_cce140_clean_{tmp_path.name}",
        _window_prs(c1, c2, c3),
    )
    # No budget: nothing truncates, every PR is processed.
    rc = orun.run(repo, dry_run_dir=fakes, no_pr=True, time_budget_seconds=0)
    assert rc == 0
    written = json.loads(state_path.read_text())
    counts = written.get("deferral_counts", {})
    assert "unknown/unknown#3" not in counts, (
        "a clean run processed PR 3, so its consecutive-deferral history must "
        f"be cleared, not carried forward: {counts}"
    )
    # A PR absent from this window keeps its history — absence is not evidence
    # it was processed (the window can shrink when the collector degrades).
    assert counts.get("unknown/unknown#99") == 1, counts


def test_no_skip_is_recorded_for_a_pr_the_cursor_never_crosses(tmp_path, init_host):
    """Forgiveness is prefix-bounded, so the alarm must be too.

    `partition_deferrals` is order-independent by design, but the EFFECT of a
    skip is not: when a forgiven PR sits behind an older still-deferred one,
    the cursor never passes it and nothing is actually abandoned. Recording it
    anyway put a false entry in `skipped_prs` -- which is append-only and
    deduped by `pr`, so it could never be corrected -- and fired a
    non-info_only alarm claiming a content loss that did not happen.
    """
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (c1, c2, c3) = _seed_window(repo, state_path)
    state_path.write_text(
        json.dumps(
            {
                "version": "1",
                "last_successful_run": {"head_sha": base},
                # PR 3 is over threshold and would be forgiven; PR 2 is not.
                "deferral_counts": {"unknown/unknown#3": 3},
            }
        )
    )
    fakes = _fakes_with_prs(
        FAKES_MULTI,
        tmp_path.parent / f"fakes_cce140_nocross_{tmp_path.name}",
        _window_prs(c1, c2, c3),
    )
    # Admit only PR 1; PR 2 AND PR 3 are deferred. PR 2 is the older unfinished
    # PR, so the walk stops before it and never reaches the forgiven PR 3.
    rc = orun.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 150]),
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    assert "skipped_prs" not in written, (
        "PR 3 was forgiven but the cursor stopped at PR 2 and never crossed "
        f"it, so nothing was abandoned and nothing may be recorded: {written}"
    )
    cr = _read_current_run(state_path)
    assert not [r for r in cr["partial_reasons"] if r.startswith("deferral_skip:")], cr[
        "partial_reasons"
    ]


def test_the_baseline_stops_at_the_last_pr_whose_pages_all_landed(tmp_path, init_host):
    """CCE-140 Decision 2's POSITIVE case, which nothing covered end to end.

    Every prior integration test drives a window whose PRs either all land or
    all fail, because one static summarizer fixture is replayed for every PR:
    each page batch then contains every admitted PR, so the cursor walk can
    only return the whole prefix or nothing. Under that constraint the rule
    this track exists to enforce -- "advance only to the last PR whose pages
    ALL landed" -- has no observable content, and the three rewritten Track A
    tests collapsing from `advance == c3` to `advance == base` is what that
    looks like from the outside.

    Per-PR summarizer fixtures make the mixed case expressible. PR 1 owns
    alpha.md and PR 2 owns beta.md; beta lint-blocks and is reverted, so PR 2
    is owed a page and PR 3 was never admitted. The walk must stop AT PR 1 --
    not before it, which would forfeit an earned advance, and not past it,
    which is the silent loss. Both neighbours are asserted, because a test
    that only pins the upper bound passes on a run that advanced nothing.
    """
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (c1, c2, c3, c4) = _seed_window(repo, state_path, 4)
    fakes = _fakes_with_prs(
        FAKES_MULTI,
        tmp_path.parent / f"fakes_cce140_mixed_{tmp_path.name}",
        _window_prs(c1, c2, c3),
    )
    summ = json.loads((FAKES_MULTI / "fake_pr_summarizer.json").read_text())
    for number, hint in ((1, "alpha.md"), (2, "beta.md"), (3, "gamma.md")):
        (fakes / f"fake_pr_summarizer__pr{number}.json").write_text(
            json.dumps(
                {
                    **summ,
                    "doc_targets": [
                        {
                            "lens": "core",
                            "action": "create",
                            "page_hint": f"connectors/{hint}",
                        }
                    ],
                }
            )
        )
    # Only beta is rejected. The revert is keyed by path, so reporting it on
    # every validation pass reverts exactly the one batch that owns it.
    (fakes / "fake_content_validator.json").write_text(
        json.dumps(
            {
                "passed": [],
                "failed": [
                    {
                        "path": "docs/site-src/core/connectors/beta.md",
                        "rule": "frontmatter_schema",
                        "severity": "block",
                        "message": "missing required field: status",
                    }
                ],
            }
        )
    )
    rc = orun.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 50, 150]),  # admit PR 1 and PR 2, defer PR 3
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    assert (repo / "docs/site-src/core/connectors/alpha.md").exists(), (
        "PR 1's page must have landed, or the advance below is not an EARNED "
        "one and this test is pinning the all-fail case again"
    )
    assert not (repo / "docs/site-src/core/connectors/beta.md").exists(), (
        "PR 2's page must have been reverted by the lint block"
    )
    assert advance == c1, written["last_successful_run"]
    assert advance != base, "PR 1 finished; refusing its advance forfeits work"
    assert advance not in (c2, c3, c4), (
        "PR 2 is owed a page and PR 3 was never admitted; advancing past "
        "either strands it below the baseline forever"
    )
    assert orun._LAST_ADVANCE_CURSOR_BACKED is True


def test_a_fully_forgiven_window_may_be_cursor_backed_at_head(tmp_path, init_host):
    """`advance_cursor_backed` is not a synonym for "advance stayed below
    HEAD", and a future reader must not "fix" it into one.

    When every deferred PR has been forgiven by the skip hatch, the walk
    covers the whole window and the cursor lands on HEAD itself -- so a
    cursor-backed advance and a full-HEAD advance coincide, which reads at a
    glance like the exact leak the CCE-140 gate exists to stop. It is not: the
    forgiven PRs are in `skipped_prs` and named in a non-info partial reason,
    so nothing the baseline crossed is unaccounted for. The invariant is "the
    baseline moved only past PRs that landed or were deliberately abandoned",
    not "the baseline stayed below HEAD" -- and this run is therefore
    legitimately eligible to merge.

    Deliberately seeds a THREE-commit window (no trailing c4) so cursor and
    HEAD are the same sha. Every other test in this file avoids that on
    purpose; this one is where it is the point.
    """
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (c1, c2, c3) = _seed_window(repo, state_path, 3)
    state_path.write_text(
        json.dumps(
            {
                "version": "1",
                "last_successful_run": {"head_sha": base},
                "deferral_counts": {"unknown/unknown#3": 3},
            }
        )
    )
    fakes = _fakes_with_prs(
        FAKES_MULTI,
        tmp_path.parent / f"fakes_cce140_forgiven_{tmp_path.name}",
        _window_prs(c1, c2, c3),
    )
    rc = orun.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 50, 150]),  # admit 2 of 3, defer PR 3
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    head = _git(repo, "rev-parse", "HEAD")
    assert head == c3, "fixture precondition: the newest PR merge IS HEAD here"
    assert written["last_successful_run"]["head_sha"] == head, written
    assert orun._LAST_ADVANCE_CURSOR_BACKED is True
    # What makes it honest rather than a leak.
    assert [e["pr"] for e in written["skipped_prs"]] == ["unknown/unknown#3"]
