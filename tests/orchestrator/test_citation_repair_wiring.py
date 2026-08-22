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


def test_a_run_input_shortening_is_reported_and_stays_info_only(repo):
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
        "citation_shortening_suspected" in r and "(candidate_in_run_inputs)" in r
        for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    assert cr["partial"] is False, (
        "an advisory must not degrade the run: the page's block is already "
        "reported by lint_block, and flipping partial here double-counts it"
    )
    assert "blind" not in cr or cr["blind"] is False


def test_the_page_is_never_written(repo):
    """THE POINT OF REVISION 3. The page's bytes and mtime-bearing content are
    untouched even when a top-labelled candidate is found — the whole class of
    defects four review rounds surfaced needed a write to happen."""
    page = repo / "page.md"
    original = "See `references/checklist.md` for the steps.\n"
    page.write_text(original)

    runner._diagnose_citation_paths(page, repo, {}, _state(), source_paths={FULL})

    assert page.read_text() == original, "the diagnostic rewrote the page"
    assert FULL not in page.read_text()


def test_a_suffix_match_only_shortening_is_reported_not_silently_dropped(repo):
    """Revision 2 declined this loudly-but-as-a-degradation; revision 3 reports
    it as an advisory with the label that says how much to trust it."""
    page = repo / "page.md"
    page.write_text("See `references/checklist.md`.\n")
    state = _state()

    runner._diagnose_citation_paths(page, repo, {}, state, source_paths=set())

    cr = state["current_run"]
    assert any(
        "citation_shortening_suspected" in r and "(suffix_match_only)" in r
        for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    assert cr["partial"] is False


def test_a_no_candidate_citation_is_kept_out_of_the_digest(repo):
    """FIX 3. `no_candidate` means the module LOOKED for a tracked file ending
    in that tail and found none — its own evidence says the token is not a
    shortening of anything in the repo. Emitting it under
    `citation_shortening_suspected` filed the dominant population under a key
    asserting the opposite of what was measured.

    Dropped from the digest rather than renamed, because a renamed key would
    still carry ZERO added information: `lint_block` already names every one
    of those paths, with severity, on the same run. One page with 40
    confabulated citations produced 1 lint_block line and 40 diagnosis lines.
    Renaming would have kept 40 lines of nothing in front of the operator and
    buried the findings that do name a file.

    The finding is DROPPED FROM THE DIGEST, not from the module: `diagnose`
    still returns it, which the second half asserts. A future caller that
    wants the census can have it; the digest is where it earns nothing.
    """
    page = repo / "page.md"
    page.write_text("See `docs/invented.md`.\n")
    state = _state()

    runner._diagnose_citation_paths(page, repo, {}, state, source_paths=set())

    assert state["current_run"]["partial_reasons"] == [], (
        "a no_candidate finding must not reach the digest: lint_block already "
        "names that path and the label asserts the opposite of the evidence"
    )

    import citation_repair

    assert citation_repair.diagnose(
        page.read_text(), repo, {}, citation_repair.tracked_files(repo), set()
    ) == [("docs/invented.md", "", "no_candidate")], (
        "the finding must still cross diagnose's return boundary — only the "
        "digest drops it"
    )


def test_a_fenced_mention_on_the_prior_page_is_not_a_run_input(repo):
    """citation_exists deliberately never validates fenced regions, so a path
    named only inside a fence on the prior commit is not evidence the pipeline
    accepted a reference to it. Under a raw substring scan it counted
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
    assert any("(suffix_match_only)" in r for r in reasons), reasons
    assert not any("(candidate_in_run_inputs)" in r for r in reasons), reasons


def test_the_prior_committed_page_supplies_rung_1(repo):
    """`_prior_page_text` is threaded for a reason: on an EDIT the prior
    commit is the git-authoritative half of the run-input ladder.

    Here `source_paths` is EMPTY, so rung 2 contributes nothing and the
    `candidate_in_run_inputs` label can only come from the prior page — which
    cited the full path in unfenced prose, exactly the site `citation_exists`
    validated. Cutting the `_prior_page_text` thread downgrades this to
    `suffix_match_only`.
    """
    page = repo / "page.md"
    page.write_text(f"The checklist lives at `{FULL}`.\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "prior cites the full path")

    page.write_text("See `references/checklist.md`.\n")
    state = _state()

    runner._diagnose_citation_paths(page, repo, {}, state, source_paths=set())

    reasons = state["current_run"]["partial_reasons"]
    assert any("(candidate_in_run_inputs)" in r for r in reasons), reasons


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


def _write_attrs() -> set[str]:
    """The module-level guard's attribute set, imported rather than re-listed.

    This test used to spell its own, four names SHORTER — `writelines`,
    `write`, `touch` and `mkdir` were missing — so `path.touch()` and
    `path.open("w").write(...)` inside `_diagnose_citation_paths` both passed
    the full suite while the same two calls inside `citation_repair` were
    caught. A guard that guards less than the one it claims to match is worse
    than no guard: it reads as coverage. Loaded by path because the two test
    files are not an importable package.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_cr_module_test", Path(__file__).with_name("test_citation_repair.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._WRITE_ATTRS


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
        and n.func.attr in _write_attrs()
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

    Asserting on the `candidate_in_run_inputs` label rather than merely on
    the reason prefix pins the `source_paths=grounding_by_path[...]` thread
    too: if the call site stopped passing the page's own batch grounding, the
    same finding would arrive labelled `suffix_match_only` and this would
    fail. That is the SUBSTRING TRAP this file fell into once — asserting
    `"corroborated" in r` was satisfied by `"uncorroborated"`, so it could not
    distinguish the two labels, the one thing its name claimed. Every label
    assertion here is now parenthesised and exact.
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
        and "(candidate_in_run_inputs)" in r
        for r in hits
    ), hits
    assert cr["partial"] is False, (
        "the diagnostic is info_only, so it must not flip partial on an "
        f"otherwise-clean run: {cr['partial_reasons']}"
    )


