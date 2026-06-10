# CCE-101 Auto-Merge Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** docs-agent PRs squash-merge themselves when the run is non-partial with zero fact-checker warnings; auto-merge defaults ON (absent config key = auto) with a setup-time opt-out question.

**Architecture:** Runner-side poll-and-merge. A new `_maybe_auto_merge` in `scripts/orchestrator_runner.py` runs after the PR number is known: eligibility short-circuits → bounded check-poll (`gh pr checks`) → `gh pr merge --squash --delete-branch` → explicit `gh workflow run <build_workflow>` dispatch (a `GITHUB_TOKEN` merge does not fire `on: push` workflows, so without the dispatch the site never redeploys). All outcomes are `info_only=True` reasons; every failure degrades to today's behavior (PR stays open).

**Tech Stack:** Python 3.11 stdlib + `gh` CLI (wrapped by `scripts/gh_client.py`), pytest, jsonschema, MkDocs.

**Spec:** `docs/superpowers/specs/2026-06-10-cce101-merge-gate-design.md` (approved 2026-06-10).

**Branch:** all work happens on `feat/CCE-101-auto-merge-gate` (already created; spec committed at `16ea5be`).

---

## Codebase primer (read first)

- Tests run from the repo root: `python3 -m pytest tests/ -x -q`. Orchestrator tests import via `sys.path.insert(0, .../scripts)` then `import orchestrator_runner as orun`.
- `scripts/gh_client.py` is the ONLY place `gh` is invoked. `GhClient` methods return `GhResult(ok, value, error)`. `FakeGhClient` (same file) is the test double — constructor takes canned `GhResult`s per method and records every call in `self.calls` as `(method_name, args_tuple)`.
- `tests/orchestrator/test_auto_close_superseded.py` is the closest existing pattern (D2 auto-close): pure-function tests of an `orun._helper` driven by `FakeGhClient`. Mirror its style.
- `tests/gh/test_gh_client.py` tests the real client by monkeypatching `gh_client.subprocess.run` with `_fake_run(stdout=..., stderr=..., returncode=..., raise_exc=...)`.
- CCE-109 time budget: `run_pipeline` computes `clock = now_monotonic or time.monotonic`, `deadline = clock() + budget if budget > 0 else None` (`orchestrator_runner.py:1199-1201`). Both are in scope at the call site we extend.
- `add_partial(state, reason, info_only=True)` records a reason WITHOUT flipping `current_run.partial`.
- `gh pr checks` exit codes are DATA, not errors: 0 = all green, 8 = pending, 1 = failing OR "no checks reported". Never run it through `_run_json` (which uses `check=True`).
- Check-state vocabulary (CLAUDE.md / CCE-83): JSON gives `name`/`state`/`bucket`. Red = `state=='FAILURE' || bucket=='fail'`; green = `state=='SUCCESS' || bucket=='pass'`. NEVER `statusCheckRollup`/`conclusion`.

## File structure

| File                                                                                                 | Change                                                                                                                   |
| ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `templates/config.schema.json`                                                                       | add top-level `merge` block                                                                                              |
| `scripts/gh_client.py`                                                                               | `GhClient.pr_checks/pr_merge/workflow_run`; same on `FakeGhClient` (pr_checks accepts a sequence)                        |
| `scripts/orchestrator_runner.py`                                                                     | `DEFAULT_MERGE_*` constants, `resolve_merge_settings`, `_maybe_auto_merge`, call-site wiring + `digest["merge_outcome"]` |
| `agents/notifier.md`                                                                                 | digest contract gains `merge_outcome`                                                                                    |
| `skills/engineering-docs-agent/SKILL.md`                                                             | PR-handling section gains the auto-merge step                                                                            |
| `skills/engineering-docs-agent-setup/SKILL.md`                                                       | step-3 question + explicit `merge:` block write                                                                          |
| `CLAUDE.md`                                                                                          | rewrite the "do NOT auto-merge" bullet into the CCE-101 decision record                                                  |
| `CHANGELOG.md`                                                                                       | behavior-change entry                                                                                                    |
| `docs/site-src/operations/docs-agent-nightly.md`, `docs/site-src/operations/nightly-cron-cadence.md` | merge-gate subsection; operator-promotion content shrinks to the left-open case                                          |
| `tests/schemas/test_config_schema.py`                                                                | merge-block validation cases                                                                                             |
| `tests/gh/test_gh_client.py`                                                                         | pr_checks/pr_merge/workflow_run cases                                                                                    |
| `tests/orchestrator/test_auto_merge.py`                                                              | NEW — eligibility, poll-loop, merge, dispatch, wiring                                                                    |

---

### Task 1: Config schema `merge` block

**Files:**

- Modify: `templates/config.schema.json` (after the `run` block, ~line 178)
- Test: `tests/schemas/test_config_schema.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/schemas/test_config_schema.py` (reuse the file's existing imports/SCHEMA constant; `_base` mirrors `test_minimal_valid`'s config):

```python
_BASE_FOR_MERGE = """
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/core }
sources: { git: { host: github } }
lint: { tier1: default, tier2: {}, tier3: {} }
publishing:
  base_url: https://x
  build_workflow: deploy.yml
  url_map_rule: standard
notifications: {}
"""


def test_merge_block_valid():
    cfg = yaml.safe_load(
        _BASE_FOR_MERGE
        + """
merge:
  policy: auto
  checks_grace_seconds: 120
  checks_timeout_seconds: 900
"""
    )
    validate(cfg, SCHEMA)


def test_merge_policy_manual_valid():
    cfg = yaml.safe_load(_BASE_FOR_MERGE + "\nmerge: { policy: manual }\n")
    validate(cfg, SCHEMA)


def test_merge_block_absent_valid():
    """CCE-101: merge is optional — absent block means policy auto."""
    cfg = yaml.safe_load(_BASE_FOR_MERGE)
    validate(cfg, SCHEMA)


def test_merge_unknown_policy_rejected():
    cfg = yaml.safe_load(_BASE_FOR_MERGE + "\nmerge: { policy: rebase }\n")
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


def test_merge_unknown_key_rejected():
    cfg = yaml.safe_load(_BASE_FOR_MERGE + "\nmerge: { method: squash }\n")
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


def test_merge_negative_grace_rejected():
    cfg = yaml.safe_load(_BASE_FOR_MERGE + "\nmerge: { checks_grace_seconds: -1 }\n")
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/schemas/test_config_schema.py -q`
Expected: `test_merge_unknown_policy_rejected`, `test_merge_unknown_key_rejected`, `test_merge_negative_grace_rejected` FAIL (`DID NOT RAISE`) — the schema accepts anything today. The three `_valid` tests pass vacuously.

