# tests/orchestrator/test_pr_boundary_authoring_cut.py
"""CCE-152: the authoring cut lands on a PR boundary, so a truncated run
still leaves a COMPLETE prefix of PRs and the baseline can advance.

The bug this pins is a starvation, not a mis-ordering. ``per_target`` is a
dict built by iterating the ``_order_prs_oldest_first`` output and calling
``setdefault`` per doc target (``scripts/orchestrator_runner.py:run``), and
``setdefault`` never re-positions an existing key, so the batch list is
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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


def _fakes(dst: Path, prs: list[dict], targets_by_pr: dict[int, list]) -> Path:
    """Copy fakes_multi, override the collector's PRs, and give each PR its OWN
    summarizer fixture so the PRs emit different doc targets.

    ``targets_by_pr`` maps a PR number to the page hints it should claim, each
    either a bare hint string (lens ``core``) or an explicit ``(lens, hint)``
    pair. Every entry becomes one (lens, page_hint) batch; a hint listed under
    two PRs is one shared batch owned by the older of them.

    ``dst`` deliberately sits OUTSIDE ``tmp_path``: ``tmp_path`` is the host repo
    under test, and ``_stage_docs_run_changes`` runs ``git add -A .`` on it, so
    fixtures placed inside would be committed onto the docs-agent branch. The
    sibling-of-tmp_path placement is the convention across this package
    (test_authoring_truncation_advance.py, test_deferral_skip.py,
    test_blind_run_interlocks.py) and still lands under pytest's session
    basetemp, which pytest garbage-collects.
    """
    # copytree rather than a per-file write_text loop: the loop assumed
    # fakes_multi stays flat and UTF-8, and would raise IsADirectoryError on the
    # first subdirectory added to it.
    shutil.copytree(FAKES_MULTI, dst, dirs_exist_ok=True)
    sc = json.loads((FAKES_MULTI / "fake_source_collector.json").read_text())
    sc["prs"] = prs
    (dst / "fake_source_collector.json").write_text(json.dumps(sc))
    base_summary = json.loads((FAKES_MULTI / "fake_pr_summarizer.json").read_text())
    for number, hints in targets_by_pr.items():
        targets = []
        for h in hints:
            lens, hint = ("core", h) if isinstance(h, str) else h
            targets.append({"lens": lens, "action": "create", "page_hint": hint})
        summ = {**base_summary, "doc_targets": targets}
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


def test_hard_cap_resolves_from_config_and_defaults_to_the_ratio():
    """Unit-level contract for the resolver.

    (Renamed: "never undercuts the soft budget" described the old
    ``max(cap, budget)`` normalisation, which the at-or-below-budget rejection
    replaced — nothing here has undercut anything since.)
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
    # A malformed run block resolves like an absent one.
    assert runner.resolve_authoring_hard_cap({"run": "nonsense"}, 100) == int(
        100 * runner.DEFAULT_AUTHORING_HARD_CAP_RATIO
    )


@pytest.mark.parametrize("cap", [60, 2100])
def test_hard_cap_at_or_below_the_budget_is_rejected_not_clamped_up(cap):
    """An explicit override that does not exceed the budget is a config error.

    The earlier resolver returned ``max(cap, budget)``, which turned both of
    these into ``cap == budget``. That is not a harmless normalisation: it
    collapses ``authoring_hard_deadline`` onto ``deadline``, which makes the
    ``_past_hard`` test equivalent to ``now > deadline`` and restores the
    arbitrary mid-PR-group cut CCE-152 exists to remove — silently, in the exact
    place the operator was trying to configure it away.

    ``cap == budget`` is included on purpose: equal is as broken as under.
    """
    with pytest.raises(runner.ConfigError) as excinfo:
        runner.resolve_authoring_hard_cap(
            {"run": {"authoring_hard_cap_seconds": cap}}, 2100
        )
    assert "authoring_hard_cap_seconds" in str(excinfo.value)


