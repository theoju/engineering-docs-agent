# tests/orchestrator/test_pr_boundary_authoring_cut.py
"""CCE-152: the authoring cut lands on a PR boundary, so a truncated run
still leaves a COMPLETE prefix of PRs and the baseline can advance.

The bug this pins is a starvation, not a mis-ordering. ``per_target`` is a
dict built by iterating ``prs`` oldest-first (orchestrator_runner.py:1686),
and ``setdefault`` never re-positions an existing key, so the batch list is
already grouped by the oldest PR that references each page — group(PR1)
first, then group(PR2), and so on.

What was missing is where the deadline may cut that list. CCE-114's guard
fires at any batch index, and its at-least-one-progress escape is ``i > 0``
— per BATCH. So a run whose OLDEST PR fans out to more pages than the budget
can author cuts inside group(PR1) every single time. PR1 is never complete,
``held_back`` contains it, ``advance_cursor_list`` breaks at index 0, and
``_last_processed_merge_sha([])`` returns None. The host reported exactly
that for 20.6 days: four nightlies authoring 1-5 of ~75 batches, two of them
authoring the identical four pages, and ``no_advance_no_cursor`` each time.

Both end-to-end tests here need a window whose PRs emit DIFFERENT doc
targets, which is what the ``fake_pr_summarizer__pr<N>.json`` per-PR fixtures
exist for — with the shared fixture every PR contributes to every batch, so
the whole window is one group and a boundary can never occur.
"""

from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import orchestrator_runner as runner  # noqa: E402

FAKES_MULTI = Path(__file__).parent / "fakes_multi"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _fake_clock(values):
    """Monotonic values in order, then repeating the last. The first value is
    consumed by the deadline calc (same helper as test_time_budget.py)."""
    it = iter(values)
    last = values[-1]
    return lambda: next(it, last)


def _seed_window(repo: Path, state_path: Path, n: int) -> tuple[str, list[str]]:
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


def _fakes(dst: Path, prs: list[dict], targets_by_pr: dict[int, list[str]]) -> Path:
    """Copy fakes_multi, override the collector's PRs, and give each PR its OWN
    summarizer fixture so the PRs emit different doc targets.

    ``targets_by_pr`` maps a PR number to the page hints it should claim. Every
    hint becomes one (lens, page_hint) batch; a hint listed under two PRs is one
    shared batch owned by the older of them.
    """
    dst.mkdir(parents=True, exist_ok=True)
    for f in FAKES_MULTI.iterdir():
        (dst / f.name).write_text(f.read_text())
    sc = json.loads((FAKES_MULTI / "fake_source_collector.json").read_text())
    sc["prs"] = prs
    (dst / "fake_source_collector.json").write_text(json.dumps(sc))
    base_summary = json.loads((FAKES_MULTI / "fake_pr_summarizer.json").read_text())
    for number, hints in targets_by_pr.items():
        summ = {
            **base_summary,
            "doc_targets": [
                {"lens": "core", "action": "create", "page_hint": h} for h in hints
            ],
        }
        (dst / f"fake_pr_summarizer__pr{number}.json").write_text(json.dumps(summ))
    return dst


# PR #1 fans out to TWO pages, PRs #2 and #3 to one each. Batch order is
# therefore [one_a, one_b] (group PR1), [two] (group PR2), [three] (group PR3),
# and index 2 is the first real PR boundary.
TARGETS_BY_PR = {
    1: ["connectors/one_a.md", "connectors/one_b.md"],
    2: ["connectors/two.md"],
    3: ["connectors/three.md"],
}


