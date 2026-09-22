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

import re
import sys
import urllib.parse
from pathlib import Path

import pytest

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


def test_a_traversal_segment_is_returned_untouched():
    """Round-2 adversarial review Important. `_REPO_PATH_RE` admits `.` and
    `/`, so it does not by itself reject a `..` path segment -- confirmed by
    running it PRE-FIX:

        IN:  `eda/../../../../evil-org/evil-repo.md`
        OUT: [`evil-repo.md`](https://github.com/o/eda/blob/main/../../../../evil-org/evil-repo.md)

    That published link is dangerous at the URL level, independent of
    whatever the linter does or does not do with it -- every browser applies
    RFC 3986 dot-segment removal before the request, so the destination
    resolves OFF the configured repository entirely:
    """
    src = "See `eda/../../../../evil-org/evil-repo.md` here."

    # The reasoning this test documents, not an assertion on production
    # output: what the (pre-fix) rendered URL would have resolved to, so the
    # danger is pinned to the actual navigation target rather than just "a
    # `..` string is present".
    danger = urllib.parse.urljoin(
        "https://github.com/theoju/engineering-docs-agent/blob/main/",
        "../../../../evil-org/evil-repo.md",
    )
    assert danger == "https://github.com/evil-org/evil-repo.md", danger

    out = render_external_refs(src, REPOS)
    assert out == src, out  # never becomes a link -- the danger above never publishes

    # NOT asserted: that citation_exists then blocks this token. Measured
    # directly that it does not -- CCE-171's `_relativize` normalizes
    # `eda/../../../../evil-org/evil-repo.md`, the normalized form escapes
    # the repo root, and `_relativize` returns None for an escaping relative
    # path, which check_path's loop treats as "not a repo citation" and
    # silently skips (`continue`), not blocks. The safety here is the same
    # as the Critical-1 tests above: the page text never changes.


def test_a_placeholder_token_is_returned_untouched():
    """Round-2 adversarial review Minor 1 (59 measured cases in the
    reviewer's fuzz). `citation_exists` deliberately exempts `YYYY` and
    `...` as documentation placeholders (`_is_placeholder`, checked BEFORE
    the grammar in `extract_citations`) -- a dated-filename example like
    `eda/docs/YYYY-MM-DD-slug.md` is meant to illustrate a naming pattern,
    not cite a real file. Pre-fix this rendered anyway:

        IN:  `eda/docs/YYYY-MM-DD-slug.md`
        OUT: [`YYYY-MM-DD-slug.md`](PUB/blob/main/docs/YYYY-MM-DD-slug.md)

    -- a live, and 404ing, link to a file that was never meant to exist.
    Same class as the Critical-1 tests' `:symbol`-suffix reasoning: a link
    that predictably 404s but passes every lint is a silent dead link. The
    gate now applies `_is_placeholder` (imported, same as `_REPO_PATH_RE`),
    so the token is left exactly as `citation_exists` would have treated it
    -- exempt, not cited, not touched.
    """
    src = "See `eda/docs/YYYY-MM-DD-slug.md` here."
    out = render_external_refs(src, REPOS)
    assert out == src, out
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


# --------------------------------------------------------------------------
# Round 3: the BACKTICK-RUN DELIMITER class.
#
# Every test above uses single-backtick delimiters, and the only
# triple-backtick anywhere in this file is a fence opener, which never
# reaches `_one` at all -- so none of them can see this class. It is a latent
# defect, not a live one: no config in this repo declares
# `lint.external_repos`.
# --------------------------------------------------------------------------

_PAYLOAD_SRC = "A `eda/scripts/x.py``` B ``<b>PAY</b>` C"