# --- the seam: a finished tree, not a half-built one -------------------------

FAKES_SIBLING = Path(__file__).parent / "fakes_sibling_citation"
_CITING = "docs/site-src/core/connectors/foo.md"
_CITED_SIBLING = "docs/site-src/core/connectors/bar.md"
# A tracked decoy whose tail is exactly the sibling's path. Without it the
# mid-loop finding would be `no_candidate`, which the digest no longer prints
# at all — the test would then pass with the call back inside the loop and
# pin nothing. With it, a mid-loop diagnosis produces a LOUD digest line
# telling an operator to repoint a working citation at a vendored mirror.
_DECOY = "vendor/mirror/" + _CITED_SIBLING


def test_a_citation_to_a_sibling_the_same_run_authors_is_not_reported(
    tmp_path, init_host, read_current_run
):
    """THE SEAM PIN. The diagnosis must run against the FINISHED tree.

    `fakes_sibling_citation` drives two doc_targets through one authoring
    loop: `connectors/foo.md` (seeded, so authoring EDITS it and the dry-run
    synth leaves its citation intact) and `connectors/bar.md` (created during
    the same run, after foo). foo cites bar.

    Called from inside the authoring loop, the diagnosis evaluated `_resolves`
    against a tree that was still being built: bar did not exist yet, so foo's
    perfectly good citation was diagnosed while `citation_exists.check_path`
    on the finished tree answers ok. A digest that flags citations the linter
    accepts is not a census — it is noise that trains an operator to ignore it.

    Both halves are asserted, because the property is that THE TWO VIEWS
    AGREE: the linter passes the page, and the digest says nothing about it.
    """
    state_path = init_host(
        _SEED_STATE,
        seed_files={
            _CITING: (
                "# foo connector\n\n"
                f"The bar connector is documented at `{_CITED_SIBLING}`.\n"
            ),
            _DECOY: "# a vendored mirror of the sibling page\n",
        },
    )

    rc = runner.run(tmp_path, dry_run_dir=FAKES_SIBLING, no_pr=True)
    assert rc == 0

    # Fixture guards: the sibling really was authored by THIS run (so the
    # citation really was unresolvable at the moment foo was authored), and
    # the decoy really is a unique strict suffix match (so a mid-loop
    # diagnosis really would print a line rather than being dropped as
    # `no_candidate`).
    assert (tmp_path / _CITED_SIBLING).exists(), "the sibling page was never authored"
    import citation_repair

    assert citation_repair.suffix_candidates(
        _CITED_SIBLING, citation_repair.tracked_files(tmp_path)
    ) == [_DECOY]

    sys.path.insert(0, str(Path(runner.__file__).resolve().parent / "lint"))
    import citation_exists

    ok, detail = citation_exists.check_path(
        tmp_path / _CITING,
        tmp_path,
        citation_exists.tracked_files(tmp_path),
        {"docs": {"source_dir": "docs/site-src"}},
    )
    assert ok, f"fixture guard: the linter must ACCEPT this page, got {detail}"

    cr = read_current_run(state_path)
    hits = [r for r in cr["partial_reasons"] if _CITED_SIBLING in r and "->" in r]
    assert hits == [], (
        "the diagnosis ran against a half-built tree and flagged a citation "
        f"the linter accepts: {hits}"
    )


