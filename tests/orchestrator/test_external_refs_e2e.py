"""CCE-181 end-to-end, on the shape production actually runs.

Tasks 1-5 proved each piece in isolation: config parsing
(test_external_refs_config.py), the pure transform
(test_external_refs_render.py), the config-load gate
(test_state_io_external_repos.py), and the wiring/ordering seam
(test_external_refs_wiring.py, which pins render-before-diagnose with spies
and the production call site with a real `run()`). None of those prove the
actual CCE-181 bug is fixed: that a page citing a real-but-elsewhere artifact
survives the whole pipeline instead of being silently discarded by the
CCE-140 deferral skip, while a page citing an undeclared prefix still gets
caught.

So every scenario here drives the real `orun.run()` against a fixture host
(`time_budget_seconds=0` -- no truncation; per CCE-179 a test that reaches
its assertion by a different code path than production is not coverage) and
then asserts on the PUBLISHED page and the run's STATE, never on internal
call order -- Task 4 already pins ordering with spies, and duplicating that
here would couple this test to the implementation rather than the behaviour.

`content-validator` is itself a dispatched subagent, and dry-run mode
replaces every subagent dispatch with a static fixture
(`fakes_external_repo/fake_content_validator.json`, always `"failed": []`) --
there is no way to make the MOCKED content-validator actually block a page
inside `orun.run()`. So "the lint does not block it" / "the lint still
blocks it" is proven the only way available under dry-run: by calling the
REAL, unmocked `citation_exists.check_path` -- the exact function the real
content-validator's `lint_runner.py` would call -- directly against the page
`run()` actually produced on disk. That is not a re-assertion of the
transform (Task 2 already unit-tests `render_external_refs` in isolation);
it is the transform's OUTPUT, produced by the real pipeline, fed to the real
linter.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts" / "lint"))

import orchestrator_runner as orun  # noqa: E402
from citation_exists import check_path, extract_citations, tracked_files  # noqa: E402
from external_refs import render_external_refs  # noqa: E402

FAKES = Path(__file__).parent / "fakes_external_repo"
PUB = "https://github.com/theoju/engineering-docs-agent"

_SEED_STATE = {"version": "1", "dismissed_gap_flags": {}, "cursors": {}}
# lens "core" -> docs/site-src/core (base_config_yaml) + page_hint "page.md"
# (fake_pr_summarizer.json, adjusted per Task 6 Step 3 to match
# fake_page_author.json's target).
_TARGET = "docs/site-src/core/page.md"


def test_a_page_citing_a_declared_external_repo_publishes(tmp_path):
    """The whole point: this page would block today and be silently
    discarded. Direct-call proof of the transform (matches Task 2's unit
    coverage) plus the missing piece: a real, unmocked lint verdict on the
    result."""
    config = {"lint": {"external_repos": {"eda": {"url": PUB}}}}
    page = tmp_path / "page.md"
    page.write_text("The gate is in `eda/scripts/orchestrator_runner.py`.")

    orun._render_external_refs_for_pages([str(page)], tmp_path, config, {})

    assert extract_citations(page.read_text())["paths"] == []
    assert PUB + "/blob/main/scripts/orchestrator_runner.py" in page.read_text()


def test_a_page_citing_a_declared_public_repo_survives_the_real_pipeline(
    tmp_path, init_host, base_config_yaml
):
    """Item 1: driven through source-collector -> pr-summarizer -> page-author
    -> render -> diagnose -> (mocked) content-validator, a page citing a
    DECLARED PUBLIC repo ends up carrying a link, and the REAL linter -- not
    the mocked content-validator -- does not block it. Pre-CCE-181, the same
    raw token would have failed `citation_exists` and the page would have
    been silently abandoned; that pre-image is asserted first so the "fixed"
    claim has a "broken" baseline to be measured against."""
    config_yaml = base_config_yaml.replace(
        "lint: { tier1: default }",
        'lint: { tier1: default, external_repos: { eda: { url: "' + PUB + '" } } }',
    )
    assert config_yaml != base_config_yaml, "fixture guard: the replace must hit"

    raw_citation = "`eda/scripts/orchestrator_runner.py`"
    page_text = f"# page\n\nThe gate lives in {raw_citation}.\n"

    # Pre-image: the SAME token, unrendered, against an otherwise-empty host
    # checkout -- this is what CCE-181 fixes. `scripts/orchestrator_runner.py`
    # does not exist in this fixture host, so the raw prefixed token cannot
    # resolve and the real linter blocks it today.
    pre = tmp_path / "pre.md"
    pre.write_text(page_text)
    ok_before, msg_before = check_path(pre, tmp_path, set(), {})
    assert ok_before is False, msg_before
    assert "cites nonexistent path" in msg_before

    state_path = init_host(
        _SEED_STATE, config_yaml=config_yaml, seed_files={_TARGET: page_text}
    )
    rc = orun.run(tmp_path, dry_run_dir=FAKES, no_pr=True, time_budget_seconds=0)
    assert rc == 0

    rendered = (tmp_path / _TARGET).read_text()
    assert raw_citation not in rendered, rendered
    assert (
        f"[`orchestrator_runner.py`]({PUB}/blob/main/scripts/orchestrator_runner.py)"
        in rendered
    ), rendered

    # The published outcome, checked against the REAL, unmocked linter.
    files = tracked_files(tmp_path)
    ok_after, msg_after = check_path(tmp_path / _TARGET, tmp_path, files, {})
    assert ok_after is True, msg_after

    # The run's state: no citation-render failure, no lint-block reason for
    # this page.
    cr = json.loads((state_path.parent / "current_run.json").read_text())["current_run"]
    reasons = cr.get("partial_reasons", [])
    assert not any("external_ref_render_failed" in r for r in reasons), reasons
    assert not any("lint_block" in r and "page.md" in r for r in reasons), reasons


def test_a_page_citing_a_declared_private_repo_survives_the_real_pipeline(
    tmp_path, init_host, base_config_yaml
):
    """Item 2: a page citing a DECLARED PRIVATE repo ends up carrying a bare,
    slash-free artifact name -- no link, since a private repo's URL must
    never reach a published page -- and is likewise not blocked by the real
    linter."""
    config_yaml = base_config_yaml.replace(
        "lint: { tier1: default }",
        "lint: { tier1: default, external_repos: { priv: { private: true } } }",
    )
    assert config_yaml != base_config_yaml, "fixture guard: the replace must hit"

    raw_citation = "`priv/scripts/internal_tool.py`"
    page_text = f"# page\n\nThe gate lives in {raw_citation}.\n"

    init_host(_SEED_STATE, config_yaml=config_yaml, seed_files={_TARGET: page_text})
    rc = orun.run(tmp_path, dry_run_dir=FAKES, no_pr=True, time_budget_seconds=0)
    assert rc == 0

    rendered = (tmp_path / _TARGET).read_text()
    assert raw_citation not in rendered, rendered
    assert "`internal_tool.py`" in rendered, rendered
    assert "](" not in rendered, "a private repo must never publish a URL"
    assert "priv" not in rendered, rendered

    files = tracked_files(tmp_path)
    ok_after, msg_after = check_path(tmp_path / _TARGET, tmp_path, files, {})
    assert ok_after is True, msg_after


def test_a_page_citing_an_undeclared_prefix_still_blocks(
    tmp_path, init_host, base_config_yaml
):
    """Item 3 -- the guardrail. A prefix that is NOT declared must not become
    a way to smuggle any unverifiable path past the linter: the render step
    leaves it untouched, and the real linter blocks it for exactly the same
    reason it always has. Declares `eda` (a DIFFERENT, real prefix) to prove
    this is per-token opt-in, not "any external_repos config disables
    checking"."""
    config_yaml = base_config_yaml.replace(
        "lint: { tier1: default }",
        'lint: { tier1: default, external_repos: { eda: { url: "' + PUB + '" } } }',
    )
    assert config_yaml != base_config_yaml, "fixture guard: the replace must hit"

    raw_citation = "`other/module.py`"
    page_text = f"# page\n\nThe gate lives in {raw_citation}.\n"

    init_host(_SEED_STATE, config_yaml=config_yaml, seed_files={_TARGET: page_text})
    rc = orun.run(tmp_path, dry_run_dir=FAKES, no_pr=True, time_budget_seconds=0)
    assert rc == 0

    rendered = (tmp_path / _TARGET).read_text()
    assert rendered == page_text, (
        "an undeclared prefix must be left byte-for-byte alone"
    )

    files = tracked_files(tmp_path)
    ok_after, msg_after = check_path(tmp_path / _TARGET, tmp_path, files, {})
    assert ok_after is False, msg_after
    assert "cites nonexistent path 'other/module.py'" in msg_after


