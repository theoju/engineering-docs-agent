from __future__ import annotations
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


def test_unique_two_segment_suffix_matches_one_file():
    """The ADIS shape: 'references/checklist.md' names exactly one tracked file."""
    assert cr.suffix_candidates("references/checklist.md", FILES) == [
        ".claude/skills/connector-builder/references/checklist.md"
    ]


def test_match_requires_segment_boundaries():
    """A substring that is not a path-segment suffix must never match.

    Without the boundary rule, 'erences/checklist.md' would 'repair' to a file
    it does not name, which is exactly the silent-retarget failure the design
    rules out.
    """
    assert cr.suffix_candidates("erences/checklist.md", FILES) == []


def test_exact_path_is_not_a_candidate():
    """A token equal to a tracked path already resolves and is never a repair
    candidate. Candidates are always a STRICT shortening."""
    assert cr.suffix_candidates("README.md", {"README.md"}) == []


def test_ambiguous_one_segment_suffix_returns_all_matches():
    """Caller decides what to do with ambiguity; this function just reports it."""
    files = {"a/notes.md", "b/notes.md"}
    assert cr.suffix_candidates("notes.md", files) == ["a/notes.md", "b/notes.md"]


def test_no_match_returns_empty():
    assert cr.suffix_candidates("nope/absent.md", FILES) == []


def test_rewrite_replaces_bare_path_in_inline_span():
    text = "See `references/checklist.md` for the steps.\n"
    out = cr.rewrite_token(
        text,
        "references/checklist.md",
        ".claude/skills/connector-builder/references/checklist.md",
    )
    assert out == (
        "See `.claude/skills/connector-builder/references/checklist.md` "
        "for the steps.\n"
    )


def test_rewrite_preserves_a_symbol_suffix():
    """`path.py:Class.method` — the path is repaired, the symbol survives."""
    text = "The helper `lint/citation_exists.py:check_path` does this.\n"
    out = cr.rewrite_token(
        text,
        "lint/citation_exists.py",
        "scripts/lint/citation_exists.py",
    )
    assert out == (
        "The helper `scripts/lint/citation_exists.py:check_path` does this.\n"
    )


def test_rewrite_leaves_other_tokens_untouched():
    text = "Both `references/checklist.md` and `README.md` are cited.\n"
    out = cr.rewrite_token(
        text, "references/checklist.md", "a/b/references/checklist.md"
    )
    assert "`README.md`" in out
    assert "`a/b/references/checklist.md`" in out


def test_rewrite_ignores_a_prose_mention_outside_backticks():
    """Only inline code spans are citations; bare prose is not."""
    text = "the file references/checklist.md is mentioned in prose\n"
    assert cr.rewrite_token(text, "references/checklist.md", "a/b/c.md") == text


def test_rewrite_is_a_noop_when_nothing_matches():
    text = "Nothing to do here `README.md`.\n"
    assert cr.rewrite_token(text, "absent.md", "a/absent.md") == text


def test_rewrite_skips_a_closed_fence():
    """extract_citations strips fenced blocks, so repair never SEES a fenced
    token. The rewrite must skip them too, or a prose repair would silently
    mutate an unrelated illustration inside a code fence."""
    text = (
        "See `references/checklist.md`.\n"
        "\n"
        "```\n"
        "cite it as `references/checklist.md`\n"
        "```\n"
    )
    out = cr.rewrite_token(
        text, "references/checklist.md", "a/b/references/checklist.md"
    )
    assert out.count("a/b/references/checklist.md") == 1
    assert "cite it as `references/checklist.md`" in out


def test_rewrite_still_applies_inside_an_unterminated_fence():
    """Mirrors strip_fenced_blocks exactly: an UNTERMINATED fence strips
    nothing, so extract_citations DOES see these tokens. If the rewrite
    skipped them, repair_text would report a repair it never applied."""
    text = "```\nsee `references/checklist.md`\n"
    out = cr.rewrite_token(
        text, "references/checklist.md", "a/b/references/checklist.md"
    )
    assert "a/b/references/checklist.md" in out


