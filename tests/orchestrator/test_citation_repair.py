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
    """The bare-path equality check in `_sub`.

    The old fixture paired the old token with `README.md`, which does not
    CONTAIN the old token -- so deleting the check could not fail it:
    `token.replace(old, new, 1)` is a no-op on a string the old token does not
    occur in. A LONGER VALID citation containing the old token as a substring
    is the discriminating case. Without the equality check,
    `docs/references/checklist.md` becomes `docs/a/b/references/checklist.md`
    -- a path invented by the repair itself, on a citation that was already
    correct.
    """
    text = (
        "Both `references/checklist.md` and `docs/references/checklist.md` "
        "are cited.\n"
    )
    out = cr.rewrite_token(
        text, "references/checklist.md", "a/b/references/checklist.md"
    )
    assert "`a/b/references/checklist.md`" in out
    assert "`docs/references/checklist.md`" in out, (
        "a longer citation that merely contains the old token must be left alone"
    )
    assert out == text.replace(
        "`references/checklist.md`", "`a/b/references/checklist.md`", 1
    )


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


def test_rewrite_applies_inside_the_body_of_an_unterminated_fence():
    """An unterminated fence loses its OPENER and keeps its BODY.

    strip_fenced_blocks `continue`s past the opener before appending it, and
    the `del out[fence_start:]` that would cut the body back out never runs on
    a fence that never closes -- nothing was appended for it to cut. So
    extract_citations DOES see the body token, and skipping it would make
    repair_text report a repair it never applied.

    The previous docstring here asserted something stronger and false ("an
    UNTERMINATED fence strips nothing"), which is exactly what let the
    CLOSED-fence mirror look correct: the body half of that claim is right,
    the opener half never was. See the test below for the half it got wrong.
    """
    text = "```\nsee `references/checklist.md`\n"
    assert cr.extract_citations(text)["paths"] == ["references/checklist.md"], (
        "fixture guard: the linter must actually READ this token, or the test "
        "asserts nothing about the mirror"
    )
    out = cr.rewrite_token(
        text, "references/checklist.md", "a/b/references/checklist.md"
    )
    assert "a/b/references/checklist.md" in out


def test_rewrite_never_touches_the_dropped_opener_of_an_unterminated_fence():
    """THE GHOST REPAIR. A citation written ON the opener line of a fence that
    never closes is invisible to extract_citations -- strip_fenced_blocks drops
    that line before appending anything -- yet the CLOSED-fence mirror reported
    NO dropped lines at all for an unterminated fence, so rewrite_token edited
    it anyway.

    That is the report/apply contract inverted: the page is mutated at a site
    the lint cannot see, so a rewrite the rule exists to police never reaches
    it. Names `_linter_dropped_lines`.
    """
    text = "~~~ see `references/checklist.md`\nbody\n"
    assert cr.extract_citations(text)["paths"] == [], (
        "fixture guard: the linter must NOT see this token, or the ghost this "
        "test names cannot occur"
    )
    assert (
        cr.rewrite_token(
            text, "references/checklist.md", "a/b/references/checklist.md"
        )
        == text
    )


def test_rewrite_skips_a_closed_info_string_fence():
    """INFO-STRING FENCES -- the dominant real-world form, and the only shape
    that exercises the `stripped[:3]` truncation in `strip_fenced_blocks`.

    A ```python opener closes against a bare ``` terminator only because both
    sides are truncated to three characters. Without the truncation the fence
    never closes, reads as UNTERMINATED, loses only its opener -- and the
    illustration inside becomes a live citation that repair rewrites, turning
    a deliberate example into a false claim about real code.

    Every other fence opener in this file is bare, so nothing else here
    discriminates on that truncation: mutating `stripped[:3]` -> `stripped`
    used to leave the whole suite green.
    """
    text = (
        "See `references/checklist.md`.\n"
        "\n"
        "```python\n"
        "cite it as `references/checklist.md`\n"
        "```\n"
    )
    out = cr.rewrite_token(
        text, "references/checklist.md", "a/b/references/checklist.md"
    )
    assert out.count("a/b/references/checklist.md") == 1
    assert "cite it as `references/checklist.md`" in out


