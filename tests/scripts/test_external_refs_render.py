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

from citation_exists import extract_citations  # noqa: E402

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
