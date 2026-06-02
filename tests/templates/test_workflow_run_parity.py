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
    # `ruamel` is bound to the ruamel.yaml module by importorskip above,
    # so YAML is accessed directly on it (not via a .yaml sub-attribute).
    yaml = ruamel.YAML(typ="rt")
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


def test_01_step_signature_parity(template_doc, dogfood_doc) -> None:
    """For each step in dogfood, the template has a step with the same uses:
    or run-first-line signature, modulo _ALLOWLIST. Match on signature + id."""
    template_steps = list(template_doc["jobs"].values())[0]["steps"]
    dogfood_steps = list(dogfood_doc["jobs"].values())[0]["steps"]

    def _signature(step: dict) -> str:
        uses = step.get("uses")
        sid = step.get("id")
        if uses:
            return f"uses:{uses}" + (f"#{sid}" if sid else "")
        run = step.get("run", "")
        first = (run.splitlines() or [""])[0].strip()
        return f"run:{first}"

    template_sigs = {_signature(s) for s in template_steps}
    dogfood_sigs = {_signature(s) for s in dogfood_steps}

    missing_in_template = dogfood_sigs - template_sigs - set(_ALLOWLIST)
    assert not missing_in_template, (
        "Dogfood steps with no template counterpart and no allowlist entry: "
        f"{sorted(missing_in_template)}.\n"
        "Action: absorb into templates/workflow-run.yml OR add an _ALLOWLIST "
        "entry in tests/templates/test_workflow_run_parity.py with rationale."
    )


def test_02_with_key_contract(template_doc, dogfood_doc) -> None:
    """Each step using an action listed in _WITH_KEY_CONTRACT has the
    documented keys present. Extra keys are allowed."""
    for doc, label in [(template_doc, "template"), (dogfood_doc, "dogfood")]:
        steps = list(doc["jobs"].values())[0]["steps"]
        for step in steps:
            uses = step.get("uses")
            if uses in _WITH_KEY_CONTRACT:
                with_block = step.get("with") or {}
                expected = _WITH_KEY_CONTRACT[uses]
                # checkout-plugin step legitimately doesn't carry `token:`.
                if (
                    uses == "actions/checkout@v5"
                    and step.get("id") == "checkout-plugin"
                ):
                    continue
                missing = expected - set(with_block.keys())
                assert not missing, (
                    f"{label}: step `{step.get('name')}` uses {uses} but "
                    f"missing required with: keys {sorted(missing)}"
                )


def test_03_high_value_substring_asserts(template_doc, dogfood_doc) -> None:
    """Substring asserts on the parsed `run:` scalar (not raw bytes)."""
    for doc, label in [(template_doc, "template"), (dogfood_doc, "dogfood")]:
        steps = list(doc["jobs"].values())[0]["steps"]
        run_blocks = [s.get("run", "") for s in steps]
        joined = "\n---\n".join(str(r) for r in run_blocks)

        assert "sk-ant-oat" in joined, f"{label}: missing sk-ant-oat assertion"
        assert "sk-ant-api" in joined, f"{label}: missing sk-ant-api arm"
        assert "which claude" in joined, f"{label}: missing which-claude verify"
        assert "engineering-docs-agent[bot]" in joined, f"{label}: missing bot identity"
        assert "partial_reasons" in joined, (
            f"{label}: missing partial_reasons echo (CCE-73 bundle)"
        )


def test_04_literal_equals_shape_contract(template_doc, dogfood_doc) -> None:
    """Locked literal values shared by both files (CCE-39 baseline)."""
    for doc, label in [(template_doc, "template"), (dogfood_doc, "dogfood")]:
        conc = doc["concurrency"]
        assert conc["group"] == "docs-agent-nightly", (
            f"{label}: concurrency.group != docs-agent-nightly"
        )
        assert conc["cancel-in-progress"] is False, (
            f"{label}: cancel-in-progress != false"
        )
        jobs = list(doc["jobs"].values())
        assert len(jobs) == 1, f"{label}: expected exactly 1 job"
        assert jobs[0]["timeout-minutes"] == 60, f"{label}: timeout-minutes != 60"
        perms = doc["permissions"]
        for k in ("contents", "pull-requests", "issues"):
            assert k in perms, f"{label}: missing permissions.{k}"
        env = jobs[0]["env"]
        for k in ("CLAUDE_CODE_OAUTH_TOKEN", "JIRA_API_TOKEN", "JIRA_EMAIL"):
            assert k in env, f"{label}: missing job-env {k}"
        triggers = doc["on"]
        assert "schedule" in triggers, f"{label}: missing schedule trigger"
        assert "workflow_dispatch" in triggers, (
            f"{label}: missing workflow_dispatch trigger"
        )


