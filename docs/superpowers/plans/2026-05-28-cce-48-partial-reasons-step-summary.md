# CCE-48 — partial_reasons in `$GITHUB_STEP_SUMMARY` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution (recommended for this scope) or superpowers:subagent-driven-development for fresh-subagent-per-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface `current_run.partial_reasons` in the docs-agent-nightly workflow's Run summary, so operators see why a run was partial without clicking into the docs-agent PR. Same formatter as the PR body (single source of truth). Hard-fail paths still flush via `try`/`finally`.

**Architecture:** Two new helpers in `scripts/orchestrator_runner.py` — `_format_partial_digest(partial_reasons)` (shared formatter, bulleted list) and `_write_step_summary(state, repo_root)` (env-detecting, failure-tolerant flush). One `try`/`finally` wrapper inside `run()`. One call-site update inside `open_or_append_pr` to reuse the shared formatter. PR-body format changes from `; `-joined to bulleted list (fold-in).

**Tech Stack:** Python 3.11+ stdlib (`os`); pytest with `monkeypatch` for env-var handling and `tmp_path` for sink files; in-process invocation of `run()` for the hard-fail integration test.

---

## File Structure

| File                                           | Change              | Purpose                                                                                                                       |
| ---------------------------------------------- | ------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `scripts/orchestrator_runner.py`               | Modify (+~50 lines) | Add `_format_partial_digest` and `_write_step_summary` helpers; wrap `run()` body in `try`/`finally`; update PR-body composer |
| `tests/orchestrator/test_step_summary.py`      | New (+~150 lines)   | Helper unit tests (env-var modes, OSError swallow) + integration test for try/finally flush                                   |
| `tests/orchestrator/test_open_or_append_pr.py` | Modify (+~30 lines) | Bulleted-format assertion for partial PR body + regression test for clean PR body                                             |

No `.github/workflows/docs-agent-nightly.yml` change. The spec already lives at `docs/superpowers/specs/2026-05-28-cce-48-partial-reasons-step-summary.md`.

## Task Dependency Order

```
Task 1 (failing test: helper no-ops when GITHUB_STEP_SUMMARY unset)
    → Task 2 (implement _write_step_summary skeleton — env-var no-op only)
        → Task 3 (failing test: helper appends digest when env var set + reasons)
            → Task 4 (implement _format_partial_digest + wire into _write_step_summary)
                → Task 5 (failing test: hard-fail in run() still flushes via finally)
                    → Task 6 (wrap run() body in try/finally)
                        → Task 7 (failing test: PR body uses bulleted format + clean-run regression)
                            → Task 8 (update open_or_append_pr to reuse _format_partial_digest)
                                → Task 9 (full pytest + ship readiness)
```

Strict TDD: each task's test fails first, then implementation lands and the test passes, then we commit.

---

## Task 1: Failing test — `_write_step_summary` no-ops when `GITHUB_STEP_SUMMARY` unset

**Files:**

- New: `tests/orchestrator/test_step_summary.py`

- [ ] **Step 1: Create the test file with the env-var-unset case**

Create `tests/orchestrator/test_step_summary.py`:

```python
"""CCE-48: surface partial_reasons in $GITHUB_STEP_SUMMARY.

The runner's _write_step_summary helper:
- no-ops when $GITHUB_STEP_SUMMARY is unset (local runs, unit tests)
- appends a bulleted digest when env var is set + partial_reasons non-empty
- swallows OSError when the env-var-pointed path is unwritable
- runs from a try/finally in run() so hard-fail paths still flush
"""

from __future__ import annotations
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402


def test_helper_noop_when_env_var_unset(tmp_path: Path, monkeypatch):
    """When GITHUB_STEP_SUMMARY is unset, the helper returns silently
    with no side effects — local runs and unit tests behave as today."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    state = {
        "version": "1",
        "current_run": {
            "partial": True,
            "partial_reasons": ["source_collector_invalid: returned None"],
        },
    }
    # Should not raise; should not touch any file.
    orun._write_step_summary(state, tmp_path)
    # Nothing on disk (assertion implicit — helper has no path to write to).
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/orchestrator/test_step_summary.py::test_helper_noop_when_env_var_unset -xvs
```

Expected: FAIL with `AttributeError: module 'orchestrator_runner' has no attribute '_write_step_summary'`.

