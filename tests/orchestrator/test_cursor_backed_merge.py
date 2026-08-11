# tests/orchestrator/test_cursor_backed_merge.py
"""CCE-140: a partial run may merge only when its advance is cursor-backed.

The dangerous case first. A run that is partial for a reason UNRELATED to the
time budget (a lint block, a failed dispatch) is not time-truncated, so its
advance falls through to full HEAD. Merging that run promotes a baseline past
work whose pages were reverted -- the silent-loss bug, automated nightly. It
must stay blocked.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as runner  # noqa: E402

FAKES_BLOCK = Path(__file__).parent / "fakes_block"
FAKES_MULTI = Path(__file__).parent / "fakes_multi"


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


def test_lint_block_partial_run_advances_to_head_and_is_not_cursor_backed(
    tmp_path, init_host, read_current_run
):
    """THE DANGEROUS CASE. A lint-block partial run is not time-truncated, so
    it advances to full HEAD (pinned by test_state_advancement_invariant).
    This test pins the OTHER half: that advance is not cursor-backed, so the
    Task-3 gate will refuse to merge it."""
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "old_sha_000"}}
    )
    head_sha = _git(tmp_path, "rev-parse", "HEAD")
    rc = runner.run(tmp_path, dry_run_dir=FAKES_BLOCK, no_pr=True)
    assert rc == 0
    cr = read_current_run(state_path)
    assert cr["partial"] is True
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == head_sha
    assert runner._LAST_ADVANCE_CURSOR_BACKED is False, (
        "a run that advanced to full HEAD must never report a cursor-backed "
        "advance -- that flag is the only thing standing between a lint-block "
        "partial and an automatic merge"
    )


def test_truncated_run_with_a_real_cursor_reports_cursor_backed(tmp_path, init_host):
    """The permitted case: admission truncation with a verified in-window
    cursor. advance_sha comes from the cursor, so the flag is True and the
    advance is strictly less than HEAD."""
    repo = tmp_path
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "seed"}}
    )
    base = _git(repo, "rev-parse", "HEAD")
    shas = []
    for i in range(1, 4):
        (repo / "f.txt").write_text(f"c{i}")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    state_path.write_text(
        json.dumps({"version": "1", "last_successful_run": {"head_sha": base}})
    )
    c1, c2, c3 = shas
    fakes = tmp_path.parent / f"fakes_cce140_cb_{tmp_path.name}"
    fakes.mkdir(parents=True, exist_ok=True)
    for f in FAKES_MULTI.iterdir():
        (fakes / f.name).write_text(f.read_text())
    sc = json.loads((FAKES_MULTI / "fake_source_collector.json").read_text())
    for pr, sha in zip(sc["prs"], [c1, c2, c3]):
        pr["merge_sha"] = sha
    (fakes / "fake_source_collector.json").write_text(json.dumps(sc))

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
    assert advance == c2, written["last_successful_run"]
    assert advance != c3, "cursor-backed advance must not reach full HEAD"
    assert runner._LAST_ADVANCE_CURSOR_BACKED is True
