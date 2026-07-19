from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPTS_LINT = Path(__file__).parent.parent.parent / "scripts" / "lint"
sys.path.insert(0, str(SCRIPTS_LINT))
import citation_exists  # noqa: E402

SCRIPT = SCRIPTS_LINT / "citation_exists.py"


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
