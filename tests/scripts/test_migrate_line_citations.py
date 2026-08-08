from __future__ import annotations
import subprocess
from pathlib import Path

# Import via the `scripts` namespace package (repo root is on sys.path through
# conftest). Do NOT `sys.path.insert` the scripts dir and import bare modules:
# that mutates process-wide sys.path and breaks later `from scripts.lint...`
# namespace resolution in other suites (test_lint_runner). See CCE-122.
from scripts import migrate_line_citations as mlc
from scripts.lint import citation_exists


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )


def _host(tmp_path: Path) -> Path:
    repo = tmp_path / "host"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "runner.py").write_text(
        "import os\n\n"
        "DEFAULT_BUDGET = 2700\n\n\n"
        "def run(repo):\n"
        "    x = 1\n"
        "    return x\n\n\n"
        "class Engine:\n"
        "    def start(self):\n"
        "        return 2\n"
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_function_line_becomes_symbol(tmp_path):
    repo = _host(tmp_path)
    new, changes = mlc.migrate_text("Entry `scripts/runner.py:6`.", repo)
    assert new == "Entry `scripts/runner.py:run`."
    assert changes == [("scripts/runner.py:6", "scripts/runner.py:run")]


def test_method_line_becomes_class_dot_method(tmp_path):
    repo = _host(tmp_path)
    new, _ = mlc.migrate_text("`scripts/runner.py:12` starts it.", repo)
    assert new == "`scripts/runner.py:Engine.start` starts it."


def test_module_assignment_line_becomes_name(tmp_path):
    repo = _host(tmp_path)
    new, _ = mlc.migrate_text("Default `scripts/runner.py:3`.", repo)
    assert new == "Default `scripts/runner.py:DEFAULT_BUDGET`."


def test_range_uses_start_line_symbol(tmp_path):
    repo = _host(tmp_path)
    new, _ = mlc.migrate_text("`scripts/runner.py:6-8` body.", repo)
    assert new == "`scripts/runner.py:run` body."


def test_unresolvable_line_strips_to_bare(tmp_path):
    repo = _host(tmp_path)
    new, _ = mlc.migrate_text("Top `scripts/runner.py:1`.", repo)
    assert new == "Top `scripts/runner.py`."


def test_non_python_strips_to_bare(tmp_path):
    repo = _host(tmp_path)
    (repo / "deploy.yml").write_text("on: push\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "yml")
    new, _ = mlc.migrate_text("Config `deploy.yml:1`.", repo)
    assert new == "Config `deploy.yml`."


def test_bare_filename_resolves_to_tracked_path(tmp_path):
    repo = _host(tmp_path)
    new, _ = mlc.migrate_text("See `runner.py:6`.", repo)
    assert new == "See `scripts/runner.py:run`."


def test_fenced_blocks_untouched(tmp_path):
    repo = _host(tmp_path)
    text = "before `scripts/runner.py:6`\n```\n`scripts/runner.py:6`\n```\n"
    new, _ = mlc.migrate_text(text, repo)
    assert new == "before `scripts/runner.py:run`\n```\n`scripts/runner.py:6`\n```\n"


def test_idempotent(tmp_path):
    repo = _host(tmp_path)
    once, _ = mlc.migrate_text("`scripts/runner.py:6`", repo)
    twice, changes = mlc.migrate_text(once, repo)
    assert twice == once
    assert changes == []


def test_migrated_page_passes_citation_exists(tmp_path):
    repo = _host(tmp_path)
    (repo / ".engineering-docs-agent").mkdir()
    (repo / ".engineering-docs-agent" / "config.yml").write_text(
        "lint: { tier1: default }\n"
    )
    page = repo / "page.md"
    page.write_text("# T\n\nThe `scripts/runner.py:6` entry runs nightly.\n")
    new, _ = mlc.migrate_text(page.read_text(), repo)
    page.write_text(new)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok, msg
    assert citation_exists.line_pinned_citations(new) == []
