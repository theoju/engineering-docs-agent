# tests/orchestrator/test_time_budget_authoring.py
"""CCE-114: time-budget enforcement in the post-admission fan-out loops.

CCE-109 gated PR *admission* on the soft deadline, but the page-author
fan-out (the most expensive phase: one Claude dispatch per doc-target
batch) and the advisory fact-checker / gap-detector loops never checked
it. A big window blew straight through the deadline into the workflow's
60-minute hard kill (run 27263616736: ~20 page-author dispatches started
after the deadline). These tests pin the per-loop guards.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import orchestrator_runner as runner  # noqa: E402

FAKES_MULTI = Path(__file__).parent / "fakes_multi"


def _fake_clock(values):
    """Monotonic values in order, then repeating the last. First value is
    consumed by the deadline calc (same helper as test_time_budget.py)."""
    it = iter(values)
    last = values[-1]
    return lambda: next(it, last)


def _write_fakes_multi_targets(dst: Path) -> Path:
    """Copy fakes_multi but have the summarizer emit three distinct doc
    targets, so the authoring loop runs three batches instead of one."""
    dst.mkdir(parents=True, exist_ok=True)
    for f in FAKES_MULTI.iterdir():
        (dst / f.name).write_text(f.read_text())
    summ = json.loads((dst / "fake_pr_summarizer.json").read_text())
    summ["doc_targets"] = [
        {"lens": "core", "action": "create", "page_hint": f"connectors/{n}.md"}
        for n in ("alpha", "beta", "gamma")
    ]
    (dst / "fake_pr_summarizer.json").write_text(json.dumps(summ))
    return dst


def test_authoring_loop_truncates_after_budget(tmp_path, init_host, read_current_run):
    repo = tmp_path
    fakes = _write_fakes_multi_targets(
        tmp_path.parent / f"fakes_cce114_{tmp_path.name}"
    )
    state_path = init_host({"version": "1", "last_successful_run": {}})
    # deadline calc=0 → deadline=100; admission i=1,2 at 10,20 (all 3 PRs
    # admitted); authoring batch 0 unconditional, batch 1 gate at 150 → trip.
    clock = _fake_clock([0, 10, 20, 150])
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 0
    cr = read_current_run(state_path)
    assert cr["partial"] is True
    assert any(
        "time_budget_exceeded: authored 1/3 page batches" in r
        for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    core = repo / "docs" / "site-src" / "core" / "connectors"
    assert (core / "alpha.md").exists()
    assert not (core / "beta.md").exists()
    assert not (core / "gamma.md").exists()


def test_fact_checker_loop_skips_after_budget(tmp_path, init_host, read_current_run):
    repo = tmp_path
    fakes = _write_fakes_multi_targets(
        tmp_path.parent / f"fakes_cce114_{tmp_path.name}"
    )
    state_path = init_host({"version": "1", "last_successful_run": {}})
    # Admission (10,20) and authoring (30,40) all inside budget → 3 pages
    # authored; first fact-checker gate at 150 → skip the whole warn layer.
    clock = _fake_clock([0, 10, 20, 30, 40, 150])
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 0
    cr = read_current_run(state_path)
    assert cr["partial"] is True
    assert any(
        "time_budget_exceeded: fact-checked 0/3 pages" in r
        for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    core = repo / "docs" / "site-src" / "core" / "connectors"
    assert (core / "gamma.md").exists()  # authoring itself was NOT cut


def test_gap_detector_loop_skips_after_budget(tmp_path, init_host, read_current_run):
    repo = tmp_path
    fakes = _write_fakes_multi_targets(
        tmp_path.parent / f"fakes_cce114_{tmp_path.name}"
    )
    state_path = init_host({"version": "1", "last_successful_run": {}})
    # Everything through the fact-checker loop passes (its three per-page
    # gates at 50,60,70 — dry-run pages cite nothing, so no dispatches);
    # the first gap-detector gate sees 150 → skip gap detection.
    clock = _fake_clock([0, 10, 20, 30, 40, 50, 60, 70, 150])
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 0
    cr = read_current_run(state_path)
    assert cr["partial"] is True
    assert any(
        "time_budget_exceeded: gap-checked 0/3 PRs" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    assert not any("fact-checked" in r for r in cr["partial_reasons"]), cr[
        "partial_reasons"
    ]


def test_unlimited_budget_authors_all_targets(tmp_path, init_host, read_current_run):
    repo = tmp_path
    fakes = _write_fakes_multi_targets(
        tmp_path.parent / f"fakes_cce114_{tmp_path.name}"
    )
    state_path = init_host({"version": "1", "last_successful_run": {}})
    rc = runner.run(repo, dry_run_dir=fakes, no_pr=True, time_budget_seconds=0)
    assert rc == 0
    cr = read_current_run(state_path)
    assert cr["partial"] is False
    assert not any("time_budget_exceeded" in r for r in cr["partial_reasons"])
    core = repo / "docs" / "site-src" / "core" / "connectors"
    for n in ("alpha", "beta", "gamma"):
        assert (core / f"{n}.md").exists()
