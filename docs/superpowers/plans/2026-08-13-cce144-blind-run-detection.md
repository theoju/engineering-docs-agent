# CCE-144 Blind-Run Detection Implementation Plan

> ## Archived 2026-08-14 — this plan was executed, then thrown away
>
> **Do not read this as a record of what the code does.** All seven tasks were implemented on `feat/CCE-144-blind-run-detection` (20 commits, four new test suites, a green suite), but the branch was never pushed, never opened as a PR, and was deleted on 2026-08-14. **None of it is on `main`.** The blind/degraded split does not exist in `scripts/`.
>
> Two specific traps for anyone reusing this text:
>
> - **The completed checkboxes are historical.** They record that a task ran on a branch that no longer exists — not that the repository contains the result.
> - **Task 7's CLAUDE.md bullet is written in the past tense** ("`add_partial` gains…", "Three consumers read the flag"). It was drafted to be pasted into CLAUDE.md _after_ the change landed. It never landed. Pasting it as-is would document behavior the code does not have.
>
> The **Global Constraints** section below also pins a worktree path and a concurrent-session warning that were true only during the original run; both are now stale.
>
> Kept for its diagnosis, task decomposition, and trap analysis — a re-attempt should re-derive the classification against today's `orchestrator_runner.py` rather than trusting this plan's tables. Spec: `docs/superpowers/specs/2026-08-13-cce144-blind-run-detection-design.md`. Archived under CCE-150; **CCE-144 remains open.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the docs-agent nightly capable of reporting failure, so a run whose subagents were all rate-limited turns the check red instead of green, cannot advance its watermark, and cannot auto-merge.

**Architecture:** A new `blind` predicate splits today's `partial` into two conditions with opposite operational meanings — _the run consumed input it could not process_ (blind, red) versus _the run held back what it could not process_ (degraded, green). `state_io.add_partial` is the single writer of the flag; three consumers read it (the exit code, the watermark advance, the auto-merge gate). Blocking reasons are blind by default so an unclassified failure mode is loud rather than silent.

**Tech Stack:** Python 3 stdlib only (`ast`, `json`, `pathlib`), pytest, GitHub Actions YAML, `jq`, `actionlint`.

**Spec:** `docs/superpowers/specs/2026-08-13-cce144-blind-run-detection-design.md` — approved, amended after adversarial validation, classification signed off by the operator. The spec's **Classification** section is authoritative; never re-derive it.

## Global Constraints

- **Worktree.** All work happens in `/private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144` on branch `feat/CCE-144-blind-run-detection`. The main repo checkout at `/Users/theo/Projects/engineering-docs-agent` is in use by a **concurrent session** — never `git checkout`, `git switch`, or otherwise mutate that tree.
- **Python interpreter is `/Users/theo/Projects/engineering-docs-agent/.venv/bin/python`.** The worktree has no `.venv`. Bare `python3` is Homebrew 3.14 with no pytest and will fail confusingly. Every command in this plan uses the full path; do not shorten it.
- **TDD, strictly.** Write the failing test, run it, watch it fail for the stated reason, then implement. A test that passes before implementation is a broken test — fix the test, do not proceed.
- **`tests/scripts/` must NOT contain `__init__.py`.** `scripts/` is a PEP 420 implicit namespace package. A `tests/scripts/__init__.py` registers as the top-level `scripts` package and shadows the real one, producing order-dependent `ModuleNotFoundError` in unrelated suites.
- **The import convention is per-directory, and `orchestrator_runner` is NOT dotted-importable.** `scripts/state_io.py` and `scripts/verify_runner.py` each `sys.path.insert` their own directory, so `from scripts.state_io import add_partial` works — the root `conftest.py` puts the repo root on `sys.path`, which makes `scripts` resolve as a namespace package. `scripts/orchestrator_runner.py` has no such self-insert: `from scripts.orchestrator_runner import run` raises `ModuleNotFoundError: No module named 'gh_client'`, both before and after this change. Follow the directory you are writing in. `tests/state_io/` uses the dotted path. All 58 files in `tests/orchestrator/` use this preamble, and new orchestrator tests must match it:

  ```python
  _REPO_ROOT = Path(__file__).resolve().parents[2]
  sys.path.insert(0, str(_REPO_ROOT / "scripts"))

  import orchestrator_runner as orun  # noqa: E402
  ```

  Never mix the two styles for the same module: `scripts.state_io` and bare `state_io` are two **distinct module objects**, so a monkeypatch applied to one has no effect on the other. CLAUDE.md's dotted-path rule exists to stop `tests/scripts/` shadowing the `scripts` namespace package, and it holds for `scripts.state_io` and `scripts.lint.*` — it does not make `orchestrator_runner` importable, and following it there breaks collection.

- **`add_partial` is a shared-helper contract.** It is the single writer of `current_run.partial_reasons`, and becomes the single writer of `current_run.blind` and `current_run.blind_reasons`. Its callers are enumerated in this plan; changing its signature means updating all of them in the same commit.
- **Docs cite code line-free:** `` `path/to/file.py` `` or `` `path/to/file.py:symbol` ``. Never `path:line`. This binds prose in commit messages, CLAUDE.md, and any doc page.
- **PR title must contain `CCE-144`** — the Jira transition workflow reads the title only.
- **Commit trailer:** every commit ends with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Never edit `agents/schemas/*.json` or `docs/site-src/api/contracts/*.schema.md` in this plan.** No agent contract changes here.

## File Structure

| File                                                         | Responsibility in this change                                                                                                                                                                 |
| ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/state_io.py`                                        | `add_partial` gains `degraded`; becomes the single writer of `blind` / `blind_reasons`. Task 1.                                                                                               |
| `scripts/orchestrator_runner.py`                             | `_record_dispatch_reasons` passthrough (Task 2), classification kwargs (Task 3), `_exit_code` + return sites (Task 4), watermark interlock (Task 5), `_maybe_auto_merge` blind gate (Task 6). |
| `scripts/verify_runner.py`                                   | Three blocking sites gain classification kwargs. Task 3. Its exit code is deliberately unchanged.                                                                                             |
| `tests/state_io/test_add_partial_blind.py`                   | **new** — the `add_partial` semantics matrix. Task 1.                                                                                                                                         |
| `tests/orchestrator/test_dispatch_reasons_classification.py` | **new** — `_record_dispatch_reasons` passthrough. Task 2.                                                                                                                                     |
| `tests/orchestrator/test_classification_coverage.py`         | **new** — the anti-decay gate. Task 3.                                                                                                                                                        |
| `tests/orchestrator/test_blind_run_interlocks.py`            | **new** — exit code (Task 4), watermark (Task 5), auto-merge (Task 6). One file, three task-scoped sections.                                                                                  |
| `tests/orchestrator/test_deferral_skip.py`                   | **modify** — its monkeypatched `add_partial` spy TypeErrors once any callsite passes `degraded=`. Task 2.                                                                                     |
| `.github/workflows/docs-agent-nightly.yml`                   | Print-step repair. Task 7.                                                                                                                                                                    |
| `templates/workflow-run.yml`                                 | Same repair, kept in parity. Task 7.                                                                                                                                                          |
| `CLAUDE.md`                                                  | CCE-127 bullet correction (Task 6) and the CCE-144 bullet (Task 7).                                                                                                                           |

`tests/orchestrator/test_blind_run_interlocks.py` deliberately holds three tasks' tests. They share one harness and splitting them would triplicate setup. Each task appends its own section and its own tests; a reviewer can still reject one task's tests without touching another's.

---

### Task 1: `add_partial` learns the blind/degraded distinction

**Files:**

- Modify: `scripts/state_io.py` — `add_partial`
- Test: `tests/state_io/test_add_partial_blind.py` (create)

**Interfaces:**

- Consumes: nothing from earlier tasks.
- Produces: `state_io.add_partial(state, reason, *, info_only: bool = False, degraded: bool = False) -> None`. Writes `state["current_run"]["blind"]: bool` and `state["current_run"]["blind_reasons"]: list[str]`. Every later task depends on these exact names.

**Background the implementer needs.** `add_partial` currently appends a redacted reason to `current_run.partial_reasons` and flips `current_run.partial` unless `info_only=True`. It also emits one stderr line per call (CCE-74), including on repeat calls that do not append. Redaction happens via `stderr_emit._redact_credentials` **before** the reason is stored, so state never carries raw credentials.

Semantics to implement, in precedence order:

1. `info_only=True` → advisory. Touches neither `partial` nor `blind`. `degraded` is ignored entirely when `info_only` is set.
2. `degraded=True` → flips `partial`, does **not** flip `blind`.
3. neither → flips `partial` **and** `blind`, and appends to `blind_reasons`.

`blind_reasons` is always a subset of `partial_reasons`, redacted identically, with the same "already present → do not append again" rule.

- [ ] **Step 1: Write the failing tests**

Create `tests/state_io/test_add_partial_blind.py`:

```python
"""CCE-144: add_partial's blind/degraded semantics."""

from __future__ import annotations

import pytest

from scripts.state_io import add_partial


def _fresh() -> dict:
    return {}


