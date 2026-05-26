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