def test_a_bare_host_run_is_byte_identical(tmp_path, init_host, base_config_yaml):
    """No `external_repos` declared at all (not even an empty block) -> the
    renderer must be a no-op across a WHOLE run, for a page that carries a
    token shaped exactly like the ones the other three scenarios rewrite.
    `render_external_refs(text, {})` is trivially an identity function by
    construction (`if not repos: return text`), so asserting that alone,
    on its own, would pass even if `orun.run()` never called the renderer at
    all -- that would not discriminate the wiring. The mtime pin below does:
    `_render_external_refs_for_pages` only writes when content actually
    changes, so an untouched page's mtime must survive the run unmoved. If a
    regression made it write unconditionally (or if the guard were removed
    and something upstream started rewriting undeclared tokens), the mtime
    would move even though the bytes end up the same.
    """
    raw_citation = "`eda/scripts/orchestrator_runner.py`"
    page_text = f"# page\n\nThe gate lives in {raw_citation}.\n"

    init_host(
        _SEED_STATE, config_yaml=base_config_yaml, seed_files={_TARGET: page_text}
    )
    before = (tmp_path / _TARGET).stat().st_mtime_ns

    rc = orun.run(tmp_path, dry_run_dir=FAKES, no_pr=True, time_budget_seconds=0)
    assert rc == 0

    pages = list((tmp_path / "docs").rglob("*.md"))
    assert pages, "the fixture run must author at least one page"

    rendered = (tmp_path / _TARGET).read_text()
    assert rendered == page_text, "a bare host must not touch the citation at all"
    after = (tmp_path / _TARGET).stat().st_mtime_ns
    assert after == before, "a bare host must not rewrite an unchanged page"

    for p in pages:
        assert render_external_refs(p.read_text(), {}) == p.read_text()
