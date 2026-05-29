# CCE-48: surface partial_reasons in `$GITHUB_STEP_SUMMARY`

**Ticket:** CCE-48
**Status:** Draft (awaiting user review)
**Related:** CCE-40 (durable state — split `current_run` out of committed `state.json`), CCE-41 (subagent forensics), CCE-43 (skip-window short-circuit), workflow `.github/workflows/docs-agent-nightly.yml`

## Problem

The docs-agent nightly's "Run summary" step at `.github/workflows/docs-agent-nightly.yml:103-125` writes `state.json` into `$GITHUB_STEP_SUMMARY`. The intent: an operator opening the workflow run page sees why a run was partial without clicking into the docs-agent PR. The reality: that summary never shows the `partial_reasons` list.

Two converging root causes:

1. `state.json` on disk is stripped of `current_run` by `save_persistent_state` (`scripts/state_io.py:194-201`). This is CCE-40 design intent — the sibling `current_run.json` carries `current_run` for the in-progress run, while the committed `state.json` carries only persistent state promoted by PR merge. The Run summary step `cat`s `state.json`, which by design no longer contains `current_run.partial_reasons`.
2. The 22 `add_partial(state, ...)` callsites in `scripts/orchestrator_runner.py` only mutate the in-memory state dict (see `add_partial` at `scripts/state_io.py:220-236`). None of them print to stdout/stderr.

Net effect: `$GITHUB_STEP_SUMMARY` literally cannot surface `partial_reasons` today. The operator's workflow is "open the workflow run, see the empty `current_run` block, click into the PR body, read the `WARNING — Partial run — …`" — two extra clicks per investigation, in a flow that should be one click.

The `current_run.json` sibling file holds the data, but it's `.gitignore`d (CCE-40 design — the sibling is per-runner ephemeral state, not promoted by merge) and the workflow's `cat` step never reads it. Reading it would also be brittle — the path is implied by `scripts/state_io.py:204` but not part of the workflow's public contract.

## Goal

Inside GitHub Actions, after the orchestrator's `run()` completes (success, partial, or hard-fail mid-pipeline), the workflow's Run summary surfaces every accumulated `partial_reason` in human-readable form. Local runs and unit tests are unaffected.

Single source of truth: the same formatter that builds the PR-body partial warning at `scripts/orchestrator_runner.py:1750` produces the step-summary digest. One composer, two sinks.

## Architecture — Shape C: helper + `try`/`finally` in `run()`

One new helper plus one wrapper in `scripts/orchestrator_runner.py`. No workflow YAML change.

### New helper: `_format_partial_digest`

Factor the existing PR-body composer's join into a reusable formatter. The current composer at `scripts/orchestrator_runner.py:1750-1754`:

```python
body = (
    "WARNING — Partial run — " + "; ".join(partial_reasons)
    if partial
    else "docs-agent run"
)
```

Replace with:

```python
def _format_partial_digest(partial_reasons: list[str]) -> str:
    """Single-source format for partial_reasons. Used by:
    - PR body composer in open_or_append_pr
    - GITHUB_STEP_SUMMARY writer in _write_step_summary
    """
    if not partial_reasons:
        return ""
    lines = ["WARNING — Partial run", ""]
    lines.extend(f"- {r}" for r in partial_reasons)
    return "\n".join(lines)
```

The bulleted-list format replaces today's `; `-joined one-liner. Both PR body and step summary share the same shape; readability is markedly better once `partial_reasons` exceeds 2-3 entries (CCE-41 forensics surfaced runs with 8+ accumulated reasons).

### New helper: `_write_step_summary`

```python
def _write_step_summary(state: dict, repo_root: Path) -> None:
    """Append the partial-reasons digest to $GITHUB_STEP_SUMMARY.

    No-op when:
    - $GITHUB_STEP_SUMMARY is unset (local runs, unit tests)
    - state has no current_run
    - current_run.partial_reasons is empty (clean run — workflow's
      existing `cat state.json` step already conveys success)

    Failure-tolerant: never raises. If the env var points to a path
    the runner can't write (read-only filesystem, missing parent),
    swallow and continue — the runner's primary job is producing
    docs, not diagnostics.
    """
    summary_path_str = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path_str:
        return
    cr = state.get("current_run") or {}
    reasons = cr.get("partial_reasons") or []
    if not reasons:
        return
    digest = _format_partial_digest(reasons)
    if not digest:
        return
    section = "\n## docs-agent partial_reasons\n\n" + digest + "\n"
    try:
        with open(summary_path_str, "a", encoding="utf-8") as fh:
            fh.write(section)
    except OSError:
        # Best-effort. The workflow's `if: always()` state.json cat
        # step still runs; this digest is additive context.
        return
```

### `try`/`finally` placement in `run()`

