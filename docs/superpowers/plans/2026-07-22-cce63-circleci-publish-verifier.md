# CCE-63 CircleCI publish-verifier provider seam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a testable provider seam to the docs publish-verify path so a `ci_provider: circleci` host degrades honestly ("modeled but unvalidated") instead of mis-verifying, while the GitHub path stays byte-for-byte unchanged.

**Architecture:** A one-line provider fork in `verify_runner.run` routes non-GitHub providers to a new `scripts/build_poller.py` seam. While `UNVALIDATED_AGAINST_LIVE_HOST` is `True`, that seam returns a non-promoting verdict + a fixed partial reason rather than polling a live CircleCI API (there is no live host to validate the API shape against). The real poll ships as documented `NotImplementedError` stubs. A required hardening extends `_redact_credentials` to mask header-form secrets. The second GitHub-only seam — the post-merge publish _trigger_ — is fenced with a strict-xfail test and tracked by a sibling ticket.

**Tech Stack:** Python 3 (stdlib-only), pytest (fixture-driven dry-run; CLI dispatch monkeypatched).

**Approved spec:** `docs/superpowers/specs/2026-07-22-cce63-circleci-publish-verifier-design.md`

**Conventions that constrain this plan:**

- `scripts/` is a PEP 420 namespace package (no `__init__.py`). New tests live in `tests/orchestrator/` and import via `sys.path.insert(scripts) + import <module>` (the pattern already in `tests/orchestrator/test_verify_runner.py`). Do NOT add `tests/scripts/__init__.py`.
- Verdict shape everywhere is `{"verified": [...], "failed": [...], "build_status": str}`.
- Promotion gate (unchanged): `verify_succeeded = not failed_urls and build_status == "success"`.
- Run the full suite with `python3 -m pytest` from the repo root.

---

### Task 1: Extend `_redact_credentials` to mask header-form secrets

Independent hardening (spec §5.5, AC5). Today's redaction only catches URL-embedded `user:token@host`; a CircleCI token is sent as a `Circle-Token` header, so header-form secrets must also be masked. The helper signature (`str -> str`) is unchanged, so no caller needs updating — but this IS a shared contract (`state_io.py:249`, `orchestrator_runner.py:2028/2525`, `stderr_emit.emit_stderr:68`), so the change must only _add_ masking, never remove existing behavior.

**Files:**

- Modify: `scripts/stderr_emit.py` (add `_CREDENTIAL_HEADER_RE`; extend `_redact_credentials`)
- Test: `tests/orchestrator/test_stderr_emit_redaction.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/orchestrator/test_stderr_emit_redaction.py`:

```python
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from stderr_emit import _redact_credentials  # noqa: E402


def test_url_credentials_still_redacted():
    # Existing behavior must not regress (test_open_or_append_pr.py depends on it).
    assert _redact_credentials("https://user:tok@github.com/x") == (
        "https://<redacted>@github.com/x"
    )


def test_circle_token_header_redacted():
    assert _redact_credentials("Circle-Token: abc123SECRET") == "Circle-Token: <redacted>"


def test_authorization_bearer_redacted():
    assert (
        _redact_credentials("Authorization: Bearer abc123SECRET")
        == "Authorization: Bearer <redacted>"
    )


def test_header_redaction_is_case_insensitive():
    assert _redact_credentials("circle-token: xyz") == "circle-token: <redacted>"


def test_header_redaction_idempotent():
    once = _redact_credentials("Circle-Token: abc123")
    assert _redact_credentials(once) == once


def test_plain_text_untouched():
    assert _redact_credentials("no secrets here") == "no secrets here"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_stderr_emit_redaction.py -v`
Expected: `test_circle_token_header_redacted` and `test_authorization_bearer_redacted` FAIL (token not masked); the URL and plain-text tests PASS.

- [ ] **Step 3: Implement the header redaction**

In `scripts/stderr_emit.py`, immediately after the existing `_CREDENTIAL_URL_RE` definition (line 40), add:

