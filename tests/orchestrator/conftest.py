# tests/orchestrator/conftest.py
"""Shared host-repo fixtures for orchestrator tests.

CONFIG_YAML / init_host / read_current_run existed as near-verbatim
module-level copies in seven test files when this conftest was introduced
(CCE-109 review). The older files were migrated onto these fixtures in
CCE-112; new tests should use them too.
"""

from __future__ import annotations
import json
import subprocess
from pathlib import Path

import pytest

CONFIG_YAML = """
docs:
  framework: mkdocs
  source_dir: docs/site-src
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths:
    core: docs/site-src/core
sources:
  git: { host: github }
lint: { tier1: default }
publishing:
  base_url: https://example.com
  build_workflow: deploy.yml
  url_map_rule: standard
  verify_timeout_seconds: 60
notifications:
  slack: { enabled: false }
  email: { enabled: false }
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture(autouse=True)
def _pin_repo_slug(monkeypatch):
    """Pin the repo slug every orchestrator test already assumes.

    `detect_repo` prefers $GITHUB_REPOSITORY, falls back to the origin remote,
    and only then returns the `unknown/unknown` sentinel. Host repos scaffolded
    by `init_host` are `git init`-ed with no remote, so on a developer machine
    the sentinel is what every computed pr_id gets — and the shared
    `fakes_*/fake_gap_detector.json` payloads hardcode `unknown/unknown#1` to
    match.

    On GitHub Actions $GITHUB_REPOSITORY is always set, so the same code
    produced `theoju/engineering-docs-agent#1` and every assertion keyed on a
    computed pr_id failed in CI while passing locally. Pinning it here makes
    the directory hermetic instead of accidentally correct, and keeps the
    checked-in fixtures true.

    Deliberately set rather than deleted: `delenv` would leave the git-remote
    branch reachable, so a scaffolded host that ever gained an origin would
    reintroduce exactly this bug.
    """
    monkeypatch.setenv("GITHUB_REPOSITORY", "unknown/unknown")


@pytest.fixture
def init_host(tmp_path):
    """Factory: scaffold a host repo (git init + config + seeded state) in
    tmp_path. Returns the state.json path.

    `seed_files` is a mapping of repo-relative path → content for files that
    must exist in the initial commit (so they're in HEAD before the runner
    runs)."""

    def _init(
        seeded_state: dict,
        config_yaml: str = CONFIG_YAML,
        seed_files: dict[str, str] | None = None,
    ) -> Path:
        (tmp_path / "docs" / "site-src" / "core").mkdir(parents=True)
        (tmp_path / ".engineering-docs-agent").mkdir()
        (tmp_path / ".engineering-docs-agent" / "config.yml").write_text(config_yaml)
        state_path = tmp_path / ".engineering-docs-agent" / "state.json"
        state_path.write_text(json.dumps(seeded_state))
        for rel, body in (seed_files or {}).items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.email", "t@example.com")
        _git(tmp_path, "config", "user.name", "T")
        (tmp_path / "README.md").write_text("init")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-q", "-m", "init")
        return state_path

    return _init


@pytest.fixture
def read_current_run():
    """CCE-40: current_run lives in the sibling ephemeral current_run.json."""

    def _read(state_path: Path) -> dict:
        sibling = state_path.parent / "current_run.json"
        return json.loads(sibling.read_text())["current_run"]

    return _read