def test_blocking_reason_is_blind_by_default():
    state = _fresh()
    add_partial(state, "source_collector_invalid: returned None")
    cr = state["current_run"]
    assert cr["partial"] is True
    assert cr["blind"] is True
    assert cr["partial_reasons"] == ["source_collector_invalid: returned None"]
    assert cr["blind_reasons"] == ["source_collector_invalid: returned None"]


def test_degraded_flips_partial_but_not_blind():
    state = _fresh()
    add_partial(state, "lint_block: page.md rule: msg", degraded=True)
    cr = state["current_run"]
    assert cr["partial"] is True
    assert cr.get("blind", False) is False
    assert cr["partial_reasons"] == ["lint_block: page.md rule: msg"]
    assert cr.get("blind_reasons", []) == []


def test_info_only_flips_neither():
    state = _fresh()
    add_partial(state, "gap_detector_unjudged: pr_id=7", info_only=True)
    cr = state["current_run"]
    assert cr["partial"] is False
    assert cr.get("blind", False) is False
    assert cr["partial_reasons"] == ["gap_detector_unjudged: pr_id=7"]
    assert cr.get("blind_reasons", []) == []


def test_info_only_wins_over_degraded():
    """Precedence: info_only is checked first and degraded is ignored."""
    state = _fresh()
    add_partial(state, "advisory thing", info_only=True, degraded=True)
    cr = state["current_run"]
    assert cr["partial"] is False
    assert cr.get("blind", False) is False


def test_blind_reasons_is_a_subset_of_partial_reasons():
    state = _fresh()
    add_partial(state, "blind one")
    add_partial(state, "degraded one", degraded=True)
    add_partial(state, "advisory one", info_only=True)
    cr = state["current_run"]
    assert set(cr["blind_reasons"]) <= set(cr["partial_reasons"])
    assert cr["blind_reasons"] == ["blind one"]
    assert len(cr["partial_reasons"]) == 3


def test_repeat_blind_reason_appends_once_to_each_list():
    state = _fresh()
    add_partial(state, "same reason")
    add_partial(state, "same reason")
    cr = state["current_run"]
    assert cr["partial_reasons"] == ["same reason"]
    assert cr["blind_reasons"] == ["same reason"]


def test_blind_reasons_are_redacted_identically():
    state = _fresh()
    add_partial(state, "clone failed: https://x-access-token:ghs_SECRET@github.com/o/r")
    cr = state["current_run"]
    assert "ghs_SECRET" not in cr["blind_reasons"][0]
    assert cr["blind_reasons"] == cr["partial_reasons"]


def test_a_degraded_run_that_later_goes_blind_stays_blind():
    """blind is monotonic within a run — one blind reason is enough."""
    state = _fresh()
    add_partial(state, "degraded first", degraded=True)
    add_partial(state, "blind second")
    add_partial(state, "degraded third", degraded=True)
    cr = state["current_run"]
    assert cr["blind"] is True
    assert cr["blind_reasons"] == ["blind second"]


def test_degraded_only_run_never_creates_the_blind_key_as_true():
    """A green-eligible run must not carry blind=True under any ordering."""
    state = _fresh()
    for i in range(3):
        add_partial(state, f"degraded {i}", degraded=True)
    assert state["current_run"].get("blind", False) is False


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"degraded": True}, {"info_only": True}],
    ids=["default", "degraded", "info_only"],
)
def test_seeded_current_run_is_not_clobbered(kwargs):
    """add_partial must preserve pre-existing current_run keys."""
    state = {"current_run": {"partial": False, "partial_reasons": [], "head_sha": "abc"}}
    add_partial(state, "reason", **kwargs)
    assert state["current_run"]["head_sha"] == "abc"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/state_io/test_add_partial_blind.py -v
```

Expected: **12 cases — 9 red, 3 green.** (pytest reports all 9 as `FAILED`, not `ERROR`: a `TypeError` raised inside a test body is an ordinary assertion-phase failure, not a fixture/collection error.) The exact split, because three of these are deliberate regression guards on behavior that already works and they must NOT be "fixed":

| Case                                                         | At this step                                                                    |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| `test_degraded_flips_partial_but_not_blind`                  | FAIL — `TypeError: add_partial() got an unexpected keyword argument 'degraded'` |
| `test_info_only_wins_over_degraded`                          | FAIL — same `TypeError`                                                         |
| `test_blind_reasons_is_a_subset_of_partial_reasons`          | FAIL — same `TypeError`                                                         |
| `test_a_degraded_run_that_later_goes_blind_stays_blind`      | FAIL — same `TypeError`                                                         |
| `test_degraded_only_run_never_creates_the_blind_key_as_true` | FAIL — same `TypeError`                                                         |
| `test_seeded_current_run_is_not_clobbered[degraded]`         | FAIL — same `TypeError` (this is why the parametrize carries explicit `ids=`)   |
| `test_blocking_reason_is_blind_by_default`                   | FAIL — `KeyError: 'blind'`                                                      |
| `test_repeat_blind_reason_appends_once_to_each_list`         | FAIL — `KeyError: 'blind_reasons'`                                              |
| `test_blind_reasons_are_redacted_identically`                | FAIL — `KeyError: 'blind_reasons'`                                              |
| `test_info_only_flips_neither`                               | **PASS** — pins existing `info_only` behavior this change must not alter        |
| `test_seeded_current_run_is_not_clobbered[default]`          | **PASS** — same, for the default path                                           |
| `test_seeded_current_run_is_not_clobbered[info_only]`        | **PASS** — same                                                                 |

The Global Constraint "a test that passes before implementation is a broken test" applies to tests asserting **new** behavior. Those three assert **existing** behavior on purpose — they are the guard that Task 1 does not regress `info_only` or clobber a seeded `current_run`. Leave them exactly as they are.

Any case _not_ in this table that passes is genuinely non-discriminating — fix it before continuing.

- [ ] **Step 3: Implement**

In `scripts/state_io.py`, replace `add_partial` in full:

```python
def add_partial(
    state: dict,
    reason: str,
    *,
    info_only: bool = False,
    degraded: bool = False,
) -> None:
    """Append a partial reason to current_run.partial_reasons.

    When info_only is False (default), also flip current_run.partial to True.
    When info_only is True, leave current_run.partial unchanged — the reason
    is informational, not a degradation of the run's data quality.

    CCE-144: a blocking reason is additionally classified blind or degraded.

    - ``info_only=True``  -> advisory; touches neither ``partial`` nor
      ``blind``. ``degraded`` is ignored.
    - ``degraded=True``   -> the run JUDGED and rejected work; flips
      ``partial`` only. Self-healing: the next run retries.
    - neither             -> the run was PREVENTED from judging; flips
      ``partial`` AND ``blind``, and records the reason in
      ``blind_reasons``. This is the fail-safe default: a blocking failure
      mode nobody classified turns the run red rather than passing silently.

    ``blind_reasons`` is always a subset of ``partial_reasons`` — same
    redaction, same idempotency rule. ``blind`` is monotonic within a run.

    Idempotent for state: a reason already present (after redaction) is not
    appended again.

    Side effect (CCE-74): writes one line to stderr via stderr_emit.emit_stderr
    on EVERY call (NOT only newly-appended) so retry-loop sequencing is visible.
    Reason string is redacted via stderr_emit._redact_credentials BEFORE being
    stored in state AND before being emitted; state.json never carries raw
    credentials regardless of which call site recorded the reason. Stderr emit
    is best-effort (OSError-swallowed); state mutation always succeeds.
    """
    safe_reason = _redact_credentials(reason)
    if "current_run" not in state:
        state["current_run"] = {"partial": False, "partial_reasons": []}
    cr = state["current_run"]
    cr.setdefault("partial_reasons", [])
    if safe_reason not in cr["partial_reasons"]:
        cr["partial_reasons"].append(safe_reason)
    if not info_only:
        cr["partial"] = True
        if not degraded:
            cr["blind"] = True
            cr.setdefault("blind_reasons", [])
            if safe_reason not in cr["blind_reasons"]:
                cr["blind_reasons"].append(safe_reason)
    emit_stderr(safe_reason, info_only=info_only)
```

Note what this deliberately does **not** do: it never writes `blind = False`. A run with no blind reason simply has no `blind` key, and an absent key reads as false everywhere. This keeps `current_run.json` byte-identical to today's for a degraded-only run, so no existing snapshot assertion moves.

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/state_io/ -v
```

Expected: all PASS, including the pre-existing `tests/state_io/` suite. `test_add_partial_stderr_emit.py` must stay green — it pins the CCE-74 emit-on-every-call behavior, which this change preserves.

- [ ] **Step 5: Commit**

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
git add scripts/state_io.py tests/state_io/test_add_partial_blind.py
git commit -m "$(cat <<'EOF'
feat(CCE-144): add_partial classifies blocking reasons blind or degraded

Blocking reasons are blind by default and flip current_run.blind plus
blind_reasons; degraded=True opts out and flips partial only; info_only
still touches neither and now takes precedence over degraded.

The default is the loud one on purpose. Failing open in the safe-looking
direction is what let a fully rate-limited run report success.