```python
# Header-form secrets (CCE-63): the URL regex above misses tokens sent as HTTP
# headers. Masks the value after `Circle-Token:` and after `Authorization: Bearer`,
# preserving the header name/scheme so logs stay legible. Case-insensitive.
_CREDENTIAL_HEADER_RE = re.compile(
    r"(Circle-Token\s*[:=]\s*|Authorization\s*[:=]\s*Bearer\s+)\S+",
    re.IGNORECASE,
)
```

Then replace the body of `_redact_credentials` (currently the single `return` at line 49) with:

```python
    text = _CREDENTIAL_URL_RE.sub(r"\1<redacted>@", text)
    text = _CREDENTIAL_HEADER_RE.sub(r"\1<redacted>", text)
    return text
```

Leave the docstring, but append one line to it before the closing `"""`:
``    CCE-63: also masks `Circle-Token:` / `Authorization: Bearer` header values.``

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/orchestrator/test_stderr_emit_redaction.py -v`
Expected: all 6 PASS.

- [ ] **Step 5: Guard against caller regression**

Run: `python3 -m pytest tests/orchestrator/test_open_or_append_pr.py -q`
Expected: PASS (the `"<redacted>" in err` assertion at ~line 779 still holds — URL redaction preserved).

- [ ] **Step 6: Commit**

```bash
git add scripts/stderr_emit.py tests/orchestrator/test_stderr_emit_redaction.py
git commit -m "feat(CCE-63): mask Circle-Token/Bearer header secrets in _redact_credentials"
```

---

### Task 2: Create the `scripts/build_poller.py` provider seam

The seam (spec §5.2, §5.3, AC3, AC4). Mirrors the `GhClient`/`FakeGhClient` DI pattern. `resolve_build_verdict` is the entry point `verify_runner` calls; `poll_circleci`/`map_circleci_status` are `NotImplementedError` stubs gated behind `UNVALIDATED_AGAINST_LIVE_HOST`.

**Files:**

- Create: `scripts/build_poller.py`
- Test: `tests/orchestrator/test_build_poller.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/orchestrator/test_build_poller.py`:

```python
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import build_poller  # noqa: E402


def test_flag_is_load_bearing_and_true_by_default():
    assert build_poller.UNVALIDATED_AGAINST_LIVE_HOST is True


def test_resolve_degrades_honestly_while_unvalidated():
    verdict, reasons = build_poller.resolve_build_verdict(
        "circleci", {"base_url": "https://x"}, {"owner": "o", "name": "r"}, 42
    )
    assert verdict["failed"] == []
    assert verdict["build_status"] != "success"  # non-promoting
    assert reasons == ["circleci_provider_modeled_but_unvalidated"]


def test_flag_flip_routes_into_poll_circleci(monkeypatch):
    # AC4: flipping the flag routes the fork into the unimplemented live poll.
    monkeypatch.setattr(build_poller, "UNVALIDATED_AGAINST_LIVE_HOST", False)
    with pytest.raises(NotImplementedError):
        build_poller.resolve_build_verdict(
            "circleci", {}, {"owner": "o", "name": "r"}, 42
        )


def test_poll_and_map_are_stubs():
    with pytest.raises(NotImplementedError):
        build_poller.poll_circleci(build_poller.FakeCircleCiClient(), {}, {}, 1)
    with pytest.raises(NotImplementedError):
        build_poller.map_circleci_status("on_hold")


def test_circleci_client_reads_token_from_env(monkeypatch):
    monkeypatch.setenv("CIRCLECI_TOKEN", "envtok")
    client = build_poller.CircleCiClient()
    assert client.auth_headers() == {"Circle-Token": "envtok"}


def test_circleci_client_missing_token_raises_typed_error(monkeypatch):
    monkeypatch.delenv("CIRCLECI_TOKEN", raising=False)
    client = build_poller.CircleCiClient()
    with pytest.raises(build_poller.CircleCiTokenMissing):
        client.auth_headers()


def test_token_never_appears_in_reason_strings():
    # The degrade reason is a fixed literal — never interpolates a token.
    _, reasons = build_poller.resolve_build_verdict("circleci", {}, {}, 1)
    assert all(
        r == "circleci_provider_modeled_but_unvalidated" or "token" not in r
        for r in reasons
    )


