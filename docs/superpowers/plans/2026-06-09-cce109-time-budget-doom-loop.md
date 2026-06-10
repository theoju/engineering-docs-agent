# CCE-109 Time-budget Soft Deadline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the nightly docs-agent from timing out on large windows by processing PRs only until a soft time budget elapses, then advancing the baseline to the last fully-processed PR so the window drains incrementally and the doom loop cannot re-form.

**Architecture:** All changes live in `scripts/orchestrator_runner.py` plus a schema key and a new test file. A soft deadline (monotonic clock, injectable for tests) gates per-PR _admission_ at the top of the existing pr-summarizer loop. PRs are reordered oldest-first before admission so the admitted set is always a contiguous oldest prefix; on truncation the baseline advances to the newest admitted PR's `merge_sha` (else to `HEAD`, unchanged). One config knob (`run.time_budget_seconds`, default 2700) plus a `--time-budget-seconds` CLI override; `0` = unlimited (today's behavior).

**Tech Stack:** Python 3.11+ stdlib (`time.monotonic`, `subprocess`/`git rev-list`, `argparse`), pytest with the fixture-driven dry-run path (`--dry-run-subagents`), JSON Schema config validation.

**Spec:** `docs/superpowers/specs/2026-06-09-cce109-time-budget-doom-loop-design.md`

**Grounding (verified line numbers as of branch `feat/CCE-109-time-budget-doom-loop`):**

- `run(repo_root, *, dry_run_dir, no_pr) -> int` — `scripts/orchestrator_runner.py:1005`; loads `config` at `:1016`.
- pr-summarizer loop `for pr in prs:` — `:1140`.
- `prs = sources.get("prs", [])` (post-clip) — `:1118`; clip call `_clip_prs_to_window` — `:1108`.
- state advance dict — `:1449`; `prior_baseline_sha` capture — `:1442`.
- gap-detector loop `for pr in prs:` — `:1387`; whats-new `if prs:` — `:1418`.
- `main()` argparse — `:2342`; calls `run(...)` — last line of `main`.
- `add_partial(state, reason, *, info_only=False)` — `scripts/state_io.py:232`.
- imports line `import argparse, fnmatch, json, os, re, subprocess, sys` — `:9`; `from typing import Any, Callable` — `:12` (Callable already imported; `time` is NOT imported).
- `_clip_prs_to_window` graceful git-missing/failure path returns `prs` unchanged — `:336`–`:352`.
- Test patterns: `tests/orchestrator/test_state_advancement_invariant.py` (`_init_host`, `_read_current_run`, direct `runner.run(...)` call); multi-PR fixture dir `tests/orchestrator/fakes_multi/` (3 PRs, numbers 1/2/3, merge_sha `a`/`b`/`c`).

---

## File Structure