`run()` at `scripts/orchestrator_runner.py:924` has many `return` paths — early returns for `ConfigError`/`StateError` (lines 928-941), the CCE-43 skip path (line 991), the no-PR branch (line 1343), the `pr_number is None` branch (line 1359), and the success path (line 1399). Any of them could leave accumulated `partial_reasons` in the in-memory `state` dict that the workflow's `state.json` cat will not see.

Worse: a hard-fail _exception_ from anywhere downstream of state initialization — `open_or_append_pr` crash on a git binary missing, `dispatch_validated` raising, an unhandled `KeyError` — leaves the workflow with neither `state.json` carrying the reasons nor any digest. Today the workflow summary in that case is literally just the trigger metadata block.

Wrap the body of `run()` in a `try`/`finally` keyed off the `state` dict so the finally always sees the latest `partial_reasons`:

```python
def run(repo_root: Path, *, dry_run_dir: Path | None, no_pr: bool) -> int:
    # ... config load + state load (still allowed to early-return; nothing
    # to flush yet because partial_reasons doesn't exist yet) ...

    state.setdefault("version", "1")
    # ... head_sha, current_run init ...

    try:
        # entire pipeline from CCE-43 short-circuit through notifier dispatch
        ...
        return 0
    finally:
        _write_step_summary(state, repo_root)
```

The `try` opens _after_ `state["current_run"]` is initialized — the early-exit paths for `ConfigError`/`StateError` (which return _before_ a `current_run` exists) deliberately stay outside the wrapper. Those errors print to stderr and exit 2; there's nothing meaningful to summarize for an unbuilt run.

CCE-43's `_remote_already_processed_window` short-circuit at `scripts/orchestrator_runner.py:984-991` stays inside the `try` — its `current_run` is fresh-empty so the `_write_step_summary` no-op (empty `partial_reasons`) fires correctly.

### PR-body composer reuse

`open_or_append_pr` at line 1750 changes from inline `"; ".join(...)` to:

```python
if partial:
    digest = _format_partial_digest(partial_reasons)
    body = digest if digest else "docs-agent run"
else:
    body = "docs-agent run"
```