# --- the reporting seam: completeness, and the bounds on it -----------------
#
# All four of these mutations to the reporting loop survived the FULL suite
# before these tests existed:
#     for cited, candidate, confidence in shown:  ->  ... in shown[:1]:
#                                                     ... in shown[-1:]:
#                                                     ... in shown[:2]:
#     inserting `if confidence == "ambiguous": continue` as the loop's first
#     line
# The test file's own words are "the digest is a census of blocked citations
# or it is nothing", and nothing pinned it HERE, at the seam that writes it.


def _commit(repo: Path, rels: list[str]) -> None:
    for rel in rels:
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"# {rel}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixture files")


def _suspected(state: dict) -> list[str]:
    return [
        r
        for r in state["current_run"]["partial_reasons"]
        if r.startswith("citation_shortening_suspected:")
    ]


def test_the_digest_reports_every_finding_on_a_page_not_a_slice_of_them(repo):
    """THE CENSUS PROPERTY, pinned at the seam that writes the digest.

    Three findings, asserted as an exact ordered list. `[:1]`, `[-1:]` and
    `[:2]` each drop at least one line and each fail here.
    """
    _commit(repo, ["pkg/alpha/one.md", "pkg/beta/two.md", "pkg/gamma/three.md"])
    page = repo / "page.md"
    page.write_text(
        "First: `alpha/one.md`.\n"
        "Second: `beta/two.md`.\n"
        "Third: `gamma/three.md`.\n"
    )
    state = _state()

    runner._diagnose_citation_paths(page, repo, {}, state, source_paths=set())

    assert _suspected(state) == [
        "citation_shortening_suspected: page.md: 'alpha/one.md' -> "
        "'pkg/alpha/one.md' (suffix_match_only)",
        "citation_shortening_suspected: page.md: 'beta/two.md' -> "
        "'pkg/beta/two.md' (suffix_match_only)",
        "citation_shortening_suspected: page.md: 'gamma/three.md' -> "
        "'pkg/gamma/three.md' (suffix_match_only)",
    ], state["current_run"]["partial_reasons"]


def test_an_ambiguous_finding_reaches_the_digest(repo):
    """The `ambiguous` class must not be filtered at the reporting seam.

    Inserting `if confidence == "ambiguous": continue` into the loop survived
    the whole suite. Ambiguity is the case an operator most needs to see: the
    page blocked, several tracked files end with that tail, and only a human
    can pick. Silently dropping it recreates exactly the inconsistency that
    made the old digest untrustworthy.
    """
    _commit(repo, ["a/shared/dup.md", "b/shared/dup.md"])
    page = repo / "page.md"
    page.write_text("Both of them: `shared/dup.md`.\n")
    state = _state()

    runner._diagnose_citation_paths(page, repo, {}, state, source_paths=set())

    assert _suspected(state) == [
        "citation_shortening_suspected: page.md: 'shared/dup.md' -> "
        "'a/shared/dup.md, b/shared/dup.md' (ambiguous)"
    ], state["current_run"]["partial_reasons"]