def test_a_token_whose_delimiter_abuts_a_backtick_run_is_left_untouched():
    """THE DISCRIMINATING TEST for the delimiter guard.

    `_INLINE_CODE_RE` models a code span as exactly one backtick per side.
    CommonMark does not: a delimiter is a RUN of backticks, and an opener
    pairs with the next run of EQUAL length anywhere in the paragraph. `_one`
    replaces its match with a markdown link, consuming exactly one backtick
    from each side -- so when the match abuts a run of length >= 2 the run
    lengths change and the whole paragraph re-pairs.

    Measured against the pre-guard code, all three mangled (PUB elided):

        IN:  See ``eda/scripts/x.py`` here.
        OUT: See `[`x.py`](PUB/blob/main/scripts/x.py)` here.

        IN:  See ``eda/scripts/x.py` here.
        OUT: See `[`x.py`](PUB/blob/main/scripts/x.py) here.

        IN:  See `eda/scripts/x.py`` here.
        OUT: See [`x.py`](PUB/blob/main/scripts/x.py)` here.

    The guard declines to rewrite when either delimiter abuts another
    backtick, so all three are byte-identical now.
    """
    for src in (
        "See ``eda/scripts/x.py`` here.",  # balanced 2-run both sides
        "See ``eda/scripts/x.py` here.",  # mismatched: opener longer
        "See `eda/scripts/x.py`` here.",  # mismatched: closer longer
        _PAYLOAD_SRC,  # the measured payload case below
    ):
        assert render_external_refs(src, REPOS) == src, src


def test_a_neighbouring_rewrite_cannot_dissolve_a_code_span(tmp_path):
    """THE CONSEQUENCE. This is the test that would have caught the defect.

    The payload is NOT in the accepted token -- a neighbouring rewrite
    dissolved the code span that was escaping it. Measured against the
    pre-guard code:

        SRC: A `eda/scripts/x.py``` B ``<b>PAY</b>` C
        OUT: A [`x.py`](PUB/blob/main/scripts/x.py)`` B ``<b>PAY</b>` C

        BEFORE html: <p>A <code>eda/scripts/x.py``` B ``&lt;b&gt;PAY&lt;/b&gt;</code> C</p>
        AFTER  html: <p>A <a href="PUB/..."><code>x.py</code></a><code>B</code><b>PAY</b>` C</p>

    `<b>PAY</b>` is escaped inside <code> before and live HTML after. A prior
    review measured 100 payload-attributable Tier-1 BLOCK->PASS flips from
    this class (84 citation_exists, 16 internal_links), 0 PASS->BLOCK; every
    one required the accepted token to sit inside a MISMATCHED backtick run.

    `markdown` is python-markdown, the engine mkdocs renders the published
    site with -- the real consumer, not a model of it. It is a dev-only
    dependency (requirements-dev.txt), skipped where absent, same pattern as
    the ruamel.yaml gate in tests/templates/test_workflow_run_parity.py.
    """
    markdown = pytest.importorskip("markdown")

    out = render_external_refs(_PAYLOAD_SRC, REPOS)
    before_html = markdown.markdown(_PAYLOAD_SRC)
    after_html = markdown.markdown(out)

    # The pre-image: the payload IS escaped in the untouched source. Without
    # this the assertion below would pass on any input that never had a
    # payload in a code span to begin with.
    assert "&lt;b&gt;PAY&lt;/b&gt;" in before_html, before_html
    assert "<b>PAY</b>" not in before_html, before_html

    # The fix: the render is a no-op here, so the rendered HTML is identical
    # and the payload is still escaped.
    assert out == _PAYLOAD_SRC, out
    assert after_html == before_html, after_html
    assert "<b>PAY</b>" not in after_html, after_html


def test_a_declined_token_reverts_to_being_blocked_by_the_linter(tmp_path):
    """The COST of the guard, stated because it is the point of the fix.

    A declared-prefix token the guard declines is left as its raw
    `prefix/path` form, which is pre-CCE-181 behaviour: `citation_exists`
    sees it and blocks. Measured here rather than asserted -- `check_path`
    is the real Tier-1 rule, run unmocked.

    That is the SAFE direction. The page blocks loudly and CCE-140's
    lint_block -> revert handles it, instead of publishing a link built on
    delimiters this module has just demonstrated it cannot model.
    """
    src = "See ``eda/scripts/x.py`` here."
    out = render_external_refs(src, REPOS)
    assert out == src, out

    page = tmp_path / "page.md"
    page.write_text(out)
    ok, msg = check_path(page, tmp_path, set(), {})
    assert ok is False, msg
    assert "cites nonexistent path 'eda/scripts/x.py'" in msg


