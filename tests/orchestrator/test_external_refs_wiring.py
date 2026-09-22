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
    orun._render_external_refs_for_pages([str(page)], tmp_path, config, {})
    orun._diagnose_citation_paths(str(page), tmp_path, config, {}, source_paths=set())

    assert seen == ["See [`CLAUDE.md`](https://x.example/r/blob/main/CLAUDE.md)."]


def test_a_bare_host_leaves_the_file_byte_identical(tmp_path):
    page = tmp_path / "page.md"
    original = "See `eda/CLAUDE.md` and `scripts/x.py`."
    page.write_text(original)
    before = page.stat().st_mtime_ns
    orun._render_external_refs_for_pages([str(page)], tmp_path, {"lint": {}}, {})
    assert page.read_text() == original
    assert page.stat().st_mtime_ns == before, "an unchanged page must not be rewritten"


def test_a_missing_page_is_skipped_not_raised(tmp_path):
    """Round-1 review fix. The old version passed `{"lint": {}}`, under which
    `resolve_config` returns `{}` and the function returns at
    `if not repos: return` BEFORE the loop even starts -- the
    `if not p.exists(): continue` line this test is named for was never
    reached, and the test would have passed identically with that guard
    deleted.

    `external_repos` must be DECLARED so the loop actually runs, and the
    listed page must actually be missing from disk (an authored path can
    legitimately point at nothing -- e.g. a page-author create the dry-run
    synth never wrote -- and that is routine, not a failure).

    Asserting `state == {}` is the real point: a missing page must be a
    silent skip, not a reason. Removing the `continue` guard no longer makes
    this raise (round-1's new exception guard around the read/render/write
    catches the resulting FileNotFoundError) -- it instead makes this
    assertion fail, because `external_ref_render_failed: ...` gets appended
    to `state["current_run"]["partial_reasons"]`. Verified: with `continue`
    removed, this test fails with
    `AssertionError: {'current_run': {'partial': True, 'partial_reasons':
    ['external_ref_render_failed: gone.md: FileNotFoundError: ...']}}`.
    """
    config = {"lint": {"external_repos": {"eda": {"url": "https://x.example/r"}}}}
    missing = tmp_path / "gone.md"
    state: dict = {}
    orun._render_external_refs_for_pages([str(missing)], tmp_path, config, state)
    assert state == {}, state


def test_a_render_failure_on_one_page_does_not_stop_the_next(tmp_path, monkeypatch):
    """Round-1 review Fix 1: the new per-page exception guard.

    Two pages; the first raises during render, the second must still be
    processed -- one bad page must not sink the batch. The failure must be
    reported as a BLOCKING reason (flips `partial`) with `degraded=True`,
    never `info_only=True`. NOT because an unrendered `prefix/path` token is
    invisible to `citation_exists` -- the separator is `/`
    (`token.partition("/")` in external_refs.py), so on a live lens the token
    keeps its slash and `citation_exists` still blocks it; a swallowed
    failure there just degrades to the pre-CCE-181 bug, loud and
    self-healing. The real reason: under an `archive-index` section CCE-124
    downgrades `citation_exists` to `warn`, so there the raw token would ship
    as prose with no block at all -- and that residual is what `degraded=True`
    makes visible. `degraded=True` (not the bare/blind default) marks this as
    work the run held back -- the same shape as `page_author_invalid` --
    rather than the blind "consumed input it could not process" shape;
    asserting `"blind" not in cr or cr["blind"] is False` pins that choice.
    """
    bad = tmp_path / "bad.md"
    good = tmp_path / "good.md"
    bad.write_text("BOOM See `eda/CLAUDE.md` here.")
    good.write_text("See `eda/CLAUDE.md` here too.")

    real_render = orun.render_external_refs

    def _boom(text, repos):
        if "BOOM" in text:
            raise RuntimeError("simulated render failure")
        return real_render(text, repos)

    monkeypatch.setattr(orun, "render_external_refs", _boom)

    config = {"lint": {"external_repos": {"eda": {"url": "https://x.example/r"}}}}
    state: dict = {}
    # bad.md is listed FIRST: proves a failure does not stop the pages after it.
    orun._render_external_refs_for_pages([str(bad), str(good)], tmp_path, config, state)

    assert (
        good.read_text()
        == "See [`CLAUDE.md`](https://x.example/r/blob/main/CLAUDE.md) here too."
    )
    assert bad.read_text() == "BOOM See `eda/CLAUDE.md` here.", (
        "the failed page must be untouched -- but this only proves it for the "
        "PRE-WRITE failure path: _boom raises inside render_external_refs, "
        "before write_text/os.replace is ever reached, so bad.md is untouched "
        "by construction here, not because of the atomic-write swap. The "
        "write-TIME path (a failure after the write has actually been "
        "invoked) is covered separately by "
        "test_a_write_time_failure_leaves_the_page_untouched, below."
    )

    cr = state["current_run"]
    assert cr["partial"] is True, cr
    assert "blind" not in cr or cr["blind"] is False, cr
    assert any(
        r.startswith("external_ref_render_failed: bad.md: RuntimeError:")
        for r in cr["partial_reasons"]
    ), cr["partial_reasons"]