- [ ] **Step 3: Add the schema block** — in `templates/config.schema.json`, inside top-level `properties`, after the `"run"` block:

```json
"merge": {
  "type": "object",
  "additionalProperties": false,
  "$comment": "CCE-101: docs-agent PR merge gate. Absent block (or absent policy) = auto.",
  "properties": {
    "policy": {
      "type": "string",
      "enum": ["auto", "manual"],
      "description": "auto (default when absent): squash-merge a fully-green non-partial run's PR. manual: every PR stays open for operator review."
    },
    "checks_grace_seconds": {
      "type": "integer",
      "minimum": 0,
      "description": "Wait for host CI checks to register before merging without them. Default 120."
    },
    "checks_timeout_seconds": {
      "type": "integer",
      "minimum": 0,
      "description": "Max wait for registered checks to settle. Default 900."
    }
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/schemas/ tests/state_io/ -q`
Expected: all PASS (state_io included because `load_config_validated` consumes this schema).

- [ ] **Step 5: Commit**

```bash
git add templates/config.schema.json tests/schemas/test_config_schema.py
git commit -m "feat(CCE-101): merge-gate config schema block (policy/grace/timeout)"
```

---

### Task 2: `resolve_merge_settings`

**Files:**

- Modify: `scripts/orchestrator_runner.py` (constants near `DEFAULT_TIME_BUDGET_SECONDS`; function next to `resolve_time_budget`, ~line 313)
- Test: Create `tests/orchestrator/test_auto_merge.py`

- [ ] **Step 1: Write the failing tests** — create `tests/orchestrator/test_auto_merge.py`:

```python
"""CCE-101: auto-merge gate tests.

`resolve_merge_settings` + `_maybe_auto_merge` — the runner-side
poll-and-merge that lands fully-green non-partial docs-agent PRs
without an operator. All auto-merge reasons are info_only=True;
every failure degrades to leaving the PR open (pre-CCE-101 behavior).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402
from gh_client import FakeGhClient, GhResult  # noqa: E402


def test_resolve_merge_settings_absent_block_defaults_to_auto():
    """CCE-101 contract: absent key = auto-merge ON."""
    s = orun.resolve_merge_settings({})
    assert s == {
        "policy": "auto",
        "checks_grace_seconds": 120,
        "checks_timeout_seconds": 900,
    }


def test_resolve_merge_settings_absent_policy_defaults_to_auto():
    s = orun.resolve_merge_settings({"merge": {"checks_grace_seconds": 5}})
    assert s["policy"] == "auto"
    assert s["checks_grace_seconds"] == 5
    assert s["checks_timeout_seconds"] == 900


def test_resolve_merge_settings_manual_respected():
    s = orun.resolve_merge_settings({"merge": {"policy": "manual"}})
    assert s["policy"] == "manual"


def test_resolve_merge_settings_non_dict_block_falls_back():
    s = orun.resolve_merge_settings({"merge": "auto"})
    assert s["policy"] == "auto"
    assert s["checks_grace_seconds"] == 120
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_auto_merge.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'resolve_merge_settings'`.

- [ ] **Step 3: Implement** — in `scripts/orchestrator_runner.py`, next to `resolve_time_budget`:

```python
DEFAULT_MERGE_POLICY = "auto"
DEFAULT_CHECKS_GRACE_SECONDS = 120
DEFAULT_CHECKS_TIMEOUT_SECONDS = 900
_CHECKS_POLL_INTERVAL_SECONDS = 15.0


def resolve_merge_settings(config: dict) -> dict:
    """CCE-101: resolve the merge-gate settings with default-ON semantics.

    Absent `merge:` block, absent `policy`, or a malformed (non-dict)
    block all resolve to auto — existing hosts flip on at tag pickup
    with zero config edits. Setup writes an explicit value for new hosts.
    """
    cfg = config.get("merge")
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "policy": cfg.get("policy", DEFAULT_MERGE_POLICY),
        "checks_grace_seconds": cfg.get(
            "checks_grace_seconds", DEFAULT_CHECKS_GRACE_SECONDS
        ),
        "checks_timeout_seconds": cfg.get(
            "checks_timeout_seconds", DEFAULT_CHECKS_TIMEOUT_SECONDS
        ),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_auto_merge.py -q`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_auto_merge.py
git commit -m "feat(CCE-101): resolve_merge_settings with default-on semantics"
```

---

### Task 3: `GhClient.pr_checks`

**Files:**

- Modify: `scripts/gh_client.py` (after `pr_view_commits`)
- Test: `tests/gh/test_gh_client.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/gh/test_gh_client.py` (reuse its `_fake_run` helper):

```python
def test_pr_checks_all_green(monkeypatch, tmp_path):
    from gh_client import GhClient

    stdout = json.dumps(
        [{"name": "pytest", "state": "SUCCESS", "bucket": "pass"}]
    )
    monkeypatch.setattr("gh_client.subprocess.run", _fake_run(stdout=stdout))
    r = GhClient(tmp_path).pr_checks(7)
    assert r.ok
    assert r.value[0]["name"] == "pytest"


def test_pr_checks_pending_exit_8_is_data_not_error(monkeypatch, tmp_path):
    """gh pr checks exits 8 while checks are pending; the JSON on stdout
    is still the payload. Treat it as data."""
    from gh_client import GhClient

    stdout = json.dumps(
        [{"name": "pytest", "state": "PENDING", "bucket": "pending"}]
    )
    monkeypatch.setattr(
        "gh_client.subprocess.run", _fake_run(stdout=stdout, returncode=8)
    )
    r = GhClient(tmp_path).pr_checks(7)
    assert r.ok
    assert r.value[0]["bucket"] == "pending"


def test_pr_checks_no_checks_reported_is_empty_list(monkeypatch, tmp_path):
    """No-App-token hosts: docs-agent PRs trigger no CI at all. gh exits
    non-zero with 'no checks reported' — that is the zero-checks case,
    not an error."""
    from gh_client import GhClient

    monkeypatch.setattr(
        "gh_client.subprocess.run",
        _fake_run(stderr="no checks reported on the 'x' branch", returncode=1),
    )
    r = GhClient(tmp_path).pr_checks(7)
    assert r.ok
    assert r.value == []


def test_pr_checks_gh_not_installed(monkeypatch, tmp_path):
    from gh_client import GhClient

    monkeypatch.setattr(
        "gh_client.subprocess.run", _fake_run(raise_exc=FileNotFoundError())
    )
    r = GhClient(tmp_path).pr_checks(7)
    assert not r.ok
    assert r.error == "gh_not_installed"


