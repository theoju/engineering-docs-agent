from __future__ import annotations
import sys
from pathlib import Path

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