- [ ] **Step 3: Do NOT commit yet** — implementation lands in Task 2.

---

## Task 2: Implement `_write_step_summary` skeleton (env-var no-op only)

**Files:**

- Modify: `scripts/orchestrator_runner.py` — add helper near the other module-level utilities.

- [ ] **Step 1: Add the skeleton helper**

Locate `def open_or_append_pr(...)` at `scripts/orchestrator_runner.py:1634`. Insert the new helper immediately BEFORE it (after `_remote_already_processed_window` ends at line 1632-ish).

```python


def _write_step_summary(state: dict, repo_root: Path) -> None:
    """Append the partial-reasons digest to $GITHUB_STEP_SUMMARY.

    No-op when the env var is unset (local runs, unit tests), when
    state lacks current_run, or when partial_reasons is empty.

    Failure-tolerant: never raises. If the path is unwritable
    (read-only fs, missing parent), swallows the OSError and returns —
    the runner's primary job is producing docs, not diagnostics.
    """
    summary_path_str = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path_str:
        return
    # Full digest-write logic lands in Task 4.
    return
```

- [ ] **Step 2: Verify the test now passes**

```bash
python3 -m pytest tests/orchestrator/test_step_summary.py::test_helper_noop_when_env_var_unset -xvs
```

Expected: PASS.

- [ ] **Step 3: Run full pytest suite**

```bash
python3 -m pytest -q
```

Expected: green (612 passed + 1 new = 613 passed; 3 skipped).

- [ ] **Step 4: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_step_summary.py
git commit -F - <<'EOF'
feat(CCE-48): _write_step_summary skeleton + env-var no-op test

First slice of the GITHUB_STEP_SUMMARY surfacing work. Helper is a
no-op when the env var is unset, which is the contract local runs
and unit tests rely on. Digest-write logic lands in the next commit
once a test exists to drive its shape.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
```

---

## Task 3: Failing test — `_write_step_summary` appends digest when env var set + reasons present

**Files:**

- Modify: `tests/orchestrator/test_step_summary.py` — append the env-var-set test.

- [ ] **Step 1: Append the test**

```python


def test_helper_writes_digest_when_env_var_set_and_reasons_present(
    tmp_path: Path, monkeypatch
):
    """With GITHUB_STEP_SUMMARY pointing to a file and partial_reasons
    non-empty, the helper appends a bulleted digest section."""
    summary = tmp_path / "summary.md"
    summary.write_text("## existing content\n")  # helper must APPEND, not overwrite
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    state = {
        "version": "1",
        "current_run": {
            "partial": True,
            "partial_reasons": [
                "source_collector_invalid: returned None",
                "page_author_invalid: docs/site-src/core/index.md",
            ],
        },
    }
    orun._write_step_summary(state, tmp_path)
    contents = summary.read_text()
    # Existing content preserved (append, not overwrite).
    assert "## existing content" in contents
    # New heading present.
    assert "## docs-agent partial_reasons" in contents
    # Each reason rendered as a bullet.
    assert "- source_collector_invalid: returned None" in contents
    assert "- page_author_invalid: docs/site-src/core/index.md" in contents
    # The bulleted list lives inside a "WARNING — Partial run" block.
    assert "WARNING — Partial run" in contents


def test_helper_noop_when_partial_reasons_empty(
    tmp_path: Path, monkeypatch
):
    """Clean runs (partial_reasons == []) leave the summary file
    untouched — the workflow's existing `state.json` cat step is
    sufficient signal for green runs."""
    summary = tmp_path / "summary.md"
    summary.write_text("baseline\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    state = {
        "version": "1",
        "current_run": {"partial": False, "partial_reasons": []},
    }
    orun._write_step_summary(state, tmp_path)
    assert summary.read_text() == "baseline\n"


def test_helper_noop_when_current_run_missing(tmp_path: Path, monkeypatch):
    """If state has no current_run (defensive — shouldn't happen at the
    flush point), the helper returns silently rather than KeyError."""
    summary = tmp_path / "summary.md"
    summary.write_text("baseline\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    state = {"version": "1"}
    orun._write_step_summary(state, tmp_path)
    assert summary.read_text() == "baseline\n"


def test_helper_swallows_oserror_when_path_unwritable(
    tmp_path: Path, monkeypatch
):
    """If the env-var-pointed path is unwritable (missing parent dir,
    read-only fs), the helper swallows OSError so the runner's primary
    output isn't held hostage by a diagnostics sink."""
    bad_path = tmp_path / "does" / "not" / "exist" / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(bad_path))
    state = {
        "version": "1",
        "current_run": {"partial": True, "partial_reasons": ["x"]},
    }
    # Must not raise.
    orun._write_step_summary(state, tmp_path)