def test_05_app_token_conditional_shape(template_doc, dogfood_doc) -> None:
    """Template-only property tests on the App-token wiring.

    The TEMPLATE has the `if:` opt-out gate (hosts may skip the App-token step);
    the DOGFOOD does not (we own this repo's auth). The dogfood divergence is
    intentional — documented in _TEMPLATE_ONLY_DIVERGENCES.
    """
    template_jobs = list(template_doc["jobs"].values())
    template_steps = template_jobs[0]["steps"]

    app_token = next((s for s in template_steps if s.get("id") == "app-token"), None)
    assert app_token is not None, "template missing app-token step"
    assert "vars.DOCS_AGENT_APP_CLIENT_ID != ''" in str(app_token.get("if", "")), (
        "template app-token step missing opt-out `if:`"
    )
    assert app_token.get("uses") == "actions/create-github-app-token@v3"
    assert "client-id" in app_token["with"], (
        "app-token must use `client-id` (not deprecated `app-id`)"
    )

    checkout = next((s for s in template_steps if s.get("id") == "checkout-host"), None)
    assert checkout is not None, "template missing checkout-host step"
    token_expr = "".join(str(checkout["with"]["token"]).split())
    expected = "${{steps.app-token.outputs.token||secrets.GITHUB_TOKEN}}"
    assert token_expr == expected, (
        f"checkout-host token wiring mismatch: got {token_expr}, expected {expected}"
    )

    authoring = next((s for s in template_steps if s.get("id") == "docs-agent"), None)
    assert authoring is not None, "template missing docs-agent authoring step"
    gh_token_expr = "".join(str(authoring["env"]["GH_TOKEN"]).split())
    assert gh_token_expr == expected, (
        f"authoring step GH_TOKEN mismatch: got {gh_token_expr}, expected {expected}"
    )


def test_06_stale_allowlist_entries(template_doc, dogfood_doc) -> None:
    """Every _ALLOWLIST entry matches at least one step; no entry matches a step
    present in BOTH (redundant-allowlist guard)."""
    template_steps = list(template_doc["jobs"].values())[0]["steps"]
    dogfood_steps = list(dogfood_doc["jobs"].values())[0]["steps"]

    def _signature(step: dict) -> str:
        uses = step.get("uses")
        sid = step.get("id")
        if uses:
            return f"uses:{uses}" + (f"#{sid}" if sid else "")
        run = step.get("run", "")
        first = (run.splitlines() or [""])[0].strip()
        return f"run:{first}"

    template_sigs = {_signature(s) for s in template_steps}
    dogfood_sigs = {_signature(s) for s in dogfood_steps}

    for key in _ALLOWLIST:
        in_template = key in template_sigs
        in_dogfood = key in dogfood_sigs
        if not (in_template or in_dogfood):
            raise AssertionError(
                f"stale allowlist entry `{key}` — no matching step in dogfood "
                f"or template. Delete from _ALLOWLIST or update."
            )
        if in_template and in_dogfood:
            raise AssertionError(
                f"redundant allowlist entry `{key}` — present in both files. "
                "Remove from _ALLOWLIST."
            )


def test_07_run_summary_if_always(template_doc, dogfood_doc) -> None:
    """Run-summary step must have `if: always()` so partial/failed runs render."""
    for doc, label in [(template_doc, "template"), (dogfood_doc, "dogfood")]:
        jobs = list(doc["jobs"].values())
        steps = jobs[0]["steps"]
        run_summary_steps = [s for s in steps if s.get("name") == "Run summary"]
        assert len(run_summary_steps) == 1, (
            f"{label}: expected exactly 1 'Run summary' step"
        )
        if_expr = str(run_summary_steps[0].get("if", ""))
        assert if_expr.startswith("always()"), (
            f"{label}: run-summary if `{if_expr}` does not start with always()"
        )


def test_08_on_key_regression(template_doc, dogfood_doc) -> None:
    """Top-level `on:` key must parse as a string-keyed mapping, NOT the YAML-1.1
    boolean True (the PyYAML SafeLoader escape route). Regression guard.
    """
    for doc, label in [(template_doc, "template"), (dogfood_doc, "dogfood")]:
        on_val = doc["on"]
        assert isinstance(on_val, dict), (
            f"{label}: top-level `on:` is {type(on_val).__name__}, expected dict"
        )