def test_pr_checks_garbage_nonzero_is_error(monkeypatch, tmp_path):
    from gh_client import GhClient

    monkeypatch.setattr(
        "gh_client.subprocess.run",
        _fake_run(stdout="boom", stderr="server error", returncode=1),
    )
    r = GhClient(tmp_path).pr_checks(7)
    assert not r.ok
    assert r.error.startswith("gh_pr_checks_failed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/gh/test_gh_client.py -q -k pr_checks`
Expected: FAIL with `AttributeError: 'GhClient' object has no attribute 'pr_checks'`.

- [ ] **Step 3: Implement** — in `scripts/gh_client.py`, after `pr_view_commits`:

```python
    def pr_checks(self, pr_number: int) -> GhResult:
        """CI check states for a PR, parsed per the CCE-83 vocabulary
        (name/state/bucket — never statusCheckRollup/conclusion).

        CCE-101: `gh pr checks` exit codes are data, not errors —
        0 = all green, 8 = pending, 1 = failing OR "no checks reported".
        Deliberately NOT routed through _run_json (check=True would turn
        a pending poll into an exception). "No checks reported" maps to
        ok-with-[] so the caller's zero-checks grace path can decide.
        """
        try:
            r = subprocess.run(
                ["gh", "pr", "checks", str(pr_number), "--json", "name,state,bucket"],
                cwd=self._cwd,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return GhResult(ok=False, error="gh_not_installed")
        if "no checks reported" in (r.stderr or "").lower():
            return GhResult(ok=True, value=[])
        try:
            data = json.loads(r.stdout or "null")
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            return GhResult(ok=True, value=data)
        return GhResult(
            ok=False,
            error=f"gh_pr_checks_failed: rc={r.returncode} {(r.stderr or '')[:200]}",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/gh/test_gh_client.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/gh_client.py tests/gh/test_gh_client.py
git commit -m "feat(CCE-101): GhClient.pr_checks — exit codes are data, no-checks is []"
```

---

### Task 4: `GhClient.pr_merge` + `GhClient.workflow_run`

**Files:**

- Modify: `scripts/gh_client.py` (after `pr_checks`)
- Test: `tests/gh/test_gh_client.py`

- [ ] **Step 1: Write the failing tests** — append:

```python
def test_pr_merge_success_builds_squash_delete_argv(monkeypatch, tmp_path):
    from gh_client import GhClient

    seen = {}

    def _capture(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("gh_client.subprocess.run", _capture)
    r = GhClient(tmp_path).pr_merge(7)
    assert r.ok and r.value == 7
    assert seen["cmd"] == [
        "gh", "pr", "merge", "7", "--squash", "--delete-branch",
    ]


def test_pr_merge_failure_surfaces_stderr(monkeypatch, tmp_path):
    from gh_client import GhClient

    monkeypatch.setattr(
        "gh_client.subprocess.run",
        _fake_run(stderr="branch protection", returncode=1),
    )
    r = GhClient(tmp_path).pr_merge(7)
    assert not r.ok
    assert r.error.startswith("gh_pr_merge_failed")
    assert "branch protection" in r.error


def test_workflow_run_dispatches_on_main(monkeypatch, tmp_path):
    from gh_client import GhClient

    seen = {}

    def _capture(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("gh_client.subprocess.run", _capture)
    r = GhClient(tmp_path).workflow_run("docs-agent-pages.yml")
    assert r.ok
    assert seen["cmd"] == [
        "gh", "workflow", "run", "docs-agent-pages.yml", "--ref", "main",
    ]


def test_workflow_run_failure(monkeypatch, tmp_path):
    from gh_client import GhClient

    monkeypatch.setattr(
        "gh_client.subprocess.run", _fake_run(stderr="404", returncode=1)
    )
    r = GhClient(tmp_path).workflow_run("docs-agent-pages.yml")
    assert not r.ok
    assert r.error.startswith("gh_workflow_run_failed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/gh/test_gh_client.py -q -k "pr_merge or workflow_run"`
Expected: FAIL with `AttributeError` (no `pr_merge` / `workflow_run`).

- [ ] **Step 3: Implement** — in `scripts/gh_client.py`:

```python
    def pr_merge(self, pr_number: int) -> GhResult:
        """CCE-101: squash-merge + delete branch. Method is fixed by spec
        (not configurable). Failure is the caller's leave-open fallback."""
        try:
            r = subprocess.run(
                ["gh", "pr", "merge", str(pr_number), "--squash", "--delete-branch"],
                cwd=self._cwd,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return GhResult(ok=False, error="gh_not_installed")
        if r.returncode != 0:
            return GhResult(
                ok=False, error=f"gh_pr_merge_failed: {(r.stderr or '')[:200]}"
            )
        return GhResult(ok=True, value=pr_number)

    def workflow_run(self, workflow_file: str) -> GhResult:
        """CCE-101: explicit pages-deploy dispatch after an auto-merge.

        A merge pushed with GITHUB_TOKEN does not fire `on: push` workflows
        (GitHub recursion suppression), so the docs would land in main with
        the site never redeploying. workflow_dispatch is exempt from the
        suppression, so this fires even under GITHUB_TOKEN.
        """
        try:
            r = subprocess.run(
                ["gh", "workflow", "run", workflow_file, "--ref", "main"],
                cwd=self._cwd,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return GhResult(ok=False, error="gh_not_installed")
        if r.returncode != 0:
            return GhResult(
                ok=False, error=f"gh_workflow_run_failed: {(r.stderr or '')[:200]}"
            )
        return GhResult(ok=True, value=workflow_file)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/gh/ -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/gh_client.py tests/gh/test_gh_client.py
git commit -m "feat(CCE-101): GhClient.pr_merge + workflow_run"
```

---

### Task 5: `FakeGhClient` extensions (pr_checks sequences)

**Files:**

- Modify: `scripts/gh_client.py` (`FakeGhClient`)
- Test: `tests/gh/test_gh_client.py`

- [ ] **Step 1: Write the failing test** — append:

```python
def test_fake_gh_client_pr_checks_sequence_pops_then_repeats_last():
    """Poll-loop tests feed a pending→green sequence; the last element
    repeats so a loop that polls extra times doesn't IndexError."""
    from gh_client import FakeGhClient, GhResult

    pending = GhResult(ok=True, value=[{"name": "ci", "state": "PENDING", "bucket": "pending"}])
    green = GhResult(ok=True, value=[{"name": "ci", "state": "SUCCESS", "bucket": "pass"}])
    fake = FakeGhClient(pr_checks=[pending, green])
    assert fake.pr_checks(1).value[0]["bucket"] == "pending"
    assert fake.pr_checks(1).value[0]["bucket"] == "pass"
    assert fake.pr_checks(1).value[0]["bucket"] == "pass"  # last repeats
    assert fake.calls.count(("pr_checks", (1,))) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/gh/test_gh_client.py -q -k fake_gh_client_pr_checks`
Expected: FAIL — `FakeGhClient.__init__` rejects `pr_checks` (unexpected keyword).

- [ ] **Step 3: Implement** — replace `FakeGhClient.__init__` with the version below (existing kwargs preserved, three added), and append the three methods after `pr_close`:

```python
    def __init__(
        self,
        *,
        pr_view_files: GhResult | None = None,
        pr_list_for_branch: GhResult | None = None,
        pr_create: GhResult | None = None,
        pr_list_docs_agent_open: GhResult | None = None,
        pr_view_commits: GhResult | None = None,
        pr_close: GhResult | None = None,
        pr_checks: GhResult | list[GhResult] | None = None,
        pr_merge: GhResult | None = None,
        workflow_run: GhResult | None = None,
    ) -> None:
        # CCE-101: pr_checks accepts a sequence so poll-loop tests can
        # model pending→green transitions; the last element repeats.
        self._pr_checks_seq = list(pr_checks) if isinstance(pr_checks, list) else None
        self._canned = {
            "pr_view_files": pr_view_files,
            "pr_list_for_branch": pr_list_for_branch,
            "pr_create": pr_create,
            "pr_list_docs_agent_open": pr_list_docs_agent_open,
            "pr_view_commits": pr_view_commits,
            "pr_close": pr_close,
            "pr_checks": pr_checks if not isinstance(pr_checks, list) else None,
            "pr_merge": pr_merge,
            "workflow_run": workflow_run,
        }
        self.calls: list[tuple[str, tuple]] = []

    def pr_checks(self, pr_number: int) -> GhResult:
        self.calls.append(("pr_checks", (pr_number,)))
        if self._pr_checks_seq is not None:
            if len(self._pr_checks_seq) > 1:
                return self._pr_checks_seq.pop(0)
            return self._pr_checks_seq[0]
        return self._canned["pr_checks"] or GhResult(ok=True, value=[])

    def pr_merge(self, pr_number: int) -> GhResult:
        self.calls.append(("pr_merge", (pr_number,)))
        return self._canned["pr_merge"] or GhResult(ok=True, value=pr_number)

    def workflow_run(self, workflow_file: str) -> GhResult:
        self.calls.append(("workflow_run", (workflow_file,)))
        return self._canned["workflow_run"] or GhResult(ok=True, value=workflow_file)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/gh/ -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/gh_client.py tests/gh/test_gh_client.py
git commit -m "test(CCE-101): FakeGhClient pr_checks sequences, pr_merge, workflow_run"
```

---

### Task 6: `_maybe_auto_merge` — eligibility short-circuits

**Files:**

- Modify: `scripts/orchestrator_runner.py` (after `_auto_close_superseded_docs_agent_prs`, ~line 2540)
- Test: `tests/orchestrator/test_auto_merge.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/orchestrator/test_auto_merge.py`:

```python
class FakeClock:
    """Injectable monotonic clock; sleep() advances it so poll loops
    terminate instantly in tests."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def _settings(**over):
    s = {"policy": "auto", "checks_grace_seconds": 120, "checks_timeout_seconds": 900}
    s.update(over)
    return s


def _bot_author():
    return {
        "name": "engineering-docs-agent[bot]",
        "login": "engineering-docs-agent-bot",
        "email": "engineering-docs-agent@users.noreply.github.com",
    }


def _run(gh, *, partial=False, fact_warnings=None, settings=None,
         build_workflow="docs-agent-pages.yml", deadline=None, clock=None):
    clock = clock or FakeClock()
    return orun._maybe_auto_merge(
        gh,
        pr_number=7,
        partial=partial,
        fact_warnings=fact_warnings or [],
        merge_settings=settings or _settings(),
        build_workflow=build_workflow,
        deadline=deadline,
        clock=clock,
        sleep=clock.sleep,
    )


def test_policy_manual_short_circuits_without_gh_calls():
    gh = FakeGhClient()
    outcome, reasons = _run(gh, settings=_settings(policy="manual"))
    assert outcome == {"merged": False, "reason": "policy_manual"}
    assert reasons == []
    assert gh.calls == []


def test_partial_run_skips_with_info_reason():
    gh = FakeGhClient()
    outcome, reasons = _run(gh, partial=True)
    assert outcome == {"merged": False, "reason": "partial_run"}
    assert reasons == [("auto_merge_skipped: partial_run", True)]
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_fact_warnings_demote_to_manual_review():
    """CCE-110 guard: under auto-merge nobody reads the PR, so a
    contradiction warning must withhold the merge (not the content)."""
    gh = FakeGhClient()
    outcome, reasons = _run(gh, fact_warnings=["page.md: contradicts source"])
    assert outcome["reason"] == "fact_check_warnings"
    assert reasons[0][0].startswith("auto_merge_skipped: fact_check_warnings")
    assert reasons[0][1] is True
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_human_edited_pr_is_never_merged():
    gh = FakeGhClient(
        pr_view_commits=GhResult(
            ok=True,
            value=[{"authors": [_bot_author()]},
                   {"authors": [{"name": "Theo", "login": "theoju", "email": "t@x.com"}]}],
        ),
    )
    outcome, reasons = _run(gh)
    assert outcome["reason"] == "human_edited"
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_commits_lookup_failure_skips_conservatively():
    gh = FakeGhClient(pr_view_commits=GhResult(ok=False, error="gh_failed: 500"))
    outcome, reasons = _run(gh)
    assert outcome["reason"] == "commits_lookup_failed"
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_exhausted_time_budget_skips_before_polling():
    gh = FakeGhClient(pr_view_commits=GhResult(ok=True, value=[{"authors": [_bot_author()]}]))
    clock = FakeClock(t=1000.0)
    # deadline already closer than the grace window
    outcome, reasons = _run(gh, deadline=1060.0, clock=clock)
    assert outcome["reason"] == "time_budget"
    assert not [c for c in gh.calls if c[0] == "pr_checks"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_auto_merge.py -q`
Expected: new tests FAIL with `AttributeError: ... no attribute '_maybe_auto_merge'`; Task-2 tests still pass.

- [ ] **Step 3: Implement the eligibility slice** — in `scripts/orchestrator_runner.py` after `_auto_close_superseded_docs_agent_prs`. (The poll loop lands in Task 7; for now end the function with `raise NotImplementedError("poll loop: Task 7")` after the budget gate so only eligibility tests pass.)

```python
def _maybe_auto_merge(
    gh: "GhClient",
    *,
    pr_number: int,
    partial: bool,
    fact_warnings: list[str],
    merge_settings: dict,
    build_workflow: str | None,
    deadline: float | None,
    clock: Callable[[], float],
    sleep: Callable[[float], None] = time.sleep,
    bot_author_names: tuple[str, ...] = _DOCS_AGENT_BOT_AUTHOR_NAMES,
    bot_author_emails: tuple[str, ...] = _DOCS_AGENT_BOT_AUTHOR_EMAILS,
) -> tuple[dict, list[tuple[str, bool]]]:
    """CCE-101: squash-merge the docs-agent PR when the run earned it.

    Eligibility (cheapest first): policy auto → non-partial → zero
    fact-checker warnings → no human commits on the PR → enough CCE-109
    budget left to wait out the check-grace window. Then a bounded poll
    of `gh pr checks`; zero registered checks after the grace window
    means a no-App-token host (the in-run validation is the gate there).

    Returns (merge_outcome, reasons): merge_outcome is the digest's
    ``{"merged": bool, "reason": str | None}``; reasons feed the caller's
    add_partial loop and are ALL info_only=True — merge automation is
    hygiene (mirrors D2 auto-close), it never flips the run to partial.
    """

    def skip(key: str, detail: str = "") -> tuple[dict, list[tuple[str, bool]]]:
        msg = f"auto_merge_skipped: {key}"
        if detail:
            msg += f": {detail}"
        return {"merged": False, "reason": key}, [(msg, True)]

    if merge_settings.get("policy") != "auto":
        # The configured normal path for a manual host — no reason entry,
        # the digest's merge_outcome line carries it.
        return {"merged": False, "reason": "policy_manual"}, []
    if partial:
        return skip("partial_run")
    if fact_warnings:
        return skip("fact_check_warnings", f"{len(fact_warnings)} warning(s)")

    # Human-edit guard (same authority as D2 auto-close): run it on both
    # PR paths — on a fresh PR every commit is the bot's, so the extra
    # lookup is one cheap gh call for one uniform code path.
    commits = gh.pr_view_commits(pr_number)
    if not commits.ok:
        return skip("commits_lookup_failed", commits.error or "")
    for commit in commits.value or []:
        for author in commit.get("authors") or []:
            if not _commit_author_is_bot(author, bot_author_names, bot_author_emails):
                return skip("human_edited")

    grace = merge_settings["checks_grace_seconds"]
    timeout = merge_settings["checks_timeout_seconds"]
    if deadline is not None and clock() + grace > deadline:
        return skip("time_budget")

    raise NotImplementedError("poll loop: Task 7")
```

- [ ] **Step 4: Run tests to verify the eligibility tests pass**

Run: `python3 -m pytest tests/orchestrator/test_auto_merge.py -q`
Expected: all Task-6 tests PASS (none reaches the `NotImplementedError`).

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_auto_merge.py
git commit -m "feat(CCE-101): _maybe_auto_merge eligibility gates"
```

---

### Task 7: `_maybe_auto_merge` — check poll, merge, pages dispatch

**Files:**

- Modify: `scripts/orchestrator_runner.py` (replace the `NotImplementedError` tail)
- Test: `tests/orchestrator/test_auto_merge.py`

- [ ] **Step 1: Write the failing tests** — append (all reuse `_run`, `_settings`, `_bot_author`, `FakeClock`; `_eligible_gh(**kw)` below builds a gh whose human-edit guard passes):

```python
def _eligible_gh(**kw):
    kw.setdefault(
        "pr_view_commits", GhResult(ok=True, value=[{"authors": [_bot_author()]}])
    )
    return FakeGhClient(**kw)


def _green(name="ci"):
    return {"name": name, "state": "SUCCESS", "bucket": "pass"}


def _pending(name="ci"):
    return {"name": name, "state": "PENDING", "bucket": "pending"}


def _red(name="ci"):
    return {"name": name, "state": "FAILURE", "bucket": "fail"}


def test_zero_checks_merges_after_grace_window():
    """No-App-token host: no checks ever register; in-run validation is
    the gate. Merge fires once the grace window elapses."""
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[]))
    clock = FakeClock()
    outcome, reasons = _run(gh, clock=clock)
    assert outcome == {"merged": True, "reason": None}
    assert ("pr_merge", (7,)) in gh.calls
    assert clock.t >= 120  # waited out the grace window
    assert ("auto_merge_succeeded: pr=7", True) in reasons