# The six characters that survive Path.read_text()'s universal-newline
# translation yet ARE str.splitlines() boundaries. Written as escapes on
# purpose: four are invisible and two are zero-width in most editors, so a
# literal here would be unreviewable. "\r" is deliberately absent -- read_text
# normalises it, so it never reaches this code.
SPLITLINES_ONLY = "\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}\x85\x0b\x0c\x1c"


def test_rewrite_skips_a_fence_opened_after_a_u2028_line_break():
    """strip_fenced_blocks iterates splitlines(), so U+2028 puts this fence
    opener at the start of its own line and the fenced token is invisible to
    extract_citations. A split("\\n") walk sees `Example:<U+2028>```` as ONE
    line, never opens the fence, reports no fenced lines at all, and rewrites
    the illustration -- turning a deliberate example into a false claim about
    real code, which repair_text's own docstring calls worse than the defect
    this module fixes.
    """
    text = "Example:\N{LINE SEPARATOR}```\ncite `references/checklist.md`\n```\n"
    out = cr.rewrite_token(
        text, "references/checklist.md", "a/b/references/checklist.md"
    )
    assert out == text


def test_rewrite_skips_a_fence_opened_after_a_vertical_tab_line_break():
    """The same divergence via \\x0b. Two of the six are covered so a partial
    revert of either iteration site is caught, not just a wholesale one."""
    text = "Example:\x0b```\ncite `references/checklist.md`\n```\n"
    out = cr.rewrite_token(
        text, "references/checklist.md", "a/b/references/checklist.md"
    )
    assert out == text


def test_rewrite_preserves_splitlines_only_terminators_byte_for_byte():
    """Iterating splitlines() is only half the fix: "\\n".join() would then
    normalise all six characters into newlines on every page containing one.
    Lines are rejoined with their OWN terminators, so a line this function did
    not rewrite comes back verbatim and only the cited span changes."""
    text = (
        "alpha\N{LINE SEPARATOR}beta\N{PARAGRAPH SEPARATOR}gamma\x85"
        "delta\x0bepsilon\x0czeta\x1ceta\n"
        "See `references/checklist.md`.\n"
        "tail\N{LINE SEPARATOR}end\n"
    )
    out = cr.rewrite_token(
        text, "references/checklist.md", "a/b/references/checklist.md"
    )
    assert out == text.replace(
        "`references/checklist.md`", "`a/b/references/checklist.md`"
    )
    for ch in SPLITLINES_ONLY:
        assert out.count(ch) == text.count(ch)


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
# candidate every ADIS-shaped fixture below repairs to, and so the corroborator
# those fixtures must supply for repair to be entered at all.
FULL = ".claude/skills/connector-builder/references/checklist.md"


def test_shortened_citation_is_repaired(repo):
    """The ADIS case, end to end."""
    text = "See `references/checklist.md` for the steps.\n"
    files = cr.tracked_files(repo)
    out, repairs, _ = cr.repair_text(text, repo, CFG, files, corroborators={FULL})
    assert repairs == [
        (
            "references/checklist.md",
            ".claude/skills/connector-builder/references/checklist.md",
        )
    ]
    assert ".claude/skills/connector-builder/references/checklist.md" in out


def test_ambiguous_suffix_is_left_alone(repo):
    """Two candidates -> fail closed.

    Corroboration narrows the entry condition; it never resolves ambiguity, so
    the `len(candidates) != 1` guard still decides this case on its own.
    """
    second = repo / "other/references"
    second.mkdir(parents=True)
    (second / "checklist.md").write_text("# other\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second")

    text = "See `references/checklist.md`.\n"
    out, repairs, _ = cr.repair_text(
        text, repo, CFG, cr.tracked_files(repo), corroborators=set()
    )
    assert repairs == []
    assert out == text


def test_resolving_citation_is_byte_identical(repo):
    text = "See `README.md`.\n"
    out, repairs, _ = cr.repair_text(
        text, repo, CFG, cr.tracked_files(repo), corroborators=set()
    )
    assert repairs == []
    assert out == text


