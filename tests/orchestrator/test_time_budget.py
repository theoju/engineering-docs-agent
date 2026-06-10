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

CONFIG_YAML = """
docs:
  framework: mkdocs
  source_dir: docs/site-src
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths:
    core: docs/site-src/core
sources:
  git: { host: github }
lint: { tier1: default }
publishing:
  base_url: https://example.com
  build_workflow: deploy.yml
  url_map_rule: standard
  verify_timeout_seconds: 60
notifications:
  slack: { enabled: false }
  email: { enabled: false }
"""


def _init_host(tmp: Path, seeded_state: dict, config_yaml: str = CONFIG_YAML) -> Path:
    (tmp / "docs" / "site-src" / "core").mkdir(parents=True)
    (tmp / ".engineering-docs-agent").mkdir()
    (tmp / ".engineering-docs-agent" / "config.yml").write_text(config_yaml)
    state_path = tmp / ".engineering-docs-agent" / "state.json"
    state_path.write_text(json.dumps(seeded_state))
    _git(tmp, "init", "-q")
    _git(tmp, "config", "user.email", "t@example.com")
    _git(tmp, "config", "user.name", "T")
    (tmp / "README.md").write_text("init")
    _git(tmp, "add", ".")
    _git(tmp, "commit", "-q", "-m", "init")
    return state_path


def _current_run(state_path: Path) -> dict:
    return json.loads((state_path.parent / "current_run.json").read_text())[
        "current_run"
    ]


def _fake_clock(values):
    """Return a callable yielding the given monotonic values in order, then
    repeating the last value. First value is consumed by the deadline calc."""
    seq = list(values)
    state = {"i": 0}

    def clock() -> float:
        i = state["i"]
        state["i"] = min(i + 1, len(seq) - 1)
        return seq[i]

    return clock


def test_unlimited_budget_processes_all_prs(tmp_path):
    # Empty baseline (first-run case) → clip + ordering take their documented
    # `if not last_sha: return prs` passthrough with NO partial reason emitted,
    # so a clean unlimited run is genuinely partial-free. (A *bogus* last_sha
    # would instead trip the pre-existing CCE-19 `out_of_window_filter_skipped`
    # clip partial, which is orthogonal to the time-budget gate under test.)
    # 3 PRs from fakes_multi; budget 0 = unlimited → no truncation.
    state_path = _init_host(
        tmp_path,
        {"version": "1", "last_successful_run": {}},
    )
    rc = runner.run(
        tmp_path, dry_run_dir=FAKES_MULTI, no_pr=True, time_budget_seconds=0
    )  # 0 = unlimited
    assert rc == 0
    cr = _current_run(state_path)
    assert cr["partial"] is False
    assert not any("time_budget_exceeded" in r for r in cr["partial_reasons"])


def test_truncates_after_budget_and_records_partial(tmp_path):
    state_path = _init_host(
        tmp_path,
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
    cr = _current_run(state_path)
    assert cr["partial"] is True
    assert any(
        "time_budget_exceeded: admitted 2/3" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]


def test_always_admits_at_least_one_pr(tmp_path):
    state_path = _init_host(
        tmp_path,
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
    cr = _current_run(state_path)
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


def test_truncated_run_advances_to_last_processed_pr(tmp_path):
    # Fake merge_shas + bogus last_sha → ordering passes through; cursor = PR2.merge_sha.
    state_path = _init_host(
        tmp_path, {"version": "1", "last_successful_run": {"head_sha": "old_sha_000"}}
    )
    clock = _fake_clock([0, 50, 150])  # admit 2 of 3
    rc = runner.run(
        tmp_path,
        dry_run_dir=FAKES_MULTI,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    # fakes_multi PRs are 1/2/3 with merge_sha a/b/c; admitted [1,2] → cursor 'b'.
    assert written["last_successful_run"]["head_sha"] == "b", written[
        "last_successful_run"
    ]


def test_oldest_first_cursor_is_oldest_commit(tmp_path):
    # Real window; PRs given newest-first; truncate after 1 → must advance to OLDEST.
    repo = tmp_path
    state_path = _init_host(
        repo, {"version": "1", "last_successful_run": {"head_sha": "x"}}
    )
    # Add 3 real commits on top of the init commit.
    base = _git(repo, "rev-parse", "HEAD")
    shas = []
    for i in range(1, 4):
        (repo / "f.txt").write_text(f"c{i}")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    c1, c2, c3 = shas
    # Seed baseline to `base` so the window base..HEAD contains c1,c2,c3.
    state_path.write_text(
        json.dumps({"version": "1", "last_successful_run": {"head_sha": base}})
    )
    fakes = tmp_path.parent / "fakes_cce109_order"
    _write_fakes_with_prs(
        FAKES_MULTI,
        fakes,
        [
            {"number": 3, "merge_sha": c3, "url": "https://github.com/o/r/pull/3"},
            {"number": 2, "merge_sha": c2, "url": "https://github.com/o/r/pull/2"},
            {"number": 1, "merge_sha": c1, "url": "https://github.com/o/r/pull/1"},
        ],
    )
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


def test_truncation_with_no_usable_cursor_does_not_advance(tmp_path):
    state_path = _init_host(
        tmp_path, {"version": "1", "last_successful_run": {"head_sha": "old_sha_000"}}
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
    cr = _current_run(state_path)
    assert any(
        "time_budget_no_advance_no_cursor" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
