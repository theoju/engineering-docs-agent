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

    runner._repair_citation_paths(
        page,
        repo,
        {},
        state,
        source_paths={".claude/skills/connector-builder/references/checklist.md"},
    )

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

    runner._repair_citation_paths(page, repo, {}, state, source_paths=set())

    assert page.read_text() == original
    assert state["current_run"]["partial_reasons"] == []


def test_uncorroborated_repair_is_declined_and_reported_loudly(repo):
    """A silent decline reproduces the CCE-141 harm in a narrower band:
    block -> deferral -> forgiveness -> page never written."""
    page = repo / "page.md"
    page.write_text("See `references/checklist.md`.\n")
    state = _state()

    runner._repair_citation_paths(page, repo, {}, state, source_paths=set())

    assert page.read_text() == "See `references/checklist.md`.\n"
    cr_ = state["current_run"]
    assert any("citation_repair_declined" in r for r in cr_["partial_reasons"])
    assert cr_["partial"] is True, (
        "a decline must NOT be info_only — it means a page did not ship"
    )


def test_corroborated_repair_fires_and_stays_info_only(repo):
    full = ".claude/skills/connector-builder/references/checklist.md"
    page = repo / "page.md"
    page.write_text("See `references/checklist.md`.\n")
    state = _state()

    runner._repair_citation_paths(page, repo, {}, state, source_paths={full})

    assert full in page.read_text()
    assert state["current_run"]["partial"] is False
    assert any(
        "citation_path_repaired" in r for r in state["current_run"]["partial_reasons"]
    )


def test_a_fenced_mention_on_the_prior_page_does_not_corroborate(repo):
    """THE CRITICAL CASE, end to end. citation_exists deliberately never
    validates fenced regions, so a path named only inside a fence on the prior
    commit is not evidence the pipeline accepted a reference to it. Under a
    raw substring scan of the prior page it corroborated anyway, and a new
    page citing an invented `.github/workflows/ci.yml` was silently repointed
    at a Docusaurus test fixture — block became pass."""
    fixture = repo / "tests/fixtures/setup_repos/js_docusaurus/.github/workflows"
    fixture.mkdir(parents=True)
    (fixture / "ci.yml").write_text("on: push\n")
    full = "tests/fixtures/setup_repos/js_docusaurus/.github/workflows/ci.yml"

    page = repo / "page.md"
    page.write_text("Example only:\n\n```text\n" f"cite it as `{full}`\n" "```\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "prior")

    cited = "The workflow lives at `.github/workflows/ci.yml`.\n"
    page.write_text(cited)
    state = _state()

    runner._repair_citation_paths(page, repo, {}, state, source_paths=set())

    assert page.read_text() == cited
    assert any(
        "citation_repair_declined" in r
        for r in state["current_run"]["partial_reasons"]
    )


def test_prior_page_text_survives_a_non_utf8_page_at_head(repo):
    """A single non-UTF-8 byte in a committed page must not take down the run.
    Under corroborated repair this is on the hot path for every edit."""
    page = repo / "page.md"
    page.write_bytes(b"# Caf\xe9\n\nSee `references/checklist.md`.\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "latin1")
    page.write_text("# Cafe\n\nSee `references/checklist.md`.\n")

    got = runner._prior_page_text(repo, page)  # must not raise
    assert got is None or isinstance(got, str)


def test_source_paths_has_no_default():
    import inspect

    sig = inspect.signature(runner._repair_citation_paths)
    assert sig.parameters["source_paths"].default is inspect.Parameter.empty