@pytest.mark.xfail(
    reason="publish-trigger is GitHub-only (orchestrator_runner.py workflow_run); "
    "provider-aware dispatch tracked by the CCE-63 sibling trigger ticket",
    strict=True,
)
def test_publish_trigger_is_provider_aware():
    # AC6: DESIRED future behavior — a circleci host's post-merge publish is
    # triggered via a CircleCI pipeline, not gh.workflow_run. Not built yet;
    # this strict-xfail flips to a hard failure the moment it is, forcing the
    # implementer to remove the marker.
    assert hasattr(build_poller, "trigger_circleci_publish")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_build_poller.py -v`
Expected: collection FAILS (`ModuleNotFoundError: build_poller`).

- [ ] **Step 3: Implement `scripts/build_poller.py`**

Create `scripts/build_poller.py`:

```python
"""CircleCI (and future non-GitHub) build-poll seam for the publish-verifier.

CCE-63 Option D': the GitHub publish-verify path stays in agents/publish-verifier.md
(the LLM-driven `gh` poll). This module is the Python seam for non-GitHub providers.

The real CircleCI poll is NOT implemented: there is no live CircleCI-publishing
host to validate the v2 API shape against (see the CCE-63 spec §10). While
UNVALIDATED_AGAINST_LIVE_HOST is True, resolve_build_verdict degrades honestly
(a non-promoting verdict + a fixed 'modeled but unvalidated' partial reason)
instead of polling. poll_circleci / map_circleci_status are explicit
NotImplementedError stubs, reached only once the flag is flipped.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

# Load-bearing honesty gate. While True, a non-github provider degrades instead
# of polling. Flip to False only once poll_circleci is implemented AND validated
# against a live CircleCI host (CCE-63 spec §10).
UNVALIDATED_AGAINST_LIVE_HOST = True

# Fixed-literal partial reason. Never interpolates a token/response/header.
PROVIDER_UNVALIDATED_REASON = "circleci_provider_modeled_but_unvalidated"
TOKEN_MISSING_REASON = "circleci_token_missing"

# Non-success sentinel build_status for the honest-degrade verdict. Any value
# other than "success" is non-promoting per verify_runner's gate.
UNVALIDATED_BUILD_STATUS = "circleci_unvalidated"


class CircleCiTokenMissing(RuntimeError):
    """Raised when a circleci poll is attempted with no CIRCLECI_TOKEN."""


class BuildPoller(Protocol):
    """Contract every provider build-poller satisfies.

    Input: publishing config block, repo {owner,name}, merged PR number.
    Output: a build_status in {'success','failure','timeout'}.
    """

    def build_status(
        self, publishing_config: dict, repo: dict, pr_number: int
    ) -> str: ...


@dataclass
class CircleCiClient:
    """Real CircleCI v2 client skeleton. Reads CIRCLECI_TOKEN from the env and
    sends it ONLY as a `Circle-Token` request header — never a URL userinfo
    segment or query param — so it cannot leak via a logged URL.

    The API-walking methods (pipeline -> workflow -> job) are NotImplementedError
    stubs pending a validated API (CCE-63 spec §10).
    """

    token: str | None = None

    def __post_init__(self) -> None:
        if self.token is None:
            self.token = os.environ.get("CIRCLECI_TOKEN")

    def auth_headers(self) -> dict[str, str]:
        if not self.token:
            raise CircleCiTokenMissing(TOKEN_MISSING_REASON)
        return {"Circle-Token": self.token}

    def pipeline_for_commit(self, repo: dict, revision: str) -> Any:
        raise NotImplementedError(
            "CircleCI v2 pipeline lookup unvalidated — see CCE-63 spec §10"
        )


class FakeCircleCiClient:
    """Test double mirroring CircleCiClient. Canned status for the eventual poll
    implementation; today it only proves flag-flip routing and token handling.
    """

    def __init__(
        self, *, token: str | None = "fake-token", status: str = "success"
    ) -> None:
        self.token = token
        self._status = status

    def auth_headers(self) -> dict[str, str]:
        if not self.token:
            raise CircleCiTokenMissing(TOKEN_MISSING_REASON)
        return {"Circle-Token": self.token}


def map_circleci_status(status: str) -> str:
    """Collapse a CircleCI workflow status onto {'success','failure','timeout'}.

    NOT IMPLEMENTED — the status vocabulary mapping (esp. `on_hold`) is an open
    decision (CCE-63 spec §10). Reached only once UNVALIDATED_AGAINST_LIVE_HOST
    is flipped.
    """
    raise NotImplementedError(
        "CircleCI status vocabulary mapping unvalidated — see CCE-63 spec §10"
    )


def poll_circleci(
    client: Any, publishing_config: dict, repo: dict, pr_number: int
) -> str:
    """Poll a CircleCI build to a terminal build_status.

    NOT IMPLEMENTED — no live CircleCI-publishing host exists to validate the v2
    API shape (CCE-63 spec §10). resolve_build_verdict never reaches here while
    UNVALIDATED_AGAINST_LIVE_HOST is True.
    """
    raise NotImplementedError("CircleCI poll unvalidated — see CCE-63 spec §10")


def resolve_build_verdict(
    provider: str, publishing_config: dict, repo: dict, pr_number: int
) -> tuple[dict, list[str]]:
    """Return (verdict, reasons) for a non-github publish provider.

    Verdict shape matches the publish-verifier contract:
    {'verified': [...], 'failed': [...], 'build_status': str}.

    While UNVALIDATED_AGAINST_LIVE_HOST is True, degrade honestly: a non-promoting
    verdict (build_status != 'success', failed empty) plus a fixed 'modeled but
    unvalidated' partial reason. No crash, no hang, no live call. Once the flag is
    flipped, route into poll_circleci (which raises until the real poll ships).
    """
    if UNVALIDATED_AGAINST_LIVE_HOST:
        return (
            {"verified": [], "failed": [], "build_status": UNVALIDATED_BUILD_STATUS},
            [PROVIDER_UNVALIDATED_REASON],
        )
    client = CircleCiClient()
    status = poll_circleci(client, publishing_config, repo, pr_number)
    return (
        {"verified": [], "failed": [], "build_status": map_circleci_status(status)},
        [],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/orchestrator/test_build_poller.py -v -rx`
Expected: all behavioral tests PASS; `test_publish_trigger_is_provider_aware` reports `XFAIL`.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_poller.py tests/orchestrator/test_build_poller.py
git commit -m "feat(CCE-63): add build_poller provider seam with honest circleci degrade + stubs"
```

---

### Task 3: Fork `verify_runner.run` on `ci_provider`

The one behavioral change to the verify path (spec §5.1, AC1, AC2, AC7). Wrap the existing `publish-verifier` dispatch in a provider guard; route non-github to the seam. Everything from the notifier dispatch onward is unchanged.

**Files:**

- Modify: `scripts/verify_runner.py` (add import; wrap lines 66–81 in a provider fork)
- Test: `tests/orchestrator/test_verify_runner.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestrator/test_verify_runner.py`. First add config constants near the top (after `SEEDED_STATE`):

```python
# CONFIG_YAML mirror (conftest) + an explicit ci_provider. Kept inline so the
# subprocess child sees a fully-valid config without importing conftest.
_BASE_CONFIG = """
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
  ci_provider: %s
