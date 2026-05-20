# CCE-5 — State Hygiene: Eliminate `partial_reasons` Carry-Forward Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `state.current_run.partial_reasons` from leaking transient failure reasons across orchestrator invocations, so each run's reasons reflect only what happened during that run.

**Architecture:** Reorder the state-init block in `scripts/orchestrator_runner.py` so a fresh `current_run` is constructed with empty `partial: false` / `partial_reasons: []` BEFORE the stale-current_run check; the stale check then references a saved local handle to the old run and writes its `stale_current_run_cleared` signal into the FRESH `current_run` via `add_partial`. This preserves the intra-invocation stale-cleared diagnostic and eliminates cross-run leakage in a single ~12-line edit.

**Tech Stack:** Python stdlib (`datetime`, `json`, `subprocess`), pytest. No new dependencies. Existing fixture infrastructure at `tests/orchestrator/fakes/` is reused.

**Spec:** `docs/superpowers/specs/2026-05-20-cce5-9-batch-prep-roadmap-design.md` §4 (acceptance criteria #1-#6).

**Branch:** `feat/CCE-5-state-hygiene` (off `main` at v0.1.2; roadmap spec already committed at c474d98).

---

## File Structure

- **Modify:** `scripts/orchestrator_runner.py` — reorder lines 185-216 (stale check + new-run init).
- **Create:** `tests/orchestrator/test_state_carry_forward.py` — three subprocess-driven integration tests asserting fresh-run hygiene.
- **Audit (no edits expected):** `tests/orchestrator/test_pipeline_integration.py:482-508` (existing stale-clear sentinel must keep passing); `tests/contracts/test_state_io.py` (unit tests of `add_partial`, no cross-run assumption); `tests/orchestrator/test_schema_invalid_soft_fail.py` (single-run); pipeline tests at lines 134, 218, 338, 551, 566, 597 (all single-run).
- **Modify:** `CHANGELOG.md` — add `## [0.1.3]` entry above `## [0.1.2]`.

The fix is mechanically small but semantically load-bearing. Each task is one verifiable step.

---

## Task 1: Add the carry-forward elimination test (failing)

**Files:**

- Create: `tests/orchestrator/test_state_carry_forward.py`

- [ ] **Step 1: Write the new integration test file**

Create `tests/orchestrator/test_state_carry_forward.py` with this content. The pattern mirrors `tests/orchestrator/test_schema_invalid_soft_fail.py`: spawn the orchestrator via `subprocess.run`, point it at an `--dry-run-subagents` fakes directory that succeeds, and inspect the resulting `state.json`.

```python
# tests/orchestrator/test_state_carry_forward.py
"""CCE-5: partial_reasons from a prior run must NOT carry forward into the
next run's current_run. Persistent root causes will re-accumulate on their
own when the next run also fails; transient reasons must not survive."""

from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

ORCH_RUNNER = Path(__file__).parent.parent.parent / "scripts" / "orchestrator_runner.py"
FAKES_OK = Path(__file__).parent / "fakes"

CONFIG_YAML = """
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
notifications:
  slack: { enabled: false }
  email: { enabled: false }
"""


def _init_host(tmp_path: Path, seeded_state: dict) -> Path:
    (tmp_path / ".engineering-docs-agent").mkdir()
    (tmp_path / ".engineering-docs-agent" / "config.yml").write_text(CONFIG_YAML)
    state_path = tmp_path / ".engineering-docs-agent" / "state.json"
    state_path.write_text(json.dumps(seeded_state))
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True
    )
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True
    )
    return state_path


def _run_orchestrator(tmp_path: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "GITHUB_REPOSITORY": "owner/repo"}
    return subprocess.run(
        [
            sys.executable,
            str(ORCH_RUNNER),
            "--repo-root",
            str(tmp_path),
            "--no-pr",
            "--dry-run-subagents",
            str(FAKES_OK),
        ],
        capture_output=True,
        text=True,
        env=env,
    )


def test_prior_run_partial_reasons_do_not_carry_forward(tmp_path):
    """A non-stale prior current_run with transient reasons must NOT leak
    those reasons into the new current_run."""
    seeded = {
        "version": "1",
        "current_run": {
            # Recent (within the 24h stale window) — staleness is NOT the
            # mechanism being tested; carry-forward is.
            "started_at": "2026-05-20T12:00:00+00:00",
            "head_sha": "priorrunsha",
            "partial": True,
            "partial_reasons": [
                "schema_invalid: source-collector: 'prs' is a required property",
                "source_collector_invalid: returned None",
            ],
        },
    }
    state_path = _init_host(tmp_path, seeded)

    r = _run_orchestrator(tmp_path)
    assert r.returncode == 0, (
        f"orchestrator should exit 0 on a clean dry-run; "
        f"rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}"
    )

    state = json.loads(state_path.read_text())
    reasons = state["current_run"].get("partial_reasons", [])
    leaked = [
        reason
        for reason in reasons
        if "schema_invalid" in reason or "source_collector_invalid" in reason
    ]
    assert leaked == [], (
        f"prior-run transient reasons must not carry forward; got {reasons}"
    )


def test_fresh_run_after_failed_run_starts_with_empty_reasons(tmp_path):
    """Acceptance criterion #5: after a prior failed run, the new run's
    current_run starts with partial: false and partial_reasons: []."""
    seeded = {
        "version": "1",
        "current_run": {
            "started_at": "2026-05-20T12:00:00+00:00",
            "head_sha": "priorrunsha",
            "partial": True,
            "partial_reasons": ["push_failed: simulated network error"],
        },
    }
    state_path = _init_host(tmp_path, seeded)

    r = _run_orchestrator(tmp_path)
    assert r.returncode == 0, r.stderr

    state = json.loads(state_path.read_text())
    cr = state["current_run"]
    # The dry-run fakes succeed, so this run is clean: partial should be
    # false and partial_reasons should be empty.
    assert cr.get("partial") is False, (
        f"clean run after failed run should have partial=false; got {cr}"
    )
    assert cr.get("partial_reasons") == [], (
        f"clean run after failed run should have empty partial_reasons; got {cr.get('partial_reasons')!r}"
    )


def test_stale_clear_signal_still_emitted_against_fresh_reasons(tmp_path):
    """Acceptance criterion #6 + interaction with the existing stale-clear
    contract: a stale prior current_run must still emit
    'stale_current_run_cleared' — and that must be the ONLY reason
    present (no leakage of the stale run's prior reasons)."""
    from datetime import datetime, timedelta, timezone

    stale_iso = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    seeded = {
        "version": "1",
        "current_run": {
            "started_at": stale_iso,
            "head_sha": "stalesha",
            "partial": True,
            "partial_reasons": ["push_failed: ancient", "lint_block: tier1: rule_x"],
        },
    }
    state_path = _init_host(tmp_path, seeded)

    r = _run_orchestrator(tmp_path)
    assert r.returncode == 0, r.stderr

    state = json.loads(state_path.read_text())
    reasons = state["current_run"]["partial_reasons"]
    assert "stale_current_run_cleared" in reasons, (
        f"stale-clear signal must still fire; got {reasons}"
    )
    leaked = [
        reason
        for reason in reasons
        if "push_failed" in reason or "lint_block" in reason
    ]
    assert leaked == [], (
        f"stale prior reasons must not leak into fresh current_run; got {reasons}"
    )
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python -m pytest tests/orchestrator/test_state_carry_forward.py -v`

Expected:

- `test_prior_run_partial_reasons_do_not_carry_forward`: **FAIL** (assertion: leaked reasons present)
- `test_fresh_run_after_failed_run_starts_with_empty_reasons`: **FAIL** (assertion: partial_reasons non-empty)
- `test_stale_clear_signal_still_emitted_against_fresh_reasons`: **FAIL** (assertion: stale prior reasons leak)

If any test passes on the unfixed code, the test is wrong — re-read the fixture and re-run before moving on.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/orchestrator/test_state_carry_forward.py
git commit -m "test(CCE-5): failing tests for partial_reasons carry-forward elimination"
```

---

## Task 2: Implement the state-init reorder

**Files:**

- Modify: `scripts/orchestrator_runner.py:185-216`

- [ ] **Step 1: Replace the stale-check + carry-forward block**

In `scripts/orchestrator_runner.py`, locate this block (currently lines 185-217):

```python
    # Clear stale current_run (>24h old) before starting a new run.
    if "current_run" in state:
        started = state["current_run"].get("started_at")
        if started:
            try:
                started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - started_dt) > timedelta(hours=24):
                    state.pop("current_run")
                    add_partial(state, "stale_current_run_cleared")
            except ValueError:
                pass

    head_sha = (
        subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        or "unknown"
    )

    repo = detect_repo(repo_root)

    now = datetime.now(timezone.utc).isoformat()
    # Preserve partial flags accumulated before this point (e.g., stale_current_run_cleared)
    carried_partial = state.get("current_run", {}).get("partial", False)
    carried_reasons = state.get("current_run", {}).get("partial_reasons", [])
    state["current_run"] = {
        "started_at": now,
        "head_sha": head_sha,
        "partial": carried_partial,
        "partial_reasons": list(carried_reasons),
    }
