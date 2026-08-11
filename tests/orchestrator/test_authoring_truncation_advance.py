# tests/orchestrator/test_authoring_truncation_advance.py
"""Track A: an authoring-truncated run advances to the CCE-109 cursor, never
to the full window HEAD.

The PR-admission loop sets ``time_truncated`` when it hits the soft deadline
(orchestrator_runner.py:1491). The authoring loop truncates for the same reason
and historically set nothing, so ``advance_sha`` fell through to
``state["current_run"]["head_sha"]`` — the full window HEAD — and the run
persisted a baseline covering PRs whose pages it never authored.

Every fixture here places a NON-PR commit (``c4``) on top of the newest PR
merge commit (``c3``), so the cursor and HEAD are provably different shas.
Asserting ``advance == cursor`` alone would pass vacuously on a fixture whose
newest PR merge happens to BE head; the discriminating assertion — and the one
that would have caught the original fall-through — is ``advance != head``.
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


def _pr(n: int, sha: str | None = None) -> dict:
    d = {"number": n, "title": f"PR {n}", "url": f"https://github.com/o/r/pull/{n}"}
    if sha:
        d["merge_sha"] = sha
    return d


def _fakes(dst: Path, prs: list[dict] | None, hints: list[str] | None) -> Path:
    """Copy fakes_multi, optionally overriding the collector's PRs and the
    summarizer's doc_targets (one batch per hint drives the authoring loop)."""
    dst.mkdir(parents=True, exist_ok=True)
    for f in FAKES_MULTI.iterdir():
        (dst / f.name).write_text(f.read_text())
    if prs is not None:
        sc = json.loads((FAKES_MULTI / "fake_source_collector.json").read_text())
        sc["prs"] = prs
        (dst / "fake_source_collector.json").write_text(json.dumps(sc))
    if hints is not None:
        summ = json.loads((FAKES_MULTI / "fake_pr_summarizer.json").read_text())
        summ["doc_targets"] = [
            {"lens": "core", "action": "create", "page_hint": h} for h in hints
        ]
        (dst / "fake_pr_summarizer.json").write_text(json.dumps(summ))
    return dst


THREE_HINTS = ["connectors/alpha.md", "connectors/beta.md", "connectors/gamma.md"]
# deadline=100; admission gates at 10 and 20 admit all 3 PRs; authoring batch 0
# is unconditional, batch 1's gate sees 150 → the authoring loop truncates.
AUTHORING_TRUNCATION_CLOCK = [0, 10, 20, 150]


def test_authoring_truncation_holds_baseline_when_every_pr_owes_pages(
    tmp_path, init_host, read_current_run
):
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (c1, c2, c3, c4) = _seed_window(repo, state_path, 4)
    # c4 is a direct (non-PR) commit, so HEAD is strictly ahead of the newest
    # PR merge — cursor and head can never coincide in this fixture.
    fakes = _fakes(
        tmp_path.parent / f"trackA_cursor_{tmp_path.name}",
        [_pr(1, c1), _pr(2, c2), _pr(3, c3)],
        THREE_HINTS,
    )
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock(AUTHORING_TRUNCATION_CLOCK),
    )
    assert rc == 0
    core = repo / "docs" / "site-src" / "core" / "connectors"
    # Precondition: the run really was cut inside the authoring loop.
    assert (core / "alpha.md").exists()
    assert not (core / "beta.md").exists()
    assert not (core / "gamma.md").exists()
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    head = _git(repo, "rev-parse", "HEAD")
    assert head == c4
    # THE assertion, unchanged and still the discriminating one: the bug
    # Track A fixed was a fall-through to head.
    assert advance != head, written["last_successful_run"]
    # CCE-140 narrowed the cursor. The summarizer fixture is replayed per PR
    # (orchestrator_runner.py:617) and the runner stamps the real number onto
    # each summary (:1518), so every PR contributes to every page batch —
    # cutting after batch 0 leaves ALL THREE PRs owing pages, the walk stops
    # at the oldest one, and nothing may anchor the advance. Before CCE-140
    # this asserted `advance == c3`, i.e. an advance past two PRs whose pages
    # were never written; spec Decision 2 forbids exactly that.
    assert advance == base, written["last_successful_run"]
    # A truncated run still stamps the window it covered for the CCE-43 guard.
    assert written["last_successful_run"].get("window_head_sha") == c4, written[
        "last_successful_run"
    ]
    cr = read_current_run(state_path)
    assert any(
        "time_budget_no_advance_no_cursor" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]


def test_authoring_truncation_without_cursor_holds_baseline(
    tmp_path, init_host, read_current_run
):
    # CCE-109 refusal branch 1 (no_cursor), now reachable from the authoring
    # loop: no admitted PR carries a merge_sha, so there is nothing to anchor
    # the advance to and the baseline must not move.
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (_c1, _c2, _c3, c4) = _seed_window(repo, state_path, 4)
    fakes = _fakes(
        tmp_path.parent / f"trackA_nocursor_{tmp_path.name}",
        [_pr(1), _pr(2), _pr(3)],
        THREE_HINTS,
    )
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock(AUTHORING_TRUNCATION_CLOCK),
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    assert advance != c4, written["last_successful_run"]
    assert advance == base, written["last_successful_run"]
    cr = read_current_run(state_path)
    assert any(
        "time_budget_no_advance_no_cursor" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]