def test_hard_cap_is_clamped_against_the_app_token_ttl():
    """The structural half of the bound (the ratio alone is not one).

    ``budget * 1.15`` is a ratio, not a ceiling. The binding ceiling is the
    GitHub App installation token, which no ``timeout-minutes`` extends, minus
    the merge poll the run may still spend and the post-run tail.
    """
    ceiling = (
        runner.GITHUB_APP_TOKEN_TTL_SECONDS
        - runner.DEFAULT_CHECKS_TIMEOUT_SECONDS
        - runner.AUTHORING_TTL_SAFETY_SECONDS
    )
    # 2400 * 1.15 = 2760, which would put budget + poll past the token.
    assert int(2400 * runner.DEFAULT_AUTHORING_HARD_CAP_RATIO) > ceiling
    assert runner.resolve_authoring_hard_cap({}, 2400) == ceiling
    # An explicit override is clamped by the same ceiling — the token does not
    # care where the number came from — and the narrowing is announced rather
    # than silent (see test_a_clamped_override_is_announced_not_silent).
    narrowed: list[str] = []
    assert (
        runner.resolve_authoring_hard_cap(
            {"run": {"authoring_hard_cap_seconds": 3400}}, 2400, out_reasons=narrowed
        )
        == ceiling
    )
    assert len(narrowed) == 1 and narrowed[0].startswith("authoring_hard_cap_clamped:")
    # The two hosts in this repo's orbit sit exactly ON it and keep their full
    # overrun, which is what fixes AUTHORING_TTL_SAFETY_SECONDS at 285: it is the
    # largest reserve for which this still holds (2415 <= 3600 - 900 - S solves
    # to S <= 285), so this pair of assertions is the constant's whole criterion.
    assert runner.resolve_authoring_hard_cap({}, 2100) == 2415
    assert 2415 <= ceiling
    assert runner.AUTHORING_TTL_SAFETY_SECONDS == 285
    assert (
        runner.GITHUB_APP_TOKEN_TTL_SECONDS
        - runner.DEFAULT_CHECKS_TIMEOUT_SECONDS
        - (runner.AUTHORING_TTL_SAFETY_SECONDS + 1)
        < 2415
    )


def test_a_clamped_override_is_announced_not_silent():
    """The third state of the resolver, and the one that used to say nothing.

    A squeeze is loud and an at-or-below-budget cap aborts, but an explicit
    override that is merely narrowed by the TTL returned a number the operator
    never wrote with nothing in ``out_reasons`` and nothing logged — the digest
    then reports a cap the config does not contain, which reads as "my config was
    ignored" rather than "your config does not fit in the token".

    The advisory has to carry all three numbers, because the operator's next
    action is arithmetic: what they asked for, what they got, and the poll term
    that is spending the difference.
    """
    reasons: list[str] = []
    cap = runner.resolve_authoring_hard_cap(
        {
            "run": {"authoring_hard_cap_seconds": 3400},
            "merge": {"checks_timeout_seconds": 600},
        },
        2400,
        out_reasons=reasons,
    )
    ceiling = (
        runner.GITHUB_APP_TOKEN_TTL_SECONDS - 600 - runner.AUTHORING_TTL_SAFETY_SECONDS
    )
    assert cap == ceiling
    assert len(reasons) == 1, reasons
    msg = reasons[0]
    assert msg.startswith("authoring_hard_cap_clamped:"), msg
    assert "run.authoring_hard_cap_seconds" in msg
    assert "3400s" in msg, msg
    assert f"{ceiling}s" in msg, msg
    assert "600s" in msg, msg
    # It is advisory, not a squeeze: this host keeps real overrun above its
    # budget, so it must not borrow the squeezed host's key.
    assert "authoring_hard_cap_squeezed" not in msg
    assert cap > 2400
    # A cap that already fits is not narrowed, so nothing is said about it.
    quiet: list[str] = []
    assert (
        runner.resolve_authoring_hard_cap(
            {
                "run": {"authoring_hard_cap_seconds": 2500},
                "merge": {"checks_timeout_seconds": 600},
            },
            2400,
            out_reasons=quiet,
        )
        == 2500
    )
    assert quiet == []
    # And the ratio path is not an override, so a clamped default stays quiet
    # too — there is no operator value to reconcile against.
    ratio: list[str] = []
    assert (
        runner.resolve_authoring_hard_cap(
            {"merge": {"checks_timeout_seconds": 600}}, 2700, out_reasons=ratio
        )
        == ceiling
    )
    assert ratio == []


