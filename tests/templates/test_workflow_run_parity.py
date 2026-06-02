"""Parity test for templates/workflow-run.yml ↔ .github/workflows/docs-agent-nightly.yml.

Key grammar (the strings used in _ALLOWLIST and matcher logic):
  uses:<action>@<ver>              — matches step by uses: signature only (no id required)
  uses:<action>@<ver>#<id>         — matches step by uses: AND id: (disambiguates duplicates)
  run:<prefix>                     — matches a step whose run: scalar starts with the prefix (first line, normalized whitespace)

XFAIL DISCIPLINE: tests are xfailed until their template-absorption task lands. Each
task in the implementation plan lifts the xfail markers it satisfies, leaving the
suite green throughout the absorption sequence (CCE-80 plan tasks 5, 6, 8).
"""

from __future__ import annotations

from pathlib import Path

import pytest

# CI10: module-level importorskip — if ruamel.yaml is missing, every test in this
# module SKIPS instead of erroring at collection time. Downstream tasks remain green.
ruamel = pytest.importorskip("ruamel.yaml")

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "workflow-run.yml"
DOGFOOD = ROOT / ".github" / "workflows" / "docs-agent-nightly.yml"


# _ALLOWLIST: step-signature entries that test_06 actively enforces (uses:/run: prefixes).
# Any step in dogfood OR template matching one of these signatures bypasses test_01's
# step-signature parity check. Entries are validated by test_06 to be neither stale
# (no matching step anywhere) nor redundant (matching step in BOTH files).
_ALLOWLIST: dict[str, str] = {
    "uses:actions/checkout@v5#checkout-plugin": "Template-only: plugin vendoring step (id: checkout-plugin discriminates from host checkout)",
    "run:python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .": "HOST-SPECIFIC entrypoint: template uses vendored-plugin path; dogfood uses its own scripts/ tree",
    'run:python3 scripts/orchestrator_runner.py --repo-root "$GITHUB_WORKSPACE"': "HOST-SPECIFIC entrypoint: dogfood-side counterpart to the template's vendored-plugin run line",
}


# _TEMPLATE_ONLY_DIVERGENCES: documentation-only notes for non-step divergences
# (triggers, env keys, if-expressions, with-keys). These are NOT enforced by any
# test function — they record WHY the human reviewer should accept these
# divergences when reading the diff. See spec §5.2.
_TEMPLATE_ONLY_DIVERGENCES: dict[str, str] = {
    "on.pull_request.types == [closed]": "Template-only trigger: real-time docs update on merge for hosts (D4)",
    "jobs.run.if contains `github.event_name == 'schedule'`": "Template-only job-level guard: paired with pull_request.closed trigger (D4 self-loop)",
    "with.path == .docs-agent-plugin": "Template-only: vendored-plugin checkout target (paired with checkout-plugin step)",
    "env.SLACK_WEBHOOK_URL": "Template-only opt-in: consumed by agents/notifier.md when notifications.slack.enabled: true",
    "if: vars.DOCS_AGENT_SKIP_OAUTH_ASSERT != 'true' on Assert OAuth step": "Template-only: enterprise/Bedrock/Vertex hosts can opt out; dogfood owns its own auth",
    "if: vars.DOCS_AGENT_APP_CLIENT_ID != '' on Generate GitHub App token step": "Template-only: hosts without an App fall back to GITHUB_TOKEN (with host-CI suppression caveat); dogfood requires the App",
    "with.token uses ||-fallback": "Template-only: checkout-host and docs-agent step env use `steps.app-token.outputs.token || secrets.GITHUB_TOKEN`; dogfood uses only the App token",
}


_WITH_KEY_CONTRACT: dict[str, set[str]] = {
    "actions/checkout@v5": {"token"},
    "actions/create-github-app-token@v3": {"client-id", "private-key"},
    "actions/upload-artifact@v6": {
        "name",
        "path",
        "retention-days",
        "if-no-files-found",
    },
}


def _load(path: Path) -> dict:
    yaml = ruamel.yaml.YAML(typ="rt")
    with path.open() as fh:
        return yaml.load(fh)


@pytest.fixture(scope="module")
def template_doc() -> dict:
    return _load(TEMPLATE)


@pytest.fixture(scope="module")
def dogfood_doc() -> dict:
    return _load(DOGFOOD)


# ---------------------------------------------------------------------------
# 8 numbered assertion functions (xfailed-skeleton; bodies replaced as tasks land)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="CCE-80 plan task 8 lifts: full step-signature parity awaits CCE-73 stdout echo bundle + dogfood id co-edit"
)
def test_01_step_signature_parity(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 8")


@pytest.mark.xfail(
    reason="CCE-80 plan task 8 lifts: with-key contract on all absorbed actions"
)
def test_02_with_key_contract(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 8")


@pytest.mark.xfail(
    reason="CCE-80 plan task 8 lifts: substring asserts include partial_reasons (CCE-73 bundle)"
)
def test_03_high_value_substring_asserts(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 8")


@pytest.mark.xfail(
    reason="CCE-80 plan task 5 lifts: literal-equals shape contract on CCE-39 baseline + App-token folded"
)
def test_04_literal_equals_shape_contract(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 5")


@pytest.mark.xfail(
    reason="CCE-80 plan task 5 lifts: App-token conditional shape (template-only properties)"
)
def test_05_app_token_conditional_shape(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 5")


@pytest.mark.xfail(
    reason="CCE-80 plan task 8 lifts: allowlist orphan/redundant guards run when all steps present"
)
def test_06_stale_allowlist_entries(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 8")


@pytest.mark.xfail(
    reason="CCE-80 plan task 5 lifts: run-summary `if: always()` (CCE-39 baseline)"
)
def test_07_run_summary_if_always(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 5")


@pytest.mark.xfail(
    reason="CCE-80 plan task 5 lifts: on-key regression guard (catches PyYAML escape route)"
)
def test_08_on_key_regression(template_doc, dogfood_doc) -> None:
    raise AssertionError("not yet implemented — see CCE-80 plan task 5")