```

Replace it with this reordered block (note: `head_sha` and `repo` assignments are unchanged; only the surrounding logic shifts):

```python
    head_sha = (
        subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        or "unknown"
    )

    repo = detect_repo(repo_root)

    # CCE-5: Always begin a new run with a fresh current_run. partial_reasons
    # from a prior run must not carry forward — persistent root causes will
    # re-accumulate naturally on this run's own dispatches; transient reasons
    # belong to the run that produced them. The stale-clear diagnostic below
    # writes into the FRESH current_run, preserving the intra-invocation signal.
    prior_run = state.pop("current_run", None)
    now = datetime.now(timezone.utc).isoformat()
    state["current_run"] = {
        "started_at": now,
        "head_sha": head_sha,
        "partial": False,
        "partial_reasons": [],
    }

    if prior_run is not None:
        prior_started = prior_run.get("started_at")
        if prior_started:
            try:
                prior_dt = datetime.fromisoformat(prior_started.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - prior_dt) > timedelta(hours=24):
                    add_partial(state, "stale_current_run_cleared")
            except ValueError:
                pass
```

What changed:

- The stale check moved BELOW the new-run init.
- The old run is captured into a local `prior_run` variable via `state.pop(...)`, not referenced from `state["current_run"]` (which is now the FRESH run).
- The carry-forward `carried_partial` / `carried_reasons` reads are deleted entirely.
- `add_partial(state, "stale_current_run_cleared")` writes into the fresh `current_run` (idempotent; sets `partial=True` and appends the reason).

- [ ] **Step 2: Run the new tests to verify they pass**

Run: `python -m pytest tests/orchestrator/test_state_carry_forward.py -v`

Expected: 3 PASS.

If any test still fails: stop, re-read the diff, and reconcile against the test assertion before continuing. Do NOT loosen a test to make it pass.

- [ ] **Step 3: Run the existing stale-clear sentinel to confirm no regression**

Run: `python -m pytest tests/orchestrator/test_pipeline_integration.py::test_stale_current_run_cleared_on_next_run -v`

Expected: PASS. This test seeds a 48h-old `current_run` with `partial_reasons: []`, runs the orchestrator, and asserts `"stale_current_run_cleared" in state["current_run"]["partial_reasons"]`. The reorder must keep this green.

- [ ] **Step 4: Commit the implementation**

```bash
git add scripts/orchestrator_runner.py
git commit -m "fix(CCE-5): stop partial_reasons from carrying forward across runs

