"""Guard: workflows must use correct auth tiers.

Repo Variables (vars.*) for non-secret identifiers (Client ID, email).
Repo Secrets (secrets.*) for credentials (private keys, tokens, webhooks).

This test fails the moment any workflow drifts back to the deprecated
`app-id` input or treats JIRA_EMAIL as a secret. Covers both the dogfood
workflow and scaffolded host templates (which propagate to onboarded
hosts via the setup skill).

CCE-66 root cause: `actions/create-github-app-token@v3` deprecated
`app-id` in favor of `client-id` (a semantically different App field).
CCE-66 also re-classifies `JIRA_EMAIL` from Secret to Variable because
it is a basic-auth username, not a credential.
"""

from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted(
    [
        *(ROOT / ".github" / "workflows").glob("*.yml"),
        *(ROOT / "templates").glob("workflow-*.yml"),
    ]
)


def test_workflows_discovered():
    """Sanity: glob-based discovery would vacuously pass with empty list."""
    assert WORKFLOWS, "no workflow files discovered"


def test_no_workflow_uses_deprecated_app_id_input():
    """CCE-66: actions/create-github-app-token@v3 deprecated `app-id`
    in favor of `client-id`. Catches stale workflows and templates that
    haven't been migrated, and forward-protects PR #383 (template
    refresh) — when the template gains App-token wiring, it must use
    `client-id` from the start."""
    offenders = [wf.name for wf in WORKFLOWS if "app-id:" in wf.read_text()]
    assert not offenders, "workflows still use deprecated `app-id:`: " + ", ".join(
        offenders
    )


def test_no_workflow_reads_jira_email_as_secret():
    """CCE-66: JIRA_EMAIL is a basic-auth username, not a credential.
    Belongs in repo Variables (vars.JIRA_EMAIL), not Secrets."""
    offenders = [wf.name for wf in WORKFLOWS if "secrets.JIRA_EMAIL" in wf.read_text()]
    assert not offenders, "workflows still read JIRA_EMAIL as secret: " + ", ".join(
        offenders
    )
