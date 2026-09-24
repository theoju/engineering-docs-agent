# tests/orchestrator/test_window_cap.py
"""CCE-169: the pre-admission PR-count window cap.

The review window had no upper bound, so a stalled baseline widened by a day
every night and each run finished a smaller fraction of it. These tests pin the
cap itself (this file's first half) and the third-category routing that keeps a
capped PR out of the deferral machinery while still stopping the cursor at the
cap boundary (second half, added in Task 2).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as orun  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from test_cursor_backed_merge import _install_fake_gh  # noqa: E402

FAKES_MULTI = Path(__file__).parent / "fakes_multi"


# ---------------------------------------------------------------------------
# resolve_window_cap
# ---------------------------------------------------------------------------


def test_window_cap_defaults_to_ten():
    """The default is the whole point of CCE-169 and NOTHING else can catch it.

    Every `fake_source_collector.json` in the tree tops out at 3 PRs, and each
    helper that rewrites them keeps 3 — so `len(prs) > cap` is False for any
    default >= 3 and no end-to-end test can observe the value. An implementer
    who writes `int(run_cfg.get("window_pr_cap") or 0)` ships the rejected
    off-by-default alternative with every other test green.
    """
    assert orun.DEFAULT_WINDOW_PR_CAP == 10
    assert orun.resolve_window_cap({}) == 10
    assert orun.resolve_window_cap({"run": {}}) == 10


def test_window_cap_reads_the_config_key():
    assert orun.resolve_window_cap({"run": {"window_pr_cap": 25}}) == 25


def test_window_cap_zero_is_unlimited():
    """`0` is the advertised opt-out, so it must survive as 0.

    This is why the resolver tests `val is None` and not truthiness: `or
    DEFAULT` would silently rewrite an explicit 0 back to 10.
    """
    assert orun.resolve_window_cap({"run": {"window_pr_cap": 0}}) == 0


def test_window_cap_tolerates_a_malformed_run_block():
    """`_run_cfg` exists because `config.get("run") or {}` raises
    AttributeError on `run: "nonsense"`. Mirror its siblings, do not reinvent.
    """
    assert orun.resolve_window_cap({"run": "nonsense"}) == 10
    assert orun.resolve_window_cap({"run": None}) == 10


# ---------------------------------------------------------------------------
# the cut: third-category routing
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


_CURSOR_FIELDS = ("admitted", "deferred", "capped", "held_back", "skipped")


def _cursor_line(capsys) -> dict[str, list[str]]:
    """Parse the run's `cursor:` line into its five PR-number lists.

    THE ONLY SIGNAL IN THE RUN THAT OBSERVES ADMISSION. Every other assertion
    in this file measures downstream bookkeeping -- watermark sha, reason
    literal, deferral counts, `pr_merge` -- and all of it is produced from
    `window_capped`, which a post-admission cap populates identically to a
    pre-admission one. Delete `prs = prs[:_window_cap]` while leaving
    `window_capped` and the reason's saved pre-cut total intact and this whole
    file stays green while `pr-summarizer` is dispatched for every PR in the
    window: the run does all N PRs' work every night, which is the unbounded
    work CCE-169 exists to stop.

    Parsed rather than asserted as a substring so a test names the set it
    expects, not a rendering of it.
    """
    err = capsys.readouterr().err
    lines = [ln for ln in err.splitlines() if ln.startswith("cursor: admitted=[")]
    assert lines, f"no `cursor:` line was emitted; stderr tail={err[-2000:]!r}"
    line = lines[-1]
    out: dict[str, list[str]] = {}
    for field in _CURSOR_FIELDS:
        m = re.search(rf"\b{field}=\[([^\]]*)\]", line)
        assert m, f"`{field}=[...]` missing from cursor line: {line!r}"
        body = m.group(1).strip()
        out[field] = [] if body == "none" else [t.strip() for t in body.split(",")]
    return out


def _seed_capped_host(
    tmp_path, init_host, base_config_yaml, *, cap, state_extra=None, unanchored=()
):
    """Real git window of three PR merges plus a trailing non-PR commit.

    Returns (state_path, base, [c1, c2, c3], fakes).

    `unanchored` is a set of PR numbers whose `merge_sha` key is REMOVED from
    the source-collector payload after the shas are assigned -- the PR still
    merged at its commit, the collector just did not report where.
    `merge_sha` is not in `required` in `agents/schemas/source_collector.schema.json`,
    and `_clip_prs_to_window` deliberately KEEPS such a PR, so this is a shape
    production can hand the cut.

    c4 exists so the newest PR merge is never HEAD: without it `advance == c2`
    and `advance != head` stop being independent statements. Copied from
    test_cursor_backed_merge._seed_merge_host for that reason.

    The cap is set by REPLACING a line of the shared config, never by appending
    a second `run:` block -- CONFIG_YAML already carries `run:` with
    `time_budget_seconds: 2100`, and PyYAML keeps only the LAST duplicate key,
    so an append would silently delete the budget and change what the test
    measures.
    """
    cfg = base_config_yaml.replace(
        "  time_budget_seconds: 2100",
        f"  time_budget_seconds: 2100\n  window_pr_cap: {cap}",
    )
    assert "window_pr_cap" in cfg, "config replacement anchor drifted"
    seeded = {"version": "1", "last_successful_run": {"head_sha": "seed"}}
    seeded.update(state_extra or {})
    state_path = init_host(seeded, config_yaml=cfg)
    repo = tmp_path
    base = _git(repo, "rev-parse", "HEAD")
    shas = []
    for i in range(1, 5):
        (repo / "f.txt").write_text(f"c{i}")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    seeded["last_successful_run"] = {"head_sha": base}
    state_path.write_text(json.dumps(seeded))
    fakes = tmp_path / "fakes_cap"
    fakes.mkdir(parents=True, exist_ok=True)
    for f in FAKES_MULTI.iterdir():
        (fakes / f.name).write_text(f.read_text())
    sc = json.loads((FAKES_MULTI / "fake_source_collector.json").read_text())
    for pr, sha in zip(sc["prs"], shas[:3]):
        pr["merge_sha"] = sha
    for pr in sc["prs"]:
        if pr["number"] in set(unanchored):
            pr.pop("merge_sha", None)
    (fakes / "fake_source_collector.json").write_text(json.dumps(sc))
    return state_path, base, shas[:3], fakes


def test_a_capped_run_advances_to_the_cap_boundary_and_says_so(
    tmp_path, init_host, base_config_yaml, read_current_run, capsys
):
    """THE CCE-151 REGRESSION GUARD, and the most important test in this file.

    A bare `prs = prs[:cap]` puts capped PRs in neither `deferred_pages_by_pr`
    nor `admission_deferred`, so `held_back` is empty, `time_truncated` is
    False, CCE-151's walk is never entered, and control reaches the `else`
    branch where `advance_sha = current_run.head_sha` -- FULL WINDOW HEAD. The
    run would document 2 PRs and advance past all 3, losing the third
    permanently and silently.

    The reason must be asserted PRESENT, by list membership on the fully
    rendered line. Nothing else here distinguishes the right label from a wrong
    one or from NO label at all, and emitting nothing is the dangerous variant
    because it passes everything else: on a healthy capped run CCE-151's walk
    takes its `if ok:` branch, which sets `advance_sha` and
    `advance_cursor_backed` WITHOUT calling `add_partial`, so this site is the
    run's only signal that any PR was held.

    THE ADMISSION ASSERTION IS SEPARATE AND ALSO REQUIRED. Everything above
    measures downstream bookkeeping, all of it produced from `window_capped` --
    so a POST-admission cap (compute `window_capped`, keep it out of
    `window_prs`, render the reason from a saved pre-cut total, but never
    truncate `prs`) satisfies every one of them while `pr-summarizer` is
    dispatched for all three PRs. The run would do all N PRs' work every night
    and nothing would notice, which is the unbounded work CCE-169 exists to
    stop. `_cursor_line` is the only observation of admission itself.
    """
    state_path, base, (c1, c2, c3), fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=2
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    # Admission itself. The ONLY assertion in this file that a post-admission
    # cap cannot satisfy -- see the docstring.
    cur = _cursor_line(capsys)
    assert cur["admitted"] == ["1", "2"], cur
    assert cur["capped"] == ["3"], cur
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    assert advance == c2, written["last_successful_run"]
    assert advance != _git(tmp_path, "rev-parse", "HEAD")
    cr = read_current_run(state_path)
    assert (
        "held_back_window_capped: 1 of 3 PRs held for a later run (cap 2)"
        in cr["partial_reasons"]
    ), cr["partial_reasons"]


def test_a_capped_pr_does_not_accrue_a_deferral_count(
    tmp_path, init_host, base_config_yaml
):
    """Row 2 of the routing table. The danger is ERASURE, not over-counting.

    `next_deferral_counts` pops the entry for any in-window PR that is not in
    `still_deferred_numbers`, and a capped PR can never be in that set. So a
    capped PR left inside `window_prs` has its genuine history DELETED every
    night it waits, permanently disarming the CCE-140 skip hatch for it.
    """
    state_path, base, (c1, c2, c3), fakes = _seed_capped_host(
        tmp_path,
        init_host,
        base_config_yaml,
        cap=2,
        state_extra={"deferral_counts": {"unknown/unknown#3": 2}},
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    written = json.loads(state_path.read_text())
    assert written.get("deferral_counts", {}).get("unknown/unknown#3") == 2, (
        written.get("deferral_counts")
    )


def test_a_capped_pr_at_threshold_is_not_abandoned(
    tmp_path, init_host, base_config_yaml
):
    """Row 3. The skip hatch must never abandon a PR the run did not attempt.

    Threshold is 3 by default, so a count of 3 is exactly at it. The PR is only
    safe because it never reaches `_deferred_all` -- `partition_deferrals` is
    order-independent and would skip it on sight.

    THE ADVANCE ASSERTION IS THE ONE THAT DISCRIMINATES. The `skipped_prs`
    assertion below does not, and it is kept only to document intent. Trace the
    counterfactual where a future change puts capped PRs into `_deferred_all`:
    `partition_deferrals` skips PR 3, so `skipped_numbers == {3}` and
    `held_back == ({3}) - {3} == set()` -- the subtraction the cut's comment
    calls "a no-op for them" stops being one. `time_truncated` is False, so
    control takes the `else` branch to full window HEAD, and `cursor_prs` is
    `[1, 2]`, so the `if _skipped_prs:` loop filters PR 3 out on
    `not in _crossed` and appends NO record and NO `deferral_skip` reason.
    `merge_skipped_pr_records(state, [])` then returns early and the
    `skipped_prs` key is never even created. The record assertion passes on an
    empty list while the baseline sails past PR 3's merge commit and strands it
    outside every future window, silently, with `rc == 0` -- the exact loss this
    test is named for. Only the baseline itself distinguishes the two worlds:
    correct -> `held_back == {3}` -> the walk runs -> c2; broken -> c4.
    """
    state_path, base, (c1, c2, c3), fakes = _seed_capped_host(
        tmp_path,
        init_host,
        base_config_yaml,
        cap=2,
        state_extra={"deferral_counts": {"unknown/unknown#3": 3}},
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    written = json.loads(state_path.read_text())
    # Documents intent; does NOT discriminate -- see the docstring. Ordered
    # first deliberately, so that running this test against the counterfactual
    # shows it passing while the assertion below fails.
    skipped = written.get("skipped_prs", [])
    assert not [s for s in skipped if "#3" in json.dumps(s)], skipped
    # The assertion that discriminates.
    assert written["last_successful_run"]["head_sha"] == c2, written[
        "last_successful_run"
    ]


def test_window_pr_cap_zero_is_a_true_no_op(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """The advertised opt-out. No reason, and the advance reaches the FULL
    WINDOW HEAD exactly as an uncapped run would.

    The compared value is `git rev-parse HEAD` (commit c4), not c3. With
    nothing held back, CCE-151's walk is not entered and the `else` branch
    assigns `advance_sha = state["current_run"]["head_sha"]`, which is the
    repo HEAD — and the fixture deliberately puts a trailing NON-PR commit
    above the newest PR merge, so HEAD is c4. Asserting c3 here would be
    asserting a cursor-backed advance on a run that never took one, and it is
    the difference between "the cap did nothing" and "something else stopped
    the cursor one commit short."
    """
    state_path, base, (c1, c2, c3), fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=0
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    cr = read_current_run(state_path)
    assert not [r for r in cr["partial_reasons"] if "window_capped" in r], cr[
        "partial_reasons"
    ]
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == _git(
        tmp_path, "rev-parse", "HEAD"
    ), written["last_successful_run"]
    assert written["last_successful_run"]["head_sha"] != c2, (
        "cap 0 must not stop at the cap-2 boundary"
    )


# ---------------------------------------------------------------------------
# the cap must only hold back PRs a later window can re-anchor
# ---------------------------------------------------------------------------


def test_an_unanchored_pr_is_never_capped(
    tmp_path, init_host, base_config_yaml, capsys
):
    """A capped PR with no merge_sha is stranded permanently -- a REGRESSION
    CCE-169 introduces, and the coupling is structural, not coincidental.

    `_order_prs_oldest_first` keys a PR with a missing merge_sha as
    `big = len(order) + 1`, so it sorts LAST; the cap takes the TAIL. Whenever
    the cap fires, an unanchored PR is GUARANTEED to be in the capped slice.

    From there it enters `held_back` but NEITHER writer of `_deferred_all`, so
    it is absent from `still_deferred` and the
    `..._no_advance_unanchored_deferred` guard -- whose entire purpose is to
    refuse advancing past a PR that cannot be re-anchored -- never sees it. The
    cursor walk covers only admitted PRs, yields a valid cursor,
    `advance_cursor_backed=True`, and the baseline advances past the unanchored
    PR's REAL merge commit. The next window is `cursor..HEAD`, so that PR is
    never returned again: permanently undocumented, rc 0, and the run
    auto-merges.

    Pre-CCE-169 there was no such path. Uncapped, the PR was admitted and
    documented; time-truncated, it entered `admission_deferred` ->
    `still_deferred` and the guard froze the baseline.

    Here PR 2 truly merged at c2 and is returned without a merge_sha, so the
    window order is [1, 3, 2] and cap 2 puts it in the capped tail.
    """
    state_path, base, (c1, c2, c3), fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=2, unanchored={2}
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    cur = _cursor_line(capsys)
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    next_window = set(_git(tmp_path, "rev-list", f"{advance}..HEAD").split())
    # THE INVARIANT, stated as the harm rather than as the mechanism: a PR the
    # run did not admit must still be inside the window the NEXT run reads.
    assert "2" in cur["admitted"] or c2 in next_window, (
        f"PR 2 merged at {c2[:8]} and was neither admitted nor left in the next "
        f"window ({advance[:8]}..HEAD): it is outside every future window and "
        f"is permanently undocumented. admitted={cur['admitted']} "
        f"capped={cur['capped']} held_back={cur['held_back']}"
    )
    # And the mechanism, so a future reader sees WHICH of the two arms holds.
    assert cur["capped"] == [], cur


def test_the_cap_still_holds_back_an_anchored_pr_beside_an_unanchored_one(
    tmp_path, init_host, base_config_yaml, read_current_run, capsys
):
    """The exemption is for unanchored PRs only, not a disabled cap.

    Cap 1 against window order [1, 3, 2] puts BOTH 3 (anchored, at c3) and 2
    (unanchored) in the capped tail. Only 2 is pulled back; 3 stays capped, so
    the reason still fires and the cursor still stops at the cap boundary --
    here c1, the newest admitted PR that carries a merge_sha, since
    `_last_processed_merge_sha` scans from the end past PR 2.
    """
    state_path, base, (c1, c2, c3), fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=1, unanchored={2}
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    cur = _cursor_line(capsys)
    assert sorted(cur["admitted"]) == ["1", "2"], cur
    assert cur["capped"] == ["3"], cur
    cr = read_current_run(state_path)
    assert (
        "held_back_window_capped: 1 of 3 PRs held for a later run (cap 1)"
        in cr["partial_reasons"]
    ), cr["partial_reasons"]
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    assert advance == c1, written["last_successful_run"]
    assert c3 in set(_git(tmp_path, "rev-list", f"{advance}..HEAD").split())


def test_a_sub_cap_window_is_untouched(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """Three PRs against a cap of 10 -- `window_capped` stays empty, nothing is
    added to `held_back`, and the code path is today's.

    Same HEAD-vs-c3 correction as the cap-0 test above: an untruncated run
    holding nothing back advances to `git rev-parse HEAD` (c4), never to the
    newest PR merge.
    """
    state_path, base, (c1, c2, c3), fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=10
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    cr = read_current_run(state_path)
    assert not [r for r in cr["partial_reasons"] if "window_capped" in r], cr[
        "partial_reasons"
    ]
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == _git(
        tmp_path, "rev-parse", "HEAD"
    ), written["last_successful_run"]
    assert written["last_successful_run"]["head_sha"] != c2, (
        "a sub-cap window must not stop at any cap boundary"
    )


# ---------------------------------------------------------------------------
# auto-merge, end to end
# ---------------------------------------------------------------------------


def test_a_capped_run_still_auto_merges(
    tmp_path, monkeypatch, init_host, base_config_yaml, read_current_run
):
    """If a capped run cannot merge, the cap accomplishes nothing.

    The whole convergence argument is: capped PRs enter `held_back` -> CCE-151's
    walk runs -> `advance_cursor_backed=True` -> CCE-140's carve-out
    (`if partial and not advance_cursor_backed`) permits the auto-merge ->
    state.json is promoted to the default branch -> the baseline advances -> the
    next run takes the next `cap` PRs. Break the merge and the baseline never
    moves, so the cap turns a compounding stall into a permanent one.

    `pr_merge` in the call log is the assertion. Nothing weaker distinguishes
    "the gate opened" from "the gate opened and something downstream closed it":
    _maybe_auto_merge returns skip("merge_vetoed") and skip("blind_run") BEFORE
    skip("partial_run"), so asserting the absence of the last one passes for a
    run vetoed by the wrong list or misclassified blind.
    """
    state_path, base, (c1, c2, c3), fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=2
    )
    # Safe to APPEND: unlike `run:`, the shared CONFIG_YAML has no `merge:`
    # block, so there is no duplicate key for PyYAML to silently drop. Same
    # append test_cursor_backed_merge._seed_merge_host performs.
    config_path = tmp_path / ".engineering-docs-agent" / "config.yml"
    config_path.write_text(
        config_path.read_text()
        + "\nmerge:\n  policy: auto\n  checks_grace_seconds: 0\n"
        + "  checks_timeout_seconds: 0\n"
    )
    gh = _install_fake_gh(monkeypatch)
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=False)
    assert rc == 0
    cr = read_current_run(state_path)
    # Preconditions -- without these the merge assertion could pass for the
    # wrong reason (a run that is not partial at all reaches the merge path
    # under today's rules too).
    assert cr["partial"] is True, cr
    assert [
        r for r in cr["partial_reasons"] if r.startswith("held_back_window_capped:")
    ], cr["partial_reasons"]
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == c2, written[
        "last_successful_run"
    ]
    fake = gh["gh"]
    assert [c for c in fake.calls if c[0] == "pr_merge"], (
        "a capped run is cursor-backed and must auto-merge; if it does not, the "
        "baseline never advances and the cap converts a compounding stall into "
        f"a permanent one. reasons={cr['partial_reasons']} calls={fake.calls}"
    )
