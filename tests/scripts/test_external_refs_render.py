"""CCE-181: the transform, and the two traps the prototype found by RUNNING it.

Trap 1 -- link text must be slash-free. [`scripts/x.py`](url) STILL BLOCKS:
extract_citations scans backticked spans wherever they appear and markdown link
syntax exempts nothing. The obvious rendering is the broken one.

Trap 2 -- the :line/:symbol suffix is citation grammar, not a filesystem path.
Left in the address it yields a 404 that PASSES the linter, so nothing
downstream can catch it.

Both are asserted against the REAL grammar via extract_citations, not against a
hand-written expectation, so a change to the grammar surfaces here.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts" / "lint"))

from citation_exists import check_path, extract_citations  # noqa: E402

from scripts.external_refs import render_external_refs, resolve_config  # noqa: E402

PUB = "https://github.com/theoju/engineering-docs-agent"
REPOS = resolve_config(
    {"lint": {"external_repos": {"eda": {"url": PUB}, "ship": {"private": True}}}}
)


def test_a_file_at_the_external_repo_root():
    out = render_external_refs("See `eda/CLAUDE.md`.", REPOS)
    assert out == "See [`CLAUDE.md`](" + PUB + "/blob/main/CLAUDE.md)."


def test_a_file_deep_in_the_external_repo():
    out = render_external_refs("See `eda/scripts/runner.py`.", REPOS)
    assert out == "See [`runner.py`](" + PUB + "/blob/main/scripts/runner.py)."


def test_the_link_text_is_slash_free_and_the_linter_sees_nothing():
    """TRAP 1. This is the regression guard. If someone 'improves' the link
    text back to the full path, extract_citations finds it again and the
    build blocks -- silently restoring the bug this ticket fixes."""
    out = render_external_refs("See `eda/scripts/runner.py`.", REPOS)
    link_text = out.split("[`")[1].split("`]")[0]
    assert "/" not in link_text, link_text
    assert extract_citations(out)["paths"] == []


def test_a_symbol_suffix_is_stripped_from_the_url_and_kept_in_the_text():
    """TRAP 2. Found by running the prototype, not by reading the design."""
    out = render_external_refs("See `eda/scripts/x.py:Klass.method`.", REPOS)
    assert out == "See [`x.py:Klass.method`](" + PUB + "/blob/main/scripts/x.py)."
    assert extract_citations(out)["paths"] == []


def test_a_line_suffix_is_stripped_from_the_url_too():
    out = render_external_refs("See `eda/scripts/x.py:128`.", REPOS)
    assert "(" + PUB + "/blob/main/scripts/x.py)" in out


def test_a_private_repo_names_the_file_and_never_the_repo():
    out = render_external_refs("See `ship/spokes/pre-flight.md`.", REPOS)
    assert out == "See `pre-flight.md`."
    assert "ship" not in out
    assert "http" not in out
    assert extract_citations(out)["paths"] == []


def test_an_undeclared_prefix_is_untouched_and_still_blocks():
    """The escape is opt-in per token. A confabulation has no declared prefix,
    so nothing rewrites it and citation_exists still sees it."""
    src = "See `scripts/does_not_exist.py`."
    out = render_external_refs(src, REPOS)
    assert out == src
    assert extract_citations(out)["paths"] == ["scripts/does_not_exist.py"]


def test_a_fenced_sample_is_never_rewritten():
    src = "Example:\n\n```\n`eda/CLAUDE.md`\n```\n"
    assert render_external_refs(src, REPOS) == src


def test_rendering_is_idempotent():
    once = render_external_refs("See `eda/CLAUDE.md`.", REPOS)
    assert render_external_refs(once, REPOS) == once


def test_no_declarations_is_a_true_no_op():
    src = "See `eda/CLAUDE.md` and `scripts/x.py`."
    assert render_external_refs(src, {}) == src


def test_an_unbalanced_paren_and_raw_html_token_is_returned_untouched(tmp_path):
    """Whole-branch review Critical 1, CONFIRMED BY RUNNING IT pre-fix:

        IN:  See `eda/x.md)<img src=x onerror=alert(1)>` here.
        OUT: See [`x.md)<img src=x onerror=alert(1)>`](PUB/blob/main/x.md)<img src=x onerror=alert(1)>) here.

    `_INLINE_CODE_RE` matches any char but a backtick, and pre-fix `_one`
    interpolated the token unvalidated. The unbalanced `)` terminates the
    CommonMark link destination early; everything after it re-emits as RAW
    HTML outside any code span -- live HTML through mkdocs/python-markdown.
    This test failed against the pre-fix code (`out == src` raised, `out`
    being the mangled OUT above) and passes now: the grammar gate in `_one`
    rejects the token -- it contains `)`, `<`, `>`, none of which
    `_REPO_PATH_RE` admits -- and returns the match completely UNCHANGED.

    Second assertion, measured rather than assumed: this token is NOT
    'blocked by citation_exists.check_path', before or after this fix. `<`
    and `>` are `_PLACEHOLDER_MARKERS`, so `_is_placeholder` makes
    `extract_citations` skip it -- citation_exists treating it as a
    doc-placeholder is pre-existing behaviour this fix neither opens nor
    closes (and must not touch: citation_exists does not change). What
    actually closes the vulnerability, and what this test pins, is that the
    page text is byte-identical to the pre-CCE-181, pre-vulnerability input
    -- an ordinary backticked code span, which markdown escapes and never
    lets break out into live HTML.
    """
    src = "See `eda/x.md)<img src=x onerror=alert(1)>` here."
    out = render_external_refs(src, REPOS)
    assert out == src, out

    page = tmp_path / "page.md"
    page.write_text(out)
    ok, msg = check_path(page, tmp_path, set(), {})
    assert ok is True, msg  # not blocked -- see docstring: is_placeholder exempts it
    assert extract_citations(out)["paths"] == []


def test_a_token_with_an_embedded_space_is_returned_untouched(tmp_path):
    """Benign sibling of the adversarial test above -- no HTML, just an
    ordinary LLM slip (a stray space), which the review named as the benign
    half of the same root cause ('a stray `)` or a space produces a
    silently-broken link'). Pre-fix this also gets mangled:

        IN:  See `eda/scripts x.py` here.
        OUT: See [`scripts x.py`](PUB/blob/main/scripts x.py) here.

    -- an unescaped space in a CommonMark link destination. Same grammar
    gate, same untouched result. Same citation_exists finding as above too,
    for a different reason: a bare space is not in `_REPO_PATH_RE`'s
    character class either, so `extract_citations` never recognized this as
    a path citation in the first place -- fixed or not, declared prefix or
    not, this token was always invisible to citation_exists.
    """
    src = "See `eda/scripts x.py` here."
    out = render_external_refs(src, REPOS)
    assert out == src, out

    page = tmp_path / "page.md"
    page.write_text(out)
    ok, msg = check_path(page, tmp_path, set(), {})
    assert ok is True, msg
    assert extract_citations(out)["paths"] == []


def test_a_ref_and_template_override_reach_the_url():
    repos = resolve_config(
        {
            "lint": {
                "external_repos": {
                    "gl": {
                        "url": "https://gitlab.com/o/r",
                        "ref": "master",
                        "blob_template": "{url}/-/blob/{ref}/{path}",
                    }
                }
            }
        }
    )
    out = render_external_refs("See `gl/a/b.py`.", repos)
    assert "https://gitlab.com/o/r/-/blob/master/a/b.py" in out
