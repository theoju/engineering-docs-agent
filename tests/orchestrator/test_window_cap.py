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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as orun  # noqa: E402

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


def _seed_capped_host(tmp_path, init_host, base_config_yaml, *, cap, state_extra=None):
    """Real git window of three PR merges plus a trailing non-PR commit.

    Returns (state_path, base, [c1, c2, c3], fakes).

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
    (fakes / "fake_source_collector.json").write_text(json.dumps(sc))
    return state_path, base, shas[:3], fakes


def test_a_capped_run_advances_to_the_cap_boundary_and_says_so(
    tmp_path, init_host, base_config_yaml, read_current_run
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
    """
    state_path, base, (c1, c2, c3), fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=2
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
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