add_partial never writes blind=False, so a degraded-only run's
current_run.json is byte-identical to today's.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `_record_dispatch_reasons` passthrough and its seven callsites

**Files:**

- Modify: `scripts/orchestrator_runner.py` — `_record_dispatch_reasons` and its 7 callsites
- Modify: `tests/orchestrator/test_deferral_skip.py` — the monkeypatched spy
- Test: `tests/orchestrator/test_dispatch_reasons_classification.py` (create)

**Interfaces:**

- Consumes: `state_io.add_partial(state, reason, *, info_only=False, degraded=False)` from Task 1.
- Produces: `_record_dispatch_reasons(state, reasons, *, ok: bool, degraded: bool = False) -> None`.

**Background the implementer needs.** Every agent dispatch failure in the orchestrator routes through this one helper. It currently reads:

```python
def _record_dispatch_reasons(state: dict, reasons: list[str], *, ok: bool) -> None:
    for r in reasons:
        add_partial(state, r, info_only=ok)
```

`ok` is "the dispatch produced usable output". When `ok` is false the reasons explain dropped work and flip `partial`; after Task 1 they now also flip `blind`. That default is correct for five of the seven dispatch sites and wrong for two.

The seven callsites, with the classification the operator signed off:

| Callsite (search string)                                             | Agent             | `degraded=`         |
| -------------------------------------------------------------------- | ----------------- | ------------------- |
| `_record_dispatch_reasons(` immediately after the app-token env read | app-token         | omit (blind)        |
| `ok=sources is not None`                                             | source-collector  | omit (blind)        |
| `ok=summary is not None`                                             | pr-summarizer     | omit (blind)        |
| `ok=out is not None`                                                 | page-author       | **`degraded=True`** |
| `ok=validation is not None`                                          | content-validator | omit (blind)        |
| `ok=verdict is not None`                                             | gap-detector      | **`degraded=True`** |
| `ok=notifier_result is not None`                                     | notifier          | omit (blind)        |

Why those two and not the others: a page-author batch that never lands is folded into `deferred_pages_by_pr` by the complement writer, holding its PR out of the advance cursor — the work is retried, nothing is consumed. A gap-detector failure produces only an advisory PR note that is explicitly excluded from the CCE-101 auto-merge gate. Both are covered in the spec's **Classification** section; do not re-derive.

**The trap.** `tests/orchestrator/test_deferral_skip.py` monkeypatches `add_partial` with a spy whose signature is `def _spy(state, reason, *, info_only=False)`. The moment any callsite passes `degraded=`, that spy raises `TypeError: _spy() got an unexpected keyword argument 'degraded'` — reproduced empirically during spec validation. It must be widened in this task, in the same commit, or the suite breaks.

- [ ] **Step 1: Write the failing test**

Create `tests/orchestrator/test_dispatch_reasons_classification.py`:

```python
"""CCE-144: _record_dispatch_reasons carries the blind/degraded classification."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402

_record_dispatch_reasons = orun._record_dispatch_reasons


def test_failed_dispatch_is_blind_by_default():
    state: dict = {}
    _record_dispatch_reasons(state, ["dispatch exploded"], ok=False)
    cr = state["current_run"]
    assert cr["partial"] is True
    assert cr["blind"] is True
    assert cr["blind_reasons"] == ["dispatch exploded"]


def test_failed_dispatch_marked_degraded_is_not_blind():
    state: dict = {}
    _record_dispatch_reasons(state, ["author gave up"], ok=False, degraded=True)
    cr = state["current_run"]
    assert cr["partial"] is True
    assert cr.get("blind", False) is False
    assert cr.get("blind_reasons", []) == []


def test_successful_dispatch_stays_advisory_even_when_degraded_is_set():
    """ok=True means info_only=True, which outranks degraded."""
    state: dict = {}
    _record_dispatch_reasons(state, ["retry 1 of 3"], ok=True, degraded=True)
    cr = state["current_run"]
    assert cr["partial"] is False
    assert cr.get("blind", False) is False


def test_empty_reasons_touches_nothing():
    state: dict = {}
    _record_dispatch_reasons(state, [], ok=False)
    assert state.get("current_run", {}).get("blind", False) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/orchestrator/test_dispatch_reasons_classification.py -v
```

Expected: the two `degraded=`-passing tests FAIL with `TypeError: _record_dispatch_reasons() got an unexpected keyword argument 'degraded'`. `test_failed_dispatch_is_blind_by_default` and `test_empty_reasons_touches_nothing` should already PASS — they exercise Task 1's default through the unchanged helper. That is expected and correct.

- [ ] **Step 3: Add the passthrough**

In `scripts/orchestrator_runner.py`, replace the `_record_dispatch_reasons` signature and body:

```python
def _record_dispatch_reasons(
    state: dict, reasons: list[str], *, ok: bool, degraded: bool = False
) -> None:
    """Record dispatch reasons, classified.

    When the dispatch SUCCEEDED (``ok=True``) its reasons are retry/warning
    noise: they are recorded ``info_only`` and must NOT flip ``partial``.
    When the dispatch failed (``ok=False``) the reasons explain dropped work
    and DO flip ``partial``.

    Advisory layers (fact-checker, deterministic generators) record
    ``info_only=True`` directly and do not route through this helper.

    CCE-144: a failed dispatch is BLIND by default — the agent never answered,
    so the pipeline was prevented from judging. Pass ``degraded=True`` at the
    two callsites whose failure holds work back rather than consuming it
    (page-author, whose unlanded batch keeps its PR out of the advance cursor;
    gap-detector, whose output is advisory and outside the merge gate).
    ``ok=True`` outranks ``degraded`` — an advisory reason is advisory.
    """
    for r in reasons:
        add_partial(state, r, info_only=ok, degraded=degraded)
```

- [ ] **Step 4: Mark the two degraded callsites**

Find the page-author callsite — the one reading `ok=out is not None`:

```python
            _record_dispatch_reasons(state, reasons, ok=out is not None)
```

Replace with:

```python
            # CCE-144: degraded, not blind. An unlanded batch is folded into
            # deferred_pages_by_pr by the complement writer below, holding its
            # PR out of the advance cursor — the page is re-authored next run.
            _record_dispatch_reasons(
                state, reasons, ok=out is not None, degraded=True
            )
```

Find the gap-detector callsite — `ok=verdict is not None`:

```python
            _record_dispatch_reasons(state, reasons, ok=verdict is not None)
```

Replace with:

```python
            # CCE-144: degraded, not blind. gap-detector output feeds only a
            # PR note and is excluded from the CCE-101 auto-merge gate, so a
            # failure here consumes no docs content.
            _record_dispatch_reasons(
                state, reasons, ok=verdict is not None, degraded=True
            )
```

Leave the other five callsites exactly as they are. Their blind default is the intended classification.

- [ ] **Step 5: Widen the deferral-skip spy**

In `tests/orchestrator/test_deferral_skip.py`, find:

```python
    def _spy(state, reason, *, info_only=False):
        seen.append((reason, info_only))
        return _real_add_partial(state, reason, info_only=info_only)
```

Replace with:

```python
    def _spy(state, reason, *, info_only=False, degraded=False):
        # CCE-144 widened add_partial's signature; the spy must accept the new
        # kwarg and forward it, or every callsite that classifies a reason
        # raises TypeError through this monkeypatch.
        seen.append((reason, info_only))
        return _real_add_partial(
            state, reason, info_only=info_only, degraded=degraded
        )
```

`seen` keeps its `(reason, info_only)` shape deliberately — this test asserts on truncation sequencing, not on classification, and widening the tuple would churn its assertions for no gain.

- [ ] **Step 6: Run the tests**