def test_rewrite_skips_a_closed_tilde_info_string_fence():
    """The same truncation on the tilde side: `~~~yaml` closed by a bare
    `~~~`. Both fence characters are covered, so a partial revert of the
    truncation is caught rather than only a wholesale one."""
    text = (
        "See `references/checklist.md`.\n"
        "\n"
        "~~~yaml\n"
        "cite it as `references/checklist.md`\n"
        "~~~\n"
    )
    out = cr.rewrite_token(
        text, "references/checklist.md", "a/b/references/checklist.md"
    )
    assert out.count("a/b/references/checklist.md") == 1
    assert "cite it as `references/checklist.md`" in out


def test_a_broken_strip_fenced_blocks_contract_fails_loudly(monkeypatch):
    """The derivation reads its index markers back out of
    `strip_fenced_blocks`'s output, which works only because that function
    appends its input lines VERBATIM. If it ever stopped doing so the alignment
    would be unknowable, and guessing it silently is the one outcome forbidden
    here: `repair_text` would report a rewrite the page never received.

    Both verbatim-contract branches, simulated by the two shapes any content
    transformation there would take -- a survivor with no marker at all, and a
    survivor whose marker no longer names its own line.
    """
    monkeypatch.setattr(cr, "strip_fenced_blocks", lambda text: "a\nb")
    with pytest.raises(RuntimeError, match="no line marker"):
        cr.rewrite_token("a\nb\n", "refs/x.md", "a/b/refs/x.md")

    # Codes intact (width 1: " " is index 0, "\t" is index 1), bodies swapped.
    monkeypatch.setattr(cr, "strip_fenced_blocks", lambda text: " b\n\ta")
    with pytest.raises(RuntimeError, match="does not name its source line"):
        cr.rewrite_token("a\nb\n", "refs/x.md", "a/b/refs/x.md")


def test_a_marker_that_perturbs_the_linter_fails_loudly(monkeypatch):
    """The index code lives in LEADING WHITESPACE because
    `strip_fenced_blocks` lstrips every line before deciding anything about
    it. That is a contract, not a law, and this is what happens when it
    breaks: the marked and unmarked runs keep DIFFERENT lines, the alignment
    stops meaning anything, and the derivation refuses rather than guesses.

    Simulated by a `strip_fenced_blocks` that reads the RAW line instead of
    the lstripped one -- precisely the change that would stop the whitespace
    code being invisible to it.
    """

    def raw_line_sensitive(text: str) -> str:
        return "\n".join(
            line for line in text.splitlines() if not line.startswith("\t")
        )

    monkeypatch.setattr(cr, "strip_fenced_blocks", raw_line_sensitive)
    with pytest.raises(RuntimeError, match="perturbs strip_fenced_blocks"):
        cr.rewrite_token("a\nb\nc\n", "refs/x.md", "a/b/refs/x.md")


# The invariant the mirror exists to deliver, as a table: repair rewrites a
# line IF AND ONLY IF the linter reads that line. One citation per row; `seen`
# is what extract_citations reports, `rewritten` is whether rewrite_token
# changed anything at all.
#
# This is the REGRESSION guard on `_linter_dropped_lines`, not a probe of
# strip_fenced_blocks. It holds trivially while the dropped set is DERIVED from
# the linter by running it, and it breaks the moment anyone re-derives that
# bookkeeping by hand: `opener_carries_the_citation` is the row that fails
# against the CLOSED-fence mirror this replaced (verified by reverting the
# derivation and re-running -- it is the ONLY row that does, which is why the
# named ghost test above exists as well). The two info-string tests are what
# discriminate on the linter's own internals; nothing here can, because both
# sides of the comparison now come from the same function.
FENCE_SHAPES = (
    ("plain_prose", "cite `refs/x.md`\n"),
    ("closed_bare_fence", "p\n```\ncite `refs/x.md`\n```\n"),
    ("closed_info_string_fence", "p\n```python\ncite `refs/x.md`\n```\n"),
    ("closed_tilde_info_string_fence", "p\n~~~yaml\ncite `refs/x.md`\n~~~\n"),
    ("indented_closed_fence", "p\n  ```\n  cite `refs/x.md`\n  ```\n"),
    ("unterminated_fence_body", "```python\ncite `refs/x.md`\n"),
    ("opener_carries_the_citation", "~~~ cite `refs/x.md`\nbody\n"),
    ("tilde_does_not_close_a_backtick_fence", "```\ncite `refs/x.md`\n~~~\n"),
    (
        "fence_opened_after_a_u2028_break",
        "Example:\N{LINE SEPARATOR}```\ncite `refs/x.md`\n```\n",
    ),
    ("closing_fence_carries_the_citation", "```\nbody\n``` cite `refs/x.md`\n"),
)


