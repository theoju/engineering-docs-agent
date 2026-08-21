from __future__ import annotations
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as runner  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    subprocess.run(
        ["git", "init", "-q", str(tmp_path)], check=True, capture_output=True
    )
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    refs = tmp_path / ".claude/skills/connector-builder/references"
    refs.mkdir(parents=True)
    (refs / "checklist.md").write_text("# checklist\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def _state() -> dict:
    return {"current_run": {"partial": False, "partial_reasons": []}}


def test_repair_rewrites_the_page_and_reports_info_only(repo):
    page = repo / "page.md"
    page.write_text("See `references/checklist.md` for the steps.\n")
    state = _state()

    runner._repair_citation_paths(page, repo, {}, state)

    assert (
        ".claude/skills/connector-builder/references/checklist.md" in page.read_text()
    )
    cr = state["current_run"]
    assert cr["partial"] is False, (
        "a successful repair must not degrade the run — flipping partial here "
        "would veto auto-merge for a self-correction"
    )
    assert any("citation_path_repaired" in r for r in cr["partial_reasons"]), (
        f"the repair must be visible in the digest: {cr['partial_reasons']}"
    )


def test_no_repair_leaves_the_page_and_state_untouched(repo):
    page = repo / "page.md"
    original = "See `docs/invented.md`.\n"
    page.write_text(original)
    state = _state()

    runner._repair_citation_paths(page, repo, {}, state)

    assert page.read_text() == original
    assert state["current_run"]["partial_reasons"] == []