```

- [ ] **Step 2: Run new tests — expect first to fail, last three may incidentally pass on the skeleton**

```bash
python3 -m pytest tests/orchestrator/test_step_summary.py -xvs
```

Expected: `test_helper_writes_digest_when_env_var_set_and_reasons_present` FAILS because the skeleton only handles the no-op branch. Either or both noop-when-empty / oserror-swallow tests may pass on the skeleton (the early-return is also "no write"); confirm which.

- [ ] **Step 3: Do NOT commit yet** — implementation lands in Task 4.

---

## Task 4: Implement `_format_partial_digest` + complete `_write_step_summary`

**Files:**

- Modify: `scripts/orchestrator_runner.py` — add `_format_partial_digest`, extend `_write_step_summary`.

- [ ] **Step 1: Add `_format_partial_digest` above `_write_step_summary`**

Insert immediately before the `_write_step_summary` helper:

```python


def _format_partial_digest(partial_reasons: list[str]) -> str:
    """Single-source format for partial_reasons.

    Used by:
    - PR body composer in open_or_append_pr
    - GITHUB_STEP_SUMMARY writer in _write_step_summary

    Returns an empty string when partial_reasons is empty so callers
    can detect the no-reasons case without re-checking the list.
    """
    if not partial_reasons:
        return ""
    lines = ["WARNING — Partial run", ""]
    lines.extend(f"- {r}" for r in partial_reasons)
    return "\n".join(lines)