def test_repair_preserves_splitlines_only_terminators_on_the_rest_of_the_page(repo):
    """The byte-identity contract, end to end, on a page carrying every
    splitlines()-only boundary character. A repair must change the cited span
    and NOTHING else — a "\n".join() round-trip would silently rewrite six
    distinct characters on every page that contains one."""
    text = (
        "alpha\u2028beta\u2029gamma\x85delta\x0bepsilon\x0czeta\x1ceta\n"
        "\n"
        "See `references/checklist.md`.\n"
    )
    out, repairs, _ = cr.repair_text(
        text, repo, CFG, cr.tracked_files(repo), corroborators={FULL}
    )
    assert repairs == [("references/checklist.md", FULL)]
    assert out == text.replace("`references/checklist.md`", f"`{FULL}`")


def test_repair_is_idempotent(repo):
    text = "See `references/checklist.md`.\n"
    files = cr.tracked_files(repo)
    once, _, _ = cr.repair_text(text, repo, CFG, files, corroborators={FULL})
    twice, repairs, _ = cr.repair_text(once, repo, CFG, files, corroborators={FULL})
    assert repairs == []
    assert twice == once


def test_exempt_token_is_never_repaired(repo):
    """Exclusion row 1. The host declared this unverifiable on purpose."""
    cfg = {"lint": {"citation_exempt_tokens": ["references/checklist.md"]}}
    text = "See `references/checklist.md`.\n"
    # Corroborated on purpose: without the exempt check the candidate would be
    # repaired, so this stays discriminating. corroborators=set() would defang it.
    out, repairs, _ = cr.repair_text(
        text, repo, cfg, cr.tracked_files(repo), corroborators={FULL}
    )
    assert repairs == []
    assert out == text


