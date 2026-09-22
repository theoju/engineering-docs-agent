"""CCE-181: ordering is load-bearing -- render, THEN diagnose, THEN validate.

_diagnose_citation_paths reports what a BLOCKED citation was probably shortened
from. Run before the render it would see `eda/CLAUDE.md`, fail to resolve it,
and emit suffix-match noise for a token that is about to become a link. Render
first and that false-positive class does not exist.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as orun  # noqa: E402


def test_the_renderer_runs_before_the_diagnostic(tmp_path, monkeypatch):
    page = tmp_path / "page.md"
    page.write_text("See `eda/CLAUDE.md`.")
    seen: list[str] = []

    def _spy(path, repo_root, config, state, source_paths=None):
        seen.append(Path(path).read_text())

    monkeypatch.setattr(orun, "_diagnose_citation_paths", _spy)
    config = {"lint": {"external_repos": {"eda": {"url": "https://x.example/r"}}}}
    orun._render_external_refs_for_pages([str(page)], config)
    orun._diagnose_citation_paths(str(page), tmp_path, config, {}, source_paths=set())

    assert seen == ["See [`CLAUDE.md`](https://x.example/r/blob/main/CLAUDE.md)."]


def test_a_bare_host_leaves_the_file_byte_identical(tmp_path):
    page = tmp_path / "page.md"
    original = "See `eda/CLAUDE.md` and `scripts/x.py`."
    page.write_text(original)
    before = page.stat().st_mtime_ns
    orun._render_external_refs_for_pages([str(page)], {"lint": {}})
    assert page.read_text() == original
    assert page.stat().st_mtime_ns == before, "an unchanged page must not be rewritten"


def test_a_missing_page_is_skipped_not_raised(tmp_path):
    orun._render_external_refs_for_pages([str(tmp_path / "gone.md")], {"lint": {}})


# --- the production call site ------------------------------------------------
#
# Everything above drives `_render_external_refs_for_pages` and
# `_diagnose_citation_paths` directly, in whatever order the test wrote them
# in -- it proves the two functions COMPOSE correctly but says nothing about
# whether `run()` actually calls them in that order. Verified empirically:
# commenting out the `_render_external_refs_for_pages(authored, config)` call
# site in `run()` left all three tests above green. The test below is what
# fails when the call site is removed or moved after the diagnostic.

_SEED_STATE = {"version": "1", "dismissed_gap_flags": {}, "cursors": {}}
FAKES = Path(__file__).parent / "fakes"

# The dry-run fakes drive one batch: source-collector reports PR #1 touching
# `backend/connectors/foo.py`, routed by the summarizer to
# `core / connectors/foo.md` (see tests/orchestrator/fakes/*.json).
_TARGET = "docs/site-src/core/connectors/foo.md"
_GROUNDED = "backend/connectors/foo.py"


def test_the_production_call_site_renders_before_the_diagnostic(
    tmp_path, init_host, base_config_yaml, monkeypatch
):
    """THE CALL-SITE PIN. Drives the real `run()`.

    Spies wrap the real functions and record the order `run()` invokes them
    in. If the render call is deleted from `run()`, "render" never appears in
    `order` and the first assertion fails. If it is moved to AFTER the
    `_diagnose_citation_paths` loop, `order.index("render") <
    order.index("diagnose")` fails. Either mutation also leaves the page
    carrying the raw `eda/CLAUDE.md` token instead of a rendered link, which
    the final assertion catches independently of the spies.
    """
    order: list[str] = []
    real_render = orun._render_external_refs_for_pages
    real_diagnose = orun._diagnose_citation_paths

    def _render_spy(authored, config):
        order.append("render")
        return real_render(authored, config)

    def _diagnose_spy(path, repo_root, config, state, source_paths=None):
        order.append("diagnose")
        return real_diagnose(path, repo_root, config, state, source_paths=source_paths)

    monkeypatch.setattr(orun, "_render_external_refs_for_pages", _render_spy)
    monkeypatch.setattr(orun, "_diagnose_citation_paths", _diagnose_spy)

    config_yaml = base_config_yaml.replace(
        "lint: { tier1: default }",
        'lint: { tier1: default, external_repos: { eda: { url: "https://x.example/r" } } }',
    )
    assert config_yaml != base_config_yaml, "fixture guard: the replace must hit"

    page_text = "# foo connector\n\nSee `eda/CLAUDE.md` for context.\n"
    init_host(
        _SEED_STATE,
        config_yaml=config_yaml,
        seed_files={_TARGET: page_text, _GROUNDED: "def connect():\n    return 1\n"},
    )

    rc = orun.run(tmp_path, dry_run_dir=FAKES, no_pr=True)
    assert rc == 0

    assert "render" in order and "diagnose" in order, order
    assert order.index("render") < order.index("diagnose"), order

    rendered = (tmp_path / _TARGET).read_text()
    assert "[`CLAUDE.md`](https://x.example/r/blob/main/CLAUDE.md)" in rendered, (
        rendered
    )
    assert "eda/CLAUDE.md" not in rendered, rendered