def test_authoring_truncation_with_unresolvable_cursor_holds_baseline(
    tmp_path, init_host, read_current_run
):
    """CCE-109 refusal branch 3 (`out_of_window`) reached with a NON-EMPTY
    cursor, which is the only way it says anything.

    Reaching it takes care under CCE-140. A PR whose merge_sha cannot be
    resolved sorts last (`_order_prs_oldest_first`), so it is the first PR a
    truncation defers, which holds it back, which stops the walk before it --
    and the run refuses at `no_cursor` instead, several branches earlier.
    fakes_multi is the fixture that gets past that: EVERY PR carries a bogus
    sha ("a"/"b"/"c"), so they share one sort key, keep their original order,
    and the admitted prefix ends on a cursor that is present but unresolvable.

    ONE hint (not THREE) is what makes the difference: the authoring loop runs
    to completion, so no PR owes a page and the cursor survives the walk. With
    three hints every PR owes a page, the walk empties, and this test
    degenerates into a duplicate of the `no_cursor` test above -- which is
    exactly what it had silently become.
    """
    repo = tmp_path
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "old_sha_000"}}
    )
    fakes = _fakes(
        tmp_path.parent / f"trackA_unresolvable_{tmp_path.name}",
        None,
        ["connectors/solo.md"],
    )
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 50, 150]),  # admit 2 of 3
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    head = _git(repo, "rev-parse", "HEAD")
    advance = written["last_successful_run"]["head_sha"]
    assert advance != head, written["last_successful_run"]
    assert advance == "old_sha_000", written["last_successful_run"]
    cr = read_current_run(state_path)
    # Preconditions: neither earlier branch fired, so the refusal below is
    # genuinely the out_of_window one and not a rename of the no_cursor test.
    assert not any(
        "time_budget_no_advance_no_cursor" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    assert any(
        "time_budget_advance_out_of_window" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]


def test_an_unanchored_deferred_pr_refuses_an_otherwise_earned_advance(
    tmp_path, init_host, read_current_run
):
    """CCE-109 refusal branch 2 (`unanchored_deferred`), which CCE-140 makes
    LOAD-BEARING rather than obsolete.

    It is tempting to read this branch as redundant now: `advance_cursor_list`
    stops at the oldest held-back PR, every still-deferred PR is held back, so
    the cursor can never reach past one. That reasoning holds only while list
    order tracks commit order -- and `_order_prs_oldest_first` documents the
    one case where it does not: a PR whose `merge_sha` is missing "sorts last
    (cannot anchor the cursor)". Sunk to the tail, it LOOKS newest to the
    walk, while its true merge point is unknown and may be older than the
    cursor. The list prefix is then not a commit-graph prefix, and advancing
    strands that PR outside every future window -- permanently, since nothing
    re-collects below the baseline.

    So the guard has to fire even though the walk looks clean. Deleting it
    would trade a held baseline for a lost PR, which is the trade this whole
    epic exists to stop making.

    This replaces a test that asserted the branch stays SILENT on the
    authoring path. That claim died with CCE-140 (`still_deferred` now
    includes authoring-deferred PRs), and the assertion was vacuous besides:
    it sits behind an `elif`, and in that fixture every PR owed a page, so
    `cursor is None` short-circuited before the branch was ever evaluated.
    """
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (c1, _c2, c3, c4) = _seed_window(repo, state_path, 4)
    fakes = _fakes(
        tmp_path.parent / f"trackA_unanchored_{tmp_path.name}",
        [_pr(1, c1), _pr(2), _pr(3, c3)],
        # ONE hint: the authoring loop runs to completion, so no PR owes a
        # page and the cursor is genuinely earned. Only the unanchored
        # deferral stands between this run and an advance to c3.
        ["connectors/solo.md"],
    )
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 50, 150]),  # admit 2 of 3
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    cr = read_current_run(state_path)
    # Precondition: the walk DID produce a cursor. Without this the refusal
    # below could be the no_cursor branch and the test would prove nothing.
    assert not any(
        "time_budget_no_advance_no_cursor" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    assert any(
        "time_budget_no_advance_unanchored_deferred" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    assert advance == base, written["last_successful_run"]
    assert advance != c3 and advance != c4, written["last_successful_run"]


def test_admission_truncation_advance_unchanged_by_track_a(
    tmp_path, init_host, read_current_run
):
    # Regression guard: Track A must not touch the admission path. One
    # doc_target keeps len(per_target) == 1, so the authoring loop's `i > 0`
    # gate never fires and admission truncation is the only truncation in play.
    # This test passes identically with and without the Track A line.
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (c1, c2, c3, c4) = _seed_window(repo, state_path, 4)
    fakes = _fakes(
        tmp_path.parent / f"trackA_admission_{tmp_path.name}",
        [_pr(1, c1), _pr(2, c2), _pr(3, c3)],
        None,
    )
    # deadline=100; admission gate at i=1 sees 50 (admit PR #2), at i=2 sees
    # 150 → truncate after 2 of 3 PRs. Cursor = c2.
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 50, 150]),
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    assert advance != c4, written["last_successful_run"]
    assert advance == c2, written["last_successful_run"]
    assert written["last_successful_run"].get("window_head_sha") == c4, written[
        "last_successful_run"
    ]
    cr = read_current_run(state_path)
    assert (
        "time_budget_exceeded: admitted 2/3 PRs (budget 100s); "
        "deferring PR #3 to next run" in cr["partial_reasons"]
    ), cr["partial_reasons"]
    # The authoring loop never truncated, so no authoring reason is present.
    assert not any("page batches" in r for r in cr["partial_reasons"]), cr[
        "partial_reasons"
    ]
    core = repo / "docs" / "site-src" / "core" / "connectors"
    assert (core / "multi.md").exists()