def test_checks_green_merges_without_waiting_full_grace():
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green()]))
    clock = FakeClock()
    outcome, _ = _run(gh, clock=clock)
    assert outcome["merged"] is True
    assert clock.t < 120  # settled checks short-circuit the grace wait


def test_pending_then_green_polls_until_settled():
    gh = _eligible_gh(
        pr_checks=[
            GhResult(ok=True, value=[_pending()]),
            GhResult(ok=True, value=[_pending()]),
            GhResult(ok=True, value=[_green()]),
        ]
    )
    outcome, _ = _run(gh)
    assert outcome["merged"] is True
    assert [c for c in gh.calls if c[0] == "pr_checks"]


def test_any_red_check_skips_immediately():
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green("a"), _red("b")]))
    outcome, reasons = _run(gh)
    assert outcome["reason"] == "checks_failed"
    assert "b" in reasons[0][0]
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_checks_never_settle_times_out():
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_pending()]))
    outcome, reasons = _run(gh, settings=_settings(checks_timeout_seconds=60))
    assert outcome["reason"] == "checks_timeout"
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_checks_query_failure_skips_conservatively():
    gh = _eligible_gh(pr_checks=GhResult(ok=False, error="gh_failed: 500"))
    outcome, reasons = _run(gh)
    assert outcome["reason"] == "checks_query_failed"
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_merge_failure_leaves_pr_open_with_info_reason():
    gh = _eligible_gh(
        pr_checks=GhResult(ok=True, value=[_green()]),
        pr_merge=GhResult(ok=False, error="gh_pr_merge_failed: protected"),
    )
    outcome, reasons = _run(gh)
    assert outcome == {"merged": False, "reason": "merge_failed"}
    assert reasons == [("auto_merge_failed: gh_pr_merge_failed: protected", True)]