A `partial=True, partial_reasons=[]` invariant violation (shouldn't happen — `add_partial` is the only writer and it appends a reason before flipping `partial`) falls back gracefully to the clean-run body rather than emitting a bare "WARNING — Partial run" with no detail.

## Failure modes

| Mode                                                                        | Helper does                                                                      | Run summary shows                                                       |
| --------------------------------------------------------------------------- | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `$GITHUB_STEP_SUMMARY` unset (local run, unit test)                         | no-op                                                                            | n/a (no workflow context)                                               |
| Env var set, clean run (`partial_reasons` empty)                            | no-op                                                                            | only the existing `state.json` cat block (no `partial_reasons` heading) |
| Env var set, partial run with N reasons                                     | append `## docs-agent partial_reasons` heading + bulleted list                   | heading + each reason on its own bullet, after the `state.json` block   |
| Env var set, hard-fail mid-pipeline (exception thrown)                      | `finally` block runs; appends whatever reasons accumulated up to the throw point | partial heading + accumulated reasons; exception propagates as today    |
| Env var set, but `GITHUB_STEP_SUMMARY` path is unwritable                   | swallowed `OSError`; helper returns silently                                     | only the existing `state.json` cat block (degrades to today's behavior) |
| Env var set, `current_run` missing from state                               | no-op (`state.get("current_run") or {}` → empty `partial_reasons`)               | only the existing `state.json` cat block                                |
| Env var set, `partial=True` but `partial_reasons=[]` (invariant violation)  | no-op (empty list is the trigger for the early-return)                           | only the existing `state.json` cat block                                |
| Env var set, very large `partial_reasons` (forensics-discovered 8+ entries) | appends full bulleted list                                                       | full list rendered; GitHub Actions summary buffer cap is ~1 MiB         |

## Testing

All tests live in `tests/orchestrator/test_step_summary.py` (new file). The fixture pattern mirrors `tests/orchestrator/test_open_or_append_pr.py` — construct a small state dict, exercise the helper, assert on the file or its absence.

1. `test_helper_noop_when_env_var_unset`: monkeypatch `os.environ` to ensure `GITHUB_STEP_SUMMARY` is absent. Call `_write_step_summary` with a state that has partial reasons. Assert: no exception, no side effects observable.
2. `test_helper_noop_when_partial_reasons_empty`: env var points to a temp file. State has `current_run` but `partial_reasons=[]`. Assert: temp file is empty (helper returned early).
3. `test_helper_writes_digest_when_env_var_set_and_reasons_present`: env var points to a temp file. State has 2 partial reasons. Assert: file contains the heading and both reasons as bullets in the new format.
4. `test_helper_swallows_oserror_when_path_unwritable`: env var points to a path inside a missing directory. State has partial reasons. Assert: no exception raised.
5. `test_run_writes_summary_in_finally_on_hard_fail`: use the existing `_run_orchestrator` fixture from `test_state_carry_forward.py`. Monkeypatch `open_or_append_pr` to raise. Run `run()` directly (in-process, not subprocess). Assert: temp `$GITHUB_STEP_SUMMARY` file contains the digest section, even though `run()` propagated the exception.
6. `test_pr_body_uses_bulleted_format`: extend `tests/orchestrator/test_open_or_append_pr.py` with a test asserting the PR body for `partial=True, partial_reasons=["A", "B"]` matches the new bulleted shape.
7. `test_pr_body_clean_run_unchanged`: regression test asserting the clean-run body still equals exactly `"docs-agent run"`.

The in-process `run()` test (test 5) needs all subagent dispatch monkeypatched away — easier path: directly construct a state with `current_run.partial_reasons` populated, wrap a call-to-something-that-raises in the same try/finally pattern, and assert flush. The test exercises the seam, not the full pipeline.

## Acceptance criteria

1. `scripts/orchestrator_runner.py` gains `_format_partial_digest(partial_reasons: list[str]) -> str` and `_write_step_summary(state: dict, repo_root: Path) -> None` helpers.
2. `run()` wraps the post-state-init body in a `try`/`finally` that calls `_write_step_summary(state, repo_root)`. The early `ConfigError`/`StateError` returns stay outside the wrapper (no `current_run` to summarize).
3. `open_or_append_pr` uses `_format_partial_digest` for the partial-run body. The clean-run body string remains `"docs-agent run"` exactly.
4. PR body format changes from `WARNING — Partial run — A; B; C` to a `WARNING — Partial run` heading plus a bulleted list with one reason per line.
5. Seven new/extended unit tests from §Testing exist and pass.
6. Full pytest suite green (baseline: 612 passed, 3 skipped).
7. `$GITHUB_STEP_SUMMARY` is appended to (not overwritten) — the workflow's existing `state.json` cat block stays intact and the new digest block follows it.
8. No `.github/workflows/docs-agent-nightly.yml` change required.

## Out of scope

- **Workflow YAML dead-code bug at line 123.** The `cat .engineering-docs-agent/state.json 2>/dev/null | sed 's/^/  /' || echo "  (no state)"` chain has a bug: the `|| echo` only fires when `sed` (the right side of the pipe) exits non-zero, not when `cat` does. The `cat … 2>/dev/null` suppresses the error and pipes empty stdin to `sed`, which exits 0. Net: the "(no state)" fallback is unreachable. Track separately as a small workflow YAML fix; orthogonal to this PR's helper work.
- **Reading `current_run.json` directly from the workflow YAML.** A simpler-looking alternative ("just `cat` the sibling file too") would couple the workflow to a `.gitignore`d file path and break CCE-40's "current_run is per-runner ephemeral" invariant. The helper approach keeps the seam inside the runner where the data lives.
- **Notifier digest changes.** The notifier digest at `scripts/orchestrator_runner.py:1365-1380` already carries `partial_reasons`; the dispatched notifier subagent decides its own formatting. Step summary and notifier digest are different sinks.
- **Backfill of historical workflow run summaries.** Only future runs benefit; past runs stay as-is.
- **Forensics directory enrichment.** CCE-41's debug-dir capture is unaffected — `partial_reasons` already appears in the per-dispatch meta files for runs that used it.

## Risks

- **GitHub Actions summary buffer cap.** Documented at ~1 MiB. `partial_reasons` strings are short (avg ~80 chars per CCE-41 forensics samples); 8 entries ≈ 700 bytes. Far under cap. Mitigation if a future stage explodes the list: the workflow already truncates `state.json` with no truncation marker, so the failure mode is observable.
- **Append-after-state.json reading.** The workflow's `Run summary` step runs `if: always()`. If the runner step exits non-zero and the runner has not flushed (e.g., SIGKILL before the `finally`), no digest is appended — same behavior as today. Mitigated by the SIGTERM/SIGKILL contract of GitHub Actions cancellation being a rare, operator-initiated path.
- **Ordering with the existing `Run summary` workflow step.** The runner appends inside `run()`, which executes during the "Run nightly authoring" workflow step. The "Run summary" step runs _after_ "Run nightly authoring" and _appends_ to the same env-var-pointed file. So both blocks end up in the file; their relative order is "runner's `partial_reasons` digest first, workflow's `state.json` block second" (because the runner ran first). That ordering is acceptable — both are present and clearly labeled.
- **Test fragility on monkeypatched `os.environ`.** Tests must clean up `GITHUB_STEP_SUMMARY` to avoid pollution across the test session. Use `monkeypatch.delenv(..., raising=False)` in the helper-noop test.

## Decomposition note

Single-file runtime change (two helpers + one wrapper + one composer-callsite update) plus one new test file and one extension to `test_open_or_append_pr.py`. Per CCE-43's precedent for single-file changes, this could justify skipping the plan doc — but per the task brief, an explicit plan-doc is required for this ticket.