@pytest.mark.parametrize(
    "shape,text", FENCE_SHAPES, ids=[name for name, _ in FENCE_SHAPES]
)
def test_rewrite_touches_a_line_iff_the_linter_reads_it(shape, text):
    seen = "refs/x.md" in cr.extract_citations(text)["paths"]
    rewritten = cr.rewrite_token(text, "refs/x.md", "a/b/refs/x.md") != text
    assert seen == rewritten, (
        f"{shape}: linter reads the citation={seen}, repair rewrote it="
        f"{rewritten} -- repair must rewrite a line iff the linter reads it"
    )


# The EIGHT characters that survive Path.read_text()'s universal-newline
# translation yet ARE str.splitlines() boundaries. Written as escapes on
# purpose: six are invisible and two are zero-width in most editors, so a
# literal here would be unreviewable. "\r" is deliberately absent -- read_text
# normalises it, so it never reaches this code.
#
# Re-derived rather than copied: every codepoint below U+3000 was written to a
# file as UTF-8, read back with Path.read_text(), and kept when it BOTH
# survived that round trip AND split "a<ch>b" into two under splitlines(). The
# previous list said six and omitted \x1d (GS) and \x1e (RS); both behaved
# exactly like the other six against the pre-fix code, so the shortfall was a
# documentation and coverage gap, not a defect -- splitlines() handles all
# eight uniformly and the shipped code always did.
SPLITLINES_ONLY = "\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}\x85\x0b\x0c\x1c\x1d\x1e"


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
    """The same divergence via \\x0b. Two of the eight are covered here as a
    spot check, so a partial revert of either iteration site is caught, not
    just a wholesale one; the byte-fidelity test below covers all eight."""
    text = "Example:\x0b```\ncite `references/checklist.md`\n```\n"
    out = cr.rewrite_token(
        text, "references/checklist.md", "a/b/references/checklist.md"
    )
    assert out == text