def test_a_manual_merge_host_is_not_charged_for_a_poll_it_never_runs():
    """The checks poll is subtracted only from an auto-merge host's ceiling."""
    manual = {"merge": {"policy": "manual"}}
    ceiling = runner.GITHUB_APP_TOKEN_TTL_SECONDS - runner.AUTHORING_TTL_SAFETY_SECONDS
    assert runner.resolve_authoring_hard_cap(manual, 2700) == int(
        2700 * runner.DEFAULT_AUTHORING_HARD_CAP_RATIO
    )
    assert int(2700 * runner.DEFAULT_AUTHORING_HARD_CAP_RATIO) <= ceiling
    # Same budget on the default auto policy has no headroom left at all.
    reasons: list[str] = []
    assert runner.resolve_authoring_hard_cap({}, 2700, out_reasons=reasons) == 2700
    assert reasons


def test_a_ttl_squeeze_holds_the_cap_at_budget_and_says_so_loudly():
    """The edge case, and it is the DEFAULT one.

    DEFAULT_TIME_BUDGET_SECONDS (2700) plus the default 900s merge poll is the
    entire 3600s token with nothing left for the tail, so a host on defaults has
    no overrun to grant. That is not a config error and must not abort — the
    budget may be perfectly serviceable, it just leaves no room on top. The cap
    is held at the budget (behaviour degrades to pre-CCE-152: cuts may land
    mid-group and such a run earns no advance) and the squeeze is reported.
    """
    # Pinned because the test's whole point is that the STOCK default is the
    # squeezed case: if the default ever drops below the ceiling this test would
    # keep passing while silently exercising the un-squeezed path instead.
    assert runner.DEFAULT_TIME_BUDGET_SECONDS == 2700
    reasons: list[str] = []
    cap = runner.resolve_authoring_hard_cap(
        {}, runner.DEFAULT_TIME_BUDGET_SECONDS, out_reasons=reasons
    )
    assert cap == runner.DEFAULT_TIME_BUDGET_SECONDS
    assert len(reasons) == 1
    assert reasons[0].startswith("authoring_hard_cap_squeezed:")
    # It has to name the squeeze concretely enough to act on.
    assert "run.time_budget_seconds" in reasons[0]
    assert "merge.checks_timeout_seconds" in reasons[0]
    # A correctly-sized host stays silent.
    quiet: list[str] = []
    assert runner.resolve_authoring_hard_cap({}, 2100, out_reasons=quiet) == 2415
    assert quiet == []