def test_successful_merge_dispatches_pages_workflow():
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green()]))
    outcome, reasons = _run(gh, build_workflow="docs-agent-pages.yml")
    assert outcome["merged"] is True
    assert ("workflow_run", ("docs-agent-pages.yml",)) in gh.calls
    assert ("pages_dispatch_succeeded: docs-agent-pages.yml", True) in reasons


def test_no_build_workflow_skips_dispatch():
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green()]))
    outcome, _ = _run(gh, build_workflow=None)
    assert outcome["merged"] is True
    assert not [c for c in gh.calls if c[0] == "workflow_run"]


def test_dispatch_failure_is_info_only_after_merge():
    gh = _eligible_gh(
        pr_checks=GhResult(ok=True, value=[_green()]),
        workflow_run=GhResult(ok=False, error="gh_workflow_run_failed: 404"),
    )
    outcome, reasons = _run(gh)
    assert outcome["merged"] is True  # merge succeeded; dispatch is best-effort
    assert ("pages_dispatch_failed: gh_workflow_run_failed: 404", True) in reasons


def test_all_reasons_are_info_only():
    """No auto-merge outcome may ever flip the run to partial."""
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_red()]))
    _, reasons = _run(gh)
    assert all(info for _, info in reasons)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_auto_merge.py -q`
Expected: Task-7 tests FAIL with `NotImplementedError: poll loop: Task 7`.

- [ ] **Step 3: Implement** — replace the `raise NotImplementedError(...)` line with:

```python
    reasons: list[tuple[str, bool]] = []
    start = clock()
    grace_end = start + grace
    poll_end = start + timeout
    if deadline is not None:
        poll_end = min(poll_end, deadline)

    while True:
        checks = gh.pr_checks(pr_number)
        if not checks.ok:
            return skip("checks_query_failed", checks.error or "")
        items = checks.value or []
        red = [
            c for c in items
            if c.get("state") == "FAILURE" or c.get("bucket") == "fail"
        ]
        if red:
            names = ",".join(sorted(c.get("name") or "?" for c in red))
            return skip("checks_failed", names)
        pending = [
            c for c in items
            if not (
                c.get("state") == "SUCCESS"
                or c.get("bucket") in ("pass", "skipping")
            )
        ]
        now = clock()
        if not items:
            if now >= grace_end:
                break  # zero checks registered: in-run validation is the gate
        elif not pending:
            break  # every registered check settled green
        if now >= poll_end:
            return skip("checks_timeout", f"{len(pending)} pending after {int(now - start)}s")
        sleep(_CHECKS_POLL_INTERVAL_SECONDS)

    merged = gh.pr_merge(pr_number)
    if not merged.ok:
        return (
            {"merged": False, "reason": "merge_failed"},
            [(f"auto_merge_failed: {merged.error}", True)],
        )
    reasons.append((f"auto_merge_succeeded: pr={pr_number}", True))
    if build_workflow:
        dispatch = gh.workflow_run(build_workflow)
        if dispatch.ok:
            reasons.append((f"pages_dispatch_succeeded: {build_workflow}", True))
        else:
            reasons.append((f"pages_dispatch_failed: {dispatch.error}", True))
    return {"merged": True, "reason": None}, reasons
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_auto_merge.py tests/gh/ -q`
Expected: all PASS. Watch `test_checks_never_settle_times_out` — with `timeout=60`, `grace=120`, the pending check hits `poll_end` (60s) before `grace_end`; the loop must exit `checks_timeout`, not sleep forever.

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_auto_merge.py
git commit -m "feat(CCE-101): _maybe_auto_merge poll loop, squash-merge, pages dispatch"
```