def test_cut_defers_to_the_pr_boundary_so_the_baseline_advances(
    tmp_path, init_host, read_current_run
):
    """The regression test. Past the soft deadline mid-group, the loop keeps
    going to finish PR #1, then cuts at the boundary — and the baseline
    advances to PR #1 rather than standing still.

    Clock: deadline=100. Admission gates at 10 and 20 admit all three PRs.
    Authoring batch 0 is unconditional; batch 1's gate sees 105 — past the
    soft deadline but INSIDE group(PR1) and under the hard cap, so the loop
    must NOT cut. Batch 2's gate sees 106, which is the PR1 -> PR2 boundary,
    and that is where the run stops.

    Before CCE-152 the batch-1 gate cut on 105 alone, PR #1 was left owing
    ``one_b.md``, and the advance fell back to the unmoved baseline.
    """
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (c1, c2, c3, c4) = _seed_window(repo, state_path, 4)
    # c4 is a direct (non-PR) commit, so HEAD is strictly ahead of the newest
    # PR merge and an advance to the cursor can never be confused with a
    # fall-through to head.
    fakes = _fakes(
        tmp_path.parent / f"cce152_boundary_{tmp_path.name}",
        [_pr(1, c1), _pr(2, c2), _pr(3, c3)],
        TARGETS_BY_PR,
    )
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 10, 20, 105, 106]),
    )
    assert rc == 0
    core = repo / "docs" / "site-src" / "core" / "connectors"
    # Precondition: PR #1's pages BOTH landed — the run ran past the soft
    # deadline rather than abandoning the group half-written.
    assert (core / "one_a.md").exists()
    assert (core / "one_b.md").exists()
    # Precondition: the run really was cut, at the boundary and no further.
    assert not (core / "two.md").exists()
    assert not (core / "three.md").exists()
    cr = read_current_run(state_path)
    assert any("page batches" in r for r in cr["partial_reasons"]), cr[
        "partial_reasons"
    ]
    # THE assertion: a complete prefix exists, so the cursor is non-empty and
    # the baseline moves to the last PR whose pages all landed.
    assert not any(
        "time_budget_no_advance_no_cursor" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    assert advance == c1, written["last_successful_run"]
    assert advance != base, written["last_successful_run"]
    assert advance != c4, written["last_successful_run"]
    # A truncated run still stamps the window it covered for the CCE-43 guard.
    assert written["last_successful_run"].get("window_head_sha") == c4, written[
        "last_successful_run"
    ]


def test_hard_cap_cuts_inside_a_group_and_says_the_baseline_cannot_advance(
    tmp_path, init_host, read_current_run
):
    """The bound on the overrun above.

    Deferring to a PR boundary is unbounded on its own: one PR fanning out to
    twenty pages would hold the run open past the GitHub App installation
    token's 1h TTL and fail it outright. The hard cap ends the run inside the
    group instead, which costs the advance — the same standstill as before
    CCE-152, and never worse — and the partial reason has to say so rather
    than read like an ordinary deferral.

    Clock: deadline=100, hard cap 115. Batch 1's gate sees 900, past both, and
    it is still inside group(PR1), so the cap is what cuts.
    """
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (c1, c2, c3, _c4) = _seed_window(repo, state_path, 4)
    fakes = _fakes(
        tmp_path.parent / f"cce152_hardcap_{tmp_path.name}",
        [_pr(1, c1), _pr(2, c2), _pr(3, c3)],
        TARGETS_BY_PR,
    )
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 10, 20, 900]),
    )
    assert rc == 0
    core = repo / "docs" / "site-src" / "core" / "connectors"
    assert (core / "one_a.md").exists()
    # Precondition: the cut landed INSIDE group(PR1), not at its boundary.
    assert not (core / "one_b.md").exists()
    cr = read_current_run(state_path)
    assert any("hard cap" in r for r in cr["partial_reasons"]), cr["partial_reasons"]
    # PR #1 owes a page, so no prefix closes and the baseline must hold.
    assert any(
        "time_budget_no_advance_no_cursor" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == base, written[
        "last_successful_run"
    ]


def test_hard_cap_resolves_from_config_and_never_undercuts_the_soft_budget():
    """Unit-level contract for the new resolver.

    The clamp is the load-bearing part: a cap below the soft budget would cut
    the loop BEFORE the deadline it exists to extend, quietly re-introducing
    the batch-boundary starvation this ticket fixes.
    """
    assert runner.resolve_authoring_hard_cap({}, 2100) == int(
        2100 * runner.DEFAULT_AUTHORING_HARD_CAP_RATIO
    )
    assert (
        runner.resolve_authoring_hard_cap(
            {"run": {"authoring_hard_cap_seconds": 2400}}, 2100
        )
        == 2400
    )
    # Below the soft budget → clamped up to it.
    assert (
        runner.resolve_authoring_hard_cap(
            {"run": {"authoring_hard_cap_seconds": 60}}, 2100
        )
        == 2100
    )
    # A malformed run block resolves like an absent one.
    assert runner.resolve_authoring_hard_cap({"run": "nonsense"}, 100) == int(
        100 * runner.DEFAULT_AUTHORING_HARD_CAP_RATIO
    )