Run:

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/orchestrator/test_dispatch_reasons_classification.py tests/orchestrator/test_deferral_skip.py -v
```

Expected: all PASS.

Then confirm nothing else regressed:

```bash
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/orchestrator/ -q
```

Expected: all PASS. If a test fails asserting a `0` return code, **stop and report it** — Task 4 renegotiates exit codes and this task must not.

- [ ] **Step 7: Commit**

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
git add scripts/orchestrator_runner.py tests/orchestrator/test_dispatch_reasons_classification.py tests/orchestrator/test_deferral_skip.py
git commit -m "$(cat <<'EOF'
feat(CCE-144): _record_dispatch_reasons carries the classification

All seven agent dispatch failures route through this one helper, so the
blind default reaches all of them at once. Five are correct that way.
page-author and gap-detector are not: an unlanded authoring batch is held
out of the advance cursor by the complement writer, and gap-detector output
is advisory and outside the merge gate. Both now pass degraded=True.

Widens the monkeypatched add_partial spy in test_deferral_skip, which
TypeErrors the moment any callsite passes the new kwarg.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Classify every blocking call site, and a test that keeps it classified

**Files:**

- Modify: `scripts/orchestrator_runner.py` — 25 direct blocking `add_partial` calls
- Modify: `scripts/verify_runner.py` — 3 direct blocking `add_partial` calls
- Test: `tests/orchestrator/test_classification_coverage.py` (create)

**Interfaces:**

- Consumes: `add_partial(..., degraded=...)` from Task 1.
- Produces: no new symbols. Produces the invariant every later task relies on — no blocking `add_partial` call may omit an explicit classification.

**The design, and why not a registry.** The obvious implementation is a registry in the test mapping each call site to its classification. It was prototyped and rejected: keys built from `enclosing_function::reason_token` **collide** in `verify_runner.py`, where three separate `for r in <reasons>: add_partial(state, r)` loops all key to the same string while carrying different classifications. A registry also decays — stale entries need pruning by hand, which is the very failure this test exists to prevent.

The rule instead:

> Every `add_partial` call in `scripts/orchestrator_runner.py` and `scripts/verify_runner.py` must pass an explicit classification keyword — `info_only` or `degraded`. A call passing neither fails the test.

The runtime default stays fail-safe (blind) to protect production if something slips through. The test forbids _relying_ on that default, so a newly added call site cannot silently inherit a classification nobody chose. Every site self-documents at the point of the call rather than in a distant table.

This means the seven blind sites carry an explicit `degraded=False`. That is verbose and intentional.

**The classification.** From the spec's **Classification** section, which is authoritative:

`degraded=False` (blind) — seven sites:

- the three `source_collector_invalid` / `source_collector_error` / `source_collector_partial` reasons
- the two `pr_summarizer_invalid` / `pr_summarizer_error` reasons
- `content_validator_invalid: returned None`
- `notifier_invalid: returned None`

`degraded=True` — eighteen sites: all four `time_budget_exceeded` reasons; the window-clip loop (`for r in clip_reasons`); `unknown_lens`; both `unsafe_page_path` reasons; `page_author_invalid`; both `lint_block_unsafe_path` reasons; `lint_block`; `gap_detector_invalid`; all four cursor-resolution reasons (`time_budget_no_advance_no_cursor`, `time_budget_no_advance_unanchored_deferred`, both `time_budget_advance_out_of_window`); `deferral_skip`.

In `scripts/verify_runner.py`: the publish-verifier reasons loop is `degraded=False`; the CircleCI poll-reasons loop and the notifier reasons loop are `degraded=True`.

The two pass-through loops in `run` — `for reason, info_only in pr_reasons:` and `for reason, info_only in merge_reasons:` — already pass `info_only=info_only`, so they satisfy the rule unchanged. Do not add `degraded` to them.

- [ ] **Step 1: Write the failing test**

Create `tests/orchestrator/test_classification_coverage.py`:

```python
"""CCE-144: every blocking add_partial call site must be explicitly classified.

The runtime default for a blocking reason is BLIND (fail-safe). This test
forbids *relying* on that default: a call site that passes neither
`info_only` nor `degraded` has been classified by nobody, and would inherit
red-or-green by accident. Adding a bare add_partial call fails this test.

Deliberately not a registry of site->classification: keys built from the
enclosing function plus reason token collide in verify_runner, where three
separate reason loops share a key but not a classification, and a registry
decays as sites move. Requiring explicitness at the call site cannot decay.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARDED_MODULES = ("scripts/orchestrator_runner.py", "scripts/verify_runner.py")


def _add_partial_calls(path: Path):
    """Yield (lineno, enclosing_function, keyword_names) per add_partial call."""
    tree = ast.parse(path.read_text())
    enclosing: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    enclosing.setdefault(child.lineno, node.name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name != "add_partial":
            continue
        yield (
            node.lineno,
            enclosing.get(node.lineno, "<module>"),
            {kw.arg for kw in node.keywords if kw.arg},
        )


@pytest.mark.parametrize("rel", GUARDED_MODULES)
def test_every_add_partial_call_is_explicitly_classified(rel):
    path = REPO_ROOT / rel
    unclassified = [
        f"{rel}:{lineno} in {fn}()"
        for lineno, fn, kwargs in _add_partial_calls(path)
        if not ({"info_only", "degraded"} & kwargs)
    ]
    assert not unclassified, (
        "add_partial call sites with no explicit classification:\n  "
        + "\n  ".join(unclassified)
        + "\n\nPass degraded=True if the run HELD BACK the work it could not "
        "process (self-healing, stays green), degraded=False if the run "
        "CONSUMED input it could not process (blind, turns the nightly red), "
        "or info_only=True if the reason is advisory. See the Classification "
        "section of the CCE-144 spec."
    )


def test_the_guard_actually_detects_a_bare_call(tmp_path):
    """Meta-test: exercise _add_partial_calls on an isolated probe, so a green
    result above means "all sites classified" and never "the walk found
    nothing".

    Deliberately does NOT read the guarded modules: a probe appended to their
    source would count every still-unclassified call alongside it, so the test
    could only pass after the classification landed — failing at the TDD red
    gate with a message blaming the walk, which is the one part that works.
    Reading a fixture instead makes it order-independent and lets it exercise
    the `.attr` branch, which no real call site currently covers.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(
        "def f(state):\n"
        "    add_partial(state, 'bare')\n"
        "    add_partial(state, 'degraded', degraded=True)\n"
        "    add_partial(state, 'advisory', info_only=True)\n"
        "    mod.add_partial(state, 'attribute-style')\n"
    )
    calls = list(_add_partial_calls(probe))
    assert len(calls) == 4, f"walk found {len(calls)} calls, expected 4"
    unclassified = [
        fn for _lineno, fn, kwargs in calls if not ({"info_only", "degraded"} & kwargs)
    ]
    assert len(unclassified) == 2, (
        "the walk must flag the bare call AND the attribute-style call; "
        f"it flagged {len(unclassified)}"
    )