Reorder state-init in orchestrator_runner.run so each new run starts
with partial: false and partial_reasons: []. The stale-current_run
diagnostic is preserved by writing into the fresh current_run via
add_partial. Transient reasons (schema_invalid, push_failed, etc.) from
a prior run no longer pollute the next run's state.

CCE-5"
```

---

## Task 3: Audit the full test suite for carry-forward assumptions

**Files:**

- Audit only (no edits expected): `tests/orchestrator/test_pipeline_integration.py`, `tests/contracts/test_state_io.py`, `tests/orchestrator/test_schema_invalid_soft_fail.py`, `tests/orchestrator/test_verify_runner.py`.

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`

Expected: 158/158 PASS (the CCE-4 baseline) + 3 new CCE-5 tests = 161/161 PASS.

If any test fails, read the failure carefully:

- If the test seeds `current_run.partial_reasons: [...]` and then asserts those same reasons appear after `runner.run(...)`, that test is encoding the buggy behavior and is the bug — confirm against acceptance criterion #4 ("Future carry-forward must be opt-in") and update the test to assert the post-fix semantics. Document the change in the commit message.
- If the test fails for an unrelated reason, that is a regression — fix the implementation, not the test.

- [ ] **Step 2: Grep for cross-run `partial_reasons` assumptions**