| File                                     | Responsibility        | Change                                                                                                                                                                                                                                                                                        |
| ---------------------------------------- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/orchestrator_runner.py`         | Orchestrator run loop | Add `DEFAULT_TIME_BUDGET_SECONDS`, `resolve_time_budget`, `_order_prs_oldest_first`, `_last_processed_merge_sha`; add `time_budget_seconds`/`now_monotonic` params to `run()`; deadline setup; admission gate + truncation; advance-SHA selection; `--time-budget-seconds` CLI; `import time` |
| `templates/config.schema.json`           | Host config contract  | Add optional top-level `run` object with `time_budget_seconds` (integer ≥ 0)                                                                                                                                                                                                                  |
| `tests/orchestrator/test_time_budget.py` | New behavior tests    | Create — 7 tests + a real-git-window helper                                                                                                                                                                                                                                                   |

DRY note: `_order_prs_oldest_first` and the existing `_clip_prs_to_window` both call `git rev-list`. Keep them as two small helpers (each one `rev-list` call); do **not** refactor clip in this work — the spec says ordering "may be shared at the plan's discretion," and a second narrow helper is simpler and lower-risk than threading shared state through clip.

---

## Task 1: Budget resolution + plumbing (no behavior change yet)

Introduces the default constant, the resolver, the `run()` parameters, the computed (but not-yet-consumed) deadline, the CLI flag, and the config-schema key. After this task the deadline is computed and unused; nothing truncates.

**Files:**

- Modify: `scripts/orchestrator_runner.py` (imports `:9`; new constant + `resolve_time_budget` near other module-level helpers; `run()` signature `:1005` and body after config load `:1016`; `main()` `:2342`)
- Modify: `templates/config.schema.json`
- Test: `tests/orchestrator/test_time_budget.py` (new)

- [ ] **Step 1: Write the failing test for `resolve_time_budget`**

Create `tests/orchestrator/test_time_budget.py` with:

```python
# tests/orchestrator/test_time_budget.py
"""CCE-109: time-budget soft deadline — break the nightly doom loop."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import orchestrator_runner as runner  # noqa: E402


def test_resolve_time_budget_precedence():
    # CLI override wins (including explicit 0 = unlimited).
    assert runner.resolve_time_budget({"run": {"time_budget_seconds": 1200}}, 999) == 999
    assert runner.resolve_time_budget({"run": {"time_budget_seconds": 1200}}, 0) == 0
    # No CLI override → config value.
    assert runner.resolve_time_budget({"run": {"time_budget_seconds": 1200}}, None) == 1200
    # No CLI, no config → default.
    assert runner.resolve_time_budget({}, None) == runner.DEFAULT_TIME_BUDGET_SECONDS
    assert runner.resolve_time_budget({"run": {}}, None) == runner.DEFAULT_TIME_BUDGET_SECONDS
    # Default is 2700.
    assert runner.DEFAULT_TIME_BUDGET_SECONDS == 2700
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 -m pytest tests/orchestrator/test_time_budget.py::test_resolve_time_budget_precedence -q`
Expected: FAIL with `AttributeError: module 'orchestrator_runner' has no attribute 'resolve_time_budget'`.

- [ ] **Step 3: Add `import time`**

In `scripts/orchestrator_runner.py:9`, change:

```python
import argparse, fnmatch, json, os, re, subprocess, sys
```

to:

```python
import argparse, fnmatch, json, os, re, subprocess, sys, time
```

- [ ] **Step 4: Add the constant and resolver**

Add near the other module-level helpers in `scripts/orchestrator_runner.py` (e.g. directly above `def _clip_prs_to_window(`):

```python
DEFAULT_TIME_BUDGET_SECONDS = 2700  # 45 min; below the 60-min job hard limit


def resolve_time_budget(config: dict, cli_override: int | None) -> int:
    """Resolve the per-run soft time budget in seconds.

    Precedence: CLI override (incl. explicit 0 = unlimited) > config
    `run.time_budget_seconds` > DEFAULT_TIME_BUDGET_SECONDS. A value <= 0 means
    "no budget" (unlimited); the caller turns that into deadline=None.
    """
    if cli_override is not None:
        return cli_override
    run_cfg = config.get("run") or {}
    val = run_cfg.get("time_budget_seconds")
    if val is None:
        return DEFAULT_TIME_BUDGET_SECONDS
    return int(val)
```

- [ ] **Step 5: Add `run()` parameters and compute the deadline**

Change the signature at `scripts/orchestrator_runner.py:1005`:

```python
def run(repo_root: Path, *, dry_run_dir: Path | None, no_pr: bool) -> int:
```

to:

```python
def run(
    repo_root: Path,
    *,
    dry_run_dir: Path | None,
    no_pr: bool,
    time_budget_seconds: int | None = None,
    now_monotonic: Callable[[], float] | None = None,
) -> int:
```

Then immediately after `config` is successfully loaded (right after the
`load_config_validated` try/except block ends, before `voice_samples = ...` at
`:1016`), insert:

```python
    clock = now_monotonic or time.monotonic
    _budget = resolve_time_budget(config, time_budget_seconds)
    deadline = clock() + _budget if _budget and _budget > 0 else None
```

(`deadline` is computed here and consumed in Task 3.)

- [ ] **Step 6: Add the CLI flag and pass it through**

In `main()` at `scripts/orchestrator_runner.py:2342`, add after the `--today` argument:

```python
    parser.add_argument(
        "--time-budget-seconds",
        type=int,
        default=None,
        help="CCE-109 soft per-run budget (seconds). 0 = unlimited. "
        "Overrides config run.time_budget_seconds.",
    )
```

and change the final `return run(...)` to thread the value:

```python
    return run(
        args.repo_root,
        dry_run_dir=args.dry_run_subagents,
        no_pr=args.no_pr,
        time_budget_seconds=args.time_budget_seconds,
    )
```

- [ ] **Step 7: Add the config-schema key**

In `templates/config.schema.json`, add to the top-level `"properties"` object (sibling of `"site"`; do **not** add it to `"required"`):

```json
    "run": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "time_budget_seconds": {
          "type": "integer",
          "minimum": 0,
          "description": "CCE-109: soft per-run time budget in seconds. 0 = unlimited. Default 2700."
        }
      }
    }
```

- [ ] **Step 8: Run the test to confirm it passes**

Run: `python3 -m pytest tests/orchestrator/test_time_budget.py::test_resolve_time_budget_precedence -q`
Expected: PASS.

- [ ] **Step 9: Confirm no regression**

Run: `python3 -m pytest tests/orchestrator/test_state_advancement_invariant.py -q`
Expected: PASS (unchanged — deadline is computed but unused).

- [ ] **Step 10: Commit**

```bash
git add scripts/orchestrator_runner.py templates/config.schema.json tests/orchestrator/test_time_budget.py
git commit -m "feat(CCE-109): time-budget resolution + run() plumbing (no behavior change)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Oldest-first PR ordering helper

Adds `_order_prs_oldest_first` and wires it in after the window-clip so PRs are processed oldest-first. Correctness requirement (spec Component 2): the admitted set must be a contiguous oldest prefix so advancing to the last admitted PR never skips an older one.

**Files:**

- Modify: `scripts/orchestrator_runner.py` (new helper near `_clip_prs_to_window`; wire after `:1118`)
- Test: `tests/orchestrator/test_time_budget.py`

- [ ] **Step 1: Write the failing test (real git window + passthrough fallback)**

Append to `tests/orchestrator/test_time_budget.py`:

```python
def _git(tmp: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(tmp), *args],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _init_repo_with_commits(tmp: Path, n: int) -> list[str]:
    """Init a git repo with 1 base commit + n numbered commits.
    Returns [base_sha, c1, c2, ..., cn] (oldest-first)."""
    tmp.mkdir(parents=True, exist_ok=True)
    _git(tmp, "init", "-q")
    _git(tmp, "config", "user.email", "t@example.com")
    _git(tmp, "config", "user.name", "T")
    (tmp / "f.txt").write_text("base")
    _git(tmp, "add", ".")
    _git(tmp, "commit", "-q", "-m", "base")
    shas = [_git(tmp, "rev-parse", "HEAD")]
    for i in range(1, n + 1):
        (tmp / "f.txt").write_text(f"c{i}")
        _git(tmp, "add", ".")
        _git(tmp, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(tmp, "rev-parse", "HEAD"))
    return shas


def test_order_prs_oldest_first_reorders_with_real_window(tmp_path):
    shas = _init_repo_with_commits(tmp_path, 3)  # [base, c1, c2, c3]
    base, c1, c2, c3 = shas
    head = c3
    # PRs supplied newest-first; merge_sha = real commits.
    prs = [
        {"number": 3, "merge_sha": c3},
        {"number": 2, "merge_sha": c2},
        {"number": 1, "merge_sha": c1},
    ]
    ordered = runner._order_prs_oldest_first(
        prs, repo_root=tmp_path, last_sha=base, head_sha=head
    )
    assert [p["number"] for p in ordered] == [1, 2, 3]


def test_order_prs_oldest_first_passthrough_when_git_fails(tmp_path):
    # Bogus last_sha → git rev-list fails → return prs unchanged (graceful).
    prs = [{"number": 3, "merge_sha": "c"}, {"number": 1, "merge_sha": "a"}]
    ordered = runner._order_prs_oldest_first(
        prs, repo_root=tmp_path, last_sha="nope000", head_sha="nope999"
    )
    assert [p["number"] for p in ordered] == [3, 1]
```

- [ ] **Step 2: Run to confirm failure**

Run: `python3 -m pytest tests/orchestrator/test_time_budget.py -k order_prs -q`
Expected: FAIL with `AttributeError: ... has no attribute '_order_prs_oldest_first'`.

- [ ] **Step 3: Implement the helper**

Add directly below `resolve_time_budget` in `scripts/orchestrator_runner.py`:

```python
def _order_prs_oldest_first(
    prs: list[dict],
    *,
    last_sha: str,
    head_sha: str,
    repo_root: Path,
) -> list[dict]:
    """Return ``prs`` sorted oldest-merge-first by position in the window.

    CCE-109 correctness requirement: the admission gate truncates to a prefix,
    and the baseline advances to the last admitted PR. Processing oldest-first
    makes that prefix a contiguous oldest run, so advancing never skips an older
    PR. Order key = index of the PR's merge_sha in
    ``git rev-list --reverse last_sha..head_sha`` (oldest-first). PRs whose
    merge_sha is missing or out-of-window sort last (cannot anchor the cursor).

    Degrades gracefully: if ``last_sha`` is empty or git is unavailable/fails,
    returns ``prs`` unchanged (mirrors ``_clip_prs_to_window``).
    """
    if not last_sha or not prs:
        return prs
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_root), "rev-list", "--reverse",
             f"{last_sha}..{head_sha}"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return prs
    if r.returncode != 0:
        return prs
    order = {sha.strip(): i for i, sha in enumerate(r.stdout.splitlines()) if sha.strip()}
    order_short = {sha[:7]: i for sha, i in order.items()}
    big = len(order) + 1

    def key(pr: dict) -> int:
        sha = (pr.get("merge_sha") or "").strip()
        if sha in order:
            return order[sha]
        if sha[:7] in order_short:
            return order_short[sha[:7]]
        return big

    return sorted(prs, key=key)
```

- [ ] **Step 4: Wire it into `run()`**

In `scripts/orchestrator_runner.py`, right after `prs = sources.get("prs", [])` (`:1118`), add:

```python
        prs = _order_prs_oldest_first(
            prs,
            last_sha=sc_inputs["last_sha"],
            head_sha=head_sha,
            repo_root=repo_root,
        )
```

- [ ] **Step 5: Run to confirm pass**

Run: `python3 -m pytest tests/orchestrator/test_time_budget.py -k order_prs -q`
Expected: PASS (both ordering tests).

- [ ] **Step 6: Confirm no regression**

Run: `python3 -m pytest tests/orchestrator/test_state_advancement_invariant.py tests/orchestrator/test_runner_state_promotion.py -q`
Expected: PASS (those fixtures seed a bogus `last_sha` so ordering passes through; behavior unchanged).

- [ ] **Step 7: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_time_budget.py
git commit -m "feat(CCE-109): oldest-first PR ordering before admission

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Admission gate + truncation

Adds the deadline check at the top of the pr-summarizer loop. When the deadline has passed and ≥1 PR is already admitted, record a partial reason, truncate `prs`, and stop. Always admits ≥1 PR (the `i > 0` guard). This task does **not** change the advance SHA yet — a truncated run still advances to `HEAD` until Task 4; the tests here assert only truncation mechanics.

**Files:**

- Modify: `scripts/orchestrator_runner.py` (loop header + gate at `:1140`; init `time_truncated` before the loop)
- Test: `tests/orchestrator/test_time_budget.py`

- [ ] **Step 1: Write the failing tests (clock-injected, dry-run)**

Append to `tests/orchestrator/test_time_budget.py`:

```python
FAKES_MULTI = Path(__file__).parent / "fakes_multi"

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


def _init_host(tmp: Path, seeded_state: dict, config_yaml: str = CONFIG_YAML) -> Path:
    (tmp / "docs" / "site-src" / "core").mkdir(parents=True)
    (tmp / ".engineering-docs-agent").mkdir()
    (tmp / ".engineering-docs-agent" / "config.yml").write_text(config_yaml)
    state_path = tmp / ".engineering-docs-agent" / "state.json"
    state_path.write_text(json.dumps(seeded_state))
    _git(tmp, "init", "-q")
    _git(tmp, "config", "user.email", "t@example.com")
    _git(tmp, "config", "user.name", "T")
    (tmp / "README.md").write_text("init")
    _git(tmp, "add", ".")
    _git(tmp, "commit", "-q", "-m", "init")
    return state_path


def _current_run(state_path: Path) -> dict:
    return json.loads((state_path.parent / "current_run.json").read_text())["current_run"]


def _fake_clock(values):
    """Return a callable yielding the given monotonic values in order, then
    repeating the last value. First value is consumed by the deadline calc."""
    seq = list(values)
    state = {"i": 0}

    def clock() -> float:
        i = state["i"]
        state["i"] = min(i + 1, len(seq) - 1)
        return seq[i]

    return clock


def test_unlimited_budget_processes_all_prs(tmp_path):
    # Bogus last_sha → clip + ordering pass through; 3 PRs from fakes_multi.
    state_path = _init_host(tmp_path, {"version": "1",
                                       "last_successful_run": {"head_sha": "old_sha_000"}})
    rc = runner.run(tmp_path, dry_run_dir=FAKES_MULTI, no_pr=True,
                    time_budget_seconds=0)  # 0 = unlimited
    assert rc == 0
    cr = _current_run(state_path)
    assert cr["partial"] is False
    assert not any("time_budget_exceeded" in r for r in cr["partial_reasons"])


def test_truncates_after_budget_and_records_partial(tmp_path):
    state_path = _init_host(tmp_path, {"version": "1",
                                       "last_successful_run": {"head_sha": "old_sha_000"}})
    # deadline calc=0 → deadline=100; i=1 check=50 (admit PR2); i=2 check=150 (trip).
    clock = _fake_clock([0, 50, 150])
    rc = runner.run(tmp_path, dry_run_dir=FAKES_MULTI, no_pr=True,
                    time_budget_seconds=100, now_monotonic=clock)
    assert rc == 0
    cr = _current_run(state_path)
    assert cr["partial"] is True
    assert any("time_budget_exceeded: admitted 2/3" in r for r in cr["partial_reasons"]), cr["partial_reasons"]


def test_always_admits_at_least_one_pr(tmp_path):
    state_path = _init_host(tmp_path, {"version": "1",
                                       "last_successful_run": {"head_sha": "old_sha_000"}})
    # Already past deadline at first gate (i=1), but i=0 is never gated → admit 1.
    clock = _fake_clock([0, 9999])
    rc = runner.run(tmp_path, dry_run_dir=FAKES_MULTI, no_pr=True,
                    time_budget_seconds=1, now_monotonic=clock)
    assert rc == 0
    cr = _current_run(state_path)
    assert cr["partial"] is True
    assert any("time_budget_exceeded: admitted 1/3" in r for r in cr["partial_reasons"]), cr["partial_reasons"]
```

- [ ] **Step 2: Run to confirm failure**

Run: `python3 -m pytest tests/orchestrator/test_time_budget.py -k "unlimited or truncates or always_admits" -q`
Expected: FAIL — `test_truncates...` and `test_always_admits...` fail because no `time_budget_exceeded` reason is ever recorded (gate not implemented). `test_unlimited...` may already pass.

- [ ] **Step 3: Initialize the truncation flag before the loop**

In `scripts/orchestrator_runner.py`, immediately before the pr-summarizer loop at `:1140` (before `for pr in prs:`), add:

```python
        time_truncated = False
```

- [ ] **Step 4: Convert the loop and add the gate**

Change the loop header at `:1140` from:

```python
        for pr in prs:
```

to:

```python
        for i, pr in enumerate(prs):
            if deadline is not None and i > 0 and clock() > deadline:
                add_partial(
                    state,
                    f"time_budget_exceeded: admitted {i}/{len(prs)} PRs "
                    f"(budget {_budget}s); deferring PR #{pr.get('number')} "
                    f"to next run",
                )
                prs = prs[:i]
                time_truncated = True
                break
```

(The existing loop body — the `jira_context = ...` line onward — stays unchanged, now indented under the `for i, pr` loop.)

- [ ] **Step 5: Run to confirm pass**

Run: `python3 -m pytest tests/orchestrator/test_time_budget.py -k "unlimited or truncates or always_admits" -q`
Expected: PASS (all three).

- [ ] **Step 6: Confirm no regression**

Run: `python3 -m pytest tests/orchestrator/test_state_advancement_invariant.py tests/orchestrator/test_pipeline_integration.py -q`
Expected: PASS (single/small windows never trip the deadline; `deadline` is `None` when no budget arg → those tests use the default 2700 via config-less path... see note).

> Implementer note: existing subprocess-invoked tests call the CLI without
> `--time-budget-seconds`, so they resolve to the **default 2700s** with a real
> `time.monotonic` deadline. Their windows are tiny (0–1 PR) and complete in
> milliseconds, so the deadline never trips. No fixture changes needed.

- [ ] **Step 7: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_time_budget.py
git commit -m "feat(CCE-109): soft-deadline admission gate + PR-set truncation

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Advance-SHA selection (last fully-processed PR)

On a truncated run, advance the baseline to the newest admitted PR's `merge_sha` instead of `HEAD`. Adds `_last_processed_merge_sha` and branches the advance at `:1449`.

**Files:**

- Modify: `scripts/orchestrator_runner.py` (new helper; advance block at `:1449`)
- Test: `tests/orchestrator/test_time_budget.py`

- [ ] **Step 1: Write the failing tests (cursor + no-cursor + oldest-first discriminator)**

Append to `tests/orchestrator/test_time_budget.py`:

```python
def _write_fakes_with_prs(src: Path, dst: Path, prs: list[dict]) -> None:
    """Copy a fakes dir and overwrite its source-collector PRs."""
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        (dst / f.name).write_text(f.read_text())
    sc = json.loads((src / "fake_source_collector.json").read_text())
    sc["prs"] = prs
    (dst / "fake_source_collector.json").write_text(json.dumps(sc))


def test_truncated_run_advances_to_last_processed_pr(tmp_path):
    # Fake merge_shas + bogus last_sha → ordering passes through; cursor = PR2.merge_sha.
    state_path = _init_host(tmp_path, {"version": "1",
                                       "last_successful_run": {"head_sha": "old_sha_000"}})
    clock = _fake_clock([0, 50, 150])  # admit 2 of 3
    rc = runner.run(tmp_path, dry_run_dir=FAKES_MULTI, no_pr=True,
                    time_budget_seconds=100, now_monotonic=clock)
    assert rc == 0
    written = json.loads(state_path.read_text())
    # fakes_multi PRs are 1/2/3 with merge_sha a/b/c; admitted [1,2] → cursor 'b'.
    assert written["last_successful_run"]["head_sha"] == "b", written["last_successful_run"]


def test_oldest_first_cursor_is_oldest_commit(tmp_path):
    # Real window; PRs given newest-first; truncate after 1 → must advance to OLDEST.
    repo = tmp_path
    state_path = _init_host(repo, {"version": "1", "last_successful_run": {"head_sha": "x"}})
    # Add 3 real commits on top of the init commit.
    base = _git(repo, "rev-parse", "HEAD")
    shas = []
    for i in range(1, 4):
        (repo / "f.txt").write_text(f"c{i}")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    c1, c2, c3 = shas
    # Seed baseline to `base` so the window base..HEAD contains c1,c2,c3.
    state_path.write_text(json.dumps({"version": "1",
                                      "last_successful_run": {"head_sha": base}}))
    fakes = tmp_path.parent / "fakes_cce109_order"
    _write_fakes_with_prs(FAKES_MULTI, fakes, [
        {"number": 3, "merge_sha": c3},
        {"number": 2, "merge_sha": c2},
        {"number": 1, "merge_sha": c1},
    ])
    clock = _fake_clock([0, 9999])  # admit exactly 1 (the oldest after ordering)
    rc = runner.run(repo, dry_run_dir=fakes, no_pr=True,
                    time_budget_seconds=1, now_monotonic=clock)
    assert rc == 0
    written = json.loads(state_path.read_text())
    # Correct oldest-first ordering admits PR#1 → cursor c1 (oldest).
    # A broken passthrough would admit PR#3 → c3. Discriminating assertion:
    assert written["last_successful_run"]["head_sha"] == c1, written["last_successful_run"]


def test_truncation_with_no_usable_cursor_does_not_advance(tmp_path):
    state_path = _init_host(tmp_path, {"version": "1",
                                       "last_successful_run": {"head_sha": "old_sha_000"}})
    fakes = tmp_path.parent / "fakes_cce109_nocursor"
    _write_fakes_with_prs(FAKES_MULTI, fakes, [
        {"number": 1, "title": "x"},  # no merge_sha
        {"number": 2, "title": "y"},  # no merge_sha
        {"number": 3, "title": "z"},  # no merge_sha
    ])
    clock = _fake_clock([0, 50, 150])  # admit 2, both lack merge_sha
    rc = runner.run(tmp_path, dry_run_dir=fakes, no_pr=True,
                    time_budget_seconds=100, now_monotonic=clock)
    assert rc == 0
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == "old_sha_000"
    cr = _current_run(state_path)
    assert any("time_budget_no_advance_no_cursor" in r for r in cr["partial_reasons"]), cr["partial_reasons"]
```

- [ ] **Step 2: Run to confirm failure**

Run: `python3 -m pytest tests/orchestrator/test_time_budget.py -k "advances_to_last or oldest_first_cursor or no_usable_cursor" -q`
Expected: FAIL — truncated runs currently advance to `HEAD` (the real init/commit SHA), not to the PR `merge_sha`, so the asserted cursor values don't match.

- [ ] **Step 3: Implement `_last_processed_merge_sha`**

Add below `_order_prs_oldest_first` in `scripts/orchestrator_runner.py`:

```python
def _last_processed_merge_sha(admitted_prs: list[dict]) -> str | None:
    """Return the merge_sha of the newest admitted PR that has one.

    ``admitted_prs`` is the oldest-first truncated prefix, so the newest admitted
    PR is the last element. Scan from the end for the first non-empty merge_sha.
    Returns None when no admitted PR carries a merge_sha (cannot anchor the
    cursor → caller must not advance).
    """
    for pr in reversed(admitted_prs):
        sha = (pr.get("merge_sha") or "").strip()
        if sha:
            return sha
    return None
```

- [ ] **Step 4: Branch the advance block**

In `scripts/orchestrator_runner.py`, replace the advance dict at `:1449`:

```python
        state["last_successful_run"] = {
            "head_sha": state["current_run"]["head_sha"],
            "completed_at": now,
        }
```

with:

```python
        if time_truncated:
            advance_sha = _last_processed_merge_sha(prs)
            if advance_sha is None:
                add_partial(
                    state,
                    "time_budget_no_advance_no_cursor: truncated run had no "
                    "admitted PR with a merge_sha; baseline unchanged",
                )
                advance_sha = state.get("last_successful_run", {}).get("head_sha", "")
        else:
            advance_sha = state["current_run"]["head_sha"]
        state["last_successful_run"] = {
            "head_sha": advance_sha,
            "completed_at": now,
        }
```

(`prs` here is already the truncated prefix from Task 3. `prior_baseline_sha` at
`:1442` is captured before this block — leave it; the PR-body composer still
renders baseline → current correctly.)

- [ ] **Step 5: Run to confirm pass**

Run: `python3 -m pytest tests/orchestrator/test_time_budget.py -k "advances_to_last or oldest_first_cursor or no_usable_cursor" -q`
Expected: PASS (all three).

- [ ] **Step 6: Full new-suite + regression run**

Run: `python3 -m pytest tests/orchestrator/test_time_budget.py tests/orchestrator/test_state_advancement_invariant.py -q`
Expected: PASS (all 9 new tests + the 3 invariant tests unchanged).

- [ ] **Step 7: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_time_budget.py
git commit -m "feat(CCE-109): advance baseline to last fully-processed PR on truncation

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Full-suite verification + graceful-degradation guard

Confirms the whole change set integrates and adds the explicit git-missing degradation test (spec test 7) at the `run()` level.

**Files:**

- Test: `tests/orchestrator/test_time_budget.py`

- [ ] **Step 1: Write the degradation test**

Append to `tests/orchestrator/test_time_budget.py`:

```python
def test_ordering_degrades_when_window_uncomputable(tmp_path):
    # Bogus last_sha (rev-list fails) + budget set → run still completes cleanly,
    # processes PRs in given order, no crash. Admit all 3 (clock under deadline).
    state_path = _init_host(tmp_path, {"version": "1",
                                       "last_successful_run": {"head_sha": "bogus_000"}})
    clock = _fake_clock([0, 1, 2, 3])  # always under deadline=100
    rc = runner.run(tmp_path, dry_run_dir=FAKES_MULTI, no_pr=True,
                    time_budget_seconds=100, now_monotonic=clock)
    assert rc == 0
    cr = _current_run(state_path)
    assert cr["partial"] is False
    assert not any("time_budget_exceeded" in r for r in cr["partial_reasons"])
```

- [ ] **Step 2: Run the full new suite**

Run: `python3 -m pytest tests/orchestrator/test_time_budget.py -q`
Expected: PASS — 10 tests.

- [ ] **Step 3: Run the entire test suite**

Run: `python3 -m pytest -q`
Expected: PASS — prior count (967) + 10 new = 977 passed, 3 skipped (or current baseline + 10).

- [ ] **Step 4: Confirm the docs site is unaffected**

Run: `python3 -m mkdocs build --strict --quiet`
Expected: exit 0 (no docs-site files changed by this work).

- [ ] **Step 5: Commit**

```bash
git add tests/orchestrator/test_time_budget.py
git commit -m "test(CCE-109): graceful-degradation guard for uncomputable window

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**

- Component 1 (injectable monotonic clock) → Task 1 Steps 3,5. ✓
- Component 2 (oldest-first ordering, correctness) → Task 2. ✓
- Component 3 (admission gate + truncation propagation) → Task 3. ✓
- Component 4 (advance-SHA selection + no-cursor guard) → Task 4. ✓
- Component 5 (config `run.time_budget_seconds` + `--time-budget-seconds` CLI + DEFAULT) → Task 1 Steps 4,6,7. ✓
- Component 6 (observability via `add_partial` reason) → Task 3 Step 4 (reason text flows through existing plumbing). ✓
- Known limitation #1 (always admit ≥1) → Task 3 `i > 0` guard + `test_always_admits_at_least_one_pr`. ✓
- Spec test list 1–7 → `test_unlimited...`(1), `test_truncates...`+`test_truncated_run_advances...`(2), `test_always_admits...`(3), `test_oldest_first_cursor...`(4), `test_truncation_with_no_usable_cursor...`(5), `test_resolve_time_budget_precedence`(6), `test_ordering_degrades...`(7). ✓ All covered.
- CCE-62 advance-on-partial preserved → regression run of `test_state_advancement_invariant.py` in Tasks 1,2,3,4. ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows complete code. Acceptance-criteria checkboxes are spec checkboxes, not plan steps.

**3. Type/name consistency:** `resolve_time_budget(config, cli_override)`, `_order_prs_oldest_first(prs, *, last_sha, head_sha, repo_root)`, `_last_processed_merge_sha(admitted_prs)`, `DEFAULT_TIME_BUDGET_SECONDS`, locals `clock`/`_budget`/`deadline`/`time_truncated`/`advance_sha` are used identically across all tasks. Partial-reason strings `time_budget_exceeded: admitted k/N` and `time_budget_no_advance_no_cursor` match between implementation and test assertions. `now_monotonic` param name matches test kwargs. ✓

---

## Verification ladder (per CLAUDE.md SDD fidelity gate)

- **Tier 0 (always):** each task's commit touches only its declared files (`scripts/orchestrator_runner.py`, `templates/config.schema.json`, `tests/orchestrator/test_time_budget.py`); cross-check the committed diff against the file list.
- **Tier 1 (`verify_cmd`):** per task, run the named `pytest` selection; Task 5 runs full `pytest -q` + `mkdocs build --strict`.
- **Tier 2 (`red_green`):** every task asserts its test FAILS at its Step "Run to confirm failure" before implementation and PASSES after — the TDD discriminator.
