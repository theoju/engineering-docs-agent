from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "preflight_host.py"
FIX = Path(__file__).parent.parent / "fixtures" / "setup_repos"


def test_preflight_json_mode_on_js_docusaurus():
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(FIX / "js_docusaurus"),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert set(out.keys()) >= {
        "discovery",
        "proposed_config",
        "secrets_checklist",
        "variables_checklist",
        "warnings",
    }
    assert out["discovery"]["framework"] == "docusaurus"
    assert out["discovery"]["toolchain"]["docusaurus_dep"] is True
    names = {s["name"] for s in out["secrets_checklist"]}
    # CCE-66: DOCS_AGENT_APP_ID is migrated out; CLAUDE_CODE_OAUTH_TOKEN
    # and DOCS_AGENT_APP_PRIVATE_KEY remain secrets.
    assert {
        "CLAUDE_CODE_OAUTH_TOKEN",
        "DOCS_AGENT_APP_PRIVATE_KEY",
    } <= names
    assert "DOCS_AGENT_APP_ID" not in names, (
        "CCE-66: DOCS_AGENT_APP_ID should no longer appear in secrets_checklist"
    )

    # CCE-66: new variables_checklist surfaces the required vars
    # (client-id, JIRA_EMAIL) so onboarding operators get correct guidance.
    var_names = {v["name"] for v in out["variables_checklist"]}
    assert {
        "DOCS_AGENT_APP_CLIENT_ID",
        "JIRA_EMAIL",
    } <= var_names


def test_preflight_text_mode_on_bare_repo():
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(FIX / "bare"),
            "--format",
            "text",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    text = r.stdout
    assert "Discovery" in text
    assert "Secrets checklist" in text
    assert "Variables checklist" in text  # CCE-66: parallel block to Secrets
    assert "framework: None" in text


def test_preflight_emits_framework_none_info_for_bare_host():
    """Bare host (no mkdocs.yml, no docusaurus.config.*) gets an info-
    level notice, NOT a block-severity warning. The notice's code is
    `framework_none`. The old `no_docs_framework` warning is gone."""
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(FIX / "bare"),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    codes = {w["code"] for w in out["warnings"]}
    assert "framework_none" in codes
    assert "no_docs_framework" not in codes
    framework_none = next(w for w in out["warnings"] if w["code"] == "framework_none")
    assert framework_none.get("severity") == "info"
    # Message names both detection points and the upgrade hint.
    msg = framework_none["message"]
    assert "mkdocs.yml" in msg
    assert "docusaurus" in msg.lower()


def test_preflight_does_not_write_to_host(tmp_path):
    (tmp_path / "README.md").write_text("# host")
    snapshot_before = sorted(p.name for p in tmp_path.iterdir())
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    snapshot_after = sorted(p.name for p in tmp_path.iterdir())
    assert snapshot_before == snapshot_after


def test_preflight_missing_repo_root_errors():
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            "/nonexistent/path/that/does/not/exist",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "does not exist" in r.stderr


def test_preflight_proposed_config_writes_framework_none_for_bare_host():
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(FIX / "bare"),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    # Was silently coerced to "mkdocs" before CCE-64; now explicit "none".
    assert out["proposed_config"]["docs"]["framework"] == "none"


def test_proposed_config_includes_site_block():
    """CCE-104: preflight proposes a site: block so the setup skill persists it
    into the host config (the missing wiring that left the rendered site empty)."""
    from scripts.preflight_host import proposed_config

    cfg = proposed_config(
        {
            "framework": "mkdocs",
            "source_dir": "docs/site-src",
            "lens_paths": {"core": "docs/site-src/"},
        }
    )
    site = cfg.get("site")
    assert site, "proposed_config must emit a site: block"
    assert site["docs_dir"] == "docs/site-src"  # tracks the discovered source_dir
    sections = site.get("sections") or []
    by_gen = {s.get("generator"): s for s in sections}
    archive = by_gen.get("archive-index")
    assert archive and archive.get("sources"), (
        "must propose an archive section with non-empty sources"
    )
    assert by_gen.get("api-extract"), "must propose an api-extract section"


def test_proposed_config_site_honors_discovery_decision_sources():
    """The archive sources are an override hook: when discovery supplies
    decision_sources (a host whose decision records live elsewhere), the
    proposed site uses them instead of the superpowers convention default."""
    from scripts.preflight_host import proposed_config

    cfg = proposed_config(
        {
            "framework": "mkdocs",
            "source_dir": "docs",
            "decision_sources": ["docs/adr", "docs/rfcs"],
        }
    )
    archive = next(
        s for s in cfg["site"]["sections"] if s.get("generator") == "archive-index"
    )
    assert archive["sources"] == ["docs/adr", "docs/rfcs"]
