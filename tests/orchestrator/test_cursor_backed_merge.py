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


def test_lint_block_partial_run_does_not_auto_merge_end_to_end(
    tmp_path, monkeypatch, init_host
):
    """Wired, not mocked at the gate: a lint-block partial run opens its PR
    and leaves it open. The FakeGhClient call log is the assertion -- no
    pr_merge, ever."""
    from gh_client import FakeGhClient, GhResult

    init_host({"version": "1", "dismissed_gap_flags": {}, "cursors": {}})
    config_path = tmp_path / ".engineering-docs-agent" / "config.yml"
    config_path.write_text(
        config_path.read_text()
        + "\nmerge:\n  policy: auto\n  checks_grace_seconds: 0\n"
        + "  checks_timeout_seconds: 0\n"
    )
    fake = None

    def _fake_factory(repo_root):
        nonlocal fake
        fake = FakeGhClient(
            pr_create=GhResult(ok=True, value=12),
            pr_view_commits=GhResult(
                ok=True,
                value=[
                    {
                        "authors": [
                            {
                                "name": "engineering-docs-agent[bot]",
                                "login": "engineering-docs-agent-bot",
                                "email": (
                                    "engineering-docs-agent@users.noreply."
                                    "github.com"
                                ),
                            }
                        ]
                    }
                ],
            ),
            pr_checks=GhResult(ok=True, value=[]),
        )
        return fake

    monkeypatch.setattr(runner, "GhClient", _fake_factory)
    real_run = runner.subprocess.run

    def selective(cmd, *a, **kw):
        if isinstance(cmd, list) and cmd[:2] == ["git", "-C"] and "push" in cmd:
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(runner.subprocess, "run", selective)

    rc = runner.run(tmp_path, dry_run_dir=FAKES_BLOCK, no_pr=False)
    assert rc == 0
    # The run must actually have reached the gate; otherwise the negative
    # assertion below is vacuous. `pr_create` proves the PR path ran.
    assert [c for c in fake.calls if c[0] == "pr_create"], fake.calls
    assert not [c for c in fake.calls if c[0] == "pr_merge"], fake.calls


# ---------------------------------------------------------------------------
# The delivery seam: run() -> _maybe_auto_merge
#
# The two tests above pin the COMPUTATION of `advance_cursor_backed` (via a
# module global) and tests/orchestrator/test_auto_merge.py pins the GATE that
# consumes it (by calling the function directly). Nothing joined them, so
# forcing `advance_cursor_backed=False` at the call site left the whole suite
# green -- CCE-140 could be entirely dead in production and CI would not say
# so. These two drive run() end to end and assert on the FakeGhClient call log.
# ---------------------------------------------------------------------------


def _seed_merge_host(tmp_path, init_host):
    """Real git window: three PR merges plus a trailing non-PR commit, with the
    baseline seeded at `base`. Returns (state_path, base, [c1, c2, c3], fakes).

    c4 exists so the newest PR merge is never HEAD: without it `advance == c2`
    and `advance != head` stop being independent statements.
    """
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "seed"}})
    base = _git(repo, "rev-parse", "HEAD")
    shas = []
    for i in range(1, 5):
        (repo / "f.txt").write_text(f"c{i}")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    state_path.write_text(
        json.dumps({"version": "1", "last_successful_run": {"head_sha": base}})
    )
    fakes = tmp_path / "fakes_merge"
    fakes.mkdir(parents=True, exist_ok=True)
    for f in FAKES_MULTI.iterdir():
        (fakes / f.name).write_text(f.read_text())
    sc = json.loads((FAKES_MULTI / "fake_source_collector.json").read_text())
    for pr, sha in zip(sc["prs"], shas[:3]):
        pr["merge_sha"] = sha
    (fakes / "fake_source_collector.json").write_text(json.dumps(sc))
    config_path = tmp_path / ".engineering-docs-agent" / "config.yml"
    config_path.write_text(
        config_path.read_text()
        + "\nmerge:\n  policy: auto\n  checks_grace_seconds: 0\n"
        + "  checks_timeout_seconds: 0\n"
    )
    return state_path, base, shas[:3], fakes