notifications:
  slack: { enabled: false }
  email: { enabled: false }
"""
CONFIG_YAML_CIRCLECI = _BASE_CONFIG % "circleci"
CONFIG_YAML_GITHUB_EXPLICIT = _BASE_CONFIG % "github"
```

Then the tests:

```python
def test_verify_runner_explicit_github_promotes(tmp_path, init_host):
    """Explicit ci_provider: github behaves identically to absent (promotes)."""
    init_host(SEEDED_STATE, config_yaml=CONFIG_YAML_GITHUB_EXPLICIT)
    r = _invoke(tmp_path, FAKES_VERIFY_OK)
    assert r.returncode == 0, r.stderr


def test_verify_runner_circleci_degrades_without_promote(tmp_path, init_host):
    """ci_provider: circleci → honest degrade: rc=1, no promotion, fixed reason."""
    state_path = init_host(SEEDED_STATE, config_yaml=CONFIG_YAML_CIRCLECI)
    r = _invoke(tmp_path, FAKES_VERIFY_OK)  # notifier fake used; publish_verifier fake unread
    assert r.returncode == 1, r.stderr

    state = json.loads(state_path.read_text())
    assert "last_successful_run" not in state, "circleci degrade must not promote"

    sibling = state_path.parent / "current_run.json"
    reasons = json.loads(sibling.read_text())["current_run"].get("partial_reasons", [])
    assert "circleci_provider_modeled_but_unvalidated" in reasons


def test_verify_runner_circleci_notifies_with_sentinel(
    tmp_path, monkeypatch, init_host
):
    """AC7: the circleci branch skips publish-verifier and notifies with the
    non-failure sentinel build_status (sane, non-misleading)."""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import verify_runner

    importlib.reload(verify_runner)
    real = verify_runner.dispatch_validated
    seen: dict = {"names": [], "digest": None}

    def capture(name, inputs, *, dry_run_dir, cwd=None, **kw):
        seen["names"].append(name)
        if name == "notifier":
            seen["digest"] = inputs["digest"]
            return ({"slack_ok": True, "email_ok": True, "errors": []}, [])
        return real(name, inputs, dry_run_dir=dry_run_dir, cwd=cwd)

    monkeypatch.setattr(verify_runner, "dispatch_validated", capture)
    init_host(SEEDED_STATE, config_yaml=CONFIG_YAML_CIRCLECI)
    rc = verify_runner.run(tmp_path, 42, dry_run_dir=FAKES_VERIFY_OK)

    assert rc == 1
    assert "publish-verifier" not in seen["names"], "circleci must not hit the LLM verifier"
    assert "notifier" in seen["names"]
    assert seen["digest"]["build_status"] == "circleci_unvalidated"
    assert seen["digest"]["failed_urls"] == [], "must not render as a hard failure"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_verify_runner.py -v -k "circleci or explicit_github"`
Expected: `explicit_github` PASSES already (default path handles `github`); the two `circleci` tests FAIL (no fork yet — provider ignored, publish-verifier dispatched, `fake_publish_verifier.json` returns success → wrong rc / no reason / `publish-verifier` in names).

- [ ] **Step 3: Add the import**

In `scripts/verify_runner.py`, after the `from gh_client import GhClient` line (line 9), add:

```python
from build_poller import resolve_build_verdict  # noqa: E402
```

- [ ] **Step 4: Wrap the dispatch in a provider fork**

Replace the current block (lines 66–81), which is:

```python
    try:
        verdict, verify_reasons = dispatch_validated(
            "publish-verifier",
            {
                "merged_pr_number": pr_number,
                "changed_paths": changed_paths,
                "publishing_config": cfg.get("publishing", {}),
                "repo": repo,
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
        for r in verify_reasons:
            add_partial(state, r)
        if verdict is None:
            verdict = {"verified": [], "failed": [], "build_status": "verifier_invalid"}
```

with:

```python
    try:
        provider = (cfg.get("publishing") or {}).get("ci_provider") or "github"
        if provider == "github":
            verdict, verify_reasons = dispatch_validated(
                "publish-verifier",
                {
                    "merged_pr_number": pr_number,
                    "changed_paths": changed_paths,
                    "publishing_config": cfg.get("publishing", {}),
                    "repo": repo,
                },
                dry_run_dir=dry_run_dir,
                cwd=repo_root,
            )
            for r in verify_reasons:
                add_partial(state, r)
            if verdict is None:
                verdict = {
                    "verified": [],
                    "failed": [],
                    "build_status": "verifier_invalid",
                }
        else:
            # Non-github provider (e.g. circleci): honest degrade via the seam.
            # No LLM dispatch, no live poll while UNVALIDATED_AGAINST_LIVE_HOST.
            verdict, poll_reasons = resolve_build_verdict(
                provider, cfg.get("publishing", {}), repo, pr_number
            )
            for r in poll_reasons:
                add_partial(state, r)
```

Do NOT touch anything from the notifier dispatch (the `dispatch_validated("notifier", …)` call) onward — the promotion gate and `try/finally` stay exactly as they are.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_verify_runner.py -v`
Expected: all tests PASS, including the three new ones and the pre-existing promote/no-promote regression tests.

- [ ] **Step 6: Commit**

```bash
git add scripts/verify_runner.py tests/orchestrator/test_verify_runner.py
git commit -m "feat(CCE-63): fork verify_runner on ci_provider; route circleci to honest degrade"
```

---

### Task 4: Config / docs scaffolding (schema + agent inputs + setup guide)

Documentation parity (spec §5.6, AC8). The `ci_provider` enum already exists; tighten its description, add `ci_provider` to the agent Inputs, and reserve `CIRCLECI_TOKEN` in the setup guide. **The host fixture (§5.6) is deferred** per the spec §10 open decision — shipping a `ci_provider: circleci` onboarding fixture would read as end-to-end readiness before the publish-_trigger_ seam exists. It moves to the sibling trigger ticket. This keeps the PR honest and tight.

**Files:**

- Modify: `templates/config.schema.json` (`ci_provider` description)
- Modify: `agents/publish-verifier.md` (Inputs list)
- Modify: `docs/site-src/setup-guide.md` (CIRCLECI_TOKEN reservation)
- Test: `tests/schemas/test_config_schema.py` (add an assertion the schema still validates a circleci config)

- [ ] **Step 1: Write the test**

In `tests/schemas/test_config_schema.py`, add a test that a `ci_provider: circleci` config validates against the schema (guards the enum and that the description edit didn't break the schema JSON).

> First read the top of `tests/schemas/test_config_schema.py` to reuse its existing schema loader and validator (it already loads `templates/config.schema.json`). Mirror the smallest valid config already used in that file and add `"ci_provider": "circleci"` to its `publishing` block. The assertion is simply that validation does not raise. Illustrative shape (adapt to the file's real helper/minimal-config):

```python
def test_ci_provider_circleci_validates():
    cfg = _minimal_valid_config()          # reuse the file's existing helper
    cfg["publishing"]["ci_provider"] = "circleci"
    _validate(cfg)                         # reuse the file's existing validator; must not raise
```

- [ ] **Step 2: Run test**

Run: `python3 -m pytest tests/schemas/test_config_schema.py -v -k circleci`
Expected: PASS (the enum already permits `circleci`). A JSON parse error here means the schema edit in Step 3 was malformed — fix before continuing. This test locks the enum against future accidental removal.

- [ ] **Step 3: Tighten the schema description**

In `templates/config.schema.json`, replace the `ci_provider` `description` string value (currently ending "…only `github` is wired through scripts/verify_runner.py.") with:

```
"Which CI provider runs the docs publish workflow. Default `github` (no field present). `circleci` is modeled but UNVALIDATED against a live host: scripts/verify_runner.py forks on this field and degrades honestly (a non-promoting 'modeled but unvalidated' result) rather than polling. Only `github` is end-to-end wired. See CCE-63."
```

Keep it a single JSON string on one line (escape nothing beyond what JSON already requires; there are no double-quotes inside).

- [ ] **Step 4: Add `ci_provider` to the agent Inputs**

In `agents/publish-verifier.md`, in the `## Inputs` list, after the `publishing_config` bullet, add:

```
- `ci_provider`: optional; `github` (default) or `circleci`. Only `github` reaches this agent — `circleci` is handled Python-side in scripts/build_poller.py (CCE-63). Do not branch on it here.
```

Do NOT modify the `## Output schema (canonical)` block or the `## Procedure` (github `gh run list` prose) — `tests/agents/test_schema_md_sync.py` locks the schema block and the github path must stay byte-for-byte.

- [ ] **Step 5: Reserve CIRCLECI_TOKEN in the setup guide**

In `docs/site-src/setup-guide.md`, first read the Secrets table (§2.4) and the reference-appendix table to learn their exact column layout. Add to **each** a `CIRCLECI_TOKEN` row carrying these three facts, formatted to match that table's columns:

- Name: `CIRCLECI_TOKEN`
- When required: only if `publishing.ci_provider: circleci`
- Note: "Reserved / not yet wired. CircleCI publish verification is modeled but unvalidated (CCE-63); no action needed for `github` hosts."

It is a Secret, not a Variable.

- [ ] **Step 6: Verify docs + schema-sync tests stay green**

Run: `python3 -m pytest tests/schemas/test_config_schema.py tests/agents/test_schema_md_sync.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add templates/config.schema.json agents/publish-verifier.md docs/site-src/setup-guide.md tests/schemas/test_config_schema.py
git commit -m "docs(CCE-63): document ci_provider circleci as modeled-but-unvalidated; reserve CIRCLECI_TOKEN"
```

---

### Task 5: Full-suite integration + spec-coverage sweep

- [ ] **Step 1: Run the entire suite**

Run: `python3 -m pytest`
Expected: all pass (prior baseline was 1134 passed, 3 skipped) + the new tests; `test_publish_trigger_is_provider_aware` shows as `xfailed`. No `xpassed`. Investigate any failure before proceeding.

- [ ] **Step 2: Confirm the trigger-gap fence is live**

Run: `python3 -m pytest tests/orchestrator/test_build_poller.py::test_publish_trigger_is_provider_aware -v -rx`
Expected: `XFAIL` (not `XPASS`). This proves the sibling-ticket gap is documented and will alarm if silently closed.

- [ ] **Step 3: Commit any residual (if a test needed adjustment)**

```bash
git add -A
git commit -m "test(CCE-63): full-suite green with circleci provider seam" || echo "nothing to commit"
```

---

## Self-Review

**Spec coverage (each AC → task):**

- AC1 (fork resolves `ci_provider or github`, byte-for-byte github) → Task 3 (fork + `explicit_github` test + preserved regression tests).
- AC2 (circleci → clean partial, non-promoting, no crash) → Task 3 `circleci_degrades_without_promote`.
- AC3 (`build_poller.py` with protocol/client/fake + stubs) → Task 2.
- AC4 (flag load-bearing; flip → `poll_circleci`) → Task 2 `flag_flip_routes_into_poll_circleci`.
- AC5 (token never in reasons; header redaction; gh path intact) → Task 1 + Task 2 `token_never_appears_in_reason_strings`.
- AC6 (trigger-gap xfail referencing sibling ticket) → Task 2 `test_publish_trigger_is_provider_aware` (strict xfail).
- AC7 (sane non-misleading circleci notification) → Task 3 `circleci_notifies_with_sentinel`.
- AC8 (config/docs/fixture scaffolding) → Task 4 (docs+schema land; **fixture explicitly deferred per §10 — call it out in the PR body**).
- AC9 (no behavioral tests for poll/map stubs) → Task 2 asserts only `NotImplementedError`; no canned-status assertions.

**Placeholder scan:** every code step shows complete code. Three steps intentionally instruct the engineer to match an existing in-file pattern (Task 4 Step 1 schema-test helper, Task 4 Step 5 setup-guide table layout, Task 1 Step 3 docstring line) — each states the exact required outcome, so they are precise instructions, not placeholders.

**Type consistency:** `resolve_build_verdict(provider, publishing_config, repo, pr_number) -> (dict, list[str])` defined in Task 2, called with matching args in Task 3. Verdict keys (`verified`/`failed`/`build_status`) match `verify_runner`'s consumers. `UNVALIDATED_BUILD_STATUS = "circleci_unvalidated"` is the exact literal asserted in Task 3's notifier test. `PROVIDER_UNVALIDATED_REASON = "circleci_provider_modeled_but_unvalidated"` matches the reason asserted in Task 3's degrade test. `CircleCiTokenMissing` defined in Task 2, referenced only there.

**Deviation from spec, flagged:** AC8's host fixture is deferred (spec §10 sanctioned this as an open call; deferring avoids a false end-to-end-readiness signal before the trigger seam exists). Everything else lands as specified.

---

## Execution note

The operator pre-selected execution mode ("use subagent-driven-development if appropriate and workflows"). Tasks 1, 2, and 4 are independent; Task 3 depends on Task 2. Execute Task 2 before Task 3; the rest may run in any order. Each task is self-contained TDD with a real `pytest` gate — suitable for either a per-task implementer subagent (with the CLAUDE.md fidelity ladder: Tier-0 git delta + Tier-1 `pytest`) or inline execution.