---

### Task 8: Wire into `run_pipeline` + digest `merge_outcome`

**Files:**

- Modify: `scripts/orchestrator_runner.py` — between `state["current_run"]["pr_number"] = pr_number` (~line 1827) and the digest dict (~line 1832)
- Test: `tests/orchestrator/test_auto_merge.py`

- [ ] **Step 1: Write the failing test** — append. It exercises the real call site by monkeypatching `orun.GhClient` (the runner constructs `gh = GhClient(repo_root)` right before `open_or_append_pr`) and stubbing `_maybe_auto_merge`'s collaborators at the gh layer only. Use the shared pipeline fixture from `tests/orchestrator/conftest.py` the same way `tests/orchestrator/test_pipeline_integration.py` does (fixture name: check conftest — it provides an initialized host repo + fixture-driven dry-run dispatch; reuse `init_pipeline_host` if that is the exported name):

```python
def test_run_pipeline_wires_auto_merge_and_digest(monkeypatch, init_pipeline_host):
    """End-to-end wiring: a green non-partial dry-run pipeline merges its
    PR, records auto_merge_succeeded, and the notifier digest carries
    merge_outcome. Asserts against current_run.json (runner observability
    contract) and the FakeGhClient call log."""
    host = init_pipeline_host()  # adapt to the conftest fixture's signature

    # Zero grace window: the wired _maybe_auto_merge uses the REAL
    # time.sleep (bound as a default arg — monkeypatching time.sleep
    # after import does NOT reach it). With grace 0 the zero-checks
    # path breaks out of the poll loop on the first iteration, so the
    # test never sleeps.
    config_path = host.repo_root / ".engineering-docs-agent" / "config.yml"
    config_path.write_text(
        config_path.read_text()
        + "\nmerge:\n  policy: auto\n  checks_grace_seconds: 0\n  checks_timeout_seconds: 0\n"
    )

    fake = None

    def _fake_factory(repo_root):
        nonlocal fake
        fake = FakeGhClient(
            pr_create=GhResult(ok=True, value=11),
            pr_view_commits=GhResult(ok=True, value=[{"authors": [_bot_author()]}]),
            pr_checks=GhResult(ok=True, value=[]),
        )
        return fake

    monkeypatch.setattr(orun, "GhClient", _fake_factory)

    rc = orun.run_pipeline(host.repo_root, dry_run_dir=host.fakes_dir)
    assert rc == 0
    assert ("pr_merge", (11,)) in fake.calls
    current_run = json.loads(
        (host.repo_root / ".engineering-docs-agent" / "current_run.json").read_text()
    )
    assert any(
        r.startswith("auto_merge_succeeded") for r in current_run["partial_reasons"]
    )
    assert current_run["partial"] is False  # info-only reasons never flip it
```

NOTE: `run_pipeline`'s exact signature/fixture names must be matched to `tests/orchestrator/conftest.py` (CCE-112 consolidated fixtures) — read that file first and adapt the fixture call, NOT the assertions. If the conftest's pipeline entry point wraps `main()` instead of `run_pipeline`, drive it the same way `test_pipeline_integration.py` does. The three assertions (pr_merge called, `auto_merge_succeeded` recorded, partial stays false) are the contract.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_auto_merge.py -q -k wires`
Expected: FAIL — `pr_merge` never called (wiring absent).

- [ ] **Step 3: Implement the wiring** — in `run_pipeline`, right after `state["current_run"]["pr_number"] = pr_number` and its two save calls:

```python
        # CCE-101: auto-merge gate. Runs on both PR paths (fresh create and
        # same-hour append) — the human-edit guard inside makes the append
        # path safe. deadline/clock are the CCE-109 budget objects.
        merge_settings = resolve_merge_settings(config)
        merge_outcome, merge_reasons = _maybe_auto_merge(
            gh,
            pr_number=pr_number,
            partial=state["current_run"]["partial"],
            fact_warnings=state["current_run"].get("fact_check_warnings") or [],
            merge_settings=merge_settings,
            build_workflow=config.get("publishing", {}).get("build_workflow"),
            deadline=deadline,
            clock=clock,
        )
        for reason, info_only in merge_reasons:
            add_partial(state, reason, info_only=info_only)
        save_persistent_state(state_path, state)
        save_current_run(state_path, state)