```

- [ ] **Step 2: Replace `_write_step_summary` body with the full digest-write logic**

Find the skeleton (only returns on env-var-unset). Replace with:

```python
def _write_step_summary(state: dict, repo_root: Path) -> None:
    """Append the partial-reasons digest to $GITHUB_STEP_SUMMARY.

    No-op when the env var is unset (local runs, unit tests), when
    state lacks current_run, or when partial_reasons is empty.

    Failure-tolerant: never raises. If the path is unwritable
    (read-only fs, missing parent), swallows the OSError and returns —
    the runner's primary job is producing docs, not diagnostics.
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
        return
```

- [ ] **Step 3: Run all of `test_step_summary.py`**

```bash
python3 -m pytest tests/orchestrator/test_step_summary.py -xvs
```

Expected: all 5 tests pass.

- [ ] **Step 4: Run full pytest suite**

```bash
python3 -m pytest -q
```

Expected: green (612 + 5 new = 617 passed; 3 skipped).

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_step_summary.py
git commit -F - <<'EOF'
feat(CCE-48): _format_partial_digest + complete _write_step_summary

Shared bulleted-list formatter that the PR-body composer (Task 8) and
the step-summary writer both consume. _write_step_summary now appends
the digest to $GITHUB_STEP_SUMMARY when the env var is set and
partial_reasons is non-empty; OSError is swallowed so an unwritable
diagnostics sink can't take down the runner.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
```

---

## Task 5: Failing test — hard-fail in `run()` still flushes via `try`/`finally`

**Files:**

- Modify: `tests/orchestrator/test_step_summary.py` — append the run() integration test.

- [ ] **Step 1: Append the test**

```python


def test_run_writes_summary_in_finally_on_hard_fail(
    tmp_path: Path, monkeypatch
):
    """Hard-fail mid-pipeline (open_or_append_pr raises) still flushes
    accumulated partial_reasons to $GITHUB_STEP_SUMMARY. The try/finally
    in run() guarantees the diagnostics sink sees what the in-memory
    state accumulated up to the throw point."""
    import json
    import shutil

    # Set up a minimal e2e_host fixture so config + state load succeed.
    HOST = (
        Path(__file__).parent.parent / "fixtures" / "e2e_host"
    )
    FAKES = Path(__file__).parent / "fakes"
    host = tmp_path / "host"
    shutil.copytree(HOST, host)
    import subprocess as sp

    sp.run(["git", "-C", str(host), "init", "-q"], check=True)
    sp.run(
        ["git", "-C", str(host), "config", "user.email", "t@t"], check=True
    )
    sp.run(["git", "-C", str(host), "config", "user.name", "t"], check=True)
    sp.run(["git", "-C", str(host), "add", "."], check=True)
    sp.run(
        ["git", "-C", str(host), "commit", "-q", "-m", "init"], check=True
    )

    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    # Patch open_or_append_pr to (a) seed a partial_reason, (b) raise.
    original_state_seed = {"seen": False}

    def fake_open(*args, **kwargs):
        # The state dict isn't passed in; we mutate via the partial_reasons
        # list the caller passes. add_partial in run() already ran for the
        # source_collector path because the fake's source-collector output
        # is good, so we need a different path: raise directly.
        raise RuntimeError("simulated hard-fail mid-PR-open")

    monkeypatch.setattr(orun, "open_or_append_pr", fake_open)

    # Seed a partial_reason via the seeded state so the digest has content.
    state_path = host / ".engineering-docs-agent" / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "version": "1",
                "current_run": {
                    "started_at": "2026-05-28T22:00:00+00:00",
                    "head_sha": "seeded",
                    "partial": True,
                    "partial_reasons": [
                        "seeded_reason: present before run() starts",
                    ],
                },
            }
        )
    )

    # run() should raise (we made open_or_append_pr crash), but the
    # finally block must have flushed first.
    raised = None
    try:
        orun.run(host, dry_run_dir=FAKES, no_pr=False)
    except RuntimeError as e:
        raised = e

    # NOTE: CCE-5 clears prior current_run at run() start, so the seeded
    # partial_reason is dropped. The fake dispatch may or may not add new
    # ones. The contract we're testing: the FINALLY runs, so if any
    # partial_reasons accumulated by the throw point, they reach the sink.
    # Easier assertion: a hard-fail path runs `_write_step_summary` at
    # least once. We assert the function was invoked by patching it.

    # (Strategy revision lands in implementation; this test as written
    # asserts the high-level contract — the test may need adjustment
    # once Task 6 settles where the seam goes.)
    assert raised is not None, (
        "expected the patched open_or_append_pr to propagate its RuntimeError"
    )
```

The test is intentionally fuzzy on the asserted state of `summary` — Task 6's implementation may add new `partial_reasons` along the dispatch path. The hard contract under test is: `RuntimeError` propagates AND the finally executes. The first assertion (`raised is not None`) catches the propagation. To catch the finally executing, we add a second test below that wraps `_write_step_summary` with a counter via `monkeypatch.setattr`.

```python


def test_run_invokes_write_step_summary_in_finally_on_hard_fail(
    tmp_path: Path, monkeypatch
):
    """Stronger contract: the finally block calls _write_step_summary
    even when run() propagates an exception from downstream."""
    import shutil

    HOST = (
        Path(__file__).parent.parent / "fixtures" / "e2e_host"
    )
    FAKES = Path(__file__).parent / "fakes"
    host = tmp_path / "host"
    shutil.copytree(HOST, host)
    import subprocess as sp

    sp.run(["git", "-C", str(host), "init", "-q"], check=True)
    sp.run(
        ["git", "-C", str(host), "config", "user.email", "t@t"], check=True
    )
    sp.run(["git", "-C", str(host), "config", "user.name", "t"], check=True)
    sp.run(["git", "-C", str(host), "add", "."], check=True)
    sp.run(
        ["git", "-C", str(host), "commit", "-q", "-m", "init"], check=True
    )

    calls = []

    def fake_write(state, repo_root):
        calls.append({"partial_reasons": list(
            (state.get("current_run") or {}).get("partial_reasons", [])
        )})

    monkeypatch.setattr(orun, "_write_step_summary", fake_write)

    def fake_open(*args, **kwargs):
        raise RuntimeError("simulated hard-fail mid-PR-open")

    monkeypatch.setattr(orun, "open_or_append_pr", fake_open)

    try:
        orun.run(host, dry_run_dir=FAKES, no_pr=False)
    except RuntimeError:
        pass

    assert len(calls) >= 1, (
        f"expected _write_step_summary to be called from run()'s finally; "
        f"got {len(calls)} calls"
    )
```

- [ ] **Step 2: Run the new test**

```bash
python3 -m pytest tests/orchestrator/test_step_summary.py::test_run_invokes_write_step_summary_in_finally_on_hard_fail -xvs
```

Expected: FAIL — `run()` doesn't yet wrap in try/finally, so when `open_or_append_pr` raises, no `_write_step_summary` call happens before the exception propagates. The fake never appends to `calls`.

The fuzzy `test_run_writes_summary_in_finally_on_hard_fail` may also fail or pass-incidentally; primary signal is the stronger one above.

- [ ] **Step 3: Do NOT commit yet** — implementation lands in Task 6.

---

## Task 6: Wrap `run()` body in `try`/`finally`

**Files:**

- Modify: `scripts/orchestrator_runner.py` — wrap the body of `run()` from after `state["current_run"]` initialization to the function's `return 0` paths.

- [ ] **Step 1: Edit `run()` to add try/finally**

Locate `run()` at `scripts/orchestrator_runner.py:924`. The current shape:

```python
def run(repo_root: Path, *, dry_run_dir: Path | None, no_pr: bool) -> int:
    cfg_path = repo_root / ".engineering-docs-agent" / "config.yml"
    state_path = repo_root / ".engineering-docs-agent" / "state.json"
    if not cfg_path.exists():
        print("no config", file=sys.stderr)
        return 2
    try:
        config = load_config_validated(cfg_path)
    except ConfigError as e:
        print(f"config invalid: {e}", file=sys.stderr)
        return 2
    voice_samples = load_voice_samples(repo_root, config)
    try:
        state = load_state_validated(state_path)
    except StateError as e:
        print(f"state invalid: {e}", file=sys.stderr)
        return 2
    state.setdefault("version", "1")
    # ... head_sha, repo detect ...
    # ... current_run init ...
    # ... ENTIRE PIPELINE ...
    return 0
```

Insert a `try`/`finally` _after_ `state["current_run"]` is initialized and _before_ any pipeline work. The `finally` calls `_write_step_summary`. The `try`'s body is the entire pipeline; transform all `return` statements inside the pipeline to nested returns inside the `try`.

Edit by identifying the line `state["current_run"] = { … }` block (around line 961-966). After it (and after the stale-run check at lines 968-976), insert `try:` and indent everything down to (but not including) the end of the function. The final `return 0` (currently at line 1399) becomes the last statement inside the `try`. Add `finally: _write_step_summary(state, repo_root)` after it.

Concretely, locate this anchor:

```python
    if prior_run is not None:
        prior_started = prior_run.get("started_at")
        if prior_started:
            try:
                prior_dt = datetime.fromisoformat(prior_started.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - prior_dt) > timedelta(hours=24):
                    add_partial(state, "stale_current_run_cleared", info_only=True)
            except ValueError:
                pass

    # CCE-43: same-hour rerun guard. ...
```

Replace `    # CCE-43: same-hour rerun guard. ...` with `    try:` and re-indent the rest of the function body by 4 spaces. The pipeline ends with `    return 0` (currently line 1399); after re-indent that becomes `        return 0`. Append `    finally:\n        _write_step_summary(state, repo_root)` after the re-indented `return 0`.

This is a large block-level reindent — use Edit with a single large `old_string` / `new_string` covering from the `# CCE-43` anchor down to the end of `run()`, OR do it in two stages (Edit re-indents the body; Edit adds the try/finally framing).

**Implementation hint:** the simplest seam is a `try:` at the line where the CCE-43 comment block starts (line 978) and a `finally:` block before `def run_bootstrap_core` (line 1402). All early `return` statements inside the pipeline (`return 0` at line 991, `return 1` at line 1359, etc.) automatically trigger the finally — Python's contract.

The `voice_samples` line at 936 stays _outside_ the try because it's before `state["current_run"]` is initialized — if it throws (which it doesn't today; it returns []), there's nothing to summarize.

- [ ] **Step 2: Run the integration test**

```bash
python3 -m pytest tests/orchestrator/test_step_summary.py -xvs
```

Expected: all step_summary tests pass, including the try/finally one.

- [ ] **Step 3: Run full pytest suite**

```bash
python3 -m pytest -q
```

Expected: green. The re-indent shouldn't break anything because the pipeline shape is unchanged (early returns still exit; the finally adds an extra observable call).

If anything fails, especially `test_state_carry_forward.py` / `test_runner_state_promotion.py`, the re-indent likely broke an early-return path. Diff against the pre-edit file and re-verify.

- [ ] **Step 4: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_step_summary.py
git commit -F - <<'EOF'
feat(CCE-48): try/finally in run() flushes partial_reasons on hard-fail

The runner's pipeline body is now wrapped in try/finally so any return
path (success, no-PR, pr_number is None, exception) flows through
_write_step_summary. Hard-fail paths (open_or_append_pr crash,
dispatch_validated raise, unhandled KeyError downstream) now surface
the accumulated partial_reasons in $GITHUB_STEP_SUMMARY before the
exception propagates.

The try opens after state["current_run"] is initialized — the
ConfigError/StateError early returns at the top of run() stay outside
the wrapper because there's no current_run to summarize there yet.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
```

---

## Task 7: Failing test — PR body uses bulleted format

**Files:**

- Modify: `tests/orchestrator/test_open_or_append_pr.py` — append a test asserting the new format.

- [ ] **Step 1: Append two new tests**

```python


# CCE-48: PR body switches from "; ".join() to a bulleted list using
# the shared _format_partial_digest formatter so the step summary and
# PR body stay format-aligned.


def test_partial_pr_body_uses_bulleted_format(tmp_path: Path):
    """Partial-run PR body is a bulleted list, not '; '-joined."""
    gh = _make_gh_client_stub(pr_number=42)
    captured_body = {}

    def capture_create(branch, commit_msg, body):
        captured_body["body"] = body
        return MagicMock(ok=True, value=42)

    gh.pr_create.side_effect = capture_create

    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_make_subprocess_stub(
            push_rc=0,
            push_stderr="",
            lsremote_sha="localsha",
        ),
    ):
        orun.open_or_append_pr(
            tmp_path,
            gh,
            branch="docs-agent/test",
            now_iso="2026-05-28T22:00:00+00:00",
            partial=True,
            partial_reasons=["reason_one", "reason_two"],
        )

    body = captured_body["body"]
    # Heading must be on its own line.
    assert "WARNING — Partial run" in body
    # Each reason is a bullet, not joined by '; '.
    assert "- reason_one" in body
    assert "- reason_two" in body
    # Confirm the old "; "-join shape is GONE.
    assert "reason_one; reason_two" not in body


def test_clean_pr_body_unchanged(tmp_path: Path):
    """Clean-run PR body remains exactly 'docs-agent run'."""
    gh = _make_gh_client_stub(pr_number=42)
    captured_body = {}

    def capture_create(branch, commit_msg, body):
        captured_body["body"] = body
        return MagicMock(ok=True, value=42)

    gh.pr_create.side_effect = capture_create

    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_make_subprocess_stub(
            push_rc=0,
            push_stderr="",
            lsremote_sha="localsha",
        ),
    ):
        orun.open_or_append_pr(
            tmp_path,
            gh,
            branch="docs-agent/test",
            now_iso="2026-05-28T22:00:00+00:00",
            partial=False,
            partial_reasons=[],
        )

    assert captured_body["body"] == "docs-agent run"
```

- [ ] **Step 2: Run both tests**

```bash
python3 -m pytest tests/orchestrator/test_open_or_append_pr.py::test_partial_pr_body_uses_bulleted_format tests/orchestrator/test_open_or_append_pr.py::test_clean_pr_body_unchanged -xvs
```

Expected: `test_partial_pr_body_uses_bulleted_format` FAILS — current PR body uses `"; ".join(...)`, so `- reason_one` won't be present. `test_clean_pr_body_unchanged` should pass (the clean path is already `"docs-agent run"`).

- [ ] **Step 3: Do NOT commit yet** — implementation lands in Task 8.

---

## Task 8: Update `open_or_append_pr` to reuse `_format_partial_digest`

**Files:**

- Modify: `scripts/orchestrator_runner.py:1750-1754` — replace inline join with shared formatter call.

- [ ] **Step 1: Edit the PR-body composer**

```python
# old_string
    body = (
        "WARNING — Partial run — " + "; ".join(partial_reasons)
        if partial
        else "docs-agent run"
    )

# new_string
    if partial:
        digest = _format_partial_digest(partial_reasons)
        body = digest if digest else "docs-agent run"
    else:
        body = "docs-agent run"
```

The fallback to `"docs-agent run"` when `partial=True` but `partial_reasons=[]` covers the invariant violation defensively (today's inline format would emit `"WARNING — Partial run — "` which is also nonsensical).

- [ ] **Step 2: Run both PR-body tests**

```bash
python3 -m pytest tests/orchestrator/test_open_or_append_pr.py -xvs
```

Expected: all existing tests PASS (the change is format-only; no test asserts the precise `"; "`-join shape because the existing tests assert different concerns). Both new tests PASS.

- [ ] **Step 3: Run full pytest suite**

```bash
python3 -m pytest -q
```

Expected: green.

- [ ] **Step 4: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_open_or_append_pr.py
git commit -F - <<'EOF'
feat(CCE-48): PR body reuses _format_partial_digest (bulleted list)

The PR body composer in open_or_append_pr now delegates to the shared
_format_partial_digest helper. Both the step summary and the PR body
render partial_reasons as a bulleted list, which scales readably past
2-3 entries (CCE-41 forensics saw runs accumulate 8+ reasons).

Defensive fallback: if partial=True but partial_reasons is empty
(invariant violation; shouldn't happen), the body falls back to
"docs-agent run" rather than emitting a bare "WARNING — Partial run"
with no context.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
```

---

## Task 9: Full pytest suite + ship readiness

**Files:** none modified — verification only.

- [ ] **Step 1: Run the FULL test suite**

```bash
python3 -m pytest -q 2>&1 | tail -10
```

Expected: `=== 619 passed, 3 skipped in <Ns> ===` (baseline 612 + 7 new = 619). Zero failures.

If anything fails: STOP. Do not proceed to /ship. Diagnose with `/systematic-debugging`.

- [ ] **Step 2: Verify branch state**

```bash
git status && git log --oneline main..HEAD
```

Expected:

- `git status`: clean working tree on `feat/CCE-48-partial-reasons-step-summary`
- `git log`: 6 commits beyond main (spec + plan + 4 implementation commits)

The exact commit list (oldest → newest beyond main):

1. `docs(CCE-48): spec — partial_reasons in $GITHUB_STEP_SUMMARY` (Step 1)
2. `docs(CCE-48): plan — partial_reasons in $GITHUB_STEP_SUMMARY` (Step 2)
3. `feat(CCE-48): _write_step_summary skeleton + env-var no-op test` (Task 2)
4. `feat(CCE-48): _format_partial_digest + complete _write_step_summary` (Task 4)
5. `feat(CCE-48): try/finally in run() flushes partial_reasons on hard-fail` (Task 6)
6. `feat(CCE-48): PR body reuses _format_partial_digest (bulleted list)` (Task 8)

- [ ] **Step 3: Surface ship readiness to the user**

End the agent's final response with the ship-readiness block per the brief. DO NOT auto-invoke `/ship`.

---

## Out of scope (do not implement in this plan)

- **Workflow YAML dead-code bug** in `.github/workflows/docs-agent-nightly.yml:123` (`cat ... 2>/dev/null | sed ... || echo "(no state)"` — the `|| echo` only fires when `sed` exits non-zero, never on `cat` failure). Track as a separate small workflow YAML fix; orthogonal to the runner helper work.
- **Reading `current_run.json` directly from the workflow.** Would couple the workflow to a gitignored sibling file and break the CCE-40 ephemerality invariant. The in-runner helper keeps the data inside the seam that owns it.
- **Backfill of historical workflow run summaries.** Only future runs benefit; past runs remain as-is.
- **Notifier digest reshape.** The notifier already carries `partial_reasons` in its digest; its subagent decides its own format. Step summary and notifier digest stay independent.

## Post-merge actions (after `/ship` and merge)

1. Fire `gh workflow run docs-agent-nightly.yml --ref main`. Wait for completion.
2. Open the workflow run page. Confirm the Run summary block now contains a `## docs-agent partial_reasons` heading + bulleted list whenever the run was partial.
3. For a clean (non-partial) run, confirm the summary contains only the existing `state.json` cat block (no false-positive partial_reasons heading).
4. Transition CCE-48 → Done on Jira (requires user authorization).
5. Open a follow-up ticket for the workflow YAML dead-code bug (the `|| echo "(no state)"` fallback unreachability).

These are session-conversation actions, not plan tasks.
