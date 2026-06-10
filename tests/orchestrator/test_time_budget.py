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