def test_a_squeezed_run_records_an_advisory_reason_without_going_partial(
    tmp_path, init_host, read_current_run, base_config_yaml, monkeypatch
):
    """The squeeze reaches the digest but must not flip ``partial``.

    CCE-140 gates auto-merge on ``partial and not advance_cursor_backed``, and a
    non-truncated run is never cursor-backed. A blocking reason here would
    therefore cost every default-budget host auto-merge permanently, for a
    condition that predates this ticket — the design's "degrades to pre-CCE-152,
    never worse" only holds if the reason is advisory.

    Advisory is not the same as quiet, though, and the design asks for LOUD.
    So the step summary is asserted as well: an operator whose host silently
    lost its overrun has no way to find out from `partial` alone, and the
    squeeze names the two keys to lower.
    """
    summary = tmp_path.parent / f"cce152_summary_{tmp_path.name}.md"
    summary.write_text("## existing\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    squeezed = base_config_yaml.replace(
        "time_budget_seconds: 2100",
        f"time_budget_seconds: {runner.DEFAULT_TIME_BUDGET_SECONDS}",
    )
    repo = tmp_path
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "s"}},
        config_yaml=squeezed,
    )
    _base, (c1, _c2) = _seed_window(repo, state_path, 2)
    fakes = _fakes(
        tmp_path.parent / f"cce152_squeeze_{tmp_path.name}",
        [_pr(1, c1)],
        {1: ["connectors/one_a.md"]},
    )
    # No time_budget_seconds override: the run resolves the squeezed budget
    # from config, exactly as a default-configured host does.
    rc = runner.run(repo, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    cr = read_current_run(state_path)
    assert any(
        r.startswith("authoring_hard_cap_squeezed:") for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    # Nothing else went wrong, so the squeeze is the only thing that could have
    # flipped `partial` — and it must not have.
    assert cr["partial"] is False, cr
    # ...and it is still reported where the operator looks, under the INFO
    # header rather than the "Partial run" warning.
    written_summary = summary.read_text()
    assert "authoring_hard_cap_squeezed:" in written_summary, written_summary
    assert "INFO — advisory notices (run not partial)" in written_summary
    assert "WARNING — Partial run" not in written_summary


def test_a_squeezed_hosts_cut_reason_does_not_read_as_a_contradiction(
    tmp_path, init_host, read_current_run, base_config_yaml
):
    """The wording of the cut on a host whose cap was squeezed flat.

    On a squeezed host the resolver returns ``budget`` itself, so
    ``authoring_hard_cap == budget`` and the ordinary hard-cap phrasing renders
    as "hard cap 2500s over budget 2500s" — a number that is over itself. That is
    the stock default's own configuration (2700 + 900 fills the token), so it is
    the phrasing most operators would actually meet, and it hides the one fact
    that explains the run: the overrun was never granted, because the App token's
    TTL took it.

    Nothing pinned the wording before, so this asserts both directions — the
    honest phrasing is present AND the self-contradictory one is absent.

    Clock: budget 2500 from config, hard deadline 2500 (squeezed). Batch 1's
    gate sees 3000, past both, inside group(PR #1).
    """
    squeezed = base_config_yaml.replace(
        "time_budget_seconds: 2100", "time_budget_seconds: 2500"
    )
    repo = tmp_path
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "s"}},
        config_yaml=squeezed,
    )
    _base, (c1, c2, c3, _c4) = _seed_window(repo, state_path, 4)
    fakes = _fakes(
        tmp_path.parent / f"cce152_squeezed_cut_{tmp_path.name}",
        [_pr(1, c1), _pr(2, c2), _pr(3, c3)],
        TARGETS_BY_PR,
    )
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        now_monotonic=_fake_clock([0, 10, 20, 3000]),
    )
    assert rc == 0
    # Precondition: the run really was squeezed, and really was cut mid-group.
    cr = read_current_run(state_path)
    assert any(
        r.startswith("authoring_hard_cap_squeezed:") for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    core = repo / "docs" / "site-src" / "core" / "connectors"
    assert (core / "one_a.md").exists()
    assert not (core / "one_b.md").exists()
    cut = [r for r in cr["partial_reasons"] if "page batches" in r]
    assert len(cut) == 1, cr["partial_reasons"]
    assert "hard cap held at budget 2500s by the App-token TTL" in cut[0], cut[0]
    assert "over budget" not in cut[0], cut[0]
    # The consequence still has to be stated — this is a mid-group cut, and it
    # costs the advance exactly as an un-squeezed one does.
    assert "the baseline cannot advance to it" in cut[0], cut[0]


def test_a_configured_hard_cap_loads_and_governs_the_cut(
    tmp_path, init_host, read_current_run, base_config_yaml
):
    """The documented override, end to end through the host's own config file.

    This is the defect the schema fix closes, seen from the operator's side:
    `run.authoring_hard_cap_seconds` was documented and read by the resolver
    while the schema's `additionalProperties: false` rejected it, so a host
    that followed the documentation exited 2 at config load every night —
    before authoring, before the digest. Every existing test missed it by
    handing the resolver a raw dict the schema never saw.

    Both halves are asserted. The run completes (rc 0), and the cut it makes
    names 150s, which is the configured value — the 1.15 default would have
    said 115s and cut at the same batch, so only the wording separates "the
    config was honoured" from "the config was ignored".

    Clock: budget 100 from config, hard deadline 150. Batch 1's gate sees 900,
    past both, inside group(PR #1).
    """
    configured = base_config_yaml.replace(
        "time_budget_seconds: 2100",
        "time_budget_seconds: 100\n  authoring_hard_cap_seconds: 150",
    )
    repo = tmp_path
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "s"}},
        config_yaml=configured,
    )
    _base, (c1, c2, c3, _c4) = _seed_window(repo, state_path, 4)
    fakes = _fakes(
        tmp_path.parent / f"cce152_configured_{tmp_path.name}",
        [_pr(1, c1), _pr(2, c2), _pr(3, c3)],
        TARGETS_BY_PR,
    )
    # No CLI budget override: both numbers come from the config file.
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        now_monotonic=_fake_clock([0, 10, 20, 900]),
    )
    assert rc == 0
    cr = read_current_run(state_path)
    assert any("hard cap 150s over budget 100s" in r for r in cr["partial_reasons"]), (
        cr["partial_reasons"]
    )
    # And the ratio default did not answer instead.
    assert not any("hard cap 115s" in r for r in cr["partial_reasons"]), cr[
        "partial_reasons"
    ]


