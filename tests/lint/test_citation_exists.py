from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

import pytest
import yaml

from scripts.lint import citation_exists

SCRIPT = Path(citation_exists.__file__)


def _tmp_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "host"
    (repo / "tests").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def _commit_all(repo: Path) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@e.st",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "seed",
        ],
        check=True,
    )


# ---------- extraction (pure) ----------


def test_extracts_repo_path_and_test_id():
    text = "See `scripts/foo.py` and `test_bar_baz` for details."
    cites = citation_exists.extract_citations(text)
    assert cites["paths"] == ["scripts/foo.py"]
    assert cites["tests"] == ["test_bar_baz"]


def test_line_suffix_stripped():
    assert citation_exists.extract_citations("`scripts/foo.py:123`")["paths"] == [
        "scripts/foo.py"
    ]
    assert citation_exists.extract_citations("`scripts/foo.py:10-20`")["paths"] == [
        "scripts/foo.py"
    ]


def test_duplicates_collapse():
    text = "`scripts/foo.py` twice `scripts/foo.py`, `test_x` twice `test_x`"
    cites = citation_exists.extract_citations(text)
    assert cites["paths"] == ["scripts/foo.py"]
    assert cites["tests"] == ["test_x"]


def test_placeholders_urls_and_env_refs_skipped():
    text = (
        "`docs/specs/YYYY-MM-DD-x.md` `<path>` `glob/*.md` `{owner}/file.py` "
        "`https://x.test/a.py` `~/conf/a.yml` `$HOME/a.sh` `dir/.../file.py`"
    )
    assert citation_exists.extract_citations(text) == {"paths": [], "tests": []}


def test_fenced_blocks_ignored():
    text = (
        "intro prose\n"
        "```python\n"
        'x = load("`scripts/fake_in_fence.py`")\n'
        "```\n"
        "outro cites `test_real_one`\n"
    )
    cites = citation_exists.extract_citations(text)
    assert cites["paths"] == []
    assert cites["tests"] == ["test_real_one"]


def test_vocabulary_tokens_skipped():
    # No slash and not a test identifier -> not a citation.
    text = "`partial_reasons` `run.time_budget_seconds` `frontmatter_contract.py`"
    assert citation_exists.extract_citations(text) == {"paths": [], "tests": []}


def test_unterminated_fence_still_checks_trailing_prose():
    """CCE-131: an unclosed fence used to swallow the rest of the file,
    silently disabling this block rule from that point on."""
    text = (
        "Intro citing `scripts/real.py`.\n"
        "\n"
        "```python\n"
        "never_closed = True\n"
        "\n"
        "Trailing prose citing `scripts/after_fence.py`.\n"
    )
    paths = citation_exists.extract_citations(text)["paths"]
    assert "scripts/after_fence.py" in paths


def test_terminated_fence_content_is_still_stripped():
    """The fix must not stop stripping properly closed fences."""
    text = (
        "Before `scripts/before.py`.\n"
        "```python\n"
        "x = `scripts/inside_fence.py`\n"
        "```\n"
        "After `scripts/after.py`.\n"
    )
    paths = citation_exists.extract_citations(text)["paths"]
    assert paths == ["scripts/before.py", "scripts/after.py"]


# ---------- verification + CLI (tmp git host) ----------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )


def _init_host(tmp_path: Path) -> tuple[Path, Path]:
    """Arbitrary-host fixture: git repo with one module, one test, a config."""
    repo = tmp_path / "host"
    (repo / "scripts").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "scripts" / "real_module.py").write_text("def real_fn():\n    return 1\n")
    (repo / "tests" / "test_real.py").write_text(
        "def test_real_behavior():\n    assert True\n"
    )
    (repo / ".engineering-docs-agent").mkdir()
    cfg = repo / ".engineering-docs-agent" / "config.yml"
    cfg.write_text("lint: { tier1: default }\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo, cfg


def _run_cli(paths: list[Path], cfg: Path) -> tuple[int, dict]:
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(cfg),
            "--paths",
            *[str(p) for p in paths],
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    return r.returncode, json.loads(r.stdout)


def test_existing_citations_pass(tmp_path):
    repo, cfg = _init_host(tmp_path)
    page = repo / "page.md"
    page.write_text("Cites `scripts/real_module.py` and `test_real_behavior`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 0
    assert out["rule"] == "citation_exists"
    assert out["severity"] == "block"
    assert out["results"][0]["ok"] is True


def test_nonexistent_test_blocks(tmp_path):
    repo, cfg = _init_host(tmp_path)
    page = repo / "page.md"
    page.write_text("Verified by `test_never_written`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 1
    assert "cites nonexistent test 'test_never_written'" in out["results"][0]["message"]


def test_nonexistent_path_blocks(tmp_path):
    repo, cfg = _init_host(tmp_path)
    page = repo / "page.md"
    page.write_text("See `scripts/ghost.py` for the sentinel logic.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 1
    assert "cites nonexistent path 'scripts/ghost.py'" in out["results"][0]["message"]


def test_untracked_but_present_path_passes(tmp_path):
    # A page authored in the same run may cite a file that exists on disk but
    # is not yet tracked (e.g. a generated sibling). Existence on disk wins.
    repo, cfg = _init_host(tmp_path)
    (repo / "scripts" / "fresh.py").write_text("x = 1\n")  # not committed
    page = repo / "page.md"
    page.write_text("Cites `scripts/fresh.py`.\n")
    rc, _ = _run_cli([page], cfg)
    assert rc == 0


def test_no_git_passes_trivially(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text("lint: { tier1: default }\n")
    page = tmp_path / "page.md"
    page.write_text("Cites `scripts/ghost.py` and `test_never_written`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 0
    assert "skipped" in out["results"][0]["message"]


def test_missing_page_file_blocks(tmp_path):
    repo, cfg = _init_host(tmp_path)
    rc, out = _run_cli([repo / "absent.md"], cfg)
    assert rc == 1
    assert out["results"][0]["message"] == "file not found"


def test_undecodable_page_blocks_with_clear_message(tmp_path):
    # A page that is not valid UTF-8 must block with a message, not crash the
    # rule (a crash surfaces as lint_runner's opaque "empty output" block).
    repo, cfg = _init_host(tmp_path)
    page = repo / "page.md"
    page.write_bytes(b"\xff\xfe invalid \xff")
    rc, out = _run_cli([page], cfg)
    assert rc == 1
    assert "not decodable" in out["results"][0]["message"]


# ---------- regression: the two confabulated pages (condensed) ----------

CONFABULATED_STATE_ADVANCEMENT = """\
# Orchestrator state advancement

Invariant 1 — no advance on partial. The runner records the decision in a
sentinel file `.engineering-docs-agent/last_run_invariant.json`.

Verified by `test_state_not_advanced_on_partial`,
`test_state_advanced_on_clean`, and `test_state_no_sha_regression`.
"""

CONFABULATED_GIT_STAGING = """\
# Orchestrator git staging

The runner does not use git add -A; PR #97 replaced it with the pathspec
form. Verified by `test_stage_uses_pathspec_not_add_all`.
"""


def test_regression_confabulated_state_advancement_blocks(tmp_path):
    repo, cfg = _init_host(tmp_path)
    page = repo / "state-advancement.md"
    page.write_text(CONFABULATED_STATE_ADVANCEMENT)
    rc, out = _run_cli([page], cfg)
    assert rc == 1
    msg = out["results"][0]["message"]
    assert "test_state_not_advanced_on_partial" in msg
    assert "test_state_advanced_on_clean" in msg
    assert "test_state_no_sha_regression" in msg
    assert "last_run_invariant.json" in msg


def test_regression_confabulated_git_staging_blocks(tmp_path):
    repo, cfg = _init_host(tmp_path)
    page = repo / "git-staging.md"
    page.write_text(CONFABULATED_GIT_STAGING)
    rc, out = _run_cli([page], cfg)
    assert rc == 1
    assert "test_stage_uses_pathspec_not_add_all" in out["results"][0]["message"]


# ---------- orchestrator-facing helper ----------


def test_resolve_cited_sources_returns_existing_relative_paths(tmp_path):
    repo, _ = _init_host(tmp_path)
    text = "Cites `scripts/real_module.py:3` and `scripts/ghost.py`."
    assert citation_exists.resolve_cited_sources(text, repo) == [
        "scripts/real_module.py"
    ]


def test_symbol_suffix_stripped_to_bare_path():
    # A path:symbol citation resolves to the bare path in ["paths"] (grounding
    # must still receive a clean file path — the shared-helper contract).
    assert citation_exists.extract_citations("`scripts/foo.py:run`")["paths"] == [
        "scripts/foo.py"
    ]
    assert citation_exists.extract_citations("`scripts/foo.py:Cls.method`")[
        "paths"
    ] == ["scripts/foo.py"]


def test_extract_symbol_citations_returns_path_and_leaf():
    text = "See `scripts/foo.py:run` and `pkg/bar.py:Cls.method` and `scripts/baz.py`."
    assert citation_exists.extract_symbol_citations(text) == [
        ("scripts/foo.py", "run"),
        ("pkg/bar.py", "method"),  # leaf = last dotted component
    ]


def test_line_pinned_citations_flags_digit_suffix_including_bare_filename():
    text = (
        "prose `scripts/foo.py:12` and `orchestrator_runner.py:128` and "
        "`scripts/foo.py:10-20` but not `scripts/foo.py:run` or `scripts/foo.py`"
    )
    assert citation_exists.line_pinned_citations(text) == [
        "scripts/foo.py:12",
        "orchestrator_runner.py:128",
        "scripts/foo.py:10-20",
    ]


def test_line_pinned_citations_ignores_fenced_blocks():
    text = "intro\n```\n`scripts/foo.py:12`\n```\nafter `scripts/bar.py:7`\n"
    assert citation_exists.line_pinned_citations(text) == ["scripts/bar.py:7"]


def test_symbol_citation_present_passes(tmp_path):
    repo, cfg = _init_host(tmp_path)
    page = repo / "page.md"
    page.write_text("The entry point is `scripts/real_module.py:real_fn`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 0, out
    assert out["results"][0]["ok"] is True


def test_confabulated_symbol_blocks(tmp_path):
    repo, cfg = _init_host(tmp_path)
    page = repo / "page.md"
    page.write_text("See `scripts/real_module.py:ghost_fn` for the logic.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 1
    assert (
        "cites nonexistent symbol 'ghost_fn' in 'scripts/real_module.py'"
        in (out["results"][0]["message"])
    )


def test_method_symbol_resolves_via_leaf(tmp_path):
    repo, cfg = _init_host(tmp_path)
    (repo / "scripts" / "svc.py").write_text(
        "class Service:\n    def handle(self):\n        return 1\n"
    )
    page = repo / "page.md"
    page.write_text("`scripts/svc.py:Service.handle` does the work.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 0, out


def test_module_constant_symbol_resolves(tmp_path):
    repo, cfg = _init_host(tmp_path)
    (repo / "scripts" / "cfg.py").write_text("DEFAULT_BUDGET = 2700\n")
    page = repo / "page.md"
    page.write_text("The default is `scripts/cfg.py:DEFAULT_BUDGET`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 0, out


def test_symbol_on_missing_file_reports_path_not_symbol(tmp_path):
    # A :symbol cite to a nonexistent file reports the path problem (from the
    # paths loop); the symbol loop must not crash or double-report.
    repo, cfg = _init_host(tmp_path)
    page = repo / "page.md"
    page.write_text("See `scripts/ghost.py:whatever`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 1
    msg = out["results"][0]["message"]
    assert "cites nonexistent path 'scripts/ghost.py'" in msg
    assert "nonexistent symbol" not in msg


def test_resolve_cited_sources_handles_symbol_suffix(tmp_path):
    repo, _ = _init_host(tmp_path)
    text = "Cites `scripts/real_module.py:real_fn` and `scripts/ghost.py:x`."
    assert citation_exists.resolve_cited_sources(text, repo) == [
        "scripts/real_module.py"
    ]


# ---------- archive-lens advisory severity (CCE-124) ----------

_SITE_CFG = (
    "lint: { tier1: default }\n"
    "site:\n"
    "  docs_dir: docs/site-src\n"
    "  sections:\n"
    "    - key: architecture\n"
    "      path: architecture/\n"
    "      generator: agent-authored\n"
    "    - key: archive\n"
    "      path: archive/\n"
    "      generator: archive-index\n"
)


def _init_host_with_site(
    tmp_path: Path, cfg_text: str = _SITE_CFG
) -> tuple[Path, Path]:
    repo, cfg = _init_host(tmp_path)
    cfg.write_text(cfg_text)
    (repo / "docs" / "site-src" / "archive").mkdir(parents=True)
    (repo / "docs" / "site-src" / "architecture").mkdir(parents=True)
    return repo, cfg


def test_archive_page_bad_citation_is_warn_not_block(tmp_path):
    repo, cfg = _init_host_with_site(tmp_path)
    page = repo / "docs" / "site-src" / "archive" / "2026-07-22-x.md"
    page.write_text("Historical note cites `scripts/removed_module.py`.\n")
    rc, out = _run_cli([page], cfg)
    res = out["results"][0]
    assert res["ok"] is False
    assert res["severity"] == "warn"
    assert rc == 0  # warn-only: no block-failure, exit clean


def test_live_page_same_bad_citation_still_blocks(tmp_path):
    repo, cfg = _init_host_with_site(tmp_path)
    page = repo / "docs" / "site-src" / "architecture" / "index.md"
    page.write_text("Cites `scripts/removed_module.py`.\n")
    rc, out = _run_cli([page], cfg)
    res = out["results"][0]
    assert res["ok"] is False
    assert res["severity"] == "block"
    assert rc == 1


def test_no_archive_section_defaults_to_block(tmp_path):
    # Generic-first: a host with no archive-index section behaves exactly as today.
    repo, cfg = _init_host_with_site(tmp_path, cfg_text="lint: { tier1: default }\n")
    page = repo / "docs" / "site-src" / "archive" / "2026-07-22-x.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("Cites `scripts/removed_module.py`.\n")
    rc, out = _run_cli([page], cfg)
    res = out["results"][0]
    assert res["ok"] is False
    assert res["severity"] == "block"
    assert rc == 1


def test_clean_archive_page_passes_with_advisory_tag(tmp_path):
    repo, cfg = _init_host_with_site(tmp_path)
    page = repo / "docs" / "site-src" / "archive" / "2026-07-22-ok.md"
    page.write_text("Cites `scripts/real_module.py` and `test_real_behavior`.\n")
    rc, out = _run_cli([page], cfg)
    res = out["results"][0]
    assert res["ok"] is True
    assert res["severity"] == "warn"  # advisory tag present even when passing
    assert rc == 0


def test_archive_dirs_resolves_only_archive_index_sections(tmp_path):
    import yaml as _yaml

    repo, cfg = _init_host_with_site(tmp_path)
    config = _yaml.safe_load(cfg.read_text())
    dirs = citation_exists.archive_dirs(config, repo)
    assert dirs == [(repo / "docs" / "site-src" / "archive").resolve()]


# ---------- test-family prefix matching (CCE-131) ----------


def test_test_family_shorthand_resolves_via_prefix(tmp_path):
    """CCE-131: `test_lint_runner` names a family; the real symbols are
    test_lint_runner_missing_script_reports_block etc."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "tests" / "test_x.py").write_text(
        "def test_lint_runner_missing_script_reports_block():\n    pass\n"
    )
    _commit_all(repo)
    assert citation_exists.cited_test_exists(repo, "test_lint_runner") is True


def test_confabulated_test_with_no_family_still_blocks(tmp_path):
    """The guard CCE-111 needed: a wholly invented name matches no prefix."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "tests" / "test_x.py").write_text(
        "def test_lint_runner_missing_script_reports_block():\n    pass\n"
    )
    _commit_all(repo)
    assert (
        citation_exists.cited_test_exists(repo, "test_no_advance_on_partial") is False
    )


def test_prefix_match_respects_the_underscore_boundary(tmp_path):
    """`test_lintrunner` must NOT match `test_lint_runner_x` — the boundary is
    what keeps the prefix match from degenerating into substring matching."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "tests" / "test_x.py").write_text("def test_lint_runner_x():\n    pass\n")
    _commit_all(repo)
    assert citation_exists.cited_test_exists(repo, "test_lintrunner") is False


# ---------- docs-relative and build-output path resolution (CCE-131) ----------

_SITE_CFG = {"site": {"docs_dir": "docs/site-src"}}


def test_docs_relative_sibling_citation_resolves(tmp_path):
    """CCE-131: a docs page citing a sibling page names it relative to
    docs_dir, not to the repo root."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "docs" / "site-src" / "api").mkdir(parents=True)
    (repo / "docs" / "site-src" / "api" / "index.md").write_text("# API\n")
    page = repo / "docs" / "site-src" / "guide.md"
    page.write_text("See `api/index.md` for the reference.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, _SITE_CFG)
    assert ok is True, msg


def test_build_output_path_is_skipped(tmp_path):
    """mkdocs site_dir output is generated, never tracked — not a confabulation."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "mkdocs.yml").write_text("docs_dir: docs/site-src\nsite_dir: site\n")
    page = repo / "page.md"
    page.write_text("Published to `site/api/http/index.html`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, _SITE_CFG)
    assert ok is True, msg


# ---------- discriminating build-dir tests (CCE-131 final-review Finding 2) --
#
# test_build_output_path_is_skipped above uses site_dir: site — the same
# value as the old hardcoded "site" fallback — so it passes against
# `def _build_dir(...): return "site"` too. It cannot tell the real
# implementation apart from a constant. These tests can.


def test_build_output_honors_reconfigured_site_dir(tmp_path):
    """site_dir: public must route public/, not the old hardcoded site/."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "mkdocs.yml").write_text("docs_dir: docs/site-src\nsite_dir: public\n")
    page = repo / "page.md"
    page.write_text("Published to `public/api/http/index.html`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, _SITE_CFG)
    assert ok is True, msg


def test_old_default_prefix_blocks_once_site_dir_is_reconfigured(tmp_path):
    """The flip side of the above: once site_dir is public, site/ is an
    ordinary (nonexistent) path again, not a permanently exempt prefix."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "mkdocs.yml").write_text("docs_dir: docs/site-src\nsite_dir: public\n")
    page = repo / "page.md"
    page.write_text("See `site/api/http/index.html`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, _SITE_CFG)
    assert ok is False
    assert "site/api/http/index.html" in msg


def test_no_mkdocs_yml_at_all_blocks_invented_site_path(tmp_path):
    """No parseable mkdocs config at all: skip nothing."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text("See `site/invented.js`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, _SITE_CFG)
    assert ok is False
    assert "site/invented.js" in msg


def test_material_style_python_name_tag_parses_and_site_dir_is_honored(tmp_path):
    """Regression for the dead-code half: plain yaml.safe_load raises on
    mkdocs-material's `!!python/name:` tag (used by pymdownx.superfences for
    custom fences), so a naive parse-or-fallback implementation never
    actually runs the parse branch on a Material config. The lax loader must
    degrade the unknown tag to None instead of aborting the whole parse."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "mkdocs.yml").write_text(
        "docs_dir: docs/site-src\n"
        "site_dir: public\n"
        "markdown_extensions:\n"
        "  - pymdownx.superfences:\n"
        "      custom_fences:\n"
        "        - name: mermaid\n"
        "          class: mermaid\n"
        "          format: !!python/name:pymdownx.superfences.fence_code_format\n"
    )
    page = repo / "page.md"
    page.write_text("Published to `public/api/http/index.html`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, _SITE_CFG)
    assert ok is True, msg


# ---------- _build_dir must not fail open (CCE-131 final-review Finding 1) --


def test_build_dir_is_empty_with_no_mkdocs_config(tmp_path):
    """No mkdocs.yml -> skip NOTHING. The previous unconditional "site"
    fallback made site/ a permanently reserved prefix on every host, even one
    that keeps real source there."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "README.md").write_text("host\n")
    _commit_all(repo)
    assert citation_exists._build_dir(repo) == ""


def test_no_mkdocs_config_does_not_reserve_site_prefix(tmp_path):
    """A host with no mkdocs.yml that happens to keep real source under
    site/ must not get site/ treated as an always-exempt build-output
    prefix: an invented sibling path must still block."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "site" / "src").mkdir(parents=True)
    (repo / "site" / "src" / "real.js").write_text("// real\n")
    page = repo / "page.md"
    page.write_text("See `site/src/totally_invented.js` for the sentinel.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is False
    assert "site/src/totally_invented.js" in msg


def test_this_repos_own_mkdocs_yml_parses_via_lax_loader():
    """CCE-131 final-review Finding 1(b): plain yaml.safe_load cannot read
    this repo's own mkdocs.yml — Material's `!!python/name:` tag raises
    ConstructorError — so the mkdocs-parsing branch was dead code here; the
    old code returned 'site' only because it coincides with the hardcoded
    fallback. _build_dir must now return 'site' by actually parsing."""
    repo_root = Path(__file__).resolve().parents[2]
    mkdocs_yml = repo_root / "mkdocs.yml"
    assert mkdocs_yml.exists()  # sanity: this is really the repo root
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(mkdocs_yml.read_text())
    assert citation_exists._build_dir(repo_root) == "site"


def test_no_docs_dir_configured_still_blocks(tmp_path):
    """Generic-first guard: a host with no site.docs_dir keeps today's
    repo-root-only behavior."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "docs" / "site-src" / "api").mkdir(parents=True)
    (repo / "docs" / "site-src" / "api" / "index.md").write_text("# API\n")
    page = repo / "page.md"
    page.write_text("See `api/index.md`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is False
    assert "api/index.md" in msg


def test_genuine_confabulation_still_blocks_with_docs_dir(tmp_path):
    """The docs_dir fallback must not become a blanket pass."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "docs" / "site-src").mkdir(parents=True)
    page = repo / "docs" / "site-src" / "page.md"
    page.write_text("See `scripts/build_doc_source_map.py`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, _SITE_CFG)
    assert ok is False
    assert "scripts/build_doc_source_map.py" in msg


def test_example_namespace_path_passes(tmp_path):
    """CCE-131: `example/` is a reserved illustrative namespace (RFC 2606
    precedent) and never resolves by design."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text("A page with `example/auth/session.py` in its file list.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is True, msg


def test_non_example_fictional_path_still_blocks(tmp_path):
    """The namespace is the affordance; inventing another root is still a defect."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text("A page with `scripts/auth/session.py` in its file list.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is False
    assert "scripts/auth/session.py" in msg


def test_host_configured_prefix_replaces_the_default(tmp_path):
    """A host with a real top-level example/ dir picks a different word."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text("Both `acme/auth/session.py` and `example/auth/session.py`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    cfg = {"lint": {"citation_example_prefixes": ["acme"]}}
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is False
    assert "example/auth/session.py" in msg
    assert "acme/auth/session.py" not in msg


def test_exempt_token_passes(tmp_path):
    """CCE-131: a file whose non-existence IS the claim."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text(
        "tests/scripts must not be a package: no `tests/scripts/__init__.py`.\n"
    )
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    cfg = {"lint": {"citation_exempt_tokens": ["tests/scripts/__init__.py"]}}
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is True, msg


def test_unlisted_sibling_still_blocks(tmp_path):
    """The list exempts exact tokens, not a directory."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text("See `tests/scripts/conftest.py`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    cfg = {"lint": {"citation_exempt_tokens": ["tests/scripts/__init__.py"]}}
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is False
    assert "tests/scripts/conftest.py" in msg


def test_plugin_default_exempts_the_rules_own_placeholder(tmp_path):
    """test_snake_case is plugin-intrinsic: it lives in this module's docstring,
    so every host documenting this lint hits it. No host config needed."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text("Test identifiers look like `test_snake_case`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is True, msg


def test_host_entries_extend_rather_than_replace_defaults(tmp_path):
    """A host that lists its own token keeps the plugin defaults."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text("Both `test_snake_case` and `tests/scripts/__init__.py`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    cfg = {"lint": {"citation_exempt_tokens": ["tests/scripts/__init__.py"]}}
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is True, msg


def test_stale_exemption_is_noted_without_blocking(tmp_path):
    """A listed token that now resolves must surface, or the list rots silently."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "real.py").write_text("x = 1\n")
    page = repo / "page.md"
    page.write_text("See `scripts/real.py`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    cfg = {"lint": {"citation_exempt_tokens": ["scripts/real.py"]}}
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is True
    assert "stale exemption" in msg
    assert "scripts/real.py" in msg


# ---------- symbol loop honors example_prefixes too (CCE-131 final-review Finding 6) --


def test_symbol_citation_under_example_prefix_is_skipped(tmp_path):
    """The symbol-existence loop in check_path checked `exempt` but not
    example_prefixes. Harmless while the cited file genuinely does not exist
    (the loop `continue`s on a missing target, already reported by the paths
    loop) -- but a host with a real example/ tree that did not reconfigure
    the prefix has a real file there, and the symbol-existence check must
    still treat example/ as reserved rather than confirming/denying a
    fictional symbol inside a real file."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "example").mkdir()
    (repo / "example" / "auth.py").write_text("def real_but_irrelevant():\n    pass\n")
    page = repo / "page.md"
    page.write_text("See `example/auth.py:totally_fake_symbol`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is True, msg


# ---------- the citation grammar's own metasyntactic placeholder (CCE-134) ----------
#
# `path/to/file.py` is the placeholder in the CCE-122 citation grammar that the
# plugin itself ships (agents/page-author.md, CLAUDE.md) and that therefore
# propagates into authored pages on EVERY host. It is an exact EXEMPT TOKEN, not
# a reserved prefix: the corpus contains exactly one such token, exempt_tokens()
# UNIONS with host config (a prefix REPLACES, so a host that renames its example
# namespace would silently lose the plugin-intrinsic entry), and the exempt
# branch reports drift when the token starts resolving. A prefix would reserve an
# unbounded subtree with a silent bare `continue`.


def test_plugin_default_exempts_the_citation_grammar_placeholder(tmp_path):
    """CCE-134: the grammar placeholder is documentation, not a citation."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text("Cite code as `path/to/file.py`, never with a line number.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is True, msg


def test_grammar_placeholder_suffix_variants_are_exempt(tmp_path):
    """`:symbol` and `:line` both strip to the same bare exempt token, and the
    symbol-existence loop must skip it too (the file does not exist to parse)."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text(
        "Grammar: `path/to/file.py`, `path/to/file.py:symbol`, "
        "never `path/to/file.py:line`.\n"
    )
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is True, msg


def test_grammar_placeholder_survives_a_host_example_prefix_override(tmp_path):
    """Durability across hosts: example_prefixes() REPLACES on host override, so
    a prefix-based fix would break every host that renamed its example
    namespace. exempt_tokens() unions, so the plugin-intrinsic entry survives."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text("Cite code as `path/to/file.py`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    cfg = {
        "lint": {
            "citation_example_prefixes": ["acme"],
            "citation_exempt_tokens": ["tests/scripts/__init__.py"],
        }
    }
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is True, msg


def test_confabulated_sibling_under_path_to_still_blocks(tmp_path):
    """The exemption is one exact token, not the `path/to/` subtree. A prefix
    would swallow this invented file with a silent bare `continue`."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text(
        "Grammar is `path/to/file.py`; the runner lives in "
        "`path/to/genuinely_missing.py`.\n"
    )
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is False, msg
    assert "path/to/genuinely_missing.py" in msg
    assert "cites nonexistent path 'path/to/file.py'" not in msg


def test_confabulated_symbol_in_a_real_path_to_file_still_blocks(tmp_path):
    """Worst case a prefix would hide: an invented symbol attributed to a REAL
    file, which reads as authoritative (the CCE-122 `:symbol` hazard)."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "path" / "to").mkdir(parents=True)
    (repo / "path" / "to" / "real_module.py").write_text(
        "def real_symbol():\n    x=1\n"
    )
    page = repo / "page.md"
    page.write_text(
        "Grammar is `path/to/file.py:symbol`; see "
        "`path/to/real_module.py:totally_invented_symbol`.\n"
    )
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is False, msg
    assert "cites nonexistent symbol 'totally_invented_symbol'" in msg
    assert "path/to/file.py'" not in msg


def test_grammar_placeholder_reports_drift_once_it_resolves(tmp_path):
    """Self-healing: a host that grows a real path/to/file.py gets an actionable
    `stale exemption` note. The prefix branch is a silent `continue` forever."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "path" / "to").mkdir(parents=True)
    (repo / "path" / "to" / "file.py").write_text("x = 1\n")
    page = repo / "page.md"
    page.write_text("Cite code as `path/to/file.py`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is True, msg
    assert "stale exemption: 'path/to/file.py' now resolves" in msg


# ---------- CCE-145: symbol resolution is language-agnostic ----------
#
# `_symbol_defined` recognized Python syntax only (`def`/`class` at any indent,
# plus a COLUMN-0 `name =` / `name:`). Two consequences, both live:
#   1. No JavaScript/TypeScript definition form resolved at all — not
#      `export const`, not `export function`, not `export class`. Every
#      `path.mjs:symbol` citation on a JS host blocked.
#   2. A symbol bound as a key inside an object/dict literal, or as an indented
#      class attribute, never resolved even in Python.
# Reference block (run 32460602658, host claude-code-self-assessment):
#   "cites nonexistent symbol 'memory' in 'scripts/score.mjs'" — a scorer
#   registered as a key inside `export const EXECUTION_SCORERS = {`.


_SCORE_MJS = """\
export function withGates(gates, fn) {
  return { gates, fn };
}

export const EXECUTION_SCORERS = {
  permissions: withGates({ transcripts: true }, (s) => s.a),

  memory: withGates({ transcripts: true }, (s) => s.b),
};

export function normalize(raw, target) {
  return Math.round((raw / target) * 100);
}
"""


def test_symbol_nested_in_exported_object_literal_resolves(tmp_path):
    """The live CCE-145 repro: a scorer registered as a key inside an exported
    object map. It is exported code at a reachable citation target; it is just
    not a top-level export BINDING."""
    repo, cfg = _init_host(tmp_path)
    (repo / "scripts" / "score.mjs").write_text(_SCORE_MJS)
    page = repo / "page.md"
    page.write_text("The scorer lives at `scripts/score.mjs:memory`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 0, out["results"][0]["message"]


@pytest.mark.parametrize(
    "source,leaf",
    [
        ("export const A_CONST = 1;\n", "A_CONST"),
        ("export function aFunc() {}\n", "aFunc"),
        ("export async function aAsync() {}\n", "aAsync"),
        ("export function* aGen() {}\n", "aGen"),
        ("export class AClass {}\n", "AClass"),
        ("export default function aDefault() {}\n", "aDefault"),
        ("function aPlain() {}\n", "aPlain"),
        ("const aArrow = () => {};\n", "aArrow"),
        ("let aLet = 1;\n", "aLet"),
        ("var aVar = 1;\n", "aVar"),
        ("export type AType = string;\n", "AType"),
        ("export interface AIface { x: number }\n", "AIface"),
        ("export enum AEnum { X }\n", "AEnum"),
    ],
)
def test_js_declaration_forms_resolve(tmp_path, source, leaf):
    repo, cfg = _init_host(tmp_path)
    (repo / "scripts" / "mod.ts").write_text(source)
    page = repo / "page.md"
    page.write_text(f"See `scripts/mod.ts:{leaf}`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 0, out["results"][0]["message"]


def test_js_re_export_resolves(tmp_path):
    """`export { name }` is the passthrough re-export form the CCE-145 ticket
    names explicitly (app/lib/assessment.ts:182 on the reference host)."""
    repo, cfg = _init_host(tmp_path)
    (repo / "scripts" / "reexport.ts").write_text(
        'import { evaluatePredicate } from "./predicate.mjs";\n'
        "export { evaluatePredicate };\n"
    )
    page = repo / "page.md"
    page.write_text("Re-exported from `scripts/reexport.ts:evaluatePredicate`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 0, out["results"][0]["message"]


def test_js_class_method_shorthand_resolves(tmp_path):
    repo, cfg = _init_host(tmp_path)
    (repo / "scripts" / "svc.mjs").write_text(
        "export class Service {\n  async handle(req) {\n    return req;\n  }\n}\n"
    )
    page = repo / "page.md"
    page.write_text("`scripts/svc.mjs:Service.handle` does the work.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 0, out["results"][0]["message"]


def test_python_indented_class_attribute_resolves(tmp_path):
    """The same object-literal defect in Python form: a class attribute bound
    at an indent, which the old column-0 anchor could not see."""
    repo, cfg = _init_host(tmp_path)
    (repo / "scripts" / "cfg.py").write_text(
        "class Settings:\n    RETRY_BUDGET = 3\n"
    )
    page = repo / "page.md"
    page.write_text("The cap is `scripts/cfg.py:Settings.RETRY_BUDGET`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 0, out["results"][0]["message"]


# ---------- CCE-145: strictness guards (the rule must still block) ----------


def test_confabulated_symbol_in_js_module_still_blocks(tmp_path):
    """Widening definition forms must not make the rule pass for a symbol that
    is genuinely absent. A fix that stops blocking is worse than the bug."""
    repo, cfg = _init_host(tmp_path)
    (repo / "scripts" / "score.mjs").write_text(_SCORE_MJS)
    page = repo / "page.md"
    page.write_text("See `scripts/score.mjs:totallyInventedScorer`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 1
    assert (
        "cites nonexistent symbol 'totallyInventedScorer' in 'scripts/score.mjs'"
        in out["results"][0]["message"]
    )


@pytest.mark.parametrize(
    "source",
    [
        "// ghostSymbol is described here but never defined.\n",
        '/* ghostSymbol */\nconst other = 1;\n',
        'const msg = "ghostSymbol";\n',
        "import { ghostSymbol } from './elsewhere.mjs';\n",
        "ghostSymbol();\n",
        "if (ghostSymbol()) { run(); }\n",
        'const registry = { "ghostSymbol": 1 };\n',
    ],
)
def test_symbol_only_mentioned_not_defined_still_blocks(tmp_path, source):
    """A name that merely APPEARS in the file — in a comment, a string, a bare
    import, or a call — is not a definition site. Matching those would let a
    citation point at the wrong file and read as authoritative."""
    repo, cfg = _init_host(tmp_path)
    (repo / "scripts" / "mod.mjs").write_text(source)
    page = repo / "page.md"
    page.write_text("See `scripts/mod.mjs:ghostSymbol`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 1, out["results"][0]["message"]
    assert "cites nonexistent symbol 'ghostSymbol'" in out["results"][0]["message"]


# ---------- CCE-145: gitignored paths are unverifiable, not missing ----------


def test_gitignored_path_absent_from_checkout_does_not_block(tmp_path):
    """A generated artifact the host gitignores by design does not exist in a
    fresh CI checkout. It is unverifiable, not confabulated: the .gitignore
    entry is the repo's own evidence that the path is expected."""
    repo, cfg = _init_host(tmp_path)
    (repo / ".gitignore").write_text("app/data/assessment.json\n")
    page = repo / "page.md"
    page.write_text("The snapshot is written to `app/data/assessment.json`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 0, out["results"][0]["message"]
    assert "unverifiable (gitignored)" in out["results"][0]["message"]
    assert "app/data/assessment.json" in out["results"][0]["message"]


def test_untracked_path_that_is_not_gitignored_still_blocks(tmp_path):
    """Strictness guard: gitignore-awareness must not become a blanket pass for
    every missing path."""
    repo, cfg = _init_host(tmp_path)
    (repo / ".gitignore").write_text("app/data/assessment.json\n")
    page = repo / "page.md"
    page.write_text("See `scripts/never_written.py`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 1
    assert "cites nonexistent path 'scripts/never_written.py'" in (
        out["results"][0]["message"]
    )