Run: `grep -n "partial_reasons" tests/ -r`

Expected matches (these are all SAFE — single-run scope, no carry-forward assumption):

- `tests/contracts/test_state_io.py:95, 101, 104, 110, 112` — unit tests of `add_partial` on a single in-memory dict.
- `tests/schemas/test_state_schema.py:30` — schema validation only.
- `tests/orchestrator/test_schema_invalid_soft_fail.py:87` — asserts reasons within a single run.
- `tests/orchestrator/test_pipeline_integration.py:134, 218, 338, 551, 566, 597` — all single-run pipeline assertions.
- `tests/orchestrator/test_pipeline_integration.py:498, 506` — `test_stale_current_run_cleared_on_next_run` seeds `partial_reasons: []` (already empty) and asserts the stale-clear signal in the NEW run; the reorder preserves this.

For each match, confirm by inspection that the test either:

- operates on a single `runner.run(...)` invocation, OR
- explicitly seeds the prior `current_run.partial_reasons` to `[]` (so there's nothing to carry forward anyway).

If any test seeds non-empty `partial_reasons` into the prior `current_run` and asserts those reasons survive into the next run, flag it: that assertion encodes the bug. Confirm with the spec (§4.4 #4: "Future carry-forward must be opt-in") before changing.

- [ ] **Step 3: No-edit confirmation**

If the full suite is 161/161 green and no carry-forward assumption was found, no edits are needed. Continue to Task 4. If edits were made, commit them now:

```bash
git add tests/
git commit -m "test(CCE-5): align suite with no-carry-forward semantics"
```

---

## Task 4: CHANGELOG entry

**Files:**

- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the v0.1.3 entry**

Insert a new section between the existing `# Changelog` header and `## [0.1.2] — 2026-05-20`. Use this exact content:

```markdown
## [0.1.3] — 2026-05-20

### State hygiene (CCE-5)

- `state.current_run.partial_reasons` no longer carries forward across runs. The state-init block in `scripts/orchestrator_runner.py` now constructs a fresh `current_run` with `partial: false` / `partial_reasons: []` before checking the prior run for staleness; the `stale_current_run_cleared` diagnostic is preserved by writing into the fresh `current_run` via `add_partial`.
- Persistent root causes (e.g. a malformed agent contract) re-accumulate naturally on each run's own dispatches. Transient reasons (e.g. `schema_invalid: source-collector: ...`, `push_failed: ...`) now belong only to the run that produced them.
- New integration tests at `tests/orchestrator/test_state_carry_forward.py` (3 cases) lock the no-carry-forward contract. Existing stale-clear sentinel at `tests/orchestrator/test_pipeline_integration.py::test_stale_current_run_cleared_on_next_run` remains green.
- No new dependencies. No new configuration. Future opt-in carry-forward (none today) would require an explicit allowlist per the design spec.
```

- [ ] **Step 2: Verify the CHANGELOG renders cleanly**

Run: `head -25 CHANGELOG.md`

Expected: the new `## [0.1.3]` block appears immediately under `# Changelog`, with `## [0.1.2]` directly below it. No accidental deletion of prior entries.

- [ ] **Step 3: Commit the CHANGELOG**

```bash
git add CHANGELOG.md
git commit -m "docs(CCE-5): CHANGELOG entry for v0.1.3 state hygiene"
```

---

## Task 5: Final verification and /ship handoff

**Files:**

- Run-only.

- [ ] **Step 1: Full test suite green-light**

Run: `python -m pytest -q`

Expected: **161/161 PASS** (158 baseline + 3 new CCE-5 tests).

- [ ] **Step 2: Confirm branch state**

Run: `git log --oneline main..HEAD`

Expected (most recent first):

```
<sha> docs(CCE-5): CHANGELOG entry for v0.1.3 state hygiene
<sha> fix(CCE-5): stop partial_reasons from carrying forward across runs
<sha> test(CCE-5): failing tests for partial_reasons carry-forward elimination
c474d98 Kickoff doc — brainstorming handoff from ADIS-235 session
```

(The `c474d98` roadmap-spec commit may have a different message if reworded; the three CCE-5 commits above it are required.)

- [ ] **Step 3: Hand off to /ship**

Invoke: `/ship`

The user has pre-authorized `/ship` per CCE ticket. The ship chain will run pre-flight → cost-gate → test → verify-agent → simplify → code review → commit (no-op, already committed) → push + PR → Jira update. The PR title should be `CCE-5: state hygiene — eliminate partial_reasons carry-forward` (or similar). The Jira stage will pick `CCE-5` from the branch name `feat/CCE-5-state-hygiene`.

After /ship completes and PR is merged, tag `v0.1.3` and proceed to CCE-9 per the batch roadmap.

---

## Self-Review

**1. Spec coverage** — all 6 acceptance criteria from spec §4.4 mapped:

| Criterion                                                                      | Task                                                                                                                                                                                                                                                      |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #1 New-run init writes `partial: false`, `partial_reasons: []` unconditionally | Task 2 step 1 (reordered code)                                                                                                                                                                                                                            |
| #2 Persistent conditions re-accumulate naturally                               | Task 1 step 1 (test asserts clean dry-run → empty reasons; persistent conditions would re-fire on a failing run, which the test design implicitly accepts) + Task 3 step 1 (full suite green proves existing failure-path tests still emit their reasons) |
| #3 Transient reasons do NOT carry forward                                      | Task 1 step 1 (`test_prior_run_partial_reasons_do_not_carry_forward` + `test_stale_clear_signal_still_emitted_against_fresh_reasons`)                                                                                                                     |
| #4 Future carry-forward must be opt-in via allowlist (none today)              | Task 2 step 1 (carried_partial / carried_reasons deletion); Task 3 step 2 (audit confirms no test encodes carry-forward)                                                                                                                                  |
| #5 New unit test: fresh run after failed run starts with `partial_reasons: []` | Task 1 step 1 (`test_fresh_run_after_failed_run_starts_with_empty_reasons`)                                                                                                                                                                               |
| #6 No regression in verify_runner write-on-failure test                        | Task 3 step 1 (full suite) + verify_runner test still uses its own `current_run` shape; the orchestrator-side reorder does not touch `scripts/verify_runner.py`                                                                                           |

**2. Placeholder scan** — no `TBD`, `TODO`, `implement later`, `similar to`, or "add appropriate X" patterns. Every code block contains the exact content to write. Every test includes its assertions. Every commit command includes its message.

**3. Type consistency** — `prior_run` is `dict | None` (from `state.pop(...)` default `None`). `prior_started` is `str | None`. `add_partial(state, reason)` matches the signature at `scripts/state_io.py:45` (`state: dict, reason: str`). The fresh-run dict shape matches `templates/state.schema.json` (verified by load_state_validated on the next invocation).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-20-cce5-state-hygiene.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review between tasks, fast iteration. Each of the 5 tasks above maps to one implementer dispatch + spec review + code-quality review.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

User has pre-authorized executing via subagent-driven-development + `/ship` per ticket once the plan is approved.
