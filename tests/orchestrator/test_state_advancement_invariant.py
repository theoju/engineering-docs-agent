# tests/orchestrator/test_state_advancement_invariant.py
"""CCE-62: regression tests pinning the §8 state-advancement invariant.

Per spec §8 (`docs/superpowers/specs/2026-05-19-engineering-docs-agent-design.md`)
the contract has two branches:

  - Subagent crash/timeout: orchestrator continues; PR opens with
    "(partial)" body. Per CCE-40 §7 row 4, `last_successful_run.head_sha`
    intentionally advances on the docs-agent branch — operators see the
    partial flag and decide whether to merge.

  - PR create/update fails: hard fail (`run()` returns 1). The on-disk
    advance in the runner's working tree is acknowledged as ephemeral per
    CCE-40 §7 row 3 — `actions/checkout@v5` provisions a fresh tree at the
    next nightly fire, so the un-pushed advance does not reach main.

These tests pin both branches so a future refactor cannot silently regress
either one without breaking at least one of these tests.
"""

from __future__ import annotations
import importlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

ORCH_RUNNER = Path(__file__).parent.parent.parent / "scripts" / "orchestrator_runner.py"
FAKES_OK = Path(__file__).parent / "fakes"
FAKES_SC_ERROR = Path(__file__).parent / "fakes_sc_error"
FAKES_BLOCK = Path(__file__).parent / "fakes_block"


def _head_sha(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _run_subproc(tmp_path: Path, fakes_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(ORCH_RUNNER),
            "--repo-root",
            str(tmp_path),
            "--no-pr",
            "--dry-run-subagents",
            str(fakes_dir),
        ],
        capture_output=True,
        text=True,
    )


def test_partial_run_via_source_collector_error_advances_state(
    tmp_path, init_host, read_current_run
):
    """Subagent-error path: source-collector returns error+partial. The run
    proceeds, ends with current_run.partial=True, and state.json on disk
    still advances last_successful_run.head_sha to HEAD.

    Per CCE-40 §7 row 4: this is intentional. The PR carries "(partial)"
    in its body and the operator decides whether to merge.
    """
    seeded = {"version": "1", "last_successful_run": {"head_sha": "old_sha_000"}}
    state_path = init_host(seeded)
    head_sha = _head_sha(tmp_path)

    result = _run_subproc(tmp_path, FAKES_SC_ERROR)
    assert result.returncode == 0, f"runner failed: {result.stderr}"

    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == head_sha, (
        "partial-via-source-collector-error must STILL advance "
        "last_successful_run.head_sha per CCE-40 §7 row 4 — operator decides "
        "on merge. Found: "
        f"{written['last_successful_run']['head_sha']}, expected {head_sha}"
    )
    # CCE-40: persistent state.json must never carry current_run.
    assert "current_run" not in written, (
        f"current_run leaked into persistent state.json: {written}"
    )

    cr = read_current_run(state_path)
    assert cr["partial"] is True, (
        f"partial flag must be True after source_collector error; got {cr}"
    )
    assert any("source_collector_error" in r for r in cr["partial_reasons"]), (
        f"partial_reasons must contain source_collector_error: {cr['partial_reasons']}"
    )


def test_partial_run_via_lint_block_advances_state(
    tmp_path, init_host, read_current_run
):
    """Lint-block path: content-validator returns a block-severity failure.
    The blocked file is unlinked, current_run.partial=True, but state.json
    on disk still advances last_successful_run.head_sha.
    """
    seeded = {"version": "1", "last_successful_run": {"head_sha": "old_sha_000"}}
    state_path = init_host(seeded)
    head_sha = _head_sha(tmp_path)

    result = _run_subproc(tmp_path, FAKES_BLOCK)
    assert result.returncode == 0, f"runner failed: {result.stderr}"

    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == head_sha, (
        "partial-via-lint-block must STILL advance last_successful_run.head_sha "
        "per CCE-40 §7 row 4. Found: "
        f"{written['last_successful_run']['head_sha']}, expected {head_sha}"
    )
    assert "current_run" not in written, (
        f"current_run leaked into persistent state.json: {written}"
    )

    cr = read_current_run(state_path)
    assert cr["partial"] is True
    assert any("lint_block" in r for r in cr["partial_reasons"]), (
        f"partial_reasons must contain lint_block: {cr['partial_reasons']}"
    )


def test_pr_open_failure_returns_1_and_records_partial_reason(
    tmp_path, monkeypatch, init_host, read_current_run
):
    """PR-open-failure path (§8 row 7): the runner hard-fails (returns 1).

    Per CCE-40 §7 row 3, the working-tree advance is acknowledged as
    ephemeral — the CI workflow's fresh ``actions/checkout@v5`` at the next
    nightly fire is what enforces "not advanced to main". Pinning the
    on-disk advance here means any future refactor that tries to gate the
    advance on PR success must update the spec and this test together.
    """
    import orchestrator_runner as runner

    # Reload so prior monkeypatches in this session don't leak in.
    importlib.reload(runner)

    seeded = {"version": "1", "last_successful_run": {"head_sha": "old_sha_000"}}
    state_path = init_host(seeded)
    head_sha = _head_sha(tmp_path)

    captured: dict = {}

    def fake_open_or_append_pr(
        repo_root, gh, *, branch, now_iso, partial, partial_reasons, **_kw
    ):
        # **_kw absorbs CCE-89 D1 kwargs (lens_paths, baseline_sha, current_sha)
        # so the existing invariant test stays focused on partial-reason routing.
        captured["partial"] = partial
        captured["partial_reasons"] = list(partial_reasons)
        return None, [("forced_failure: pr_open simulated", False)]

    monkeypatch.setattr(runner, "open_or_append_pr", fake_open_or_append_pr)

    # GhClient constructor is benign (no network) — open_or_append_pr is
    # mocked so the client is never actually called.
    rc = runner.run(tmp_path, dry_run_dir=FAKES_OK, no_pr=False)

    assert rc == 1, "PR-open failure must hard-fail (return 1) per spec §8 row 7"

    written = json.loads(state_path.read_text())
    # CCE-40 §7 row 3: the on-disk advance is the working-tree write; CI's
    # checkout cycle is what enforces "not advanced to main". This assertion
    # pins that design choice so a future "fix" that conditionally gates the
    # advance breaks this test loudly.
    assert written["last_successful_run"]["head_sha"] == head_sha, (
        "on-disk state.json reflects the working-tree write per CCE-40 §7 "
        "row 3; CI's fresh checkout discards it when PR-open fails. Found: "
        f"{written['last_successful_run']['head_sha']}, expected {head_sha}"
    )
    assert "current_run" not in written

    cr = read_current_run(state_path)
    assert any("forced_failure" in r for r in cr["partial_reasons"]), (
        f"partial_reasons must contain forced_failure: {cr['partial_reasons']}"
    )

    # Sanity: the runner did pass through the partial flag and reasons to
    # open_or_append_pr (so a real failure mode would show "(partial)" in
    # the PR body when there are partial_reasons).
    assert "partial" in captured, "open_or_append_pr was never called"
