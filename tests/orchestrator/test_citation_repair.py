"""CCE-141, revision 3: DETECTION ONLY.

The page is never rewritten, so there is nothing here about rewriting one.
Every test that existed to make a rewrite safe — the fence mirror, the line
marker, the byte-identity contract, the whole candidate-side rejection gate —
went with the rewrite. What is left tests what the module now does: report the
tracked file a blocked citation was probably shortened from, with an honest
confidence label.
"""

from __future__ import annotations
import ast
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import citation_repair as cr  # noqa: E402

FILES = {
    ".claude/skills/connector-builder/references/checklist.md",
    ".claude/skills/other-skill/references/notes.md",
    "docs/site-src/index.md",
    "README.md",
}


# --- suffix_candidates: unchanged ------------------------------------------


def test_unique_two_segment_suffix_matches_one_file():
    """The ADIS shape: 'references/checklist.md' names exactly one tracked file."""
    assert cr.suffix_candidates("references/checklist.md", FILES) == [
        ".claude/skills/connector-builder/references/checklist.md"
    ]


def test_match_requires_segment_boundaries():
    """A substring that is not a path-segment suffix must never match.

    Without the boundary rule, 'erences/checklist.md' would name a file it
    does not name — a suggestion pointing at the wrong file is worse than no
    suggestion, because the operator has no reason to doubt it.
    """
    assert cr.suffix_candidates("erences/checklist.md", FILES) == []


def test_exact_path_is_not_a_candidate():
    """A token equal to a tracked path already resolves and is never a
    candidate. Candidates are always a STRICT shortening."""
    assert cr.suffix_candidates("README.md", {"README.md"}) == []


def test_ambiguous_one_segment_suffix_returns_all_matches():
    """Caller decides what to do with ambiguity; this function just reports it."""
    files = {"a/notes.md", "b/notes.md"}
    assert cr.suffix_candidates("notes.md", files) == ["a/notes.md", "b/notes.md"]


def test_no_match_returns_empty():
    assert cr.suffix_candidates("nope/absent.md", FILES) == []


# --- the shape of the module ------------------------------------------------


_WRITE_ATTRS = {
    "write_text",
    "write_bytes",
    "writelines",
    "write",
    "rename",
    "replace",
    "unlink",
    "touch",
    "mkdir",
}


def test_the_module_never_writes_anything():
    """THE LOAD-BEARING CONSTRAINT, asserted on the source rather than argued
    in a docstring.

    The whole point of revision 3 is that a page that is never rewritten
    cannot be corrupted by a rewrite. Four review rounds produced four
    Criticals of exactly one class — a repair moving a citation into a region
    `citation_exists` does not verify — and every one of them needed a write
    to happen. Deleting the write deleted the class. A future contributor
    reaching for `Path.write_text` here is re-opening it, and this is what
    stops them.

    An AST walk, not a substring grep: the module docstring names
    `Path.write_text` in prose precisely to forbid it, and a grep would trip
    on its own warning.
    """
    tree = ast.parse(Path(cr.__file__).read_text())
    writes = [
        f"line {n.lineno}: .{n.func.attr}()"
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in _WRITE_ATTRS
    ]
    assert writes == [], (
        "citation_repair is DETECTION ONLY and must never mutate anything:\n  "
        + "\n  ".join(writes)
    )


def test_diagnose_returns_findings_and_takes_no_destination():
    """It takes text and returns findings. It does not return a modified
    string, and it has no parameter to write to."""
    params = list(inspect.signature(cr.diagnose).parameters)
    assert params == ["text", "repo_root", "config", "files", "run_inputs"]
    ret = inspect.signature(cr.diagnose).return_annotation
    assert "list" in str(ret), ret


def test_diagnose_is_the_public_name_and_repair_is_gone():
    """The name must not suggest mutation, and the retired surface must not
    linger as an alias that a caller could still reach."""
    assert set(cr.__all__) == {
        "build_run_inputs",
        "diagnose",
        "suffix_candidates",
        "tracked_files",
    }
    for gone in (
        "repair_text",
        "rewrite_token",
        "_candidate_rejection",
        "_resolves_absent",
        "_linter_reports_an_absent_file",
        "_extractor_sees",
        "_linter_dropped_lines",
        "_closed_fence_lines",
        "_ABSENT_TWIN_STEM",
    ):
        assert not hasattr(cr, gone), f"{gone} survived the deletion"