def test_example_namespace_token_is_never_repaired(repo):
    """Exclusion row 2. `example/` is fictional by design.

    Rewriting it into a real path would make an illustration silently claim to
    cite real code — worse than the defect this module fixes.

    The tracked file lives at `docs/example/auth/session.py`, NOT at the cited
    path itself: `example/auth/session.py` does not resolve on its own, but it
    IS a unique suffix of the tracked file. That makes this test discriminating
    — without the example_prefixes check, suffix_candidates would find exactly
    one match and repair_text WOULD rewrite it. A tracked file at the cited
    path itself (the original fixture) made the prefix check provably
    unreachable: _resolves() already short-circuits before it, so deleting the
    check could not fail that version of the test.
    """
    ex = repo / "docs/example/auth"
    ex.mkdir(parents=True)
    (ex / "session.py").write_text("# ex\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "ex")

    text = "See `example/auth/session.py`.\n"
    # Corroborated on purpose — see the exempt-token test for why.
    out, repairs, _ = cr.repair_text(
        text,
        repo,
        CFG,
        cr.tracked_files(repo),
        corroborators={"docs/example/auth/session.py"},
    )
    assert repairs == []
    assert out == text


def test_gitignored_path_is_never_repaired(repo):
    """Exclusion row 3 (CCE-145): declared but absent from a fresh checkout.

    The gitignore pattern `generated/output.md` has a non-trailing internal
    slash, so it is anchored to the repo root: it ignores ONLY a top-level
    `generated/output.md`, not the tracked `docs/generated/output.md` this
    test commits (verified empirically — `git check-ignore` returns 1/not
    ignored for the nested path and 0/ignored for the top-level one). That
    keeps the test discriminating: `generated/output.md` does not resolve on
    its own, but it IS a unique suffix of `docs/generated/output.md`, so
    without the _is_gitignored check, suffix_candidates would find exactly
    one match and repair_text WOULD rewrite it. The original fixture cited a
    path with no tracked file suffix-matching it at all, so suffix_candidates
    already returned [] regardless of this check — deleting the check could
    not fail that version of the test.
    """
    (repo / ".gitignore").write_text("generated/output.md\n")
    docs_generated = repo / "docs/generated"
    docs_generated.mkdir(parents=True)
    (docs_generated / "output.md").write_text("# generated\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "ignore")

    text = "See `generated/output.md`.\n"
    # Corroborated on purpose — see the exempt-token test for why.
    out, repairs, _ = cr.repair_text(
        text,
        repo,
        CFG,
        cr.tracked_files(repo),
        corroborators={"docs/generated/output.md"},
    )
    assert repairs == []
    assert out == text


def test_absolute_path_outside_repo_is_never_repaired(repo):
    """Exclusion row 4: `_relativize` returns None for a path outside the repo.

    `citation_exists._relativize` treats an absolute path that does not
    resolve inside `repo_root` as an environment reference, not a repo
    citation — there is nothing repo-relative to check it against. Verified
    (via a standalone script, not guessed): `/etc/nginx/nginx.conf` matches
    `_REPO_PATH_RE`, is not filtered by `_is_placeholder`, so
    `extract_citations` DOES surface it as a path citation and it genuinely
    reaches this branch through `repair_text`'s own call path — this is not a
    contrived unreachable case.
    """
    text = "See `/etc/nginx/nginx.conf`.\n"
    out, repairs, _ = cr.repair_text(
        text, repo, CFG, cr.tracked_files(repo), corroborators=set()
    )
    assert repairs == []
    assert out == text


# --- Exclusions on the CANDIDATE side ---------------------------------------
# The four rows above test the CITED token. Testing only that end let a repair
# MOVE a citation INTO an excluded class instead of out of one: every class
# below is a place check_path never verifies, so a page rewritten into one
# reads `(True, 'ok')` forever. Each row gets its own reason string so the
# digest distinguishes it from a plain `uncorroborated` decline.


def test_candidate_in_the_example_namespace_is_declined(repo):
    """THE REPRODUCED CASE. Cited `auth/session.py`, corroborated candidate
    `example/auth/session.py`: the repair used to fire and park the citation in
    the reserved illustrative namespace, where check_path skips it permanently.
    check_path went (False, 'cites nonexistent path ...') -> (True, 'ok').
    """
    ex = repo / "example/auth"
    ex.mkdir(parents=True)
    (ex / "session.py").write_text("# ex\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "example ns")

    text = "See `auth/session.py`.\n"
    out, repairs, declines = cr.repair_text(
        text,
        repo,
        CFG,
        cr.tracked_files(repo),
        corroborators={"example/auth/session.py"},
    )
    assert repairs == []
    assert out == text
    assert declines == [
        ("auth/session.py", "example/auth/session.py", "candidate_example_namespace")
    ]


def test_candidate_that_is_an_exempt_token_is_declined(repo):
    """The host declared this exact path unverifiable on purpose. Repairing
    INTO it parks a live citation on a token check_path never checks."""
    cfg = {"lint": {"citation_exempt_tokens": [FULL]}}
    text = "See `references/checklist.md`.\n"
    out, repairs, declines = cr.repair_text(
        text, repo, cfg, cr.tracked_files(repo), corroborators={FULL}
    )
    assert repairs == []
    assert out == text
    assert declines == [("references/checklist.md", FULL, "candidate_exempt_token")]


def test_candidate_that_is_gitignored_is_declined(repo):
    """Tracked AND gitignored is reachable: git keeps tracking a file added
    before the ignore rule, so it is in `git ls-files` AND `check-ignore` says
    ignored. CCE-145 downgrades such a path to an advisory because it is absent
    from a fresh checkout -- so repairing INTO it converts a hard block into a
    permanent advisory, which is not a fix.

    The cited token stays clean: `docs/generated/output.md` has a non-trailing
    internal slash, so the pattern is anchored at the repo root and does NOT
    ignore the bare `generated/output.md` the page cites.
    """
    docs_generated = repo / "docs/generated"
    docs_generated.mkdir(parents=True)
    (docs_generated / "output.md").write_text("# generated\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "tracked first")
    (repo / ".gitignore").write_text("docs/generated/output.md\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-qm", "ignored after tracking")

    files = cr.tracked_files(repo)
    assert "docs/generated/output.md" in files, "the candidate must stay tracked"

    text = "See `generated/output.md`.\n"
    out, repairs, declines = cr.repair_text(
        text, repo, CFG, files, corroborators={"docs/generated/output.md"}
    )
    assert repairs == []
    assert out == text
    assert declines == [
        ("generated/output.md", "docs/generated/output.md", "candidate_gitignored")
    ]


def test_candidate_outside_the_repo_is_declined(repo):
    """`_relativize` rejects an absolute path that does not resolve inside the
    repo -- an environment reference, not a repo citation.

    `git ls-files` never emits one, but `files` is a PARAMETER of repair_text,
    so this guard is a contract on the parameter rather than on git's output: a
    candidate that escapes the repo must never be written into a page.
    """
    files = cr.tracked_files(repo) | {"/etc/nginx/nginx.conf"}
    text = "See `nginx/nginx.conf`.\n"
    out, repairs, declines = cr.repair_text(
        text, repo, CFG, files, corroborators={"/etc/nginx/nginx.conf"}
    )
    assert repairs == []
    assert out == text
    assert declines == [
        ("nginx/nginx.conf", "/etc/nginx/nginx.conf", "candidate_outside_repo")
    ]


def test_rung1_admits_a_path_the_linter_validated_in_prose():
    """Rung 1 is the LINTER'S view of the prior page: an inline code span in
    unfenced prose is exactly what citation_exists validated there, so it is
    evidence the pipeline already accepted a reference to that file."""
    full = ".claude/skills/connector-builder/references/checklist.md"
    prior = f"The checklist lives at `{full}`.\n"
    assert cr.build_corroborators(prior, set(), {full}) == {full}


def test_rung1_ignores_sites_the_linter_never_validates():
    """Frontmatter and table cells are not inline code spans in prose, so
    citation_exists never checked them. A raw substring scan would admit them
    and thereby corroborate a path the pipeline never validated — the surplus
    a raw scan buys is precisely the unvalidated part, so it evidences
    nothing."""
    full = ".claude/skills/connector-builder/references/checklist.md"
    prior = (
        "---\n"
        f"sources:\n  - {full}\n"
        "---\n\n"
        f"| step | ref |\n| --- | --- |\n| 1 | {full} |\n"
    )
    assert cr.build_corroborators(prior, set(), {full}) == set()


def test_rung1_ignores_a_path_named_only_inside_a_fence():
    """THE CRITICAL CASE. citation_exists strips fenced blocks on purpose —
    "fenced examples are legitimately hypothetical". A path named only inside
    a fence on the prior commit was therefore never validated, and must not
    corroborate a new page's invented citation of the same tail. Backticked
    INSIDE the fence on purpose: this must fail closed on the fence itself,
    not merely on the absence of an inline span."""
    full = "tests/fixtures/setup_repos/js_docusaurus/.github/workflows/ci.yml"
    prior = "Nothing is cited here.\n\n```text\n" f"cite it as `{full}`\n" "```\n"
    assert cr.build_corroborators(prior, set(), {full}) == set()


def test_rung1_only_admits_tracked_paths():
    """A citation the linter validated on the prior page still has to name a
    tracked file — extract_citations reports tokens, not existence."""
    prior = "See `totally/invented/thing.md` for details.\n"
    assert cr.build_corroborators(prior, set(), {"real/file.md"}) == set()


def test_rung2_admits_the_batch_source_set():
    got = cr.build_corroborators(None, {"a/b/c.md"}, {"a/b/c.md"})
    assert got == {"a/b/c.md"}


def test_rung2_excludes_glob_entries():
    """Glob characters in source paths must be filtered even when the path is
    tracked. The old fixture (`source_paths={"core/**"}`, `files={"core/x.md"}`)
    was vacuous: "core/**" is never in files, so it was excluded by the pre-existing
    `p in files` check before the glob filter ever ran. This fixture exercises
    the glob filter directly: a path that IS in files but contains a glob character.

    Manifest source_files can carry globs (core/**). Expanding them would make the
    gate ceremony while the diff still reads `if candidate in corroborated`, so we
    exclude them at filter time instead.
    """
    # Discriminating case: path is in files but contains glob char
    got = cr.build_corroborators(None, {"weird[x].md"}, {"weird[x].md"})
    assert got == set()

    # Original manifest case: glob patterns not in files (now a regression test)
    got = cr.build_corroborators(
        None, {"core/**", "docs/superpowers/**"}, {"core/x.md"}
    )
    assert got == set()


def test_no_prior_and_no_sources_corroborates_nothing():
    assert cr.build_corroborators(None, set(), {"a/b.md"}) == set()


def test_uncorroborated_candidate_is_declined_not_repaired(repo):
    """THE CORE GUARD. A unique suffix match with no corroboration must NOT
    be repaired — uniqueness alone establishes nothing about whether the
    token was ever a shortening of anything."""
    text = "See `references/checklist.md`.\n"
    files = cr.tracked_files(repo)
    out, repairs, declines = cr.repair_text(text, repo, CFG, files, corroborators=set())
    assert repairs == []
    assert out == text
    assert declines == [
        (
            "references/checklist.md",
            ".claude/skills/connector-builder/references/checklist.md",
            "uncorroborated",
        )
    ]


def test_corroborated_candidate_is_repaired(repo):
    """The ADIS shape, once the candidate is corroborated."""
    full = ".claude/skills/connector-builder/references/checklist.md"
    text = "See `references/checklist.md`.\n"
    out, repairs, declines = cr.repair_text(
        text, repo, CFG, cr.tracked_files(repo), corroborators={full}
    )
    assert repairs == [("references/checklist.md", full)]
    assert declines == []
    assert full in out


def test_corroboration_matches_the_candidate_not_the_cited_token(repo):
    """Corroborating the TOKEN would be circular — the token is what the
    agent wrote. Only the candidate's provenance counts."""
    text = "See `references/checklist.md`.\n"
    out, repairs, declines = cr.repair_text(
        text,
        repo,
        CFG,
        cr.tracked_files(repo),
        corroborators={"references/checklist.md"},
    )
    assert repairs == []
    assert len(declines) == 1


def test_confabulated_path_that_uniquely_suffix_matches_is_declined(repo):
    """THE REGRESSION PROOF. This is the defect that produced Revision 2.

    Write it against the PRE-FIX code first and watch it FAIL: today a
    unique suffix match is repaired regardless of provenance, so a page
    citing an invented path is silently re-pointed at a real file and the
    lint block becomes a pass."""
    nested = repo / "tests/fixtures/setup_repos/js_docusaurus/.github/workflows"
    nested.mkdir(parents=True)
    (nested / "ci.yml").write_text("on: push\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixture")

    text = "The workflow lives at `.github/workflows/ci.yml`.\n"
    out, repairs, declines = cr.repair_text(
        text, repo, CFG, cr.tracked_files(repo), corroborators=set()
    )
    assert repairs == [], (
        "an invented path that happens to uniquely suffix-match a test "
        "fixture must never be repaired"
    )
    assert out == text


def test_corroborated_invention_is_still_repaired_this_is_the_residual(repo):
    """UNCOMFORTABLE BY DESIGN. Corroboration narrows the confabulation
    surface by ~2 orders of magnitude; it does not close it. ~56% of a real
    batch's source set still exposes a unique non-resolving suffix, and that
    set IS the author's prompt input. This test exists so the residual is
    visible in the suite rather than discovered in production."""
    nested = repo / "tests/fixtures/setup_repos/js_docusaurus/.github/workflows"
    nested.mkdir(parents=True)
    (nested / "ci.yml").write_text("on: push\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixture")

    text = "The workflow lives at `.github/workflows/ci.yml`.\n"
    full = "tests/fixtures/setup_repos/js_docusaurus/.github/workflows/ci.yml"
    out, repairs, declines = cr.repair_text(
        text, repo, CFG, cr.tracked_files(repo), corroborators={full}
    )
    assert repairs == [(".github/workflows/ci.yml", full)]
    assert declines == []
    assert full in out


def test_ambiguous_candidate_is_declined_even_when_corroborated(repo):
    """Corroboration narrows; it does not resolve ambiguity. Two candidates
    still fail closed."""
    second = repo / "other/references"
    second.mkdir(parents=True)
    (second / "checklist.md").write_text("# other\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second")

    both = {
        ".claude/skills/connector-builder/references/checklist.md",
        "other/references/checklist.md",
    }
    text = "See `references/checklist.md`.\n"
    out, repairs, _ = cr.repair_text(
        text, repo, CFG, cr.tracked_files(repo), corroborators=both
    )
    assert repairs == []
    assert out == text


def test_corroborators_has_no_default(repo):
    """An un-threaded call site must fail loudly, never silently revert to
    unconditional repair."""
    import inspect

    sig = inspect.signature(cr.repair_text)
    assert sig.parameters["corroborators"].default is inspect.Parameter.empty
