from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "setup_discover.py"
FIX = Path(__file__).parent.parent / "fixtures" / "setup_repos"


def test_mkdocs_lensy_detected():
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        cwd=FIX / "mkdocs_lensy",
        capture_output=True,
        text=True,
    )
    out = json.loads(r.stdout)
    assert out["framework"] == "mkdocs"
    assert "core" in out["lens_paths"]
    assert "archive" in out["lens_paths"]


def test_bare_repo_minimal():
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        cwd=FIX / "bare",
        capture_output=True,
        text=True,
    )
    out = json.loads(r.stdout)
    assert out["framework"] is None


def test_setup_discover_warns_on_docusaurus(tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import setup_discover

    (tmp_path / "docusaurus.config.js").write_text("module.exports = {};")
    result = setup_discover.discover(tmp_path)
    assert "warnings" in result
    assert any(
        "docusaurus_v0.1_unsupported" in w.get("code", "") for w in result["warnings"]
    )


def test_detect_jira_hint_from_workflow_yaml(tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import setup_discover

    wf = tmp_path / ".github" / "workflows" / "ci.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("""
env:
  JIRA_BASE_URL: https://acme.atlassian.net
  JIRA_PROJECT: ADIS
""")

    hint = setup_discover.detect_jira_hint(tmp_path)
    assert hint
    assert hint.get("base_url") == "https://acme.atlassian.net"


import sys as _sys

_sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from setup_discover import derive_pages_base_url, detect_pages_publishable


def test_base_url_project_site():
    assert (
        derive_pages_base_url("theoju", "engineering-docs-agent")
        == "https://theoju.github.io/engineering-docs-agent/"
    )


def test_base_url_user_site():
    assert (
        derive_pages_base_url("theoju", "theoju.github.io")
        == "https://theoju.github.io/"
    )


def test_base_url_custom_domain():
    assert (
        derive_pages_base_url("theoju", "r", "docs.example.com")
        == "https://docs.example.com/"
    )


def test_pages_publishable_only_mkdocs_on_actions():
    assert detect_pages_publishable("mkdocs", "github_actions") is True
    assert detect_pages_publishable("docusaurus", "github_actions") is False
    assert detect_pages_publishable("mkdocs", "gitlab_ci") is False
    assert detect_pages_publishable(None, "github_actions") is False