def test_a_hard_cap_below_the_budget_fails_the_run_cleanly_not_with_a_traceback(
    tmp_path, init_host, base_config_yaml, capsys
):
    """The rejection above must not escape ``run()``.

    ``main()`` has no ConfigError handler, so an uncaught raise from the resolver
    would terminate the process with a traceback. Exit 2 with a logged reason is
    the contract the two config rejections above it already meet — a missing
    config file and a schema-invalid one — and the hard cap is a third config
    rejection, not a new failure class. (Neither path notifies: the notifier
    dispatch is at the end of ``run()``, far below this return, so a config
    rejection never reaches the digest either way. What the guard buys is a
    legible reason instead of a stack trace.)

    The emitted message is asserted too, not just the exit code: ``run()``
    returns 2 for several unrelated config rejections, so an rc-only assertion
    would still pass if this config were refused for some other reason and the
    hard-cap guard never ran at all.
    """
    bad = base_config_yaml.replace(
        "time_budget_seconds: 2100",
        "time_budget_seconds: 2100\n  authoring_hard_cap_seconds: 1800",
    )
    init_host(
        {"version": "1", "last_successful_run": {"head_sha": "s"}}, config_yaml=bad
    )
    assert runner.run(tmp_path, dry_run_dir=FAKES_MULTI, no_pr=True) == 2
    err = capsys.readouterr().err
    assert "config invalid" in err, err
    assert "run.authoring_hard_cap_seconds (1800)" in err, err


# PR #1's first target names a lens the host does not define, so its batch hits
# the `unknown_lens` continue path before anything is authored. PR #1's second
# target is a normal page, and PR #2's is the boundary after it.
TARGETS_WITH_A_SKIPPED_BATCH = {
    1: [("ghost", "connectors/ghost.md"), "connectors/one_b.md"],
    2: ["connectors/two.md"],
}