def _install_fake_gh(monkeypatch):
    """Mock the gh surface so run() can reach the merge gate: a PR that opens,
    carries only bot commits, and has zero registered checks."""
    from gh_client import FakeGhClient, GhResult

    holder = {}

    def _factory(repo_root):
        holder["gh"] = FakeGhClient(
            pr_create=GhResult(ok=True, value=12),
            pr_view_commits=GhResult(
                ok=True,
                value=[
                    {
                        "authors": [
                            {
                                "name": "engineering-docs-agent[bot]",
                                "login": "engineering-docs-agent-bot",
                                "email": (
                                    "engineering-docs-agent@users.noreply.github.com"
                                ),
                            }
                        ]
                    }
                ],
            ),
            pr_checks=GhResult(ok=True, value=[]),
            pr_merge=GhResult(ok=True, value=None),
        )
        return holder["gh"]

    monkeypatch.setattr(runner, "GhClient", _factory)
    real_run = runner.subprocess.run

    def selective(cmd, *a, **kw):
        if isinstance(cmd, list) and cmd[:2] == ["git", "-C"] and "push" in cmd:
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(runner.subprocess, "run", selective)
    return holder


def test_cursor_backed_partial_run_actually_merges_end_to_end(
    tmp_path, monkeypatch, init_host, read_current_run
):
    """THE POINT OF THE EPIC, wired. A truncated run with a verified in-window
    cursor must reach `gh pr merge`.

    Every run this pipeline produces is partial, so before CCE-140 the merge
    path never fired once and ten PRs were merged by hand. Asserting the gate
    in isolation cannot catch a mis-wired call site: forcing
    `advance_cursor_backed=False` where run() calls _maybe_auto_merge leaves
    every other test green, because the only end-to-end merge test covers a
    NON-partial run and every partial test asserts the refusal.

    `pr_merge` in the call log is the assertion. Nothing weaker distinguishes
    "the gate opened" from "the gate opened and something downstream closed it".
    """
    state_path, base, (c1, c2, c3), fakes = _seed_merge_host(tmp_path, init_host)
    gh = _install_fake_gh(monkeypatch)
    rc = runner.run(
        tmp_path,
        dry_run_dir=fakes,
        no_pr=False,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 50, 150]),
    )
    assert rc == 0
    cr = read_current_run(state_path)
    # Preconditions -- without these the merge assertion could pass for the
    # wrong reason (a non-partial run merges under the OLD rules too).
    assert cr["partial"] is True, cr
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    assert advance == c2, written["last_successful_run"]
    assert advance != _git(tmp_path, "rev-parse", "HEAD")
    fake = gh["gh"]
    assert [c for c in fake.calls if c[0] == "pr_create"], fake.calls
    assert [c for c in fake.calls if c[0] == "pr_merge"], (
        "a partial run with a cursor-backed advance is exactly the case "
        "CCE-140 exists to auto-merge; it did not reach pr_merge. "
        f"reasons={cr['partial_reasons']} calls={fake.calls}"
    )


def test_app_token_veto_blocks_the_merge_end_to_end(
    tmp_path, monkeypatch, init_host, read_current_run
):
    """The veto, wired. Same run as above -- same cursor, same eligibility --
    with only DOCS_AGENT_APP_TOKEN_STATUS=failure added.

    A PR built on the fallback GITHUB_TOKEN never triggers host CI, so
    `gh pr checks` returns [] and reads as green. The cursor proves the
    baseline is honest; it proves nothing about whether anything validated
    this PR. That coupling used to be carried by accident by the
    unconditional partial gate, and CCE-140 removed it -- so the veto is now
    the only thing holding it, and it was never tested through run().

    Asserting cursor-backed is True is what makes the refusal attributable:
    without it, a broken cursor would produce the same green.
    """
    state_path, base, (c1, c2, c3), fakes = _seed_merge_host(tmp_path, init_host)
    gh = _install_fake_gh(monkeypatch)
    monkeypatch.setenv("DOCS_AGENT_APP_TOKEN_STATUS", "failure")
    rc = runner.run(
        tmp_path,
        dry_run_dir=fakes,
        no_pr=False,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 50, 150]),
    )
    assert rc == 0
    cr = read_current_run(state_path)
    assert runner._LAST_ADVANCE_CURSOR_BACKED is True, (
        "the run must still be cursor-backed, or this test proves nothing "
        "about the veto -- it would just be re-testing the partial gate"
    )
    fake = gh["gh"]
    assert [c for c in fake.calls if c[0] == "pr_create"], fake.calls
    assert not [c for c in fake.calls if c[0] == "pr_merge"], fake.calls
    assert any("merge_vetoed" in r for r in cr["partial_reasons"]), cr[
        "partial_reasons"
    ]