def test_the_guard_does_not_over_reject_ordinary_citations():
    """Over-rejection is the quiet failure mode of a lexical guard: a
    legitimate citation silently left unrendered, which post-CCE-140 means a
    silently abandoned page. Single-backtick delimiters are what the pipeline
    actually emits, and none of these abut a run, so all three must still
    render."""
    public = render_external_refs("See `eda/scripts/runner.py`.", REPOS)
    assert public == "See [`runner.py`](" + PUB + "/blob/main/scripts/runner.py)."

    private = render_external_refs("See `ship/spokes/pre-flight.md`.", REPOS)
    assert private == "See `pre-flight.md`."

    suffixed = render_external_refs("See `eda/scripts/x.py:Klass.method`.", REPOS)
    assert suffixed == "See [`x.py:Klass.method`](" + PUB + "/blob/main/scripts/x.py)."

    # Two adjacent citations in one line: neither abuts the other, so the
    # guard must not reject either.
    two = render_external_refs("`eda/a.md` and `eda/b.md`", REPOS)
    assert two == (
        "[`a.md`](" + PUB + "/blob/main/a.md) and [`b.md`](" + PUB + "/blob/main/b.md)"
    )


def test_every_rewrite_preserves_the_lines_backtick_run_lengths():
    """The MECHANISM the guard's comment claims, pinned so it cannot go stale.

    What makes a rewrite safe is not that it happens outside a code span --
    code-span membership is a per-paragraph property nothing local can
    determine. It is that the rewrite leaves the line's sequence of
    backtick-run lengths exactly as it found it, so CommonMark pairs the
    paragraph's spans identically before and after. `[`name`](url)` carries
    the same two length-1 runs as the `` `token` `` it replaces, and the
    guard is what keeps those runs at length 1.

    Not pinned, because it is outside the trusted boundary this module
    draws: a backtick in the operator-configured `url`/`ref`/`blob_template`
    would break the property. Those come from the host's own config, not
    from the agent.
    """

    def runs(s):
        return [len(m) for m in re.findall(r"`+", s)]

    lines = [
        "See `eda/scripts/x.py`.",
        "`eda/a.md` and `eda/b.md`",
        "See `ship/spokes/pre-flight.md`.",
        "See ``eda/scripts/x.py`` here.",
        "See ``eda/scripts/x.py` here.",
        "See `eda/scripts/x.py`` here.",
        _PAYLOAD_SRC,
        "``` `eda/a.md` ``` and `eda/b.md`",
        "`eda/a.md``eda/b.md`",
        "See `eda/../evil.md` and `eda/docs/YYYY-MM-DD.md`.",
        "No citation here at all.",
    ]
    for src in lines:
        assert runs(render_external_refs(src, REPOS)) == runs(src), src


def test_a_path_shaped_url_is_not_re_substituted():
    """Whole-branch review Minor: chained `.replace()` scans its OWN output,
    so a `{path}` embedded inside the configured `url` was substituted AGAIN
    when the `{path}` replacement ran last. Pre-fix, `url: "https://h/{path}"`
    plus a citation of `a.md` produced `https://h/a.md/blob/main/a.md` (the
    URL's own literal `{path}` got the real path substituted into it) instead
    of the correct `https://h/{path}/blob/main/a.md`."""
    repos = resolve_config(
        {"lint": {"external_repos": {"eda": {"url": "https://h/{path}"}}}}
    )
    out = render_external_refs("See `eda/a.md`.", repos)
    assert "https://h/{path}/blob/main/a.md" in out, out