def test_a_skipped_batch_still_advances_the_boundary_owner(
    tmp_path, init_host, read_current_run
):
    """``_prev_owner`` must advance on the `continue` paths, not only on the
    paths that author.

    The loop's `unknown_lens` and `unsafe_page_path` branches `continue` before
    the end of the body, so moving ``_prev_owner = _owner`` down to the end —
    which reads like ordinary tidying, and which the comment above it warns
    against — leaves ``_prev_owner`` stranded on the previous PR. The next batch
    then compares its owner against a stale value and reports a PR boundary that
    is not there, cutting the run inside group(PR #1) at the first
    past-the-deadline gate.

    Nothing else in this package covers it: ``TARGETS_BY_PR`` only yields
    batches that resolve and author cleanly, so every existing test is green
    under that mutation.

    Clock: deadline=100, and this window is TWO PRs, so admission spends only
    one value (10). Batch 0 is the ghost-lens batch (unconditional, i=0,
    skipped). Batch 1 is ``one_b.md`` at 105 — past the soft deadline, under the
    hard cap, still inside group(PR #1), so the run must keep going. Batch 2 is
    the real boundary at 106.
    """
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (c1, c2, _c3) = _seed_window(repo, state_path, 3)
    fakes = _fakes(
        tmp_path.parent / f"cce152_skipbatch_{tmp_path.name}",
        [_pr(1, c1), _pr(2, c2)],
        TARGETS_WITH_A_SKIPPED_BATCH,
    )
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 10, 105, 106]),
    )
    assert rc == 0
    cr = read_current_run(state_path)
    # Precondition: the skip really happened, and it happened at batch 0.
    assert any("unknown_lens: ghost" in r for r in cr["partial_reasons"]), cr[
        "partial_reasons"
    ]
    core = repo / "docs" / "site-src" / "core" / "connectors"
    # THE assertion: the batch after the skip is still recognised as part of
    # group(PR #1), so the past-deadline gate does not cut there.
    assert (core / "one_b.md").exists(), cr["partial_reasons"]
    # And the cut still lands on the real boundary, no further.
    assert not (core / "two.md").exists()


def test_past_the_hard_cap_at_a_boundary_still_defers_rather_than_cutting_in(
    tmp_path, init_host, read_current_run
):
    """``_past_hard`` alone must not pick the hard-cap reason.

    The two states are not the same run. Past the hard cap AND mid-group is a
    forced cut that costs the advance. Past the hard cap AND standing on a PR
    boundary is an ordinary deferral: the group behind the cut is complete, the
    cursor is non-empty, and the baseline moves. Simplifying
    ``if _past_hard and not _at_boundary`` to ``if _past_hard`` reads as
    redundancy removal and converts every advanceable late run into one that
    reports it cannot advance.

    Clock: deadline=100, hard cap 115. Batch 1's gate sees 110 — past the soft
    deadline, under the cap, mid-group — so no cut. Batch 2's gate sees 900,
    past BOTH, and it is the PR1 -> PR2 boundary.
    """
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (c1, c2, c3, c4) = _seed_window(repo, state_path, 4)
    fakes = _fakes(
        tmp_path.parent / f"cce152_hardboundary_{tmp_path.name}",
        [_pr(1, c1), _pr(2, c2), _pr(3, c3)],
        TARGETS_BY_PR,
    )
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 10, 20, 110, 900]),
    )
    assert rc == 0
    core = repo / "docs" / "site-src" / "core" / "connectors"
    assert (core / "one_a.md").exists()
    assert (core / "one_b.md").exists()
    assert not (core / "two.md").exists()
    cr = read_current_run(state_path)
    # THE assertion: the deferral vocabulary, not the hard-cap vocabulary.
    assert any("deferring the rest" in r for r in cr["partial_reasons"]), cr[
        "partial_reasons"
    ]
    assert not any("hard cap" in r for r in cr["partial_reasons"]), cr[
        "partial_reasons"
    ]
    # ...and the run really does advance, which is what the wording claims.
    assert not any(
        "time_budget_no_advance_no_cursor" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == c1, written[
        "last_successful_run"
    ]
    assert written["last_successful_run"]["head_sha"] != base
