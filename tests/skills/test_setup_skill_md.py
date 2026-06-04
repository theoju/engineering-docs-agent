"""Grep-style integration test for SKILL.md edits (CCE-80 spec §6.3).

Locks the FN rename, the scaffold_workflow.py invocation, and the App-token warning.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "engineering-docs-agent-setup" / "SKILL.md"


def _content() -> str:
    return SKILL.read_text()


def test_skill_references_docs_agent_nightly_filename() -> None:
    """FN — workflow filename matches dogfood + all 3 known hosts."""
    assert ".github/workflows/docs-agent-nightly.yml" in _content()


def test_skill_does_not_reference_legacy_filename() -> None:
    """`docs-agent-run.yml` is the pre-CCE-80 name; must be fully removed."""
    assert "docs-agent-run.yml" not in _content()


def test_skill_invokes_scaffold_workflow_helper() -> None:
    """SKILL.md step 6 must reference scripts/scaffold_workflow.py."""
    assert "scripts/scaffold_workflow.py" in _content()


def test_skill_step8_warns_about_app_token_for_ci() -> None:
    """Step 8 must surface the App-token-for-host-CI consequence.

    CI6 fix: second clause is `host ci` (lowercase) so the OR is meaningful.
    """
    text = _content()
    assert "DOCS_AGENT_APP_CLIENT_ID" in text
    assert "host CI" in text or "host ci" in text.lower() or "host_ci" in text
