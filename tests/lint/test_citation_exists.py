from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

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
