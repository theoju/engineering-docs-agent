"""CCE-141 revision 3: the orchestrator seam of the DETECTION-ONLY diagnostic.

`_diagnose_citation_paths` reads the authored page, reports what each blocked
citation was probably shortened from, and returns. It never writes the page.
"""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as runner  # noqa: E402

FAKES = Path(__file__).parent / "fakes"


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


FULL = ".claude/skills/connector-builder/references/checklist.md"


def _state() -> dict:
    return {"current_run": {"partial": False, "partial_reasons": []}}


def test_a_corroborated_shortening_is_reported_and_stays_info_only(repo):
    """The finding is visible in the digest and does NOT degrade the run.

    Classification change from revision 2: this line used to be degraded=True,
    on the reasoning that a decline meant a page did not ship. Nothing here
    affects whether the page ships — `citation_exists` decides that, and its
    block is already reported and already classified — so a second degraded
    reason would double-count one failure and cost the run auto-merge through
    CCE-140's `partial and not advance_cursor_backed` gate.
    """
    page = repo / "page.md"
    page.write_text("See `references/checklist.md` for the steps.\n")
    state = _state()

    runner._diagnose_citation_paths(page, repo, {}, state, source_paths={FULL})

    cr = state["current_run"]
    assert any(
        "citation_shortening_suspected" in r and "corroborated" in r
        for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    assert cr["partial"] is False, (
        "an advisory must not degrade the run: the page's block is already "
        "reported by lint_block, and flipping partial here double-counts it"
    )
    assert "blind" not in cr or cr["blind"] is False


def test_the_page_is_never_written(repo):
    """THE POINT OF REVISION 3. The page's bytes and mtime-bearing content are
    untouched even when a corroborated candidate is found — the whole class of
    defects four review rounds surfaced needed a write to happen."""
    page = repo / "page.md"
    original = "See `references/checklist.md` for the steps.\n"
    page.write_text(original)

    runner._diagnose_citation_paths(page, repo, {}, _state(), source_paths={FULL})

    assert page.read_text() == original, "the diagnostic rewrote the page"
    assert FULL not in page.read_text()


def test_an_uncorroborated_shortening_is_reported_not_silently_dropped(repo):
    """Revision 2 declined this loudly-but-as-a-degradation; revision 3 reports
    it as an advisory with the label that says how much to trust it."""
    page = repo / "page.md"
    page.write_text("See `references/checklist.md`.\n")
    state = _state()

    runner._diagnose_citation_paths(page, repo, {}, state, source_paths=set())

    cr = state["current_run"]
    assert any(
        "citation_shortening_suspected" in r and "uncorroborated" in r
        for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    assert cr["partial"] is False


def test_an_unmatched_citation_is_still_reported(repo):
    """The zero-match case reaches the digest too. Silence here is what made
    the old digest untrustworthy as a census of blocked citations."""
    page = repo / "page.md"
    page.write_text("See `docs/invented.md`.\n")
    state = _state()

    runner._diagnose_citation_paths(page, repo, {}, state, source_paths=set())

    assert any(
        "citation_shortening_suspected" in r and "no_candidate" in r
        for r in state["current_run"]["partial_reasons"]
    ), state["current_run"]["partial_reasons"]


def test_a_fenced_mention_on_the_prior_page_does_not_corroborate(repo):
    """citation_exists deliberately never validates fenced regions, so a path
    named only inside a fence on the prior commit is not evidence the pipeline
    accepted a reference to it. Under a raw substring scan it corroborated
    anyway. It no longer decides whether anything happens to the page — but it
    still decides the CONFIDENCE an operator reads, and an over-confident
    label on a confabulated citation is how a reviewer is talked into the
    wrong edit."""
    fixture = repo / "tests/fixtures/setup_repos/js_docusaurus/.github/workflows"
    fixture.mkdir(parents=True)
    (fixture / "ci.yml").write_text("on: push\n")
    full = "tests/fixtures/setup_repos/js_docusaurus/.github/workflows/ci.yml"

    page = repo / "page.md"
    page.write_text(f"Example only:\n\n```text\ncite it as `{full}`\n```\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "prior")

    cited = "The workflow lives at `.github/workflows/ci.yml`.\n"
    page.write_text(cited)
    state = _state()

    runner._diagnose_citation_paths(page, repo, {}, state, source_paths=set())

    assert page.read_text() == cited
    reasons = state["current_run"]["partial_reasons"]
    assert any("uncorroborated" in r for r in reasons), reasons
    assert not any("(corroborated)" in r for r in reasons), reasons


def test_the_prior_committed_page_supplies_rung_1_corroboration(repo):
    """`_prior_page_text` is threaded for a reason: on an EDIT the prior
    commit is the git-authoritative half of the corroborator ladder.

    Here `source_paths` is EMPTY, so rung 2 contributes nothing and the
    `corroborated` label can only come from the prior page — which cited the
    full path in unfenced prose, exactly the site `citation_exists` validated.
    Cutting the `_prior_page_text` thread downgrades this to
    `uncorroborated`.
    """
    page = repo / "page.md"
    page.write_text(f"The checklist lives at `{FULL}`.\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "prior cites the full path")

    page.write_text("See `references/checklist.md`.\n")
    state = _state()

    runner._diagnose_citation_paths(page, repo, {}, state, source_paths=set())

    reasons = state["current_run"]["partial_reasons"]
    assert any("(corroborated)" in r for r in reasons), reasons


def test_prior_page_text_survives_a_non_utf8_page_at_head(repo):
    """A single non-UTF-8 byte in a committed page must not take down the run.
    This is on the hot path for every edit."""
    page = repo / "page.md"
    page.write_bytes(b"# Caf\xe9\n\nSee `references/checklist.md`.\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "latin1")
    page.write_text("# Cafe\n\nSee `references/checklist.md`.\n")

    got = runner._prior_page_text(repo, page)  # must not raise
    assert got is None or isinstance(got, str)


def test_a_malformed_mkdocs_yml_does_not_take_down_the_run(repo):
    """A diagnostic must never be fatal.

    `citation_exists._build_dir` catches OSError and yaml.YAMLError, but a
    `mkdocs.yml` whose top level is a YAML LIST parses cleanly and then raises
    AttributeError on `mk.get("site_dir")`. There is no top-level handler in
    `run()` or `main()`, so before the broad wrapper this killed the entire
    unattended nightly for an advisory.

    Reported rather than swallowed, and reported as an advisory: a broken
    diagnostic has no bearing on page correctness, but a diagnostic that
    silently stopped working is indistinguishable from one with nothing to say.
    """
    (repo / "mkdocs.yml").write_text("- one\n- two\n")
    page = repo / "page.md"
    page.write_text("See `references/checklist.md`.\n")
    state = _state()

    # Fixture guard: the failure must be REAL, not simulated. Without the
    # wrapper this call propagates AttributeError out of run().
    import citation_repair

    with pytest.raises(AttributeError):
        citation_repair.diagnose(
            page.read_text(), repo, {}, citation_repair.tracked_files(repo), set()
        )

    runner._diagnose_citation_paths(page, repo, {}, state, source_paths=set())

    cr = state["current_run"]
    assert any(
        "citation_diagnosis_failed" in r and "AttributeError" in r
        for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    assert cr["partial"] is False, "a broken advisory must not degrade the run"


def test_an_undecodable_page_is_passed_over_in_silence(repo):
    """The narrow read_text guard, kept deliberately in front of the broad
    wrapper. `citation_exists.check_path` already reports an undecodable page
    in its own words ("file not decodable as UTF-8"); a second, vaguer
    `citation_diagnosis_failed` line from here would be noise attached to a
    failure someone else already named. Without the guard the broad wrapper
    catches the UnicodeDecodeError and emits exactly that noise."""
    page = repo / "page.md"
    page.write_bytes(b"# Caf\xe9\n\nSee `references/checklist.md`.\n")
    state = _state()

    runner._diagnose_citation_paths(page, repo, {}, state, source_paths=set())

    assert state["current_run"]["partial_reasons"] == []


def test_source_paths_has_no_default():
    import inspect

    sig = inspect.signature(runner._diagnose_citation_paths)
    assert sig.parameters["source_paths"].default is inspect.Parameter.empty


def test_the_diagnostic_never_writes_a_page():
    """Source-level pin on the orchestrator half, matching the module-level one
    in test_citation_repair.py. `path.write_text(new_text)` lived here in
    revision 2 and is what made every Critical possible."""
    import ast
    import inspect as _inspect

    tree = ast.parse(_inspect.getsource(runner._diagnose_citation_paths))
    writes = [
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in {"write_text", "write_bytes", "rename", "replace", "unlink"}
    ]
    assert writes == [], f"the diagnostic must not mutate anything: {writes}"


# --- the production call site ----------------------------------------------
#
# Everything above drives `_diagnose_citation_paths` directly. That left the
# real call site in `run()` UNPINNED: replacing `if target_path.exists():` with
# `if False:` -- disabling the feature outright -- kept the whole 1531-test
# suite green, because every dry-run synth page is citation-free and all 43
# real invocations are no-ops. The test below is what fails when the call site
# is removed.

_SEED_STATE = {"version": "1", "dismissed_gap_flags": {}, "cursors": {}}

# The dry-run fakes drive one batch: source-collector reports PR #1 touching
# `backend/connectors/foo.py`, and the summarizer routes it to
# `core / connectors/foo.md`. So the page the runner authors is
# docs/site-src/core/connectors/foo.md and the grounding threaded into
# `source_paths` is exactly {"backend/connectors/foo.py"}.
_TARGET = "docs/site-src/core/connectors/foo.md"
_GROUNDED = "backend/connectors/foo.py"
_SHORTENED = "connectors/foo.py"


def test_the_production_call_site_diagnoses_an_authored_page(
    tmp_path, init_host, read_current_run
):
    """THE CALL-SITE PIN. Drives the real `run()`.

    The page is SEEDED (so it is tracked, in HEAD, and already exists when
    authoring reaches it) carrying a citation shortened from the batch's own
    grounding file. Because the page exists, the dry-run synth does not
    overwrite it — which is exactly why every other dry-run test's page is
    citation-free and why this call site was previously unreachable from the
    suite.

    Asserting on the `corroborated` label rather than merely on the reason
    prefix pins the `source_paths=grounding` thread too: if the call site
    stopped passing the batch's grounding, the same finding would arrive
    labelled `uncorroborated` and this would fail.
    """
    page_text = (
        "# foo connector\n\n"
        f"The connector lives at `{_SHORTENED}` and is wired at startup.\n"
    )
    state_path = init_host(
        _SEED_STATE,
        seed_files={_TARGET: page_text, _GROUNDED: "def connect():\n    return 1\n"},
    )

    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)
    assert rc == 0

    # The page is untouched: detection only, all the way through the seam.
    assert (tmp_path / _TARGET).read_text() == page_text

    cr = read_current_run(state_path)
    hits = [r for r in cr["partial_reasons"] if "citation_shortening_suspected" in r]
    assert hits, (
        "the production call site produced no diagnosis for a page carrying a "
        f"shortened citation: {cr['partial_reasons']}"
    )
    assert any(
        _TARGET in r
        and f"'{_SHORTENED}'" in r
        and f"'{_GROUNDED}'" in r
        and "(corroborated)" in r
        for r in hits
    ), hits
    assert cr["partial"] is False, (
        "the diagnostic is info_only, so it must not flip partial on an "
        f"otherwise-clean run: {cr['partial_reasons']}"
    )