def test_rewrite_preserves_splitlines_only_terminators_byte_for_byte():
    """Iterating splitlines() is only half the fix: "\\n".join() would then
    normalise all EIGHT characters into newlines on every page containing one.
    Lines are rejoined with their OWN terminators, so a line this function did
    not rewrite comes back verbatim and only the cited span changes.

    All eight appear below, \\x1d and \\x1e included -- they were missing from
    the original list of six, and an uncovered character is a character the
    join could silently normalise with nothing to catch it."""
    text = (
        "alpha\N{LINE SEPARATOR}beta\N{PARAGRAPH SEPARATOR}gamma\x85"
        "delta\x0bepsilon\x0czeta\x1ceta\x1dtheta\x1eiota\n"
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


def test_a_resolving_citation_is_never_retargeted(repo):
    """THE `_resolves` GUARD, in isolation.

    Deleting `if _resolves(...): continue` from repair_text left the whole
    suite green. The tests that name this case
    (test_resolving_citation_is_byte_identical, test_repair_is_idempotent) have
    fixtures with ZERO strict suffix candidates, so `len(candidates) != 1`
    decided them first and `_resolves` was never consulted.

    Here the cited `docs/index.md` RESOLVES and also has exactly one strict
    suffix candidate, `vendor/pkg/docs/index.md`, which IS corroborated. Every
    other guard passes, so `_resolves` is the only thing standing between a
    working citation and being silently retargeted at a different tracked file.
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
    # by `len(candidates) != 1` and would stop exercising `_resolves` at all.
    assert cr.suffix_candidates("docs/index.md", files) == ["vendor/pkg/docs/index.md"]

    text = "See `docs/index.md`.\n"
    out, repairs, declines = cr.repair_text(
        text, repo, CFG, files, corroborators={"vendor/pkg/docs/index.md"}
    )
    assert repairs == []
    assert declines == []
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
    and NOTHING else — a "\n".join() round-trip would silently rewrite eight
    distinct characters on every page that contains one."""
    text = (
        "alpha\u2028beta\u2029gamma\x85delta\x0bepsilon\x0czeta\x1ceta"
        "\x1dtheta\x1eiota\n"
        "\n"
        "See `references/checklist.md`.\n"
    )
    out, repairs, _ = cr.repair_text(
        text, repo, CFG, cr.tracked_files(repo), corroborators={FULL}
    )
    assert repairs == [("references/checklist.md", FULL)]
    assert out == text.replace("`references/checklist.md`", f"`{FULL}`")


def test_a_padded_inline_span_is_both_reported_and_applied(repo):
    """THE `.strip()` IN `_sub`'s EQUALITY TEST.

    `extract_citations` strips each inline-code token before matching, so
    `` ` references/checklist.md ` `` IS a citation the linter extracts and
    `repair_text` therefore repairs. `_sub` must strip the same way before
    comparing, or the two ends disagree: `repair_text` reports the repair while
    `rewrite_token` matches nothing and the page is returned untouched —
    precisely the report/apply divergence this module forbids, and the reason
    the assertion below is on `out`, not only on `repairs`.

    Mutating `_SUFFIX_RE.sub("", token.strip())` -> `_SUFFIX_RE.sub("", token)`
    used to leave the full suite green.

    The padding survives the rewrite: the replacement happens inside the
    ORIGINAL token, so only the path changes, and a second pass is a no-op.
    """
    text = "See ` references/checklist.md ` for the steps.\n"
    files = cr.tracked_files(repo)
    assert cr.extract_citations(text)["paths"] == ["references/checklist.md"], (
        "fixture guard: the linter must extract the PADDED span, or repair_text "
        "never reports anything and the divergence cannot occur"
    )

    out, repairs, declines = cr.repair_text(
        text, repo, CFG, files, corroborators={FULL}
    )
    assert repairs == [("references/checklist.md", FULL)]
    assert declines == []
    assert out != text, "reported a repair the page never received"
    assert out == f"See ` {FULL} ` for the steps.\n"

    again, repairs_again, _ = cr.repair_text(
        out, repo, CFG, files, corroborators={FULL}
    )
    assert repairs_again == []
    assert again == out


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


# An absolute path outside the repo has an EMPTY first segment, and no path
# `git ls-files` emits has one -- so for any git-derived `files`,
# `suffix_candidates` returns nothing for such a token and `len(candidates)
# != 1` decides it before `if rel is None` is ever consulted. The previous
# version of the test below cited `/etc/nginx/nginx.conf` against the plain
# fixture and claimed the opposite in its docstring; mutating the named guard
# to `rel = cited` left the whole suite green, and only total deletion turned
# it red, via an incidental TypeError from `repo_root / None`. It proved "no
# crash", not "never repaired".
_ABSOLUTE_CITED = "/etc/__cr_absent__/thing.conf"
# The only shape that can suffix-match an absolute token: a tracked path whose
# tail segments include that empty one. Grotesque on purpose -- see the test.
_ABSOLUTE_CANDIDATE = "vendor/" + _ABSOLUTE_CITED  # note the doubled slash


def test_absolute_path_outside_repo_is_never_repaired(repo):
    """Exclusion row 4: `_relativize` returns None for a path outside the repo,
    and that guard is the ONLY thing standing between this input and a repair.

    `citation_exists._relativize` treats an absolute path that does not resolve
    inside `repo_root` as an environment reference, not a repo citation — there
    is nothing repo-relative to check it against.

    Making the guard decide takes an injected candidate, and the injection is
    honest about what it is. `git ls-files` cannot emit
    `vendor//etc/__cr_absent__/thing.conf`: git has no empty path segments, so
    with a git-derived `files` this guard can never be the decider. But `files`
    is a PARAMETER of `repair_text`, so the guard is a contract on the
    parameter rather than on git's output — the same framing, and the same
    injection, as the candidate-side sibling
    `test_candidate_outside_the_repo_is_declined`. What the injection buys is a
    fixture where every EARLIER guard passes, asserted below, so deleting or
    inverting `if rel is None` is what flips the result.

    The cited path must be guaranteed ABSENT from the test machine, which is
    why it is `/etc/__cr_absent__/thing.conf` and not `/etc/nginx/nginx.conf`.
    `repo_root / "/abs/path"` is `/abs/path`, so `_resolves`'s on-disk arm
    would answer True for a file that happens to exist on the runner and
    short-circuit before the candidate arithmetic — re-vacuuming the test on
    some machines and not others.
    """
    files = cr.tracked_files(repo) | {_ABSOLUTE_CANDIDATE}
    text = f"See `{_ABSOLUTE_CITED}`.\n"

    # Fixture guards: every earlier guard must PASS, or this test stops
    # exercising `if rel is None` and goes back to proving nothing.
    assert cr.extract_citations(text)["paths"] == [_ABSOLUTE_CITED], (
        "the linter must surface this token as a path citation"
    )
    assert cr._relativize(_ABSOLUTE_CITED, repo) is None, "the guard must be armed"
    assert not (repo / _ABSOLUTE_CITED).exists(), "the cited token must not resolve"
    assert cr.suffix_candidates(_ABSOLUTE_CITED, files) == [_ABSOLUTE_CANDIDATE], (
        "exactly one candidate, or `len(candidates) != 1` decides this first"
    )
    assert cr._candidate_rejection(_ABSOLUTE_CANDIDATE, repo, CFG, files) is None, (
        "the candidate gate must pass, or IT decides this first"
    )

    out, repairs, declines = cr.repair_text(
        text, repo, CFG, files, corroborators={_ABSOLUTE_CANDIDATE}
    )
    assert repairs == []
    assert declines == []
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


# --- The verifiability gate -------------------------------------------------
# The four rows above were a BLACKLIST of the classes check_path declines to
# check, and a blacklist can only enumerate what someone thought of. It missed
# a row twice, both times the same shape: the repair moved the citation into a
# region the linter does not verify, so the page flipped from BLOCK to `ok` and
# was never checked again. The gate is positive now -- the linter must both SEE
# the candidate and verify it BY EXISTENCE -- so an unnamed class declines.


def test_candidate_the_extractor_cannot_parse_is_declined(repo):
    r"""MISS 1, the reproduced case. `_REPO_PATH_RE` admits only `[\w.\-/]`, so a
    tracked candidate carrying a parenthesis survives every candidate-side
    check the blacklist knew about, gets written into the page, and is then not
    SEEN by extract_citations at all: check_path went (False, 'cites
    nonexistent path ...') -> (True, 'ok'), and stayed 'ok' after `git rm` of
    the file it names. Bracketed and parenthesised route paths are ordinary --
    the reference host tracks `app/dimensions/[id]/page.tsx` and
    `app/tips/[n]/page.tsx`.

    Names `_extractor_sees`.
    """
    routed = repo / "app/(marketing)/guides"
    routed.mkdir(parents=True)
    (routed / "setup.md").write_text("# setup\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "parenthesised route")

    files = cr.tracked_files(repo)
    candidate = "app/(marketing)/guides/setup.md"
    # Fixture guards: every EARLIER guard must pass, or this test would be
    # decided before `_extractor_sees` is ever consulted.
    assert candidate in files
    assert cr.suffix_candidates("guides/setup.md", files) == [candidate]
    assert not (repo / "guides/setup.md").exists(), "the cited token must not resolve"

    text = "See `guides/setup.md`.\n"
    out, repairs, declines = cr.repair_text(
        text, repo, CFG, files, corroborators={candidate}
    )
    assert repairs == []
    assert out == text
    assert declines == [("guides/setup.md", candidate, "candidate_unextractable")]


def test_candidate_with_a_placeholder_marker_is_declined_despite_corroboration(repo):
    """THE FAIL-CLOSED PROPERTY, stated directly: a candidate the linter's
    extractor does not return is declined no matter how well corroborated.

    A second, DIFFERENT extractor rule from the one above -- `_is_placeholder`,
    not `_REPO_PATH_RE` -- reached through the same round-trip, which is the
    point of round-tripping rather than re-deriving: both rules, and any future
    third, are inherited.

    The corroborator is passed directly rather than built by
    `build_corroborators`, whose `_GLOB_CHARS` filter would drop a `{` path
    first and decide this case as `uncorroborated` -- the gate would never be
    reached and the test would assert nothing about it.

    Names `_extractor_sees`.
    """
    templated = repo / "app/{slug}/guides"
    templated.mkdir(parents=True)
    (templated / "page.md").write_text("# page\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "templated route")

    files = cr.tracked_files(repo)
    candidate = "app/{slug}/guides/page.md"
    assert candidate in files
    assert cr.suffix_candidates("guides/page.md", files) == [candidate]
    assert not (repo / "guides/page.md").exists(), "the cited token must not resolve"

    text = "See `guides/page.md`.\n"
    out, repairs, declines = cr.repair_text(
        text, repo, CFG, files, corroborators={candidate}
    )
    assert repairs == []
    assert out == text
    assert declines == [("guides/page.md", candidate, "candidate_unextractable")]


def test_candidate_under_the_mkdocs_build_dir_is_declined(repo):
    """MISS 2, the reproduced case. `_resolves` returns True for ANY path under
    the mkdocs `site_dir` with no existence check whatsoever, so a tracked
    candidate under it parks the citation in an unconditionally-resolving
    namespace -- structurally identical to `example/`. Repair used to fire with
    no decline; then `git rm site/refs/notes.md` and check_path still answered
    (True, 'ok'). `repair_text` already computed `build_dir` and never
    consulted it for candidates.

    Names `_resolves_absent`.
    """
    (repo / "mkdocs.yml").write_text("site_name: x\nsite_dir: site\n")
    built = repo / "site/refs"
    built.mkdir(parents=True)
    (built / "notes.md").write_text("# notes\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "committed build output")

    files = cr.tracked_files(repo)
    candidate = "site/refs/notes.md"
    assert candidate in files
    assert cr.suffix_candidates("refs/notes.md", files) == [candidate]
    assert not (repo / "refs/notes.md").exists(), "the cited token must not resolve"
    # Fixture guard: with no parseable mkdocs config `build_dir` is "" and the
    # arm under test is INERT, which would make this test vacuous.
    assert cr._build_dir(repo) == "site"

    text = "See `refs/notes.md`.\n"
    out, repairs, declines = cr.repair_text(
        text, repo, CFG, files, corroborators={candidate}
    )
    assert repairs == []
    assert out == text
    assert declines == [
        ("refs/notes.md", candidate, "candidate_unverified_namespace")
    ]


def test_candidate_outside_the_build_dir_is_still_repaired(repo):
    """The build-dir probe must DISCRIMINATE, not blanket-decline. Same host,
    same configured `site_dir`, a candidate that simply is not under it: the
    ADIS repair still fires.

    Names `_resolves_absent` in the other direction -- forcing it to True
    breaks this test while leaving the decline tests green.
    """
    (repo / "mkdocs.yml").write_text("site_name: x\nsite_dir: site\n")
    built = repo / "site"
    built.mkdir()
    (built / "index.html").write_text("<html></html>\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "build dir exists")

    files = cr.tracked_files(repo)
    assert cr._build_dir(repo) == "site", "the arm under test must be armed"
    assert cr.suffix_candidates("references/checklist.md", files) == [FULL]

    text = "See `references/checklist.md`.\n"
    out, repairs, declines = cr.repair_text(
        text, repo, CFG, files, corroborators={FULL}
    )
    assert declines == []
    assert repairs == [("references/checklist.md", FULL)]
    assert FULL in out


def test_a_cause_the_gate_does_not_name_fails_closed(repo, monkeypatch):
    """THE FAIL-CLOSED PROPERTY of the gate as a whole. Every named check
    answers a question this module thought to ask; the last one asks
    `check_path` whether it would report an absent file in the candidate's
    location, so a skip class nobody has heard of still answers.

    Simulated by making that probe's `check_path` answer `ok` -- exactly what a
    new skip branch in its paths loop would do -- on an otherwise perfect ADIS
    repair. Every other guard passes, corroboration is present, and the repair
    is still refused.

    Names `_linter_reports_an_absent_file`.
    """
    files = cr.tracked_files(repo)
    text = "See `references/checklist.md`.\n"
    # Fixture guard: unpatched, this exact call repairs (see
    # test_shortened_citation_is_repaired), so the probe is what decides it.
    assert cr.suffix_candidates("references/checklist.md", files) == [FULL]

    monkeypatch.setattr(cr, "check_path", lambda *_a, **_kw: (True, "ok"))
    out, repairs, declines = cr.repair_text(
        text, repo, CFG, files, corroborators={FULL}
    )
    assert repairs == []
    assert out == text
    assert declines == [("references/checklist.md", FULL, "candidate_unverified")]


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