def test_orchestrator_has_the_expected_call_site_population():
    """Tripwire on the audit's scope. Not a hard contract — if this fails
    because sites were legitimately added or removed, re-audit the new ones
    against the spec's Classification section and update the number here in
    the same commit that adds them."""
    calls = list(_add_partial_calls(REPO_ROOT / "scripts/orchestrator_runner.py"))
    assert len(calls) == 38, (
        f"expected 38 add_partial calls, found {len(calls)}; re-audit and "
        "update this count deliberately"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/orchestrator/test_classification_coverage.py -v
```

Expected, precisely:

- `test_every_add_partial_call_is_explicitly_classified[scripts/orchestrator_runner.py]` FAILS, listing **25** unclassified sites.
- `test_every_add_partial_call_is_explicitly_classified[scripts/verify_runner.py]` FAILS, listing **3**.
- `test_the_guard_actually_detects_a_bare_call` PASSES — it reads a `tmp_path` fixture, not the guarded modules, so it is green at every point in the sequence.
- `test_orchestrator_has_the_expected_call_site_population` PASSES (38 calls).

If the population tripwire fails, the file has drifted since the audit — report the actual number and stop; do not silently update it.

- [ ] **Step 3: Classify the orchestrator's 25 sites**

Work through the failure list from Step 2 top to bottom. For each site, add the kwarg from the classification above. Two worked examples:

A blind site — the source-collector fallback:

```python
        if sources is None:
            if not reasons:
                add_partial(
                    state, "source_collector_invalid: returned None", degraded=False
                )
            sources = {"prs": [], "jira_issues": []}
```

A degraded site — the canonical lint block:

```python
                    add_partial(
                        state,
                        f"lint_block: {fail['path']} {fail['rule']}: {fail['message']}",
                        degraded=True,
                    )
```

Do not reformat, reorder, or otherwise touch surrounding code. The diff for this step should be additions of a single keyword argument plus whatever line wrapping that requires.

Re-run after each cluster of edits to shrink the failure list:

```bash
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest "tests/orchestrator/test_classification_coverage.py::test_every_add_partial_call_is_explicitly_classified[scripts/orchestrator_runner.py]" -v
```

- [ ] **Step 4: Classify `verify_runner`'s 3 sites**

In `scripts/verify_runner.py`:

```python
            for r in verify_reasons:
                # CCE-144: blind. A failed publish-verifier dispatch means the
                # run could not judge whether the pages went live.
                add_partial(state, r, degraded=False)
```

```python
            for r in poll_reasons:
                # CCE-144: degraded. The CCE-63 CircleCI seam degrades on
                # purpose and reports an informational line.
                add_partial(state, r, degraded=True)
```

```python
        for r in notifier_reasons:
            # CCE-144: degraded. verify_runner's exit code is deliberately
            # unchanged by CCE-144; only orchestrator_runner.run returns 1
            # on blind. Classified so the coverage test is exhaustive.
            add_partial(state, r, degraded=True)
```

- [ ] **Step 5: Run the tests**

Run:

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/orchestrator/test_classification_coverage.py -v
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/ -q
```

Expected: coverage test all PASS. The full suite must be green **except** for tests that assert a `0` return code on a run that now records a blind reason — those are Task 4's business. Record any such failure in the commit body and leave it; do not fix it here.

- [ ] **Step 6: Commit**

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
git add scripts/orchestrator_runner.py scripts/verify_runner.py tests/orchestrator/test_classification_coverage.py
git commit -m "$(cat <<'EOF'
feat(CCE-144): classify every blocking add_partial site

28 blocking sites: 7 blind, 21 degraded (18 orchestrator + 3 verify_runner).
Classification is the spec's, signed off by the operator.

The coverage test requires an explicit classification kwarg rather than
maintaining a registry of sites. A registry was prototyped and rejected: its
enclosing-function-plus-token keys collide in verify_runner, where three
reason loops share a key but not a classification, and a registry decays as
sites move. Requiring explicitness at the call site cannot decay, and each
site documents itself where it lives.

The runtime default stays fail-safe blind; the test only forbids relying on
it, so a new call site cannot inherit red-or-green by accident.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `run` exits non-zero on a blind run

**Files:**

- Modify: `scripts/orchestrator_runner.py` — add `_exit_code`, change the three `return 0` sites in `run`
- Test: `tests/orchestrator/test_blind_run_interlocks.py` (create)

**Interfaces:**

- Consumes: `state["current_run"]["blind"]` from Task 1.
- Produces: `_exit_code(state: dict) -> int`. Tasks 5 and 6 append to the same test file.

**Background the implementer needs.** `run` has seven returns: `return 2` at three config-error sites, `return 1` at one site (the docs PR could not be opened), and `return 0` at three. Exit `1` is therefore **not** a new code — it already means "this run failed, read the reasons," which is exactly what blind means. Blind joins that class rather than competing with it. `2` stays with config errors.

All three `return 0` sites become `return _exit_code(state)`. The spec is explicit: _every existing `return 0` path keeps returning `0` unless the run is blind_. That includes the CCE-43 same-hour guard and the `no_pr` path — a blind run must not be able to escape through either.

- [ ] **Step 1: Write the failing test**

Create `tests/orchestrator/test_blind_run_interlocks.py`:

```python
"""CCE-144: the three consumers of the blind flag — exit code (Task 4),
watermark advance (Task 5), auto-merge gate (Task 6)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402


# --------------------------------------------------------------------------
# Task 4 — exit code
# --------------------------------------------------------------------------


def test_exit_code_is_1_when_blind():
    assert orun._exit_code({"current_run": {"partial": True, "blind": True}}) == 1


def test_exit_code_is_0_when_degraded_only():
    assert orun._exit_code({"current_run": {"partial": True}}) == 0


def test_exit_code_is_0_on_a_clean_run():
    assert orun._exit_code({"current_run": {"partial": False}}) == 0


def test_exit_code_is_0_when_current_run_is_absent():
    """Defensive: an early return before current_run exists must not crash."""
    assert orun._exit_code({}) == 0


def test_exit_code_treats_explicit_false_as_not_blind():
    assert orun._exit_code({"current_run": {"blind": False}}) == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/orchestrator/test_blind_run_interlocks.py -v
```

Expected: all five tests FAIL with `AttributeError: module 'orchestrator_runner' has no attribute '_exit_code'`. Collection itself succeeds — the module imports fine, the attribute simply does not exist yet.

- [ ] **Step 3: Implement `_exit_code`**

Add to `scripts/orchestrator_runner.py`, immediately after `_record_dispatch_reasons`:

```python
def _exit_code(state: dict) -> int:
    """CCE-144: 1 when the run is blind, else 0.

    Exit 1 is not a new code — `run` already returns 1 when the docs PR could
    not be opened, which is the same class of signal ("this run failed, read
    the reasons"). Blind joins that class rather than competing with it, so an
    operator reading only the run status takes the same action for both.
    Exit 2 stays with the config-error paths.

    The exit code is the alarm channel because it is the only one requiring
    zero provisioning: GitHub's native failure email and a red run-history
    entry need no secret, no webhook, no config. It is also the only channel
    that survives total quota exhaustion, since nothing in this path invokes
    the Claude CLI — which is exactly the outage it must report.
    """
    return 1 if (state.get("current_run") or {}).get("blind") else 0
```

- [ ] **Step 4: Route the three `return 0` sites through it**

In `run`, there are exactly three bare `return 0` statements. Replace each with `return _exit_code(state)`:

1. The CCE-43 same-hour guard.
2. The `if no_pr:` early return.
3. The final return at the end of the `try` block, after the notifier.

Verify you found all three and none remain:

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python - <<'PY'
import ast, pathlib
tree = ast.parse(pathlib.Path("scripts/orchestrator_runner.py").read_text())
fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")
nested = {id(x) for d in ast.walk(fn)
          if isinstance(d, (ast.FunctionDef, ast.AsyncFunctionDef)) and d is not fn
          for x in ast.walk(d)}
for n in ast.walk(fn):
    if isinstance(n, ast.Return) and id(n) not in nested:
        print(f"L{n.lineno}: return {ast.unparse(n.value)}")
PY
```

Expected: three `return 2`, one `return 1`, three `return _exit_code(state)`. No bare `return 0`.

- [ ] **Step 5: Run the tests and adjudicate the fallout**

Run:

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/orchestrator/test_blind_run_interlocks.py -v
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/ -q
```

Expected: new tests PASS. For the full suite: any pre-existing test that drives a fixture run producing a **blind** reason and asserts `rc == 0` will now fail. That is the intended behavior change, not a regression.

For each such failure, decide deliberately and record the decision in the commit body:

- if the fixture's failure is genuinely blind → update the assertion to `rc == 1` and add a one-line comment naming the blind reason
- if the fixture's failure should be degraded → **stop**, the classification in Task 3 is wrong; report it rather than adjusting the test to match the code

Do not batch-rewrite assertions. Each one is a claim about what that fixture means.

- [ ] **Step 6: Commit**

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
git add scripts/orchestrator_runner.py tests/orchestrator/test_blind_run_interlocks.py
git commit -m "$(cat <<'EOF'
feat(CCE-144): run exits 1 on a blind run

All three return-0 paths route through _exit_code, including the CCE-43
same-hour guard and the no_pr early return — a blind run must not escape
through either.

Exit 1 is not a new code: run already returns 1 when the docs PR could not
be opened, the same "this run failed" class blind belongs to. The exit code
is the alarm channel because it needs zero provisioning and is the only one
that survives the quota exhaustion it has to report.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: A blind run cannot advance the watermark

**Files:**

- Modify: `scripts/orchestrator_runner.py` — the `last_successful_run` assignment in `run`
- Test: `tests/orchestrator/test_blind_run_interlocks.py` (append)

**Interfaces:**

- Consumes: `state["current_run"]["blind"]` from Task 1.
- Produces: `_should_advance_watermark(state: dict) -> bool`.

**Background the implementer needs.** This is the change that closes a loss that has already occurred. The assignment is currently unconditional — its only enclosing block is the `try:` in `run`:

```python
        state["last_successful_run"] = {
            "head_sha": advance_sha,
            "completed_at": now,
        }
        if time_truncated:
            # CCE-43 guard support: record the window this truncated run
            # covered so a same-hour re-dispatch is recognized as already
            # processed (the cursor alone never equals HEAD).
            state["last_successful_run"]["window_head_sha"] = state["current_run"][
                "head_sha"
            ]
```

`last_successful_run` is a consume-once cursor. A window it skips is never re-read. On 2026-08-12 a blind run advanced it past three feature PRs, and that content was never documented.

**The subtlety that will bite you.** The `if time_truncated:` block mutates `state["last_successful_run"]`. If you guard only the assignment and leave that block outside the guard, a blind run writes `window_head_sha` into the **previous** run's `last_successful_run` dict — silently corrupting a cursor it was supposed to leave alone. Both statements go inside the guard.

- [ ] **Step 1: Write the failing test**

Append to `tests/orchestrator/test_blind_run_interlocks.py`:

```python
# --------------------------------------------------------------------------
# Task 5 — watermark interlock
# --------------------------------------------------------------------------


def _advance(state: dict, *, advance_sha: str, now: str, time_truncated: bool):
    """Mirror of the guarded advance in run(), exercised directly.

    run() is a ~1000-line function whose advance sits behind a full fixture
    dispatch; this pins the guard's logic in isolation.
    """
    if orun._should_advance_watermark(state):
        state["last_successful_run"] = {"head_sha": advance_sha, "completed_at": now}
        if time_truncated:
            state["last_successful_run"]["window_head_sha"] = state["current_run"][
                "head_sha"
            ]


def test_blind_run_does_not_advance_the_watermark():
    state = {
        "last_successful_run": {"head_sha": "old", "completed_at": "t0"},
        "current_run": {"partial": True, "blind": True, "head_sha": "new"},
    }
    _advance(state, advance_sha="new", now="t1", time_truncated=False)
    assert state["last_successful_run"] == {"head_sha": "old", "completed_at": "t0"}


def test_blind_truncated_run_does_not_write_window_head_sha_into_the_old_cursor():
    """The time_truncated block mutates last_successful_run in place. If it
    escapes the guard, a blind run corrupts the cursor it must not touch."""
    state = {
        "last_successful_run": {"head_sha": "old", "completed_at": "t0"},
        "current_run": {"partial": True, "blind": True, "head_sha": "new"},
    }
    _advance(state, advance_sha="new", now="t1", time_truncated=True)
    assert "window_head_sha" not in state["last_successful_run"]
    assert state["last_successful_run"]["head_sha"] == "old"


def test_degraded_run_still_advances():
    state = {
        "last_successful_run": {"head_sha": "old", "completed_at": "t0"},
        "current_run": {"partial": True, "head_sha": "new"},
    }
    _advance(state, advance_sha="new", now="t1", time_truncated=False)
    assert state["last_successful_run"]["head_sha"] == "new"


def test_degraded_truncated_run_still_records_window_head_sha():
    state = {
        "last_successful_run": {"head_sha": "old", "completed_at": "t0"},
        "current_run": {"partial": True, "head_sha": "new"},
    }
    _advance(state, advance_sha="cursor", now="t1", time_truncated=True)
    assert state["last_successful_run"]["window_head_sha"] == "new"


def test_clean_run_advances():
    state = {
        "last_successful_run": {"head_sha": "old", "completed_at": "t0"},
        "current_run": {"partial": False, "head_sha": "new"},
    }
    _advance(state, advance_sha="new", now="t1", time_truncated=False)
    assert state["last_successful_run"]["head_sha"] == "new"


def test_should_advance_is_true_when_current_run_is_absent():
    assert orun._should_advance_watermark({}) is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/orchestrator/test_blind_run_interlocks.py -v
```

Expected: the six Task 5 tests FAIL with `AttributeError: module 'orchestrator_runner' has no attribute '_should_advance_watermark'`. Task 4's five tests still PASS.

- [ ] **Step 3: Implement the predicate and the guard**

Add to `scripts/orchestrator_runner.py`, immediately after `_exit_code`:

```python
def _should_advance_watermark(state: dict) -> bool:
    """CCE-144: a blind run must not move `last_successful_run`.

    The cursor is consume-once — a window it skips is never re-read. On
    2026-08-12 a blind run advanced it past three feature PRs whose content
    was never authored, and that loss is permanent.

    Re-processing a window is cheap and idempotent. Skipping one is not, so
    the asymmetry decides: when in doubt, do not advance.

    Read at the moment of the advance. Every blind reason except
    `notifier_invalid` is recorded upstream of that point; the notifier's is
    recorded near the end of `run`, where it sets the exit code but cannot
    rewind a cursor that is already written — correctly, since a failed
    digest means the operator was not told, while the authoring work itself
    completed and its watermark is honest.
    """
    return not (state.get("current_run") or {}).get("blind")
```

Then wrap the advance in `run`:

```python
        if _should_advance_watermark(state):
            state["last_successful_run"] = {
                "head_sha": advance_sha,
                "completed_at": now,
            }
            if time_truncated:
                # CCE-43 guard support: record the window this truncated run
                # covered so a same-hour re-dispatch is recognized as already
                # processed (the cursor alone never equals HEAD).
                state["last_successful_run"]["window_head_sha"] = state[
                    "current_run"
                ]["head_sha"]
```

Both statements inside the guard. The `if time_truncated:` block mutates `last_successful_run` in place; left outside, it would write into the previous run's cursor.

- [ ] **Step 4: Run the tests**

Run:

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/orchestrator/test_blind_run_interlocks.py -v
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/orchestrator/ -q
```

Expected: all PASS. `tests/orchestrator/test_state_advancement_invariant.py` pins the CCE-40 advancement rules and must stay green — if it fails, read it before changing anything: it may be asserting a property this change deliberately narrows, which is a decision to report rather than to absorb.

- [ ] **Step 5: Commit**

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
git add scripts/orchestrator_runner.py tests/orchestrator/test_blind_run_interlocks.py
git commit -m "$(cat <<'EOF'
feat(CCE-144): a blind run cannot advance the watermark

last_successful_run is consume-once; a skipped window is never re-read. On
2026-08-12 a blind run advanced it past #211/#212/#213 and that content was
never documented. Re-processing a window is cheap and idempotent; skipping
one is not, and that asymmetry is the whole argument.

The time_truncated block goes inside the guard with the assignment. It
mutates last_successful_run in place, so leaving it outside would let a
blind run write window_head_sha into the previous run's cursor.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: A blind run cannot auto-merge

**Files:**

- Modify: `scripts/orchestrator_runner.py` — `_maybe_auto_merge` and its caller in `run`
- Modify: `CLAUDE.md` — the CCE-127 bullet's stale description of this gate
- Test: `tests/orchestrator/test_blind_run_interlocks.py` (append)

**Interfaces:**

- Consumes: `state["current_run"]["blind"]` from Task 1.
- Produces: `_maybe_auto_merge(..., blind: bool = False)`.

**Background the implementer needs.** This gap was found by adversarial review of the spec, which had claimed no code was needed here. The claim was true until CCE-140 (merged 2026-08-12) narrowed the gate from `if partial:` to:

```python
    if partial and not advance_cursor_backed:
        return skip("partial_run")
```

CCE-140's reasoning holds for a _degraded_ run: a cursor-backed advance moves the baseline only past PRs whose pages all landed, so merging promotes nothing unread. It does not transfer to a _blind_ run — the cursor proves the baseline is honest about what the run **saw**, and a blind run did not see.

The gap is reachable, not theoretical. A run truncated by the CCE-109 time budget sets `advance_cursor_backed = True`. If its content-validator dispatch then returns `None`, the run is blind, partial, and cursor-backed at once. `_MERGE_VETO_REASON_PREFIXES` is `("app_token_unavailable",)`, which does not match `content_validator_invalid`, so no veto fires; `partial and not True` is false, so the gate opens. `merge_deadline` is also disabled on the cursor-backed path, removing the time-budget skip that might have caught it.

Leave `_MERGE_VETO_REASON_PREFIXES` alone. Once `app_token_unavailable` classifies as blind the entry is redundant, but removing it is a separate behavior change with its own risk, and the redundancy costs nothing.

- [ ] **Step 1: Write the failing test**

Append to `tests/orchestrator/test_blind_run_interlocks.py`:

```python
# --------------------------------------------------------------------------
# Task 6 — auto-merge interlock
# --------------------------------------------------------------------------

import pytest


class _ExplodingGh:
    """Any gh access means the gate let the run through when it should not.

    __getattr__ rather than a single stub method: the gate must be proven to
    return BEFORE it touches the client at all, and hard-coding one method
    name would silently pass if the implementation reached for a different
    one first.
    """

    def __getattr__(self, name):  # pragma: no cover - must not run
        raise AssertionError(
            f"reached gh.{name}; the blind gate did not skip"
        )


_MERGE_SETTINGS = {
    "policy": "auto",
    "checks_grace_seconds": 1,
    "checks_timeout_seconds": 1,
}


def _call(*, blind, partial, cursor_backed, gh=None, reasons=()):
    return orun._maybe_auto_merge(
        gh if gh is not None else _ExplodingGh(),
        pr_number=1,
        partial=partial,
        blind=blind,
        fact_warnings=[],
        merge_settings=dict(_MERGE_SETTINGS),
        build_workflow=None,
        deadline=None,
        clock=lambda: 0.0,
        sleep=lambda _s: None,
        advance_cursor_backed=cursor_backed,
        partial_reasons=tuple(reasons),
    )


def test_blind_and_cursor_backed_does_not_merge():
    """The case current code merges. This is the regression test for CCE-144's
    auto-merge interlock: blind + time-truncated + cursor-backed passes the
    CCE-140 gate and reaches the merge path today."""
    outcome, reasons = _call(blind=True, partial=True, cursor_backed=True)
    assert outcome["merged"] is False
    assert outcome["reason"] == "blind_run"
    assert any("auto_merge_skipped: blind_run" in r for r, _info in reasons)


def test_blind_without_cursor_backing_skips_as_blind_not_partial():
    """Both gates would stop this run. Asserting the REASON is the point: if
    the blind gate is removed, partial_run silently covers for it and a
    weaker assertion would still pass."""
    outcome, _reasons = _call(blind=True, partial=True, cursor_backed=False)
    assert outcome["reason"] == "blind_run"


def test_blind_gate_precedes_the_cce140_carve_out():
    """A blind run that is somehow not marked partial must still be stopped."""
    outcome, _reasons = _call(blind=True, partial=False, cursor_backed=True)
    assert outcome["reason"] == "blind_run"


def test_degraded_and_cursor_backed_still_reaches_the_merge_path():
    """CCE-140 must survive CCE-144. If the blind classification over-reaches
    into the time-budget reasons, this fails — which is the alarm-fatigue
    guard expressed as a test."""
    with pytest.raises(AssertionError, match="the blind gate did not skip"):
        _call(blind=False, partial=True, cursor_backed=True)
    # Sanity: the same call with blind=True must NOT raise, or the assertion
    # above would pass for the wrong reason (e.g. a stub that always throws).
    outcome, _ = _call(blind=True, partial=True, cursor_backed=True)
    assert outcome["reason"] == "blind_run"


def test_veto_still_wins_for_a_non_blind_run():
    outcome, _reasons = _call(
        blind=False,
        partial=True,
        cursor_backed=True,
        reasons=("app_token_unavailable: mint failed",),
    )
    assert outcome["reason"] == "merge_vetoed"


def test_manual_policy_is_unchanged_by_blind():
    outcome, reasons = orun._maybe_auto_merge(
        _ExplodingGh(),
        pr_number=1,
        partial=True,
        blind=True,
        fact_warnings=[],
        merge_settings={"policy": "manual"},
        build_workflow=None,
        deadline=None,
        clock=lambda: 0.0,
        advance_cursor_backed=True,
        partial_reasons=(),
    )
    assert outcome["reason"] == "policy_manual"
    assert reasons == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/orchestrator/test_blind_run_interlocks.py -v -k "merge or blind_run or veto or manual"
```

Expected: every Task 6 test that passes `blind=` FAILs with `TypeError: _maybe_auto_merge() got an unexpected keyword argument 'blind'`.

- [ ] **Step 3: Add the gate**

In `_maybe_auto_merge`, add the parameter to the keyword-only block, next to `advance_cursor_backed`:

```python
    advance_cursor_backed: bool = False,
    blind: bool = False,
    partial_reasons: tuple[str, ...] = (),
```

Add to the docstring, after the CCE-140 paragraph:

```
    CCE-144: `blind` skips unconditionally, ahead of the CCE-140 carve-out.
    A cursor-backed advance proves the baseline is honest about what the run
    SAW; a blind run did not see. The reachable case is a time-truncated run
    (advance_cursor_backed=True) whose content-validator dispatch returned
    None — blind, partial, and cursor-backed at once, matching no entry in
    _MERGE_VETO_REASON_PREFIXES.
```

Insert the gate immediately after the veto check and **before** the CCE-140 test:

```python
    veto = merge_veto_reason(partial_reasons)
    if veto:
        return skip("merge_vetoed", veto)
    if blind:
        # CCE-144. Ahead of the CCE-140 carve-out below on purpose: a
        # cursor-backed advance is not evidence for a run that was prevented
        # from judging. Gating on the computed flag rather than extending
        # _MERGE_VETO_REASON_PREFIXES closes the whole class of blind reasons
        # instead of one hand-listed member of it.
        return skip("blind_run")
    if partial and not advance_cursor_backed:
```

- [ ] **Step 4: Pass it at the callsite**

In `run`, the `_maybe_auto_merge(...)` call gains one argument alongside `advance_cursor_backed`:

```python
            advance_cursor_backed=advance_cursor_backed,
            blind=bool(state["current_run"].get("blind")),
            partial_reasons=tuple(state["current_run"]["partial_reasons"]),
```

- [ ] **Step 5: Correct the stale CLAUDE.md bullet**

In `CLAUDE.md`, the CCE-127 bullet describes this gate as `if partial: return skip("partial_run")`. That has been wrong since CCE-140, and it is where the CCE-144 spec inherited the error. Find:

```
Flipping `partial` reuses the existing `_maybe_auto_merge` interlock (`if partial: return skip("partial_run")`)
```

Replace with:

```
Flipping `partial` reuses the existing `_maybe_auto_merge` interlock (since CCE-140 the gate is `if partial and not advance_cursor_backed`, and `app_token_unavailable` is additionally covered by `_MERGE_VETO_REASON_PREFIXES`; since CCE-144 a blind run is skipped unconditionally ahead of both)
```

- [ ] **Step 6: Run the tests**

Run:

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/orchestrator/test_blind_run_interlocks.py -v
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/ -q
```

Expected: all PASS. Pay attention to any existing auto-merge suite — if a test asserts a partial cursor-backed run merges, confirm its fixture produces no blind reason. If it does produce one, the test now correctly does not merge and its assertion moves; record why in the commit body.

- [ ] **Step 7: Commit**

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
git add scripts/orchestrator_runner.py tests/orchestrator/test_blind_run_interlocks.py CLAUDE.md
git commit -m "$(cat <<'EOF'
feat(CCE-144): a blind run cannot auto-merge

Found by adversarial review of the spec, which had claimed no code was
needed here. True until CCE-140 narrowed the gate from `if partial` to
`if partial and not advance_cursor_backed`. That carve-out is sound for a
degraded run and invalid for a blind one: the cursor proves the baseline is
honest about what the run SAW, and a blind run did not see.

Reachable path: a time-budget-truncated run sets advance_cursor_backed, its
content-validator returns None, and content_validator_invalid matches no
entry in the one-element _MERGE_VETO_REASON_PREFIXES allowlist. Gate opens.

Gating on the computed blind flag rather than extending that allowlist
closes the class instead of one hand-listed member — the allowlist is scar
tissue from this same mistake made once already.

Also corrects CLAUDE.md's CCE-127 bullet, which still described the gate in
its pre-CCE-140 form and is where the spec inherited the error.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Repair the workflow diagnostic, and document the change

**Files:**

- Modify: `.github/workflows/docs-agent-nightly.yml` — the `Print partial-run reasons` step
- Modify: `templates/workflow-run.yml` — the same step
- Modify: `CLAUDE.md` — add the CCE-144 bullet
- Test: `tests/templates/` — parity suite must stay green; audit its divergence list

**Interfaces:**

- Consumes: `current_run.blind_reasons` from Task 1.
- Produces: nothing consumed by later tasks. This is the final task.

**Background the implementer needs.** This is the third independent layer of silence, and it is a decomposition casualty. The step greps `.engineering-docs-agent/state.json` for `.current_run.partial_reasons`. But `state_io.save_persistent_state` filters `_EPHEMERAL_KEYS = ("current_run",)` before writing — the reasons go to the sibling `current_run.json`, which the workflow never reads. `state.json` on disk contains exactly `last_successful_run` and `version`. The step prints nothing, always, and exits 0 either way, which is indistinguishable from a run with no reasons.

The step was added when `partial_reasons` lived in `state.json`. The later ephemeral split moved the key for good reasons — merge-as-promotion should commit only durable state — and the reader was never updated.

**Both files carry this step.** Repair both.

**CI does not lint `templates/`.** `.github/workflows/actionlint.yml` runs bare `actionlint`, which searches `.github/workflows/` only. Template changes must be linted explicitly. That gap is plausibly how the template drifted from the dogfood during CCE-127.

- [ ] **Step 1: Repair the dogfood workflow**

In `.github/workflows/docs-agent-nightly.yml`, replace the `Print partial-run reasons` step:

```yaml
- name: Print partial-run reasons
  # CCE-73: echo the run's partial reasons to stdout so they show in
  # `gh run view --log` even when the run-summary block is collapsed.
  # CCE-144: read current_run.json, NOT state.json. save_persistent_state
  # strips _EPHEMERAL_KEYS = ("current_run",) before writing state.json,
  # so this step read a key that is never there and printed nothing on
  # every run since the ephemeral split — indistinguishable from a clean
  # run. Blind reasons print under their own label: they are the subset
  # that turns the run red.
  if: always()
  shell: bash
  run: |
    run_file=".engineering-docs-agent/current_run.json"
    if [ -f "$run_file" ]; then
      jq -r '.current_run.partial_reasons[]? // empty' "$run_file" || true
      jq -r '.current_run.blind_reasons[]? // empty | "BLIND: " + .' "$run_file" || true
    fi
```

`// empty` keeps it null-safe and `|| true` keeps a malformed file from failing the step — both preserved from the original.

- [ ] **Step 2: Apply the identical repair to the template**

Make the same change to the `Print partial-run reasons` step in `templates/workflow-run.yml`. The `run:` body must be byte-identical to the dogfood's; only surrounding template-specific content may differ.

- [ ] **Step 3: Lint both files**

Run:

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
actionlint .github/workflows/docs-agent-nightly.yml
actionlint templates/workflow-run.yml
```

Expected: no output from either (actionlint is silent on success).

If `actionlint` is not installed, report that and run the YAML parse check instead — do not skip verification silently:

```bash
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -c "
import yaml, pathlib
for p in ('.github/workflows/docs-agent-nightly.yml', 'templates/workflow-run.yml'):
    yaml.safe_load(pathlib.Path(p).read_text())
    print(f'{p}: parses')
"
```

- [ ] **Step 4: Verify the jq expressions against real data**

A YAML parse proves nothing about the `jq` filter, and a wrong filter fails exactly the way the original bug did — silently, printing nothing. Exercise it against a synthetic file with the real shape:

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
cat > /tmp/cce144_probe.json <<'EOF'
{"current_run": {"partial": true, "blind": true,
 "partial_reasons": ["lint_block: a.md rule: msg", "source_collector_invalid: returned None"],
 "blind_reasons": ["source_collector_invalid: returned None"]}}
EOF
jq -r '.current_run.partial_reasons[]? // empty' /tmp/cce144_probe.json
jq -r '.current_run.blind_reasons[]? // empty | "BLIND: " + .' /tmp/cce144_probe.json
echo "--- and against a degraded-only run (no blind key) ---"
echo '{"current_run": {"partial": true, "partial_reasons": ["lint_block: a.md rule: msg"]}}' > /tmp/cce144_probe2.json
jq -r '.current_run.partial_reasons[]? // empty' /tmp/cce144_probe2.json
jq -r '.current_run.blind_reasons[]? // empty | "BLIND: " + .' /tmp/cce144_probe2.json
echo "(no BLIND line above is correct)"
rm -f /tmp/cce144_probe.json /tmp/cce144_probe2.json
```

Expected: two reason lines then one `BLIND: source_collector_invalid: returned None`; then one reason line and no `BLIND:` line.

- [ ] **Step 5: Audit the template-parity divergence list**

Run:

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/templates/ -v
```

Expected: all PASS.

Then read `_TEMPLATE_ONLY_DIVERGENCES` in `tests/templates/test_workflow_run_parity.py` and check whether this change makes any entry stale. CCE-127's meta-lesson is that documenting a divergence converts an unexamined gap into an accepted one and stops anyone re-examining it; nothing detects staleness automatically, so it must be read by a person whenever a safety property lands on one side. Report what you found either way — "audited, no entry affected" is a valid and expected result.

- [ ] **Step 6: Add the CLAUDE.md bullet**

Append to the plugin-conventions bullet list in `CLAUDE.md`:

```markdown
- **A blind run exits non-zero, freezes the watermark, and cannot auto-merge (CCE-144).** `partial` conflated two conditions with opposite meanings. The split: **blind** = the run CONSUMED input it could not process (`source_collector_*`, `pr_summarizer_*`, `content_validator_invalid`, `notifier_invalid`, `app_token_unavailable`); **degraded** = the run HELD BACK what it could not process (every `time_budget_exceeded`, `lint_block*`, `unsafe_page_path`, `unknown_lens`, `page_author_invalid`, `gap_detector_invalid`, the cursor-resolution failures, `deferral_skip`). `partial` remains the union. The complement writer (the only writer of `deferred_pages_by_pr`) is what decides which: `page_author_invalid` is degraded because an unlanded batch holds its PR out of the advance cursor, while `content_validator_invalid` is blind because those pages are already in `landed_batches` and the cursor walks past them. `state_io.add_partial` gains `degraded=True` as the opt-out and stays the single writer of `partial_reasons`, `blind`, and `blind_reasons`; **blocking reasons are blind by DEFAULT** so an unclassified new failure mode is loud, not silent. Three consumers read the flag: `_exit_code` (1, sharing the code `run` already returns when the PR can't be opened), `_should_advance_watermark`, and `_maybe_auto_merge`'s `blind` gate. Four traps: (1) **the auto-merge gate is not `if partial`** — CCE-140 narrowed it to `if partial and not advance_cursor_backed`, so a blind + time-truncated + cursor-backed run reaches the merge path; the blind gate goes ahead of that carve-out, and gating on the computed flag rather than extending the one-entry `_MERGE_VETO_REASON_PREFIXES` allowlist closes the class instead of one member. (2) **The `time_budget_exceeded` sites MUST stay degraded** — marking them blind turns every truncated run red and freezes its advance, deleting the cursor-backed advance CCE-140 exists to produce and reinstating the CCE-109 doom loop permanently; `tests/orchestrator/test_blind_run_interlocks.py` asserts a degraded cursor-backed run still merges, as the alarm-fatigue guard. (3) **The `if time_truncated:` block goes inside the watermark guard** — it mutates `last_successful_run` in place, so left outside it lets a blind run write `window_head_sha` into the previous run's cursor. (4) **`_record_dispatch_reasons` is the single path for all seven agent dispatches**, so the blind default reaches all of them at once; page-author and gap-detector pass `degraded=True`, and each agent additionally has a direct `add_partial` fallback for when the dispatch reported nothing — both paths must carry the same classification or a failure changes colour depending on whether it managed to explain itself. `tests/orchestrator/test_classification_coverage.py` requires an explicit classification kwarg at every blocking call site (a registry was prototyped and rejected — its keys collide in `verify_runner` and it decays). Incident: runs `31472240064` and `31579090583` both reported `conclusion: success` with every subagent rate-limited; PR #215 then merged a watermark advance past #211/#212/#213, whose content is permanently undocumented. Spec: `docs/superpowers/specs/2026-08-13-cce144-blind-run-detection-design.md`. Reference: CCE-144 (2026-08-13).
```

- [ ] **Step 7: Run the full integrated suite**

Per CLAUDE.md, merge only on a green _integrated_ suite — never on GitHub's mergeable flag.

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
git fetch origin
git merge origin/main --no-edit
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest -q
```

Expected: all PASS against the combined tree. `git fetch` first — `origin/main` goes stale after an API-side merge.

- [ ] **Step 8: Commit**

```bash
cd /private/tmp/claude-501/-Users-theo-Projects-engineering-docs-agent/68c365a3-5685-4cb8-90de-3caac1bd51ad/scratchpad/cce144
git add .github/workflows/docs-agent-nightly.yml templates/workflow-run.yml CLAUDE.md
git commit -m "$(cat <<'EOF'
fix(CCE-144): the partial-reasons diagnostic reads the file that has them

The step grepped state.json for .current_run.partial_reasons, but
save_persistent_state strips _EPHEMERAL_KEYS = ("current_run",) before
writing, so the key is never there. It printed nothing on every run since
the ephemeral split and exited 0 either way — indistinguishable from a run
with no reasons, which is worse than no diagnostic because it suppresses
inquiry. Repointed at current_run.json; blind reasons print under their own
label.

Applied to both the dogfood workflow and templates/workflow-run.yml, and
both linted explicitly: CI runs bare actionlint, which searches
.github/workflows/ only, so template drift is invisible to it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**1. Spec coverage.**

| Spec section                                                  | Task |
| ------------------------------------------------------------- | ---- |
| Fail-safe by default (`add_partial` + `degraded`)             | 1    |
| New state fields (`blind`, `blind_reasons`)                   | 1    |
| `_record_dispatch_reasons` passthrough + 2 degraded callsites | 2    |
| Classification (7 blind / 21 degraded incl. `verify_runner`)  | 3    |
| Classification-coverage test                                  | 3    |
| Exit code                                                     | 4    |
| Watermark interlock                                           | 5    |
| Auto-merge interlock                                          | 6    |
| Workflow repair, both files, explicit actionlint              | 7    |
| Template-parity divergence audit                              | 7    |
| CLAUDE.md CCE-127 correction                                  | 6    |
| CLAUDE.md CCE-144 bullet                                      | 7    |

Spec sections with no task, deliberately: **Out of scope** — the Slack `curl` alarm, moving the cron, enabling notifications, and recovering the three lost PRs. All four are named in the spec as excluded, and three require operator action no code change can perform. `templates/state.schema.json` is untouched by design: the new fields live on `current_run`, which `save_persistent_state` strips, so they never reach `state.json`.

**2. Placeholder scan.** No TBD/TODO. Every code step carries the actual code. Every test step carries the actual assertions. No "similar to Task N".

**3. Type consistency.** Verified across tasks: `add_partial(state, reason, *, info_only: bool = False, degraded: bool = False) -> None` (Task 1) is called with `degraded=` in Tasks 2 and 3. `_record_dispatch_reasons(state, reasons, *, ok: bool, degraded: bool = False)` (Task 2) matches its 7 callsites. `_exit_code(state: dict) -> int` (Task 4) and `_should_advance_watermark(state: dict) -> bool` (Task 5) are both imported by name in `test_blind_run_interlocks.py`. `_maybe_auto_merge(..., blind: bool = False, ...)` (Task 6) matches the callsite kwarg and every test invocation. State keys are spelled `blind` and `blind_reasons` throughout.

**4. The red-gate predictions were executed, not asserted.** Adversarial review of a first draft found three predictions wrong, each of which would have cost a task cycle: the dotted `from scripts.orchestrator_runner import …` that four tasks used does not work at all (the module has no self-insert, unlike `state_io.py` and `verify_runner.py`); a meta-test that counted every unclassified call alongside its probe, so it could only go green _after_ the step it was meant to gate, failing with a message blaming the AST walk; and a blanket "9 tests fail first" claim that was wrong for 3 of 12 cases, where the step's own rule would have directed the implementer to break three deliberate regression guards.

Both testable files were therefore extracted from this plan, written to the tree, and run before this plan was committed:

- `tests/state_io/test_add_partial_blind.py` → **9 failed, 3 passed**, and the three passing are exactly `test_info_only_flips_neither`, `test_seeded_current_run_is_not_clobbered[default]`, and `[info_only]`.
- `tests/orchestrator/test_classification_coverage.py` → **2 failed, 2 passed**; the failures list 25 sites in `orchestrator_runner.py` and 3 in `verify_runner.py`, and both meta-tests are green.

Both files were then removed. Tasks 4–6's `AttributeError` predictions follow from the same verified import preamble but were not executed, since their subjects do not exist yet.

**One residual risk, flagged rather than hidden.** Task 3's classification changes the exit code of existing fixture-driven tests, and Task 4 Step 5 is where that surfaces. The plan instructs the implementer to adjudicate each such test individually and to **stop and report** rather than adjust a test to match the code when the two disagree — a test asserting `rc == 0` on a run that is genuinely blind is a test encoding the bug. The number of affected tests is deliberately not predicted here: one verifier's estimate of "at least 18" was refuted as inflated roughly fifty-fold by counting unrelated assertions, and a fabricated number would be worse than none.
