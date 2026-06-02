# CCE-74 — Extend `add_partial` stderr emission to broader call sites

**Jira:** [CCE-74](https://designitright.atlassian.net/browse/CCE-74) (Task, Backlog, Low priority, labels: observability / orchestrator / p3 / tech-debt)
**Builds on:** [CCE-73](https://designitright.atlassian.net/browse/CCE-73) (PR #93 merged 2026-06-01 — `_record_failure` + exit-1 stderr dump inside `open_or_append_pr`)
**Related:** CCE-48 (PR body / step summary digest), CCE-75 (PR #97/#98 — `_stage_docs_run_changes` polish)

## Problem statement

CCE-73 fixed silent exit-1 inside `open_or_append_pr` by emitting recorded `partial_reasons` to stderr at the source. The fix is scoped to **7 failure paths inside `open_or_append_pr`** (all routed through `_record_failure` at `scripts/orchestrator_runner.py:1849`) plus the **exit-1 dump at `scripts/orchestrator_runner.py:1410-1416`** in `run()`.

It does NOT cover:

- **22+ `add_partial(state, ...)` sites in `run()`** at `scripts/orchestrator_runner.py` lines 1015, 1049, 1052, 1056, 1058, 1076, 1116, 1119, 1122, 1145, 1151, 1154, 1179, 1182, 1206, 1209, 1288, 1306, 1317, 1346, 1349, 1399, 1452, 1455 — these record reasons silently with zero log signal
- **3 `lint_block` direct mutations** at `scripts/orchestrator_runner.py:1223`, `1231`, `1268` that bypass `add_partial` entirely (directly mutate `state["current_run"]["partial_reasons"]` + set `partial=True`)
- **2 `verify_runner.py` direct writes** at lines 79-81 and 101-104 (using the `setdefault().setdefault().append(r); state["current_run"]["partial"] = True` chain) — **note: line 49 is a notifier digest field, NOT a state write; out of scope**
- **9 raw `print(..., file=sys.stderr)` sites** at lines 643, 683, 969, 975, 981, 1493, 1498, 1503, 1508 that lack `flush=True`, vulnerable to the same GitHub Actions block-buffering bug CCE-73 fixed (the existing exit-1 dump at line 1412 is a 10th site that is also routed through the new helper)
- **Exit-0 partial runs** — a run that records partial reasons but completes notifier dispatch returns `0` at line 1458, leaving the workflow log with no signal that anything went wrong

Operationally: if a future failure originates in any phase outside `open_or_append_pr` and the orchestrator exits 1, the existing exit-1 dump at 1412 catches it. But if the orchestrator exits 0 with a partial PR (notifier completes, PR body says WARNING-Partial), the workflow log shows green and the operator has no signal to look at state.json.

## Scope

**IN scope:**

1. Add stderr emission to every `add_partial` call site via a refactor of `state_io.add_partial` itself (the centralized helper).
2. Refactor 3 `lint_block` direct mutations (`scripts/orchestrator_runner.py:1223`, `1231`, `1268`) to use `add_partial`.
3. Refactor 2 `verify_runner.py` direct writes (lines 79-81, 101-104) to use `add_partial`. **Leave line 49 untouched — it is a notifier digest field, not a state mutation.**
4. Add a NEW shutdown-dump helper `_emit_shutdown_dump(state)` called from `run()`'s finally block to surface partial reasons on exit-0 partial runs. Do NOT move the existing exit-1 dump at line 1412 — keep it as a belt-and-suspenders.
5. Replace 9 raw `print(..., file=sys.stderr)` sites (lines 643, 683, 969, 975, 981, 1493, 1498, 1503, 1508) with a new `emit_log(text)` helper that locks `flush=True`. Additionally route the existing exit-1 dump at line 1412-1416 through `emit_log` (10 sites total). The single intentional remaining direct `print(..., file=sys.stderr)` is `_record_failure` at line 1862, which stays direct because it must fire before any later crash.
6. Move `_redact_credentials` from `scripts/orchestrator_runner.py:1835` into a new leaf module `scripts/stderr_emit.py`.
7. Address 5 of 6 CCE-73 verification-panel nice-to-haves (skip #2 per validator panel — see "Decisions" below).

**OUT of scope:**

- Structured key=value stderr emission (deferred; current free-text + class-prefix convention is greppable)
- A `reason_class` kwarg on the emit helper (speculative)
- pytest conftest changes (verified: zero `capsys.readouterr().err == ""` equality assertions exist in `tests/`; no mitigation needed)
- New partial_reasons categories (separate observability question)
- Deletion of `_record_failure` (would break 16 test call sites in `tests/orchestrator/test_open_or_append_pr.py`; double-emit on the `open_or_append_pr` path is intentional belt-and-suspenders)
- Changes to `verify_runner.py:49` (notifier digest field)

## Architecture

### New module: `scripts/stderr_emit.py`

**Single-purpose leaf module** holding stderr write helpers + redaction. Imports stdlib only (`sys`, `re`). **Does NOT import from `state_io.py` or `orchestrator_runner.py`** — this invariant is locked by a dedicated test (see "Tests").

```python
"""stderr_emit — single point for stderr writes from the docs-agent pipeline.

This is a LEAF module: it imports only stdlib (sys, re) and is depended on by
state_io.py and orchestrator_runner.py. It MUST NOT import from state_io or
orchestrator_runner — doing so creates a cycle that breaks state_io's role as
the data layer. If structured emit is wanted later, build a separate module
that wraps these helpers; do NOT retrofit state into stderr_emit.

The flush=True invariant is locked via _OBSERVABILITY_FLUSH so a future
copy-paste cannot drop it.
"""
import re
import sys

_OBSERVABILITY_FLUSH = True

# Pattern and substitution kept identical to pre-CCE-74
# orchestrator_runner._CREDENTIAL_URL_RE (line 1832) so callers migrated in
# implementation step 5 (and the existing test_open_or_append_pr.py:779
# assertion `"<redacted>" in err`) see no behavioral change. Matches both
# http:// and https://; replaces any user[:pass] segment with `<redacted>`.
_CREDENTIAL_URL_RE = re.compile(r"(https?://)[^@/\s]*@")


def _redact_credentials(text: str) -> str:
    """Replace `https?://user[:token]@host` with `https?://<redacted>@host`.

    Idempotent. Returns the input verbatim if no credential pattern matches.
    Moved verbatim from scripts/orchestrator_runner.py:1832-1846 (CCE-73 origin).
    """
    return _CREDENTIAL_URL_RE.sub(r"\1<redacted>@", text)


def emit_stderr(reason: str, *, info_only: bool = False) -> None:
    """Emit a redacted reason to stderr with PARTIAL or INFO prefix.

    Called from state_io.add_partial on every call (not just newly-appended)
    so retry-loop sequencing is visible — a flaky upstream calling back with
    the same reason 10x produces 10 stderr lines, surfacing the retry storm.
    State-side dedup at state_io.py still applies; stderr is the unbounded
    log stream.

    Side-effect-only. Best-effort: OSError on stderr is caught and discarded
    so a closed/broken stderr cannot crash the orchestrator.
    """
    prefix = "INFO" if info_only else "PARTIAL"
    safe = _redact_credentials(reason)
    try:
        print(f"docs-agent {prefix}: {safe}", file=sys.stderr, flush=_OBSERVABILITY_FLUSH)
    except OSError:
        # Diagnostic stream failure must never crash the orchestrator.
        pass


def emit_log(text: str) -> None:
    """Raw-text stderr emit with flush=True. No prefix, no redaction.

    For operator diagnostic lines that are not partial_reasons: bootstrap
    progress, exception messages from non-credential code paths, etc.
    Replaces existing `print(..., file=sys.stderr)` calls at
    scripts/orchestrator_runner.py lines 643, 683, 969, 975, 981, 1493,
    1498, 1503, 1508 — locks flush=True so a future contributor cannot
    drop it via copy-paste from older code.

    Best-effort: OSError swallowed (same rationale as emit_stderr).
    """
    try:
        print(text, file=sys.stderr, flush=_OBSERVABILITY_FLUSH)
    except OSError:
        pass
```

### Modified: `scripts/state_io.py:add_partial`

**Two changes:**

1. **Redact at entry** — call `stderr_emit._redact_credentials` on `reason` BEFORE writing to `state.partial_reasons`. This extends CCE-73's post-redact-then-append invariant (currently scoped to the 7 `_record_failure` sites in `open_or_append_pr`) to all 28+ `add_partial` sites. Future addition of an `add_partial` call site whose reason interpolates a subprocess result containing `https://x-access-token:ghs_xxx@github.com/...` cannot write the raw token to `state.json`.

2. **Emit unconditionally** — call `stderr_emit.emit_stderr(reason, info_only=info_only)` AFTER the state mutation, on EVERY call. State-side dedup at line 233 (existing `if reason not in cr["partial_reasons"]`) is preserved (avoids `state.json` bloat); stderr emit fires whether the reason was newly appended or a duplicate. Validator V3's rationale: retry-loop sequencing is the signal CCE-73 was designed to preserve, and a 10× retry storm hidden behind dedup is exactly the regression we're shipping to prevent.

Final shape:

```python
from stderr_emit import _redact_credentials, emit_stderr  # at top of state_io.py

def add_partial(state: dict, reason: str, *, info_only: bool = False) -> None:
    """Append a partial reason to current_run.partial_reasons.

    When info_only is False (default), also flip current_run.partial to True.
    When info_only is True, leave current_run.partial unchanged — the reason
    is informational, not a degradation of the run's data quality.

    Idempotent for state: a reason already present is not appended again.

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
    emit_stderr(safe_reason, info_only=info_only)
```

**Order matters:** redact → write state → emit. If `emit_stderr` raised (it doesn't — OSError-swallowed — but defensively), state would still be correctly mutated. The opposite order (emit first) would risk an emit-without-state in the OSError case, which is the wrong failure mode.

### Modified: `scripts/orchestrator_runner.py`

**Six changes:**

1. **Delete local `_redact_credentials`** (lines 1835-1846). Import from `stderr_emit` at the top of the file.

2. **Replace 3 `lint_block` direct mutations** at lines 1222-1224, 1230-1233, 1267-1270 with single `add_partial(state, reason)` calls. Pre-refactor:

   ```python
   state["current_run"]["partial"] = True
   state["current_run"]["partial_reasons"].append(
       f"lint_block_unsafe_path: {fail['path']} (outside repo)"
   )
   ```

   Post-refactor:

   ```python
   add_partial(state, f"lint_block_unsafe_path: {fail['path']} (outside repo)")
   ```

   `add_partial`'s default behavior (append then flip `partial=True` for non-info_only) matches the original pre-append flip in single-threaded semantics. **Behavior change call-out:** `lint_block` and `lint_block_unsafe_path` messages currently flow without `_redact_credentials`; after refactor they will (because `add_partial` redacts at entry). A path containing a credential-bearing URL (unlikely but possible from test data) now gets redacted before storage. This is captured by a dedicated test.

3. **Keep `_record_failure` as-is** (lines 1849-1863). The 8 call sites inside `open_or_append_pr` continue to use it. The function does NOT call `add_partial` — it accumulates into a local `reasons: list[tuple[str, bool]]` returned to the caller, which then loops at lines 1398-1399 and calls `add_partial` on each. After Approach A this means: on `open_or_append_pr`'s failure path, EACH reason produces TWO stderr lines:
   - `docs-agent: open_or_append_pr {reason}` (from `_record_failure` at the failure source, line 1862)
   - `docs-agent PARTIAL: {reason}` (from `add_partial` via the caller's loop)

   This is **intentional belt-and-suspenders**. `_record_failure` fires before any subsequent crash could prevent the caller from looping; `add_partial` fires once the reason reaches `state`. Tests at `tests/orchestrator/test_open_or_append_pr.py:534`, `564`, `593` assert substring presence (`'checkout_failed' in err`), not occurrence count — both lines satisfy substring assertions. A new test (see below) explicitly locks the two-line symmetry.

4. **Keep existing exit-1 dump at line 1412** unchanged. This dump fires BEFORE the `finally` block runs, surviving any `_write_step_summary` exception. Validator panel rejected moving it into the finally because `_write_step_summary` early-returns when `GITHUB_STEP_SUMMARY` is unset (line 1722-1724, local/dev runs) and silently swallows `OSError` (lines 1736-1739, read-only filesystem).

5. **Add new helper `_emit_shutdown_dump(state)`** called from the `finally` block at line 1460, BEFORE `_write_step_summary`. Gates on `state.get('current_run', {}).get('partial_reasons')` being non-empty (matches `_write_step_summary`'s existing precedent at line 1726-1728 of gating on reasons list, NOT the `partial` flag — `info_only` reasons still warrant exit-time visibility). Format under Open Question resolution (a):

   ```
   docs-agent: run exit summary (reasons=3):
   docs-agent PARTIAL: lint_block: docs/foo.md line-length: line 23 exceeds 120
   docs-agent PARTIAL: source_collector_partial: true
   docs-agent PARTIAL: source_map_failed: PermissionError
   ```

   Under Option (a) (locked below), ALL reasons in the shutdown dump share a single prefix per run: `PARTIAL` when `state["current_run"]["partial"]` is `True`, `INFO` when `partial` is `False` (info_only-only run). Per-reason `INFO` vs `PARTIAL` granularity is visible only in the per-call emit during the run, never in the shutdown dump.

   **Implementation mechanism:** `_emit_shutdown_dump` calls `print(..., file=sys.stderr, flush=_OBSERVABILITY_FLUSH)` directly — NOT via `emit_stderr()` or `emit_log()`. Both helper functions swallow `OSError`, which would make the documented "OSError propagates" contract unreachable. The shutdown dump is the operator's last-resort observability signal and must fail loudly if stderr is broken. It does still call `stderr_emit._redact_credentials` on each reason before printing (though reasons stored in state are already redacted by `add_partial`'s redact-first invariant — the call is defense-in-depth).

6. **Replace 9 raw `print(..., file=sys.stderr)` calls** at lines 643, 683, 969, 975, 981, 1493, 1498, 1503, 1508 with `emit_log(text)` calls from `stderr_emit`. Additionally route the existing exit-1 dump at line 1412-1416 through `emit_log` (10 sites total). Locks `flush=True` at module level via `_OBSERVABILITY_FLUSH`. The single intentional remaining direct `print(..., file=sys.stderr)` is `_record_failure` at line 1862 (must fire before any later crash; cannot be best-effort).

### Modified: `scripts/verify_runner.py`

**Two sites refactored, one site explicitly preserved:**

- **Lines 79-81 and 101-104:** replace `state.setdefault('current_run', {}).setdefault('partial_reasons', []).append(r); state['current_run']['partial'] = True` with `add_partial(state, r)`. End-state semantics are equivalent: `add_partial` at `state_io.py:229-230` handles the missing `current_run` case with the same setdefault behavior.
- **Line 49:** UNCHANGED. This is a dict-literal field in a notifier payload (`'partial_reasons': [view.error or 'gh failed']`), NOT a state mutation. Refactoring it would corrupt the notifier digest schema.

### Locked stderr prefix scheme (spec invariant)

| Prefix                                                    | Source                               | Test reference                                                                                                         |
| --------------------------------------------------------- | ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| `docs-agent: open_or_append_pr {reason}`                  | `_record_failure` only               | `tests/orchestrator/test_open_or_append_pr.py:809` — discipline test asserts this prefix does NOT appear on happy path |
| `docs-agent PARTIAL: {reason}`                            | `add_partial` when `info_only=False` | NEW: `tests/state_io/test_add_partial_stderr_emit.py`                                                                  |
| `docs-agent INFO: {reason}`                               | `add_partial` when `info_only=True`  | NEW: `tests/state_io/test_add_partial_stderr_emit.py`                                                                  |
| `docs-agent: orchestrator exiting 1; partial_reasons=...` | Existing exit-1 dump at line 1412    | NEW: `tests/orchestrator/test_orchestrator_run.py`                                                                     |
| `docs-agent: run exit summary (reasons=N):`               | NEW: `_emit_shutdown_dump` header    | NEW: `tests/orchestrator/test_emit_shutdown_dump.py`                                                                   |

**The four `add_partial` and shutdown-dump prefixes MUST NOT contain the substring `docs-agent: open_or_append_pr`** — otherwise the discipline test at `tests/orchestrator/test_open_or_append_pr.py:809` breaks. The proposed prefixes don't collide; the spec locks this as an invariant so future renames cannot silently violate it.

## Data flow

### Per-reason recording (success and failure paths)

```
Reason recorded via add_partial(state, "X", info_only=False)
  ├─ stderr_emit._redact_credentials("X") → "X_safe"
  ├─ state["current_run"]["partial_reasons"].append("X_safe") (if new)
  ├─ state["current_run"]["partial"] = True (always, when info_only=False)
  └─ stderr_emit.emit_stderr("X_safe", info_only=False)
        └─ stderr: "docs-agent PARTIAL: X_safe"
```

### open_or_append_pr failure path (double-emit)

```
checkout fails inside open_or_append_pr
  ├─ _record_failure(reasons, "checkout_failed: ...")
  │     ├─ _redact_credentials("checkout_failed: ...") → safe
  │     ├─ stderr: "docs-agent: open_or_append_pr checkout_failed: ..." [LINE 1]
  │     └─ reasons.append((safe, False))
  └─ return None, reasons
  ↓ caller at run() line 1398-1399 loops
  for reason, info_only in pr_reasons:
      add_partial(state, reason, info_only=info_only)
        ├─ _redact_credentials(reason) → already safe (idempotent)
        ├─ state["current_run"]["partial_reasons"].append(safe) (if new)
        ├─ state["current_run"]["partial"] = True
        └─ emit_stderr(safe, info_only=False)
              └─ stderr: "docs-agent PARTIAL: checkout_failed: ..." [LINE 2]
```

### Exit-0 partial run path (state["current_run"]["partial"] = True)

```
run() completes successfully but state["current_run"]["partial_reasons"] is non-empty
  ↓ falls into finally block at line 1459
  _emit_shutdown_dump(state)  ← NEW (called BEFORE _write_step_summary)
      ├─ stderr: "docs-agent: run exit summary (reasons=3):"
      ├─ stderr: "docs-agent PARTIAL: lint_block: ..."
      ├─ stderr: "docs-agent PARTIAL: source_collector_partial: true"
      └─ stderr: "docs-agent PARTIAL: source_map_failed: ..."
  _write_step_summary(state, repo_root)  ← unchanged (GITHUB_STEP_SUMMARY writer)
```

Under Option (a), all shutdown-dump reasons take the `PARTIAL` prefix when `state["current_run"]["partial"]` is `True` (the common case — any non-info_only reason has flipped it). When `partial` is `False` (info_only-only run), all reasons take the `INFO` prefix. The shutdown dump is a coarse run-level signal; per-reason `PARTIAL` vs `INFO` granularity is visible only in the per-call `emit_stderr` lines during the run.

### Exit-1 path (existing dump + new shutdown-dump = belt-and-suspenders)

```
PR creation fails, run() reaches line 1410
  ├─ existing dump at line 1412: "docs-agent: orchestrator exiting 1; partial_reasons=[...]" [via emit_log, was raw print]
  └─ return 1
       ↓ falls into finally block
       _emit_shutdown_dump(state)  ← also emits the same reasons one-per-line
       _write_step_summary(state, repo_root)
```

On exit-1 the operator sees TWO stderr signals: the existing single-line summary and the new multi-line dump. The redundancy is the safety net validators flagged as critical — `_write_step_summary` swallows OSError, so the existing pre-finally dump is the guaranteed signal even if `_emit_shutdown_dump` somehow failed.

## Error handling

- **`emit_stderr` and `emit_log`:** OSError on stderr is caught and discarded. Diagnostic stream failure must never crash the orchestrator. State mutation in `add_partial` always succeeds; emit is best-effort.
- **`_emit_shutdown_dump`:** does NOT swallow OSError. The shutdown dump IS the operator-facing observability signal; if stderr is broken the orchestrator should fail loudly rather than silently. **Implementation note:** this is achieved by calling `print(..., file=sys.stderr, flush=_OBSERVABILITY_FLUSH)` directly rather than `emit_stderr()` / `emit_log()` — if the helpers were used, their internal OSError-swallow would make the propagation contract unreachable.
- **`add_partial`:** redaction happens first, then state mutation, then emit. If `_redact_credentials` somehow raised (it doesn't — pure regex sub), state would not be mutated and emit would not fire — the call would propagate the exception, which is the correct failure mode for a redaction bug.

## Open question (deferred, to be resolved in writing-plans)

State.json currently stores `partial_reasons` as `list[str]` — the `info_only` flag is consumed by `add_partial` to gate `partial=True` but NOT persisted per-reason. The new `_emit_shutdown_dump` needs to know which prefix (`PARTIAL` vs `INFO`) to apply per reason at shutdown time.

**Options for the plan to resolve:**

- (a) **Run-level prefix (LOCKED for this spec).** Apply a single prefix to ALL reasons in the shutdown dump per run: `PARTIAL` when `state["current_run"]["partial"]` is `True` (any non-info_only reason has flipped it), `INFO` when `partial` is `False` and `partial_reasons` is non-empty (info_only-only run). Per-reason granularity is sacrificed at shutdown time; the per-call `emit_stderr` lines preserve it during the run. The shutdown dump is a coarse operator signal, not a per-reason audit. **Simplest; preserves existing state schema.**
- (b) Add a parallel `state["current_run"]["partial_reasons_info_only"]: list[bool]` field tracked at append time. **Schema migration; full per-reason granularity in the shutdown dump.**
- (c) Encode `info_only` into the stored reason string itself (e.g., prefix with `[INFO]`). **No schema change; pollutes the reason string.**

**Resolution: Option (a).** Preserves the existing state schema, the per-reason prefix is already visible during the run, and the shutdown dump is a summary not an audit. Plan can revisit if operator feedback warrants. This resolution is reflected in the Architecture / Data flow examples + the locked behavior of `_emit_shutdown_dump`.

## Decisions

| Decision                              | Choice                                                                                                     | Rationale                                                                                                                                                                                                                                                                                                                                                |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Module name                           | `stderr_emit.py` (NOT `observability.py`)                                                                  | Matches `scripts/` purpose-descriptive convention: `state_io.py`, `gh_client.py`, `frontmatter_contract.py`, `core_manifest.py`. The module's job IS stderr emission with redaction, not telemetry broadly.                                                                                                                                              |
| Emit signature                        | `emit_stderr(reason: str, *, info_only: bool = False)`                                                     | Free-text only, no state, no run_id. Leaf-module invariant. If structured emit wanted later, wrap don't retrofit.                                                                                                                                                                                                                                        |
| Emit policy                           | **Every call**, not newly-appended only                                                                    | Retry-loop sequencing is the signal CCE-73 was built to preserve. Existing `_record_failure` at line 1862 already emits unconditionally; aligning `add_partial` matches that contract. State dedup stays.                                                                                                                                                |
| Redact location                       | At `add_partial` entry, BEFORE state mutation                                                              | Extends CCE-73's 7-site "state never carries raw credentials" invariant to all 28 sites. Future `add_partial(state, f"X: {subprocess_stderr}")` cannot leak a token to state.json.                                                                                                                                                                       |
| Exit-1 dump location                  | Stays at line 1412 (unchanged)                                                                             | `_write_step_summary` early-returns and swallows OSError — cannot be the sole emit site for the highest-priority failure surface. Validator critical finding.                                                                                                                                                                                            |
| Exit-0 shutdown dump                  | New `_emit_shutdown_dump(state)` sibling helper, called BEFORE `_write_step_summary` in finally            | Single emit-on-shutdown location for partial-but-exit-0 runs. Does NOT swallow OSError. Gated on `partial_reasons` non-empty (not on `partial` flag — info_only reasons still warrant visibility).                                                                                                                                                       |
| `_record_failure`                     | Keep as-is, do NOT delete or rename "reasons" param                                                        | Deletion would break 16 test call sites at `tests/orchestrator/test_open_or_append_pr.py` (lines 74, 101, 130, 157, 216, 262, 455, 494, 529, 561, 590, 620, 651, 681, 708, 743). Double-emit on `open_or_append_pr` path is intentional belt-and-suspenders. Param rename (CCE-73 panel nice-to-have #2) is cosmetic and forces 8-line churn — REJECTED. |
| `emit_log` second helper              | YES, replaces all 9 raw stderr-print sites + the exit-1 dump (10 total)                                    | Locks `flush=True` for the broader set of stderr writes, not just CCE-73 panel's named-two (lines 643, 975). Prevents copy-paste regression.                                                                                                                                                                                                             |
| `_emit_shutdown_dump` emit mechanism  | Direct `print(..., file=sys.stderr, flush=_OBSERVABILITY_FLUSH)` calls, NOT via `emit_stderr` / `emit_log` | `emit_stderr` / `emit_log` swallow OSError as best-effort. The shutdown dump is the last-resort observability signal and must fail loudly if stderr is broken. Direct print preserves OSError propagation. Still calls `_redact_credentials` per reason for defense-in-depth (reasons already redacted by `add_partial`).                                |
| Open Question (info_only persistence) | Option (a) — single run-level prefix in shutdown dump (`PARTIAL` if `partial=True`, else `INFO`)           | Per-reason granularity preserved during the run via per-call emit; shutdown dump is a coarse summary. Preserves existing state schema.                                                                                                                                                                                                                   |
| `_redact_credentials` regex           | EXACT VERBATIM copy of pre-CCE-74 `_CREDENTIAL_URL_RE` (`r"(https?://)[^@/\s]*@"` → `r"\1<redacted>@"`)    | Existing test at `tests/orchestrator/test_open_or_append_pr.py:779` asserts `<redacted>` substring; matches http:// and https://; broad user-segment match. Narrowing or changing the replacement marker is OUT OF SCOPE for CCE-74 — it would be a separate hardening ticket.                                                                           |
| `_OBSERVABILITY_FLUSH` const          | Module-level in `stderr_emit.py`, consumed by both `emit_stderr` and `emit_log`                            | Single source of truth. Spec invariant: all new stderr writes in `scripts/` route through `emit_stderr` or `emit_log`.                                                                                                                                                                                                                                   |
| pytest mitigations                    | NONE                                                                                                       | Grep verified zero `capsys.readouterr().err == ""` equality assertions in `tests/`. No conftest changes needed.                                                                                                                                                                                                                                          |
| verify_runner line 49                 | LEAVE UNTOUCHED                                                                                            | Notifier digest field, not state mutation. Misreading would corrupt notifier payload schema.                                                                                                                                                                                                                                                             |

## CCE-73 verification-panel nice-to-haves (status)

| #   | Nice-to-have                                                                              | Status                                                                                                                                                                              |
| --- | ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Lock `flush=True` invariant                                                               | DONE via `_OBSERVABILITY_FLUSH` module constant in `stderr_emit.py`                                                                                                                 |
| 2   | Rename `_record_failure`'s `reasons` param to `reason_log` or make keyword-only           | **REJECTED** — cosmetic, 8-line churn, function is one helper away from deletion if future work consolidates                                                                        |
| 3   | Reformat exit-1 dump as one-reason-per-line for grepability                               | DONE via new `_emit_shutdown_dump` (fires in finally on every exit path); existing line 1412 stays as single-line summary                                                           |
| 4   | Migrate CCE-73 tests to `_make_subprocess_stub_with_fetch` for CCE-42 alignment           | DONE — migrate during implementation                                                                                                                                                |
| 5   | Add CCE-73 stderr-emission invariant note to `test_open_or_append_pr.py` module docstring | DONE — add invariant note covering both `_record_failure` and the new `add_partial` emit                                                                                            |
| 6   | Audit existing stderr prints at lines 643, 975 — upgrade to flush=True                    | DONE — extended to ALL 9 raw stderr prints (lines 643, 683, 969, 975, 981, 1493, 1498, 1503, 1508) via `emit_log`, plus the exit-1 dump at line 1412 (10 sites total), not just two |

## Tests (regression invariants)

### New test file: `tests/stderr_emit/test_stderr_emit.py`

- `test_emit_stderr_writes_partial_prefix_when_not_info_only` — `emit_stderr("X", info_only=False)` → `capsys.readouterr().err == "docs-agent PARTIAL: X\n"`
- `test_emit_stderr_writes_info_prefix_when_info_only` — `emit_stderr("Y", info_only=True)` → `"docs-agent INFO: Y\n"`
- `test_emit_stderr_redacts_credentials` — `emit_stderr("push: https://x-access-token:ghs_xxx@github.com/r/r")` → stderr contains `"REDACTED"`, NOT `"ghs_xxx"`
- `test_emit_stderr_survives_oserror` — monkeypatch `sys.stderr.write` to raise IOError → `emit_stderr("X")` returns None without raising
- `test_emit_log_writes_text_with_flush` — `emit_log("hello")` → `capsys.readouterr().err == "hello\n"` AND `flush=True` was set (assert on `_OBSERVABILITY_FLUSH` constant)
- `test_emit_log_no_prefix_no_redaction` — `emit_log("https://x-access-token:ghs_xxx@github.com/...")` → stderr contains the raw URL (no redaction, by design for non-partial logging paths)
- `test_emit_log_survives_oserror` — same as above for `emit_log`

### New test file: `tests/contracts/test_stderr_emit_imports.py`

- `test_stderr_emit_imports_only_stdlib` — assert `stderr_emit` module has no transitive dependency on `state_io` or `orchestrator_runner`. Use `importlib` introspection. Concrete sketch:

  ```python
  import importlib
  m = importlib.import_module("stderr_emit")
  assert "state_io" not in dir(m)
  assert "orchestrator_runner" not in dir(m)
  ```

  Prevents future contributors from creating a `stderr_emit → state_io` cycle.

- `test_no_new_raw_stderr_prints_in_orchestrator_runner` — source-level regression guard for Acceptance Criterion #8. Reads `scripts/orchestrator_runner.py` as text, regex-scans for `print\(.*file=sys\.stderr`, and asserts the only remaining matches are the single intentional `_record_failure` site near line 1862 (matched by surrounding `def _record_failure` context). Protects against future contributors adding raw stderr prints that bypass `emit_log`.

### Extended: `tests/state_io/test_add_partial_stderr_emit.py` (NEW)

- `test_add_partial_emits_partial_prefix_on_call` — `add_partial({}, "x")` → `capsys.readouterr().err` contains `"docs-agent PARTIAL: x"`
- `test_add_partial_emits_info_prefix_when_info_only` — `add_partial({}, "y", info_only=True)` → `"docs-agent INFO: y"`
- `test_add_partial_emits_on_every_call_not_just_first` — call `add_partial(state, "x")` twice → `err.count("docs-agent PARTIAL: x") == 2`, BUT `state["current_run"]["partial_reasons"] == ["x"]` (state-dedup preserved)
- `test_add_partial_redacts_credentials_before_state_write` — `add_partial({}, "push_failed: https://x-access-token:ghs_xxx@github.com/r/r")` → `"ghs_xxx" not in state["current_run"]["partial_reasons"][0]` AND `"ghs_xxx" not in capsys.readouterr().err`
- `test_add_partial_survives_stderr_failure` — monkeypatch `sys.stderr.write` → IOError; `add_partial(state, "x")` still mutates state

### Extended: `tests/orchestrator/test_open_or_append_pr.py`

- `test_open_or_append_pr_checkout_failure_double_emit_symmetry` — on `checkout` failure, `capsys.readouterr().err` contains BOTH `"docs-agent: open_or_append_pr checkout_failed"` AND `"docs-agent PARTIAL: checkout_failed"`, with the `open_or_append_pr` prefix appearing first (order-preserving regression for the belt-and-suspenders contract)
- Migrate CCE-73 tests to `_make_subprocess_stub_with_fetch` (panel nice-to-have #4)
- Add stderr-emission invariant note to module docstring (panel nice-to-have #5)

### New test file: `tests/orchestrator/test_emit_shutdown_dump.py`

- `test_emit_shutdown_dump_emits_header_and_reasons` — state with 3 partial_reasons → stderr contains `"docs-agent: run exit summary (reasons=3):"` followed by 3 `"docs-agent PARTIAL: ..."` lines
- `test_emit_shutdown_dump_no_op_when_reasons_empty` — empty partial_reasons → no stderr output
- `test_emit_shutdown_dump_no_op_when_partial_false_and_reasons_empty` — `partial=False`, empty reasons → no stderr
- `test_emit_shutdown_dump_emits_when_partial_false_but_reasons_nonempty` — info_only-only run (`partial=False`, reasons non-empty) → stderr emit (gated on reasons, not partial flag)
- `test_emit_shutdown_dump_does_not_swallow_oserror` — monkeypatch `sys.stderr.write` → IOError; `_emit_shutdown_dump` raises (intentional, different from `emit_stderr`)

### New test file: `tests/orchestrator/test_orchestrator_run.py`

- `test_run_exit_0_with_partial_reasons_emits_shutdown_dump` — orchestrator returns 0 with non-empty partial_reasons; stderr contains shutdown dump
- `test_run_exit_1_emits_both_existing_dump_and_shutdown_dump` — orchestrator returns 1; stderr contains BOTH `"docs-agent: orchestrator exiting 1; partial_reasons=..."` (line 1412) AND `"docs-agent: run exit summary (reasons=N):"` (from `_emit_shutdown_dump` in finally) — belt-and-suspenders verification
- `test_lint_block_add_partial_redacts_credentials` — orchestrator path that triggers `lint_block_unsafe_path` with a credential-bearing path. Assert `state["current_run"]["partial_reasons"][0]` contains `"<redacted>"` (not the raw URL) AND `capsys.readouterr().err` contains `"docs-agent PARTIAL: lint_block_unsafe_path: ...<redacted>..."`. Locks Acceptance Criterion #9's behavior-change call-out.

### Extended: `tests/verify_runner/test_verify_runner.py`

- `test_verify_runner_failure_path_emits_partial_via_add_partial` — verify_runner.py line 79-81 path triggers `add_partial`, stderr contains `"docs-agent PARTIAL: ..."`
- `test_verify_runner_promotion_path_emits_partial_via_add_partial` — verify_runner.py line 101-104 path same

### Extended: existing `tests/orchestrator/test_step_summary.py`

- **Verify during implementation** that the two existing test paths (`test_run_invokes_write_step_summary_on_hard_fail` near line 137 and `test_run_invokes_write_step_summary_on_clean_success` near line 181) produce empty `partial_reasons` in the fixture path so `_emit_shutdown_dump` no-ops and does not bleed into capsys. The exit-1 dump stays at orchestrator_runner.py:1412 (NOT moved into `_write_step_summary`) and the new `_emit_shutdown_dump` is a SEPARATE sibling call (called BEFORE `_write_step_summary` in finally), so the existing spy-based assertions on `_write_step_summary` still cover their original surface.
- If either test path turns out to accumulate `partial_reasons` (e.g., from `fakes/fake_notifier.json` returning failure), add `monkeypatch.setattr(orun, "_emit_shutdown_dump", lambda s: None)` to that test to guard against unexpected capsys bleed. Do NOT change the existing assertions on `_write_step_summary` behavior.

## Acceptance criteria

1. **Every `add_partial` call surfaces its reason to stderr** with the appropriate `PARTIAL` or `INFO` prefix, on EVERY call (not just newly-appended). Verified by `test_add_partial_emits_on_every_call_not_just_first`.

2. **State.json never carries raw credentials** regardless of which `add_partial` call site recorded the reason. Verified by `test_add_partial_redacts_credentials_before_state_write`.

3. **Exit-0 partial runs emit a shutdown dump** to stderr before returning. Verified by `test_run_exit_0_with_partial_reasons_emits_shutdown_dump`.

4. **Exit-1 path emits both existing dump and shutdown dump** (belt-and-suspenders). Verified by `test_run_exit_1_emits_both_existing_dump_and_shutdown_dump`.

5. **Module dependency invariant:** `stderr_emit` imports only stdlib. Verified by `test_stderr_emit_imports_only_stdlib`.

6. **Prefix invariants locked:** discipline tests assert `'docs-agent: open_or_append_pr'` substring does NOT appear in `add_partial`-only emit paths. The 4 prefixes (`docs-agent: open_or_append_pr`, `docs-agent PARTIAL:`, `docs-agent INFO:`, `docs-agent: run exit summary`) are tested separately.

7. **Double-emit symmetry on `open_or_append_pr` failure:** verified by `test_open_or_append_pr_checkout_failure_double_emit_symmetry`.

8. **All 9 raw stderr-print sites** (lines 643, 683, 969, 975, 981, 1493, 1498, 1503, 1508) in `orchestrator_runner.py` route through `emit_log`, plus the existing exit-1 dump at line 1412-1416 (10 sites total). The single intentional remaining direct `print(..., file=sys.stderr)` is `_record_failure` at line 1862. Verified by the automated source-scan test `test_no_new_raw_stderr_prints_in_orchestrator_runner` in `tests/contracts/test_stderr_emit_imports.py` + grep at PR time.

9. **3 `lint_block` direct mutations refactored** to use `add_partial`. Behavior change: lint_block reasons now pass through redaction. Verified by `test_lint_block_add_partial_redacts_credentials` in `tests/orchestrator/test_orchestrator_run.py`.

10. **2 `verify_runner.py` direct writes refactored** to use `add_partial` (lines 79-81, 101-104). Line 49 unchanged. Verified by dedicated tests in `tests/verify_runner/`.

11. **Full pytest suite passes** with zero regressions. Existing tests assert substring presence in stderr; the new emissions are additive — no test should break from added stderr volume alone. Pre-implementation audit confirmed zero empty-stderr equality assertions.

## Files changed (summary)

| File                                             | Change                                                                                                                                                                                                                    | Lines (approx) |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| `scripts/stderr_emit.py`                         | NEW module                                                                                                                                                                                                                | ~60            |
| `scripts/state_io.py`                            | `add_partial` refactor (redact-first, emit-on-every-call) + import                                                                                                                                                        | ~15            |
| `scripts/orchestrator_runner.py`                 | Delete `_redact_credentials`, refactor 3 lint_block sites, add `_emit_shutdown_dump` (uses direct print, not emit_stderr), replace 9 raw stderr prints + the exit-1 dump (10 sites) with `emit_log`, update finally block | ~85            |
| `scripts/verify_runner.py`                       | 2 refactors (lines 79-81, 101-104); line 49 unchanged                                                                                                                                                                     | ~10            |
| `tests/stderr_emit/test_stderr_emit.py`          | NEW test file                                                                                                                                                                                                             | ~120           |
| `tests/contracts/test_stderr_emit_imports.py`    | NEW test file (importlib leaf-module invariant + source-scan AC #8 guard)                                                                                                                                                 | ~50            |
| `tests/state_io/test_add_partial_stderr_emit.py` | NEW test file                                                                                                                                                                                                             | ~100           |
| `tests/orchestrator/test_open_or_append_pr.py`   | Add double-emit symmetry test, migrate to `_make_subprocess_stub_with_fetch`, update module docstring                                                                                                                     | ~50            |
| `tests/orchestrator/test_emit_shutdown_dump.py`  | NEW test file                                                                                                                                                                                                             | ~100           |
| `tests/orchestrator/test_orchestrator_run.py`    | NEW test file (exit-0 dump + exit-1 dump + lint_block redaction tests)                                                                                                                                                    | ~80            |
| `tests/verify_runner/test_verify_runner.py`      | Add 2 add_partial-driven emit tests                                                                                                                                                                                       | ~40            |

Total: ~715 lines added/modified across 11 files. ~420 lines in tests; ~170 lines in production code; ~130 lines in spec/docs. Increase vs initial estimate reflects expanded test_stderr_emit_imports.py (importlib + source-scan) and test_orchestrator_run.py (added lint_block redaction test).

## Implementation order (informs the plan)

1. Create `scripts/stderr_emit.py` with `_redact_credentials` (verbatim copy of pre-CCE-74 `_CREDENTIAL_URL_RE` regex + `\1<redacted>@` replacement), `emit_stderr`, `emit_log`, `_OBSERVABILITY_FLUSH` constant. Create `tests/stderr_emit/` directory with `__init__.py` (match convention in `tests/state_io/`, `tests/orchestrator/`, `tests/lint/`). Confirm `tests/contracts/` directory exists (it should — `tests/contracts/test_state_io.py` already lives there). Write `tests/stderr_emit/test_stderr_emit.py` + `tests/contracts/test_stderr_emit_imports.py`. Land green.

2. Refactor `state_io.add_partial` to redact-first + emit-on-every-call. Write `tests/state_io/test_add_partial_stderr_emit.py`. Land green.

3. Refactor 3 `lint_block` direct mutations in `orchestrator_runner.py` to use `add_partial`. Add `test_lint_block_add_partial_redacts_credentials` to NEW file `tests/orchestrator/test_orchestrator_run.py`: assert that `add_partial` called from the `lint_block_unsafe_path` path with a credential-bearing path produces a redacted reason in `state["current_run"]["partial_reasons"]` AND a redacted line via `emit_stderr` in stderr. Land green.

4. Refactor 2 `verify_runner.py` direct writes (lines 79-81, 101-104) to use `add_partial`. Add 2 emit tests. Land green.

5. Delete local `_redact_credentials` from `orchestrator_runner.py`; replace 2 callers (lines 1410, 1861) with imports from `stderr_emit`. Land green.

6. Add `_emit_shutdown_dump(state)` helper. Write `tests/orchestrator/test_emit_shutdown_dump.py`. Wire into finally block at line 1460 (BEFORE `_write_step_summary`). Add exit-0 and exit-1 dump tests in `tests/orchestrator/test_orchestrator_run.py`. Land green.

7. Replace 9 raw `print(..., file=sys.stderr)` sites (lines 643, 683, 969, 975, 981, 1493, 1498, 1503, 1508) in `orchestrator_runner.py` with `emit_log(...)`. Additionally route the exit-1 dump at line 1412-1416 through `emit_log` (10 sites total). Leave `_record_failure` at line 1862 as direct `print(...)` — it stays direct intentionally. No functional change; lock flush. Verify `test_no_new_raw_stderr_prints_in_orchestrator_runner` (added in step 1) passes. Land green.

8. Update `tests/orchestrator/test_open_or_append_pr.py`: add double-emit symmetry test, migrate to `_make_subprocess_stub_with_fetch`, update module docstring. Land green.

9. Full pytest suite. Verify zero regressions.

Each task ships as a separate commit. The plan (next step) will break each into TDD micro-steps.

## Non-goals / explicit rejections

- **Deletion of `_record_failure`** — would break 16 test call sites; double-emit is intentional safety net
- **Renaming `_record_failure`'s `reasons` parameter** — cosmetic, 8-line churn
- **Moving exit-1 dump into `_write_step_summary`** — early-returns + swallows OSError, would silently regress in non-Actions environments
- **Conftest-level stderr capture** — no empty-stderr equality assertions exist in tests; mitigation unnecessary
- **Structured key=value emit / `reason_class` kwarg** — speculative; current free-text + class-prefix convention is greppable
- **Schema migration of `partial_reasons`** — Open Question resolves to "default shutdown dump to PARTIAL prefix unless partial=False", preserving existing schema

## References

- Jira: [CCE-74](https://designitright.atlassian.net/browse/CCE-74), [CCE-73](https://designitright.atlassian.net/browse/CCE-73)
- CCE-73 PR: [#93](https://github.com/theoju/engineering-docs-agent/pull/93) (merged 2026-06-01)
- Related CCE-73 commits: `3c10b49`, `e22dede`
- Related CCE-75 commits (for context on `_stage_docs_run_changes`): `1512165`, `b3ac6eb`, `8912a37`, `4cc258a`, `2d4abfb`
- Codebase entry points: `scripts/state_io.py:220` (`add_partial`), `scripts/orchestrator_runner.py:1849` (`_record_failure`), `scripts/orchestrator_runner.py:1835` (`_redact_credentials`)
