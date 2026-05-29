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


def test_discover_reports_pages_publishable_for_mkdocs_actions(tmp_path):
    (tmp_path / "mkdocs.yml").write_text("site_name: x\n")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    from setup_discover import discover

    out = discover(tmp_path)
    assert out["pages_publishable"] is True


def test_discover_not_publishable_without_framework(tmp_path):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    from setup_discover import discover

    out = discover(tmp_path)
    assert out["pages_publishable"] is False


# --- CCE-57: detect_toolchain (JS/TS host shape) ---


def test_detect_toolchain_bare_dir(tmp_path):
    import setup_discover

    out = setup_discover.detect_toolchain(tmp_path)
    assert out == {
        "node": False,
        "bun": False,
        "deno": False,
        "package_manager": None,
        "docusaurus_dep": False,
    }


def test_detect_toolchain_node_with_npm_lock(tmp_path):
    import setup_discover

    (tmp_path / "package.json").write_text('{"name":"x"}')
    (tmp_path / "package-lock.json").write_text("{}")
    out = setup_discover.detect_toolchain(tmp_path)
    assert out["node"] is True
    assert out["package_manager"] == "npm"
    assert out["docusaurus_dep"] is False


def test_detect_toolchain_bun_lockfile_wins(tmp_path):
    import setup_discover

    (tmp_path / "package.json").write_text('{"name":"x"}')
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "bun.lockb").write_bytes(b"\x00")
    out = setup_discover.detect_toolchain(tmp_path)
    assert out["bun"] is True
    assert out["package_manager"] == "bun"


def test_detect_toolchain_pnpm(tmp_path):
    import setup_discover

    (tmp_path / "package.json").write_text('{"name":"x"}')
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n")
    out = setup_discover.detect_toolchain(tmp_path)
    assert out["package_manager"] == "pnpm"


def test_detect_toolchain_docusaurus_dep(tmp_path):
    import setup_discover

    (tmp_path / "package.json").write_text(
        '{"name":"x","devDependencies":{"@docusaurus/core":"^3.0.0"}}'
    )
    out = setup_discover.detect_toolchain(tmp_path)
    assert out["docusaurus_dep"] is True


def test_detect_toolchain_malformed_package_json_is_quiet(tmp_path):
    import setup_discover

    (tmp_path / "package.json").write_text("{not json")
    out = setup_discover.detect_toolchain(tmp_path)
    assert out["node"] is True
    assert out["docusaurus_dep"] is False


def test_detect_toolchain_deno(tmp_path):
    import setup_discover

    (tmp_path / "deno.json").write_text("{}")
    out = setup_discover.detect_toolchain(tmp_path)
    assert out["deno"] is True


def test_discover_surfaces_toolchain_block(tmp_path):
    import setup_discover

    out = setup_discover.discover(tmp_path)
    assert "toolchain" in out
    assert isinstance(out["toolchain"], dict)
    assert set(out["toolchain"].keys()) == {
        "node",
        "bun",
        "deno",
        "package_manager",
        "docusaurus_dep",
    }
