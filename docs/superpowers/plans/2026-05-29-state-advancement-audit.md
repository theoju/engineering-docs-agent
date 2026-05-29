# State-advancement audit on partial runs — execution plan

**Ticket:** CCE-62
**Spec:** `docs/superpowers/specs/2026-05-29-state-advancement-audit-design.md`
**Date:** 2026-05-29

## Goal

Pin the two §8 state-advancement contracts (subagent-partial advances on
disk; PR-open-failure leaves main un-advanced via fresh-checkout semantics)
with regression tests that fail loudly if either branch regresses.

## Pre-flight

- Branch: `chore/CCE-62-state-advancement-audit` off main.
- Worktree: isolated.
- Test runner: `python3 -m pytest`.
- No source code change. Tests + audit docs only.

## Tasks

### Task 1 — Write the spec

Already done: `docs/superpowers/specs/2026-05-29-state-advancement-audit-design.md`.

### Task 2 — Write the plan

This file.

### Task 3 — Verify fixture inventory

Confirm the existing fixtures still trigger the partial reasons the tests
will assert on:

```bash
ls tests/orchestrator/fakes_sc_error/
ls tests/orchestrator/fakes_block/
```

Read both fixture sets to confirm:

- `fakes_sc_error` carries `error` and `partial` true keys in the
  source-collector fake (per `orchestrator_runner.py:1055-1058`, both
  produce add_partial calls).
- `fakes_block` carries a content-validator fake with at least one
  `severity: block` failure (per `orchestrator_runner.py:1210-1269`).

### Task 4 — Author regression tests

Create `tests/orchestrator/test_state_advancement_invariant.py`.

Follow the layout used by `test_runner_state_promotion.py`:

- A `CONFIG_YAML` constant matching the host shape used in other integration
  tests.
- A `_init_host(tmp_path, seeded_state)` helper that initializes a git repo
  with a single commit, writes config and state, returns
  `(state_path, head_sha)`.
- For the lint-block test, seed `docs/site-src/core/connectors/foo.md` is
  NOT required — `fakes_block` exercises the create-then-block path.
- For the PR-failure test, run in-process via
  `orchestrator_runner.run(tmp_path, dry_run_dir=..., no_pr=False)` and
  monkeypatch `orchestrator_runner.open_or_append_pr` to return
  `(None, [("forced_failure", False)])`.

#### Test 1: `test_partial_run_via_source_collector_error_advances_state`

```python
def test_partial_run_via_source_collector_error_advances_state(tmp_path):
    seeded = {"version": "1", "last_successful_run": {"head_sha": "old_sha"}}
    state_path, head_sha = _init_host(tmp_path, seeded)

    result = _run(tmp_path, FAKES_SC_ERROR)
    assert result.returncode == 0, result.stderr

    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == head_sha
    # Persistent state must not contain current_run.
    assert "current_run" not in written

    cr_path = state_path.parent / "current_run.json"
    cr = json.loads(cr_path.read_text())["current_run"]
    assert cr["partial"] is True
    assert any("source_collector_error" in r for r in cr["partial_reasons"])
```

#### Test 2: `test_partial_run_via_lint_block_advances_state`

Mirror test 1 but with `FAKES_BLOCK` and `lint_block` in the assertion.

#### Test 3: `test_pr_open_failure_returns_1_and_acknowledges_ephemeral_advance`

```python
def test_pr_open_failure_returns_1_and_acknowledges_ephemeral_advance(
    tmp_path, monkeypatch
):
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner
    import importlib
    importlib.reload(runner)

    seeded = {"version": "1", "last_successful_run": {"head_sha": "old_sha"}}
    state_path, head_sha = _init_host(tmp_path, seeded)

    def fake_open(*args, **kwargs):
        return None, [("forced_failure: pr_open simulated", False)]
    monkeypatch.setattr(runner, "open_or_append_pr", fake_open)

    # GhClient init shouldn't matter because open_or_append_pr is mocked.
    rc = runner.run(tmp_path, dry_run_dir=FAKES_OK, no_pr=False)
    assert rc == 1, "PR open failure must hard-fail (return 1) per spec §8"

    # CCE-40 §7 row 3: the on-disk advance is acknowledged as ephemeral —
    # CI's fresh checkout is what enforces "not advanced to main". Pinning
    # this means a future "fix" that conditionally gates the advance breaks
    # this test, forcing an explicit spec update.
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == head_sha

    cr_path = state_path.parent / "current_run.json"
    cr = json.loads(cr_path.read_text())["current_run"]
    assert any("forced_failure" in r for r in cr["partial_reasons"])
```

### Task 5 — Run the test suite

```bash
python3 -m pytest tests/orchestrator/test_state_advancement_invariant.py -v
python3 -m pytest
```

Both must be green before commit.

### Task 6 — Ship

Use the `/ship` skill chain: tests → code-review → commit → push → PR →
Jira comment (no transition). Branch `chore/CCE-62-state-advancement-audit`,
PR title prefixed with `CCE-62`.

## Verification checklist

- [ ] Spec exists at the documented path.
- [ ] Plan exists at the documented path.
- [ ] `tests/orchestrator/test_state_advancement_invariant.py` exists with
      three tests.
- [ ] All three new tests pass.
- [ ] `python3 -m pytest` passes overall.
- [ ] No source-code change in `scripts/` or `agents/`.
- [ ] PR opened; CCE-62 commented with PR URL (no Jira transition).