def test_findings_are_capped_per_page_and_the_cap_says_what_it_withheld(repo):
    """FIX 4, second half. A page whose author confabulated wholesale can
    produce dozens of findings; past a handful they stop being a census an
    operator reads and become a wall they skip.

    The cap is the easy part. The line that says how many were withheld is the
    load-bearing part: a SILENTLY truncated digest reads as a complete one,
    which is the exact failure mode this whole ticket exists to fight.
    """
    n = runner._CITATION_FINDINGS_CAP + 2
    _commit(repo, [f"pkg/f{i:02d}/x.md" for i in range(n)])
    page = repo / "page.md"
    page.write_text("".join(f"See `f{i:02d}/x.md`.\n" for i in range(n)))
    state = _state()

    runner._diagnose_citation_paths(page, repo, {}, state, source_paths=set())

    hits = _suspected(state)
    assert len(hits) == runner._CITATION_FINDINGS_CAP, hits
    assert hits[0].endswith("'f00/x.md' -> 'pkg/f00/x.md' (suffix_match_only)")
    assert (
        f"citation_diagnosis_truncated: page.md: reported "
        f"{runner._CITATION_FINDINGS_CAP} of {n} findings; "
        f"{n - runner._CITATION_FINDINGS_CAP} withheld"
    ) in state["current_run"]["partial_reasons"], state["current_run"][
        "partial_reasons"
    ]


# 30 x 11 - 1 = 329 characters, comfortably over _STDERR_TRUNCATE and
# comfortably under PATH_MAX once tmp_path is prepended. Each segment is 11
# bytes, far under the 255-byte per-component limit.
_DEEP = "/".join(f"seg{i:02d}aaaa" for i in range(30))


def test_the_reason_truncates_the_llm_authored_halves_of_the_line(repo):
    """FIX 4, first half. `cited` and `candidate` are LLM-authored text with
    no length bound, embedded verbatim into a state reason that ends up in the
    PR body. This file already defines `_STDERR_TRUNCATE = 300` and applies it
    to every other embedded untrusted string; the citation lines did not.

    Measured before the fix: a 40,000-char citation token produced a single
    40,198-byte `partial_reasons` entry, and 40 pages x 40 blocked citations
    produced a 167,005-byte PR body against GitHub's 65,536-byte limit.

    The EXISTING convention is applied — no new one is invented.
    """
    tracked = f"vendor/{_DEEP}/y.md"
    _commit(repo, [tracked])
    cited = f"{_DEEP}/y.md"
    page = repo / "page.md"
    page.write_text(f"See `{cited}`.\n")
    state = _state()

    # Fixture guards: the token really is over the limit, and it really does
    # reach the digest (a no_candidate finding would be dropped instead).
    assert len(cited) > runner._STDERR_TRUNCATE
    import citation_repair

    assert citation_repair.suffix_candidates(
        cited, citation_repair.tracked_files(repo)
    ) == [tracked]

    runner._diagnose_citation_paths(page, repo, {}, state, source_paths=set())

    hits = _suspected(state)
    assert len(hits) == 1, hits
    assert f"'{cited[: runner._STDERR_TRUNCATE]}'" in hits[0]
    assert cited not in hits[0], "the untruncated token reached the digest"