def test_run_inputs_has_no_default():
    """An un-threaded call site must fail loudly, never silently downgrade
    every finding to `suffix_match_only`."""
    sig = inspect.signature(cr.diagnose)
    assert sig.parameters["run_inputs"].default is inspect.Parameter.empty


def test_source_paths_has_no_default():
    sig = inspect.signature(cr.build_run_inputs)
    assert sig.parameters["source_paths"].default is inspect.Parameter.empty


# --- the fixture repo -------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A real git repo — _resolves and _is_gitignored both shell out to git."""
    subprocess.run(
        ["git", "init", "-q", str(tmp_path)], check=True, capture_output=True
    )
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    target = tmp_path / ".claude/skills/connector-builder/references"
    target.mkdir(parents=True)
    (target / "checklist.md").write_text("# checklist\n")
    (tmp_path / "README.md").write_text("# readme\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


CFG: dict = {}
# The one tracked file the `repo` fixture commits under a nested prefix — the
# candidate every ADIS-shaped fixture below suggests.
FULL = ".claude/skills/connector-builder/references/checklist.md"


# --- the four confidence labels ---------------------------------------------


def test_a_shortening_whose_candidate_is_a_run_input_is_labelled_as_such(repo):
    """The ADIS case, end to end. One strict suffix candidate, and an input to
    this run other than the authoring agent already named that file.

    The label says the candidate is IN THE RUN'S INPUTS and nothing more. It
    was `corroborated` until CCE-141 round 5, a name that read as "confirmed"
    while being granted by batch membership alone."""
    text = "See `references/checklist.md` for the steps.\n"
    got = cr.diagnose(text, repo, CFG, cr.tracked_files(repo), run_inputs={FULL})
    assert got == [("references/checklist.md", FULL, "candidate_in_run_inputs")]


def test_a_batch_touched_vendored_file_gets_no_stronger_label_than_it_earns(repo):
    """WHY THE LABEL WAS RENAMED, pinned as behaviour.

    The repo tracks only a vendored third-party module. The page cites an
    invented `auth/session.py`, which is a unique strict suffix of it, and the
    batch happened to touch the vendored file — so it lands in `run_inputs`
    and takes the top label. Under the old name the digest called that
    `corroborated`, which an operator reads as "confirmed". Nothing about the
    vendored file confirms anything; the label may only say that this run's
    inputs already named it."""
    vendored = repo / "vendor/third_party/oauthlib/auth"
    vendored.mkdir(parents=True)
    (vendored / "session.py").write_text("# oauthlib\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "vendored")
    full = "vendor/third_party/oauthlib/auth/session.py"

    got = cr.diagnose(
        "See `auth/session.py`.\n",
        repo,
        CFG,
        cr.tracked_files(repo),
        run_inputs={full},
    )
    assert got == [("auth/session.py", full, "candidate_in_run_inputs")]
    assert "corroborated" not in got[0][2], (
        "batch membership alone must never be labelled as corroboration"
    )


def test_a_suffix_match_only_shortening_is_reported_not_withheld(repo):
    """THE REVISION-3 CHANGE. The old code DECLINED this case, because acting
    on it was dangerous — a unique suffix match establishes only that the
    candidate exists, never that the cited token was ever a shortening of it.

    Nothing acts now. An operator reading the digest is better served by a
    labelled suggestion than by silence, so this is reported with its
    confidence set to `suffix_match_only` rather than dropped.
    """
    text = "See `references/checklist.md`.\n"
    got = cr.diagnose(text, repo, CFG, cr.tracked_files(repo), run_inputs=set())
    assert got == [("references/checklist.md", FULL, "suffix_match_only")]


def test_the_run_input_match_is_on_the_candidate_not_the_cited_token(repo):
    """Matching the TOKEN would be circular — the token is what the authoring
    agent wrote. Only the candidate's provenance counts, so a run input equal
    to the token must leave the label at `suffix_match_only`."""
    text = "See `references/checklist.md`.\n"
    got = cr.diagnose(
        text,
        repo,
        CFG,
        cr.tracked_files(repo),
        run_inputs={"references/checklist.md"},
    )
    assert got == [("references/checklist.md", FULL, "suffix_match_only")]


def test_an_ambiguous_citation_is_reported_with_its_candidates(repo):
    """THE OTHER REVISION-3 CHANGE. Two candidates used to `continue`
    silently, so a page that blocked because repair found two candidates
    produced no digest line at all while the single-candidate case was loud.
    Consistency is the whole value of the feature now: the digest is a census
    of blocked citations or it is nothing."""
    second = repo / "other/references"
    second.mkdir(parents=True)
    (second / "checklist.md").write_text("# other\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second")

    text = "See `references/checklist.md`.\n"
    got = cr.diagnose(text, repo, CFG, cr.tracked_files(repo), run_inputs=set())
    assert got == [
        (
            "references/checklist.md",
            f"{FULL}, other/references/checklist.md",
            "ambiguous",
        )
    ]


def test_the_ambiguous_candidate_list_is_capped_and_says_so(repo):
    """A one-segment tail can match hundreds of tracked files on a real host.
    An unbounded join would drown every other reason in the digest, so the
    list is capped — and it says how many it withheld, because a silently
    truncated list is a lie about the ambiguity's size."""
    n = cr._AMBIGUITY_CAP + 2
    for i in range(n):
        d = repo / f"d{i}/x"
        d.mkdir(parents=True)
        (d / "y.md").write_text("# y\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "many")

    got = cr.diagnose(
        "See `x/y.md`.\n", repo, CFG, cr.tracked_files(repo), run_inputs=set()
    )
    assert len(got) == 1
    cited, listed, confidence = got[0]
    assert (cited, confidence) == ("x/y.md", "ambiguous")
    assert listed.count(",") == cr._AMBIGUITY_CAP - 1, listed
    assert listed.endswith(f"(+{n - cr._AMBIGUITY_CAP} more)"), listed
    assert listed.startswith("d0/x/y.md, d1/x/y.md"), (
        "the cap must keep sorted order, or which candidates survive is "
        f"set-iteration roulette: {listed}"
    )


def test_a_citation_with_no_candidate_is_reported_as_such(repo):
    """The zero-match case also used to `continue` silently. It is the most
    common shape of all — a confabulated path nothing in the repo resembles —
    and an operator triaging a blocked page needs to see that the diagnostic
    looked and found nothing, not to wonder whether it ran."""
    got = cr.diagnose(
        "See `docs/invented.md`.\n",
        repo,
        CFG,
        cr.tracked_files(repo),
        run_inputs=set(),
    )
    assert got == [("docs/invented.md", "", "no_candidate")]


def test_four_citations_produce_one_finding_each_for_the_three_that_do_not_resolve(
    repo,
):
    """The census property, stated directly: FOUR citations on one page, one
    of which resolves, produce THREE findings, in document order and one per
    citation.

    Name, docstring and assertions agree here, and they did not before. The
    docstring claimed four findings while asserting three, and its "resolving"
    line was `README.md` — which `_REPO_PATH_RE` does not even accept as a
    citation (it requires a slash), so `extract_citations` never emitted it
    and the `_resolves` arm this test credited was never reached. The
    resolving citation is now `docs/index.md`, a real tracked path with a
    slash. (The `_resolves` guard is pinned DISCRIMINATINGLY in isolation by
    `test_a_resolving_citation_is_never_reported`; its job here is only to be
    a genuine citation that this loop must skip.)
    """
    second = repo / "other/references"
    second.mkdir(parents=True)
    (second / "checklist.md").write_text("# other\n")
    other_tail = repo / "vendor/pkg/references"
    other_tail.mkdir(parents=True)
    (other_tail / "notes.md").write_text("# notes\n")
    (repo / "docs").mkdir()
    (repo / "docs/index.md").write_text("# index\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "more")

    files = cr.tracked_files(repo)
    # Fixture guard: all four really are citations the linter surfaces, or the
    # count below is measuring the extractor rather than the diagnosis.
    text = (
        "Resolving: `docs/index.md`.\n"
        "Ambiguous: `references/checklist.md`.\n"
        "A run input: `references/notes.md`.\n"
        "Missing: `docs/invented.md`.\n"
    )
    assert cr.extract_citations(text)["paths"] == [
        "docs/index.md",
        "references/checklist.md",
        "references/notes.md",
        "docs/invented.md",
    ]

    got = cr.diagnose(
        text, repo, CFG, files, run_inputs={"vendor/pkg/references/notes.md"}
    )
    assert [(c, k) for c, _, k in got] == [
        ("references/checklist.md", "ambiguous"),
        ("references/notes.md", "candidate_in_run_inputs"),
        ("docs/invented.md", "no_candidate"),
    ], got


def test_diagnose_inherits_the_linters_fence_stripping(repo):
    """`extract_citations` calls `strip_fenced_blocks` ON PURPOSE — "fenced
    examples are legitimately hypothetical" — so a path named only inside a
    fence NEVER blocks a page. Nothing asserted that `diagnose` inherits that,
    and it must: a citation the linter will not block needs no diagnosis, and
    a digest line for one is a line telling an operator to fix a page that is
    not broken.

    Inheritance, not reimplementation: `diagnose` gets this for free by
    calling the linter's own extractor, which is the whole point of the
    import-never-reimplement rule at the top of the module.

    The fixture is DISCRIMINATING in the loudest direction available. The
    fenced path has exactly one strict suffix candidate AND that candidate is
    a run input, so if the fence markers were stripped before extraction the
    token would surface with the TOP label — the strongest line the digest can
    print — rather than merely changing shade.

    (The mutation that proves this is a real catch splits the text on triple
    backticks and rejoins it, which removes the fence markers. The naive
    `text.replace("```", "")` form is NOT a valid mutation here: `replace` is
    in `_WRITE_ATTRS`, so it fails the AST write-guard instead — an artifact,
    not a behavioural catch.)
    """
    text = (
        "Nothing is cited in prose on this page.\n"
        "\n"
        "```text\n"
        "cite it as `references/checklist.md`\n"
        "```\n"
    )
    files = cr.tracked_files(repo)

    # Fixture guards: the linter really does drop this token, and the token
    # really would produce the loudest possible finding if it did not.
    assert cr.extract_citations(text)["paths"] == []
    assert cr.suffix_candidates("references/checklist.md", files) == [FULL]
    assert not (repo / "references/checklist.md").exists()

    assert cr.diagnose(text, repo, CFG, files, run_inputs={FULL}) == []


# --- the guards that keep noise out of the digest ---------------------------


def test_a_resolving_citation_is_never_reported(repo):
    """THE `_resolves` GUARD, in isolation.

    Deleting `if _resolves(...): continue` once left the whole suite green:
    every test that named the case had a fixture with ZERO strict suffix
    candidates, so `not candidates` decided them first and `_resolves` was
    never consulted.

    Here the cited `docs/index.md` RESOLVES and ALSO has exactly one strict
    suffix candidate, `vendor/pkg/docs/index.md`, which IS a run input. Every
    other guard passes, so `_resolves` is the only thing standing between a
    working citation and a digest line telling an operator to repoint it at a
    different tracked file.
    """
    (repo / "docs").mkdir()
    (repo / "docs/index.md").write_text("# index\n")
    vendored = repo / "vendor/pkg/docs"
    vendored.mkdir(parents=True)
    (vendored / "index.md").write_text("# a different index\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "two index pages")

    files = cr.tracked_files(repo)
    # Fixture guard: without exactly one candidate this test would be decided
    # by the candidate count and would stop exercising `_resolves` at all.
    assert cr.suffix_candidates("docs/index.md", files) == ["vendor/pkg/docs/index.md"]

    got = cr.diagnose(
        "See `docs/index.md`.\n",
        repo,
        CFG,
        files,
        run_inputs={"vendor/pkg/docs/index.md"},
    )
    assert got == []


def test_exempt_token_is_never_reported(repo):
    """Exclusion row 1. The host declared this unverifiable on purpose, so it
    is not a defect and a suggestion for it is pure noise.

    Corroborated on purpose: without the exempt check the candidate would be
    reported, so this stays discriminating. run_inputs=set() would not —
    the finding would merely change label rather than disappear.
    """
    cfg = {"lint": {"citation_exempt_tokens": ["references/checklist.md"]}}
    got = cr.diagnose(
        "See `references/checklist.md`.\n",
        repo,
        cfg,
        cr.tracked_files(repo),
        run_inputs={FULL},
    )
    assert got == []


def test_example_namespace_token_is_never_reported(repo):
    """Exclusion row 2. `example/` is fictional by design.

    The tracked file lives at `docs/example/auth/session.py`, NOT at the cited
    path itself: `example/auth/session.py` does not resolve on its own, but it
    IS a unique suffix of the tracked file. That makes this discriminating —
    without the example_prefixes check there would be exactly one candidate
    and a finding. A tracked file at the cited path itself would make the
    prefix check unreachable, since `_resolves` short-circuits before it.
    """
    ex = repo / "docs/example/auth"
    ex.mkdir(parents=True)
    (ex / "session.py").write_text("# ex\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "ex")

    got = cr.diagnose(
        "See `example/auth/session.py`.\n",
        repo,
        CFG,
        cr.tracked_files(repo),
        run_inputs={"docs/example/auth/session.py"},
    )
    assert got == []


def test_gitignored_path_is_never_reported(repo):
    """Exclusion row 3 (CCE-145): declared but absent from a fresh checkout.

    The gitignore pattern `generated/output.md` has a non-trailing internal
    slash, so it is anchored to the repo root: it ignores ONLY a top-level
    `generated/output.md`, not the tracked `docs/generated/output.md` this
    test commits. That keeps the fixture discriminating — `generated/output.md`
    does not resolve on its own but IS a unique suffix of the tracked file, so
    without the _is_gitignored check there would be exactly one candidate and
    a finding.
    """
    (repo / ".gitignore").write_text("generated/output.md\n")
    docs_generated = repo / "docs/generated"
    docs_generated.mkdir(parents=True)
    (docs_generated / "output.md").write_text("# generated\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "ignore")

    got = cr.diagnose(
        "See `generated/output.md`.\n",
        repo,
        CFG,
        cr.tracked_files(repo),
        run_inputs={"docs/generated/output.md"},
    )
    assert got == []


# An absolute path outside the repo has an EMPTY first segment, and no path
# `git ls-files` emits has one -- so for any git-derived `files`,
# `suffix_candidates` returns nothing for such a token and the candidate count
# decides it before `if rel is None` is ever consulted. Making the guard decide
# takes an injected candidate, and the injection is honest about what it is:
# git cannot emit `vendor//etc/__cr_absent__/thing.conf`, but `files` is a
# PARAMETER of `diagnose`, so the guard is a contract on the parameter.
_ABSOLUTE_CITED = "/etc/__cr_absent__/thing.conf"
_ABSOLUTE_CANDIDATE = "vendor/" + _ABSOLUTE_CITED  # note the doubled slash


def test_absolute_path_outside_repo_is_never_reported(repo):
    """Exclusion row 4: `_relativize` returns None for a path outside the repo.

    `citation_exists._relativize` treats an absolute path that does not
    resolve inside `repo_root` as an ENVIRONMENT reference, not a repo
    citation — there is nothing repo-relative to check it against, so there is
    nothing to have been shortened.

    The cited path must be guaranteed ABSENT from the test machine, which is
    why it is `/etc/__cr_absent__/thing.conf` and not `/etc/nginx/nginx.conf`:
    `repo_root / "/abs/path"` is `/abs/path`, so `_resolves`'s on-disk arm
    would answer True for a file that happens to exist on the runner and
    short-circuit before the candidate arithmetic — re-vacuuming the test on
    some machines and not others.
    """
    files = cr.tracked_files(repo) | {_ABSOLUTE_CANDIDATE}
    text = f"See `{_ABSOLUTE_CITED}`.\n"

    # Fixture guards: every earlier guard must PASS, or this stops exercising
    # `if rel is None` and goes back to proving nothing.
    assert cr.extract_citations(text)["paths"] == [_ABSOLUTE_CITED], (
        "the linter must surface this token as a path citation"
    )
    assert cr._relativize(_ABSOLUTE_CITED, repo) is None, "the guard must be armed"
    assert not (repo / _ABSOLUTE_CITED).exists(), "the cited token must not resolve"
    assert cr.suffix_candidates(_ABSOLUTE_CITED, files) == [_ABSOLUTE_CANDIDATE], (
        "exactly one candidate, or the candidate count decides this first"
    )

    assert cr.diagnose(text, repo, CFG, files, run_inputs=set()) == []


# --- build_run_inputs: unchanged behaviour, changed role and name -----------


def test_rung1_admits_a_path_the_linter_validated_in_prose():
    """Rung 1 is the LINTER'S view of the prior page: an inline code span in
    unfenced prose is exactly what citation_exists validated there, so it is
    evidence the pipeline already accepted a reference to that file."""
    full = ".claude/skills/connector-builder/references/checklist.md"
    prior = f"The checklist lives at `{full}`.\n"
    assert cr.build_run_inputs(prior, set(), {full}) == {full}


def test_rung1_ignores_sites_the_linter_never_validates():
    """Frontmatter and table cells are not inline code spans in prose, so
    citation_exists never checked them. A raw substring scan would admit them
    and raise a suggestion with no independent support to
    `candidate_in_run_inputs`."""
    full = ".claude/skills/connector-builder/references/checklist.md"
    prior = (
        "---\n"
        f"sources:\n  - {full}\n"
        "---\n\n"
        f"| step | ref |\n| --- | --- |\n| 1 | {full} |\n"
    )
    assert cr.build_run_inputs(prior, set(), {full}) == set()


def test_rung1_ignores_a_path_named_only_inside_a_fence():
    """THE CRITICAL CASE. citation_exists strips fenced blocks on purpose —
    "fenced examples are legitimately hypothetical". A path named only inside
    a fence on the prior commit was therefore never validated, so it must not
    raise a new page's invented citation of the same tail to
    `candidate_in_run_inputs`.
    Backticked INSIDE the fence on purpose: this must fail on the fence
    itself, not merely on the absence of an inline span."""
    full = "tests/fixtures/setup_repos/js_docusaurus/.github/workflows/ci.yml"
    prior = f"Nothing is cited here.\n\n```text\ncite it as `{full}`\n```\n"
    assert cr.build_run_inputs(prior, set(), {full}) == set()


def test_rung1_only_admits_tracked_paths():
    """A citation the linter validated on the prior page still has to name a
    tracked file — extract_citations reports tokens, not existence."""
    prior = "See `totally/invented/thing.md` for details.\n"
    assert cr.build_run_inputs(prior, set(), {"real/file.md"}) == set()


def test_rung2_admits_the_batch_source_set():
    got = cr.build_run_inputs(None, {"a/b/c.md"}, {"a/b/c.md"})
    assert got == {"a/b/c.md"}


def test_rung2_excludes_an_untracked_source_path():
    """`p in files` is a real guard, not decoration. source-collector's
    `files[]` is an LLM subagent's output that nothing under scripts/ checks
    against git, so an invented entry would otherwise pin a run-input label on
    a path that is not in the repo at all."""
    assert (
        cr.build_run_inputs(None, {"invented/thing.md"}, {"real/file.md"}) == set()
    )


def test_rung2_excludes_glob_entries():
    """Manifest source_files can carry globs (`core/**`). Expanding them would
    make the label ceremony, so they are excluded at filter time.

    The first case is the discriminating one: a path that IS in files but
    contains a glob character, so the `p in files` check cannot decide it and
    only the glob filter can. The second is the original manifest shape, kept
    as a regression.
    """
    assert cr.build_run_inputs(None, {"weird[x].md"}, {"weird[x].md"}) == set()
    assert (
        cr.build_run_inputs(None, {"core/**", "docs/superpowers/**"}, {"core/x.md"})
        == set()
    )


def test_no_prior_and_no_sources_yields_no_run_inputs():
    assert cr.build_run_inputs(None, set(), {"a/b.md"}) == set()


def test_one_pathological_token_costs_only_itself(repo, monkeypatch):
    """ROUND 6. `_resolves` reaches `(repo_root / rel).exists()`, and pathlib
    RE-RAISES OSError for errno values outside its ignored set — ENAMETOOLONG
    is not in that set. The exception propagated out of `diagnose` and
    discarded the local `findings` list wholesale, so ONE bad token destroyed
    the whole page's census, including good findings that appeared EARLIER in
    document order. The page label survived; every finding did not.

    The OSError is INJECTED rather than provoked with a 3000-char filename,
    because provoking it is platform-dependent and the guard is not. On macOS
    (APFS) a 3000-char component raises ENAMETOOLONG out of `stat`, which is
    how this defect was found; on Linux CI the same fixture returned False and
    the token merely degraded to `no_candidate`, so the natural fixture passed
    locally and failed in CI while testing nothing on either. What is being
    pinned is that an OSError from anywhere inside the per-citation body costs
    that token and no other — inject it, and the platform stops mattering.
    """
    (repo / "pkg/weird").mkdir(parents=True)
    (repo / "pkg/weird/notes.md").write_text("# notes\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second")
    text = (
        "See `references/checklist.md`.\n"
        "And `doomed/token.md`.\n"
        "And `weird/notes.md`.\n"
    )

    real = cr._resolves

    def boom(rel, *a, **kw):
        if rel == "doomed/token.md":
            raise OSError(63, "File name too long", rel)
        return real(rel, *a, **kw)

    monkeypatch.setattr(cr, "_resolves", boom)

    got = cr.diagnose(text, repo, CFG, cr.tracked_files(repo), set())

    # The findings on either side of the pathological token both survive; only
    # the token itself is dropped.
    assert got == [
        ("references/checklist.md", FULL, "suffix_match_only"),
        ("weird/notes.md", "pkg/weird/notes.md", "suffix_match_only"),
    ], got


def test_a_same_run_untracked_sibling_is_a_known_blind_spot(repo):
    """ROUND 6, PINNED AS A LIMITATION — this is not the behaviour we want, it
    is the behaviour we accept, and the test exists so a future reader meets it
    deliberately rather than by surprise.

    The candidate search and the resolution test use different universes.
    `_resolves` accepts `rel in files or (repo_root / rel).exists()` — the disk
    arm covers same-run siblings not yet added to git — while
    `suffix_candidates` iterates `files` alone (`git ls-files`). A page this
    run just CREATED is therefore invisible as a candidate, so a citation
    shortened to a same-run sibling names a TRACKED decoy elsewhere in the tree
    instead of the real target.

    Not fixed, and the reason is the ticket's whole history: widening the
    candidate universe to untracked disk state is precisely the
    region-the-linter-does-not-verify class that produced a Critical in four
    consecutive review rounds. The cost is bounded — the label is
    `suffix_match_only`, the weakest of the four, whose documented meaning is
    "resting on the match alone" — and nothing acts on it.
    """
    decoy = repo / "vendor/mirror/connectors/bar.md"
    decoy.parent.mkdir(parents=True)
    decoy.write_text("# decoy\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "decoy")
    real = repo / "docs/site-src/core/connectors/bar.md"
    real.parent.mkdir(parents=True)
    real.write_text("the real target, written this run, not yet tracked\n")

    got = cr.diagnose(
        "The bar connector is documented at `connectors/bar.md`.\n",
        repo,
        CFG,
        cr.tracked_files(repo),
        set(),
    )

    assert got == [
        ("connectors/bar.md", "vendor/mirror/connectors/bar.md", "suffix_match_only")
    ], got


def test_the_ambiguity_cap_is_bounded_in_absolute_terms():
    """`test_the_ambiguous_candidate_list_is_capped_and_says_so` sizes its
    fixture from the constant, so `_AMBIGUITY_CAP = 5 -> 5000` passes the FULL
    suite. Lowering is caught, raising was not. The bound exists because a
    one-segment tail matches hundreds of paths on a real host, and an unbounded
    join drowns every other reason in the run.
    """
    assert cr._AMBIGUITY_CAP <= 10
