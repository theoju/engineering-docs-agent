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


def test_shortened_citation_is_repaired(repo):
    """The ADIS case, end to end."""
    text = "See `references/checklist.md` for the steps.\n"
    files = cr.tracked_files(repo)
    out, repairs = cr.repair_text(text, repo, CFG, files)
    assert repairs == [
        (
            "references/checklist.md",
            ".claude/skills/connector-builder/references/checklist.md",
        )
    ]
    assert ".claude/skills/connector-builder/references/checklist.md" in out


def test_confabulated_path_is_left_alone(repo):
    """STRICTNESS GUARD. Repair must not weaken the gate citation_exists IS.

    A path matching nothing is a confabulation. Leaving the page byte-identical
    is what keeps citation_exists blocking it.
    """
    text = "See `docs/invented-by-the-model.md`.\n"
    files = cr.tracked_files(repo)
    out, repairs = cr.repair_text(text, repo, CFG, files)
    assert repairs == []
    assert out == text


def test_ambiguous_suffix_is_left_alone(repo):
    """Two candidates, no prior version to disambiguate -> fail closed."""
    second = repo / "other/references"
    second.mkdir(parents=True)
    (second / "checklist.md").write_text("# other\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second")

    text = "See `references/checklist.md`.\n"
    out, repairs = cr.repair_text(text, repo, CFG, cr.tracked_files(repo))
    assert repairs == []
    assert out == text


def test_ambiguity_is_broken_by_the_previous_version(repo):
    """When the prior page cited exactly one candidate, that one wins."""
    second = repo / "other/references"
    second.mkdir(parents=True)
    (second / "checklist.md").write_text("# other\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second")

    prior = "See `.claude/skills/connector-builder/references/checklist.md`.\n"
    text = "See `references/checklist.md`.\n"
    out, repairs = cr.repair_text(
        text, repo, CFG, cr.tracked_files(repo), prior_text=prior
    )
    assert repairs == [
        (
            "references/checklist.md",
            ".claude/skills/connector-builder/references/checklist.md",
        )
    ]


def test_resolving_citation_is_byte_identical(repo):
    text = "See `README.md`.\n"
    out, repairs = cr.repair_text(text, repo, CFG, cr.tracked_files(repo))
    assert repairs == []
    assert out == text


def test_repair_is_idempotent(repo):
    text = "See `references/checklist.md`.\n"
    files = cr.tracked_files(repo)
    once, _ = cr.repair_text(text, repo, CFG, files)
    twice, repairs = cr.repair_text(once, repo, CFG, files)
    assert repairs == []
    assert twice == once


def test_exempt_token_is_never_repaired(repo):
    """Exclusion row 1. The host declared this unverifiable on purpose."""
    cfg = {"lint": {"citation_exempt_tokens": ["references/checklist.md"]}}
    text = "See `references/checklist.md`.\n"
    out, repairs = cr.repair_text(text, repo, cfg, cr.tracked_files(repo))
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
    out, repairs = cr.repair_text(text, repo, CFG, cr.tracked_files(repo))
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
    out, repairs = cr.repair_text(text, repo, CFG, cr.tracked_files(repo))
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
    out, repairs = cr.repair_text(text, repo, CFG, cr.tracked_files(repo))
    assert repairs == []
    assert out == text


def test_rung1_raw_scan_sees_frontmatter_and_table_sites():
    """The ADIS incident cited the full path in frontmatter (line 6), prose
    (27) and a table (92). extract_citations sees only backticked spans in
    unfenced prose, so a rung built on it could miss the very evidence this
    ticket exists for. The scan must be raw."""
    full = ".claude/skills/connector-builder/references/checklist.md"
    prior = (
        "---\n"
        f"sources:\n  - {full}\n"
        "---\n\n"
        f"| step | ref |\n| --- | --- |\n| 1 | {full} |\n"
    )
    got = cr.build_corroborators(prior, set(), {full})
    assert full in got


def test_rung1_only_admits_tracked_paths():
    """A raw scan must not admit arbitrary strings from the prior page."""
    prior = "See totally/invented/thing.md for details.\n"
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