def test_a_diagnosis_failure_names_the_page_by_its_repo_relative_label(repo):
    """The failure line used a bare `path.name` while the finding line used
    the repo-relative label — so `citation_diagnosis_failed: index.md: …` did
    not say WHICH index.md. Worse, `add_partial` dedupes identical strings, so
    every `index.md` in a run collapsed into one line naming no page at all.

    Both pages fail here. With `path.name` the two reasons are byte-identical
    and the dedupe leaves ONE; with `label` there are two, each naming its
    page. The exception message is also truncated: `str(exc)` is the least
    bounded string of the three.
    """
    _commit(repo, ["docs/a/index.md", "docs/b/index.md"])
    state = _state()

    import citation_repair

    boom = "E" * 40_000

    def _explode(_repo_root):
        raise RuntimeError(boom)

    original = citation_repair.tracked_files
    citation_repair.tracked_files = _explode
    try:
        for rel in ("docs/a/index.md", "docs/b/index.md"):
            runner._diagnose_citation_paths(
                repo / rel, repo, {}, state, source_paths=set()
            )
    finally:
        citation_repair.tracked_files = original

    failures = [
        r
        for r in state["current_run"]["partial_reasons"]
        if r.startswith("citation_diagnosis_failed:")
    ]
    assert len(failures) == 2, (
        "a bare basename makes the two reasons identical and add_partial "
        f"dedupes them into one: {failures}"
    )
    assert any("docs/a/index.md" in r for r in failures), failures
    assert any("docs/b/index.md" in r for r in failures), failures
    assert all(boom not in r for r in failures), "str(exc) reached state untruncated"
    assert all(len(r) < 2 * runner._STDERR_TRUNCATE for r in failures), failures


def test_the_run_wide_cap_bounds_what_reaches_the_pr_body(repo):
    """ROUND 6. The per-page cap bounds ONE page and says nothing about their
    sum — and it is the sum that reaches the PR body.

    `_format_partial_digest` joins every reason unconditionally, so N pages x
    `_CITATION_FINDINGS_CAP` findings x ~950 bytes (label, cited and candidate
    are truncated at `_STDERR_TRUNCATE` SEPARATELY) clears GitHub's 65,536-byte
    limit at roughly seven pages. Round 5 called the digest BOUNDED after
    fixing only the per-page half.
    """
    per_page = runner._CITATION_FINDINGS_CAP
    pages = (runner._CITATION_RUN_FINDINGS_CAP // per_page) + 2
    _commit(repo, [f"pkg/f{i:03d}/x.md" for i in range(pages * per_page)])
    state = _state()

    i = 0
    for pg in range(pages):
        page = repo / f"page{pg}.md"
        page.write_text("".join(f"See `f{i + k:03d}/x.md`.\n" for k in range(per_page)))
        i += per_page
        runner._diagnose_citation_paths(page, repo, {}, state, source_paths=set())

    assert len(_suspected(state)) == runner._CITATION_RUN_FINDINGS_CAP

    # EVERY line the feature contributes, not just the findings. Asserting on
    # the `suspected` subset alone was vacuous: deleting the `return` that
    # follows the run-cap line still passed, because `[:room]` already empties
    # `shown` — while each page past the cap went on to emit its OWN
    # `citation_diagnosis_truncated: <page>: reported 0 of 10` line, which
    # names a page, so `add_partial`'s dedupe cannot collapse them and the
    # growth the cap exists to stop resumes one line per page.
    lines = [
        r
        for r in state["current_run"]["partial_reasons"]
        if r.startswith("citation_")
    ]
    assert len(lines) == runner._CITATION_RUN_FINDINGS_CAP + 1, lines
    # The +1: exactly one run-cap line. It names no page precisely so that
    # `add_partial`'s string-dedupe collapses every page past the cap into it.
    assert lines[-1].startswith("citation_diagnosis_run_cap: "), lines[-1]
    body = runner._format_partial_digest(state["current_run"]["partial_reasons"])
    assert len(body.encode()) < 65_536, len(body.encode())


def test_the_citation_caps_are_bounded_in_absolute_terms():
    """Both cap tests derive their fixture size FROM the constant, so raising
    either to an ineffective value scales the fixture with it and the suite
    stays green: `_CITATION_FINDINGS_CAP = 10 -> 10000` and `_AMBIGUITY_CAP =
    5 -> 5000` were each mutation-verified to pass the FULL suite. Lowering is
    caught; raising was not. These are the absolute assertions, and they carry
    the reason each bound exists.
    """
    # A per-page wall an operator skips instead of reads.
    assert runner._CITATION_FINDINGS_CAP <= 20
    # ~950 bytes per line against GitHub's 65,536-byte PR-body limit.
    assert runner._CITATION_RUN_FINDINGS_CAP * 1000 < 65_536