def test_a_write_time_failure_leaves_the_page_untouched(tmp_path, monkeypatch):
    """Round-2 review: the atomic write.

    `Path.write_text` opens in `'w'` mode, which truncates before writing, so
    a failure AFTER the write has been invoked (disk full, permission revoked
    mid-write) could leave the real page as neither the old content nor the
    new -- and `git add -A .` stages whatever is left. The fix writes to a
    `.tmp` sibling and `os.replace`s it onto the real page, which is atomic
    on POSIX: the page is always fully old or fully new.

    `Path.write_text` is monkeypatched to perform the REAL write (so the call
    genuinely happens, exercising "invoked then fails", not "never reached")
    and then raise -- simulating e.g. a disk-full error surfacing right after
    the bytes are flushed. Because the implementation writes to `page.md.tmp`
    and only `os.replace`s it onto `page.md` on success, the real page is
    never touched by this failure at all.

    Verified against the round-1 (pre-atomic) code first: with a bare
    `p.write_text(after)`, this same monkeypatch writes the NEW content
    straight into the real page and then raises, so the page ends up fully
    rewritten (not reverted) despite the reported failure -- see the fix
    report for the exact transcript. That is the corruption class this test
    exists to close: the round-1 code "failed loudly" but still left bad
    content on disk for `git add -A .` to stage.
    """
    page = tmp_path / "page.md"
    original = "See `eda/CLAUDE.md` here."
    page.write_text(original)

    real_write_text = Path.write_text

    def _write_then_boom(self, *args, **kwargs):
        real_write_text(self, *args, **kwargs)
        raise OSError("simulated disk-full mid-write")

    monkeypatch.setattr(Path, "write_text", _write_then_boom)

    config = {"lint": {"external_repos": {"eda": {"url": "https://x.example/r"}}}}
    state: dict = {}
    orun._render_external_refs_for_pages([str(page)], tmp_path, config, state)

    assert page.read_text() == original, (
        "the real page must never be touched by a write-time failure"
    )
    assert not (tmp_path / "page.md.tmp").exists(), (
        "the leftover temp file must be cleaned up"
    )

    cr = state["current_run"]
    assert cr["partial"] is True, cr
    assert "blind" not in cr or cr["blind"] is False, cr
    assert any(
        r.startswith("external_ref_render_failed: page.md: OSError:")
        for r in cr["partial_reasons"]
    ), cr["partial_reasons"]


# --- the production call site ------------------------------------------------
#
# Everything above drives `_render_external_refs_for_pages` and
# `_diagnose_citation_paths` directly, in whatever order the test wrote them
# in -- it proves the two functions COMPOSE correctly but says nothing about
# whether `run()` actually calls them in that order. Verified empirically:
# commenting out the `_render_external_refs_for_pages(authored, repo_root,
# config, state)` call site in `run()` left all three tests above green. The
# test below is what fails when the call site is removed or moved after the
# diagnostic.

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
    order.index("diagnose")` fails.

    The final content assertion is an INDEPENDENT check, but only for the
    deletion case: a deleted call leaves the page carrying the raw
    `eda/CLAUDE.md` token instead of a rendered link. The reorder-to-after-
    the-loop mutation still renders the page correctly, just too late, so
    that content assertion alone would pass under it -- only the
    `order.index()` assertions above catch the reorder.
    """
    order: list[str] = []
    real_render = orun._render_external_refs_for_pages
    real_diagnose = orun._diagnose_citation_paths

    def _render_spy(authored, repo_root, config, state):
        order.append("render")
        return real_render(authored, repo_root, config, state)

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


def test_the_payload_carries_declared_prefixes_only():
    """An agent that cannot see the declaration cannot use it. Prefixes only --
    the agent must never construct the URL itself, so it is not given one."""
    config = {
        "lint": {
            "external_repos": {
                "eda": {"url": "https://x.example/r"},
                "ship": {"private": True},
            }
        }
    }
    assert orun._external_repo_prefixes(config) == ["eda", "ship"]


def test_a_bare_host_offers_no_prefixes():
    assert orun._external_repo_prefixes({"lint": {}}) == []


def test_the_contract_documents_the_third_escape():
    """The grounding rule offered only `example/` (fictional) and fenced blocks
    (dead names). Real-but-elsewhere was the missing third case."""
    text = (
        Path(__file__).resolve().parents[2] / "agents" / "page-author.md"
    ).read_text()
    assert "declared as external" in text
    assert "Never construct the URL yourself" in text
    assert "exists in the HOST repo" in text


def test_external_repos_is_declared_in_the_inputs_list():
    """## Inputs is a complete enumeration of the payload keys (CLAUDE.md:
    each agent's .md file is the canonical input shape) -- an eighth payload
    key absent from it makes the list wrong, not merely terse. Scoped to the
    Inputs section specifically: `external_repos` is already mentioned in
    Procedure step 3's prose, so a bare substring check on the whole file
    would pass even if the Inputs bullet were deleted."""
    text = (
        Path(__file__).resolve().parents[2] / "agents" / "page-author.md"
    ).read_text()
    inputs_section = text.split("## Inputs", 1)[1].split("\n## ", 1)[0]
    assert "- `external_repos`" in inputs_section, inputs_section
