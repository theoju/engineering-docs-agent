from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_requirements_docs_declares_playwright_and_mkdocs():
    txt = (ROOT / "requirements-docs.txt").read_text().lower()
    assert "playwright" in txt
    assert "mkdocs" in txt  # building the site is part of the gate's CI job


def test_requirements_docs_separate_from_agent_runtime():
    # The agent runtime stays stdlib + pyyaml + jsonschema; playwright must not
    # leak into a general requirements.txt if one exists.
    rt = ROOT / "requirements.txt"
    if rt.exists():
        assert "playwright" not in rt.read_text().lower()


def test_makefile_has_docs_verify_target():
    mk = (ROOT / "Makefile").read_text()
    assert "docs-verify:" in mk
    assert "verify_diagrams.py" in mk


def test_docs_workflow_runs_the_gate():
    import yaml  # already a runtime dep

    wf = ROOT / ".github" / "workflows" / "docs.yml"
    data = yaml.safe_load(wf.read_text())
    # `on:` may parse as the boolean True key in YAML 1.1 — accept either.
    triggers = data.get("on") or data.get(True)
    assert triggers, "workflow must declare triggers"
    body = wf.read_text()
    assert "playwright install" in body
    assert "verify_diagrams.py" in body
    assert "--require" in body  # CI must hard-fail when Playwright is missing
    assert "mkdocs build" in body
    # Scoped to docs / gate files, not every push.
    assert "paths:" in body