```

and add one line to the digest dict (after `"fact_check_warnings": ...`):

```python
            "merge_outcome": merge_outcome,
```

- [ ] **Step 4: Run the orchestrator suite**

Run: `python3 -m pytest tests/orchestrator/ -q`
Expected: all PASS. If pre-existing pipeline tests fail because the runner now calls `pr_view_commits`/`pr_checks` on fakes that lack them — that cannot happen with `FakeGhClient` (Task 5 gave it defaults: `pr_checks` → `[]`, `pr_merge` → ok), but tests using ad-hoc stub objects instead of `FakeGhClient` may need the three methods added. Fix those stubs, never the runner. ALSO: pre-existing tests that assert a left-open PR may now see a merge (default is auto) — those fixtures should set `merge: {policy: manual}` in their config IF the test's subject is unrelated to merging; if the test asserts post-PR behavior, prefer asserting the new default.

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/
git commit -m "feat(CCE-101): wire auto-merge gate into run_pipeline + digest merge_outcome"
```

---

### Task 9: Notifier contract

**Files:**

- Modify: `agents/notifier.md` (digest line, ~line 18)

- [ ] **Step 1: Update the contract** — change the digest line to include `merge_outcome` and document rendering:

In the Inputs list, replace:

```
- `digest`: `{ pr_url, run_summary_bullets, gap_flags, lint_failures, build_status, verified, failed_urls, partial_reasons, source_drift, citation_drift, core_drift }`
```

with:

```
- `digest`: `{ pr_url, run_summary_bullets, gap_flags, lint_failures, build_status, verified, failed_urls, partial_reasons, source_drift, citation_drift, core_drift, merge_outcome }`
  - `merge_outcome` (CCE-101): `{ merged: bool, reason: string | null }`. Render as one line: `Merged automatically` when `merged` is true; `Left open for review: <reason>` otherwise (reason keys: `policy_manual`, `partial_run`, `fact_check_warnings`, `human_edited`, `commits_lookup_failed`, `checks_failed`, `checks_timeout`, `checks_query_failed`, `time_budget`, `merge_failed`). Absent field (older runner): omit the line.
```

- [ ] **Step 2: Validate + commit**

Run: `python3 -m pytest tests/agents/ -q` (agent-contract tests, if any cover notifier inputs)
Expected: PASS.

```bash
git add agents/notifier.md
git commit -m "docs(CCE-101): notifier digest contract gains merge_outcome"
```

---

### Task 10: Skill docs + pages-workflow concurrency check

**Files:**

- Modify: `skills/engineering-docs-agent/SKILL.md` (PR handling + Procedure)
- Modify: `skills/engineering-docs-agent-setup/SKILL.md` (step 3, step 4)
- Verify: `templates/workflow-pages.yml` (concurrency block at ~line 21)

- [ ] **Step 1: Orchestrator SKILL.md** — append to the "PR handling" section:

```markdown
- CCE-101 auto-merge gate: after the PR number is known (either path), the
  runner calls `_maybe_auto_merge`. Eligible = `merge.policy: auto` (the
  default when the config block is absent) AND `partial: false` AND zero
  fact-check warnings AND no human commits on the PR AND enough CCE-109
  budget to wait out `checks_grace_seconds`. Check polling parses
  `gh pr checks --json name,state,bucket` (state/bucket vocabulary, CCE-83);
  zero registered checks after the grace window merges on in-run validation
  (no-App-token hosts never get checks). Merge is `--squash --delete-branch`.
  After merging, dispatch `publishing.build_workflow` via `gh workflow run`
  (a GITHUB_TOKEN merge cannot fire `on: push` workflows). Every outcome is
  an info-only reason; any failure leaves the PR open (pre-CCE-101 behavior).
```

and in the numbered Procedure, change step 13 to:

```markdown
13. Open or append-commit to the docs-agent PR (see "PR handling" below), then run the CCE-101 auto-merge gate; record its outcome in the digest's `merge_outcome`.
```

- [ ] **Step 2: Setup SKILL.md** — in step 3's question list, append:

```markdown
Also ask (CCE-101): "Should nightly docs PRs auto-merge when fully green
and non-partial, or stay open for your review?" Options: `auto`
(recommended, default) / `manual`. ALWAYS write the answer as an explicit
`merge: { policy: <answer> }` block in the composed config — scaffolded
hosts must never rely on the implicit default (absent key = auto).
```

- [ ] **Step 3: Verify pages-workflow concurrency** — read `templates/workflow-pages.yml` around line 21. Requirement: the explicit post-merge dispatch can race the push-trigger on App-token hosts; the concurrency group must coalesce them. If the existing block already serializes the whole workflow (e.g. `group: docs-agent-pages` or the standard `group: pages`), no change. If it is missing or per-ref in a way that lets two deploys run concurrently, set:

```yaml
concurrency:
  group: docs-agent-pages
  cancel-in-progress: true
```

Also verify the workflow has `workflow_dispatch:` in its `on:` block (the explicit dispatch needs it). If absent, add `workflow_dispatch: {}` under `on:`. Apply the same check to the dogfood `.github/workflows/docs-pages.yml`.

- [ ] **Step 4: Run docs/templates tests + commit**

Run: `python3 -m pytest tests/templates/ tests/skills/ tests/ci/ -q`
Expected: PASS.

```bash
git add skills/ templates/workflow-pages.yml .github/workflows/docs-pages.yml
git commit -m "docs(CCE-101): skill docs auto-merge step + pages workflow dispatchability"
```

---

### Task 11: CLAUDE.md + CHANGELOG

**Files:**

- Modify: `CLAUDE.md` (the "docs-agent PRs do NOT auto-merge by design" bullet)
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Rewrite the CLAUDE.md bullet** — replace the bullet beginning `**docs-agent PRs do NOT auto-merge by design; ...**` with (keep the historical CCE-89 narrative, flip the headline):

```markdown
- **docs-agent PRs auto-merge by default since CCE-101 (the CCE-89 D3 decision).** Eligible = non-partial AND zero fact-checker warnings AND no human commits on the PR; the runner polls `gh pr checks` (grace 120s for checks to register, 900s for them to settle — both bounded by the CCE-109 budget), squash-merges with branch deletion, then explicitly dispatches `publishing.build_workflow` (a `GITHUB_TOKEN` merge cannot fire `on: push` workflows — without the dispatch the site never redeploys). Absent `merge:` config = auto; hosts opt out with `merge: {policy: manual}`; setup asks every new host explicitly. Any skip/failure leaves the PR open with an info-only `auto_merge_*` reason — `state.json.last_successful_run` then advances only when the operator merges, and D2 auto-close sweeps superseded PRs. History: six stale PRs accumulated 2026-05-30→06-01 when merging was manual-only (head SHAs archived under `.engineering-docs-agent/stale-prs-archive/`); D1 body-enrichment + D2 auto-close shipped first, CCE-101 closed the loop. Spec: `docs/superpowers/specs/2026-06-10-cce101-merge-gate-design.md`.
```

- [ ] **Step 2: CHANGELOG entry** — under the unreleased/next-version heading (match the file's existing convention):

```markdown
- **Behavior change (CCE-101):** docs-agent PRs now auto-merge by default
  when the run is non-partial with zero fact-checker warnings (squash +
  branch delete, host CI respected when it reports). Set
  `merge: { policy: manual }` in `.engineering-docs-agent/config.yml` to
  keep PRs open for review. The setup skill now asks this explicitly.
  After an auto-merge the runner dispatches `publishing.build_workflow`
  directly, so Pages deploys fire even for `GITHUB_TOKEN` merges.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs(CCE-101): CLAUDE.md decision record + CHANGELOG behavior-change entry"
```

---

### Task 12: Ops docs + site build validation

**Files:**

- Modify: `docs/site-src/operations/docs-agent-nightly.md`
- Modify: `docs/site-src/operations/nightly-cron-cadence.md`

- [ ] **Step 1: Read both pages**, then add a "Merge gate (CCE-101)" subsection to `docs-agent-nightly.md` (adapt placement to the page's structure):

```markdown
## Merge gate (CCE-101)

Nightly PRs merge themselves when the run earned it: `partial: false`, zero
factual-accuracy warnings, no human commits on the PR, and host CI green
(checks that never register — the no-App-token case — count as "no gate";
the in-run lint/build validation already passed). The merge is squash +
branch-delete, followed by an explicit dispatch of the Pages workflow.

A PR is left open, with the reason in the run digest and
`current_run.partial_reasons`, when any of:

| Reason                                                                           | Meaning                                    | Operator action                             |
| -------------------------------------------------------------------------------- | ------------------------------------------ | ------------------------------------------- |
| `policy_manual`                                                                  | host opted out (`merge: {policy: manual}`) | review + merge as before                    |
| `partial_run`                                                                    | a subagent failed mid-run                  | read `partial_reasons`, merge if acceptable |
| `fact_check_warnings`                                                            | the fact-checker flagged a contradiction   | verify the flagged page before merging      |
| `human_edited`                                                                   | someone pushed to the PR branch            | finish the review you started               |
| `checks_failed` / `checks_timeout`                                               | host CI red or unsettled                   | fix CI, then merge manually                 |
| `time_budget` / `checks_query_failed` / `commits_lookup_failed` / `merge_failed` | infrastructure                             | merge manually; recurs → file a ticket      |

An unmerged PR is superseded the next night (D2 auto-close keeps the list
clean), but `state.json` only advances on merge — so a left-open PR means
the next run re-covers the same window.
```

and in `nightly-cron-cadence.md`, update the cadence-policy paragraph that says operators must merge within ~24h: state that auto-merge (CCE-101) is now the default closure mechanism, manual merge is only needed for the left-open reasons above, and link to the new subsection.

- [ ] **Step 2: Validate with the real consumer tool** (CLAUDE.md invariant — not `test -f`):

Run: `mkdocs build --strict 2>&1 | tail -5` and `python3 scripts/lint/lint_runner.py --paths docs/site-src/operations/docs-agent-nightly.md docs/site-src/operations/nightly-cron-cadence.md 2>/dev/null || python3 -m pytest tests/lint -q`
Expected: strict build PASS; lint (incl. `citation_exists`) clean. (If the lint runner CLI differs, run the docs lint the way `tests/lint` fixtures show.)

- [ ] **Step 3: Commit**

```bash
git add docs/site-src/operations/
git commit -m "docs(CCE-101): merge-gate operations doc + cadence policy update"
```

---

### Task 13: Full-suite validation + spec coverage audit

- [ ] **Step 1: Full test suite**

Run: `python3 -m pytest tests/ -q`
Expected: 0 failures (baseline was 1018 passed, 3 skipped before this branch; expect ~+30).

- [ ] **Step 2: Strict site build**

Run: `mkdocs build --strict`
Expected: exit 0.

- [ ] **Step 3: Spec coverage checklist** — verify each spec section maps to landed code; fix anything missing BEFORE shipping:

| Spec requirement                                   | Where                                                      |
| -------------------------------------------------- | ---------------------------------------------------------- |
| `merge` schema block, absent = auto                | Task 1, 2                                                  |
| Eligibility: non-partial + zero fact warnings      | Task 6                                                     |
| Human-edit guard on append path                    | Task 6 (uniform both paths)                                |
| CCE-109 budget bound                               | Tasks 6, 7                                                 |
| Zero-checks grace merge; state/bucket vocabulary   | Tasks 3, 7                                                 |
| Squash + delete branch                             | Task 4                                                     |
| Pages dispatch after GITHUB_TOKEN merge            | Tasks 4, 7, 10                                             |
| All reasons info_only; failures degrade to open PR | Tasks 7, 8 (`test_all_reasons_are_info_only`, wiring test) |
| Digest merge_outcome + notifier contract           | Tasks 8, 9                                                 |
| Setup question writes explicit value               | Task 10                                                    |
| CLAUDE.md / CHANGELOG / ops docs                   | Tasks 11, 12                                               |

---

### Task 14: Ship

- [ ] **Step 1:** Invoke `/ship` (the user's shipping chain: pre-flight, cost-gate, test, verify, **simplify**, **code-review**, commit, push + PR, Jira). Apply `/simplify` and `/code-review` findings before push — fix what they flag, re-run `python3 -m pytest tests/ -q` after any fix.
- [ ] **Step 2:** PR title MUST contain `CCE-101` (Jira auto-transition reads the title): `feat(CCE-101): auto-merge gate for docs-agent PRs — default on, setup-time opt-out`.
- [ ] **Step 3:** Merge per repo convention (green integrated suite, not GitHub "mergeable"), then `python3 scripts/prune_merged_branches.py --apply`.
