# Task 1 report — resolve_window_cap + run.window_pr_cap schema key (CCE-169)

Status: DONE

Commit: `97c84aee6f87b5646637177bba8abc7ad6572cad` (branch `feat/CCE-169-window-cap`)

## What changed and where

- `scripts/orchestrator_runner.py`
  - Added `DEFAULT_WINDOW_PR_CAP = 10` immediately after `DEFAULT_DEFERRAL_SKIP_THRESHOLD = 3` (was line 320; now line 320, followed by a blank-line-separated new constant at 322, matching the brief's neighbour formatting).
  - Added `resolve_window_cap(config: dict) -> int` immediately after `resolve_deferral_stall_days` (which still ends with `return int(val)`) and before `def resolve_authoring_hard_cap(`. Body transcribed verbatim from the brief: `_run_cfg(config)` → `run_cfg.get("window_pr_cap")` → `if val is None: return DEFAULT_WINDOW_PR_CAP` → `return int(val)`. No truthiness test, no `or DEFAULT`.
- `templates/config.schema.json`
  - Added the `window_pr_cap` property to `properties.run.properties`, immediately after `authoring_hard_cap_seconds` (added the required trailing comma to that entry's closing brace). `"type": "integer", "minimum": 0`, description transcribed verbatim from the brief.
- `tests/orchestrator/test_window_cap.py` (new file)
  - Created verbatim from the brief's code block: module docstring, imports (mirroring `tests/orchestrator/test_deferral_skip.py`), `FAKES_MULTI` constant, and the four tests (`test_window_cap_defaults_to_ten`, `test_window_cap_reads_the_config_key`, `test_window_cap_zero_is_unlimited`, `test_window_cap_tolerates_a_malformed_run_block`).
- `tests/schemas/test_config_schema.py`
  - Appended `test_run_window_pr_cap_accepted` and `test_run_window_pr_cap_rejects_negative` verbatim, after the existing last test (`test_deferral_skip_threshold_rejects_a_negative`). No new imports added — reused `SCHEMA`, `validate`, `ValidationError`, `pytest` already bound at module level.

## TDD steps, exact commands, and pass/fail counts

**Step 2 — resolver tests, red:**

```
cd /Users/theo/Projects/eda-cce181 && python3 -m pytest tests/orchestrator/test_window_cap.py -v
```

Result: 4 failed. Actual failure messages seen:

```
tests/orchestrator/test_window_cap.py::test_window_cap_defaults_to_ten FAILED
E       AttributeError: module 'orchestrator_runner' has no attribute 'DEFAULT_WINDOW_PR_CAP'

tests/orchestrator/test_window_cap.py::test_window_cap_reads_the_config_key FAILED
E       AttributeError: module 'orchestrator_runner' has no attribute 'resolve_window_cap'

tests/orchestrator/test_window_cap.py::test_window_cap_zero_is_unlimited FAILED
E       AttributeError: module 'orchestrator_runner' has no attribute 'resolve_window_cap'

tests/orchestrator/test_window_cap.py::test_window_cap_tolerates_a_malformed_run_block FAILED
E       AttributeError: module 'orchestrator_runner' has no attribute 'resolve_window_cap'
```

`4 failed in 0.18s` — matches the brief's prediction exactly. Output was not mangled; no `rtk proxy` prefix was needed at any point in this task.

**Step 5 — resolver tests, green (after adding the constant and resolver):**

```
cd /Users/theo/Projects/eda-cce181 && python3 -m pytest tests/orchestrator/test_window_cap.py -v
```

Result: `4 passed in 0.13s`.

**Step 7 — schema round-trip test, red:**

```
cd /Users/theo/Projects/eda-cce181 && python3 -m pytest tests/schemas/test_config_schema.py -k window_pr_cap -v
```

Result: `1 failed, 1 passed, 36 deselected in 0.12s`. Actual failure message:

```
E       jsonschema.exceptions.ValidationError: Additional properties are not allowed ('window_pr_cap' was unexpected)
```

(`error = <ValidationError: "Additional properties are not allowed ('window_pr_cap' was unexpected)">`) — matches the brief's prediction exactly. `test_run_window_pr_cap_rejects_negative` passed vacuously (no `window_pr_cap` key exists yet, so `validate` never even reaches the `minimum` check — it's rejected as an unknown property first, same negative-space result for the wrong reason), also as the brief predicted.

**Step 9 — both files, green (after adding the schema property):**

```
cd /Users/theo/Projects/eda-cce181 && python3 -m pytest tests/schemas/test_config_schema.py tests/orchestrator/test_window_cap.py -v
```

Result: `42 passed in 0.30s` — includes all pre-existing schema tests plus the 2 new schema tests plus the 4 new resolver tests.

**Extra verification beyond the brief — full repo suite (not in the brief's steps, run as a safety check before committing):**

```
cd /Users/theo/Projects/eda-cce181 && python3 -m pytest -q
```

Result: `1633 passed, 4 skipped in 258.13s (0:04:18)`, exit code 0. Confirms nothing else regressed.

## Anything in the brief that was wrong or ambiguous

Nothing wrong. Line numbers (`:320`, `resolve_deferral_stall_days` ending at `:466`, `authoring_hard_cap_seconds` ending at `:226`/`:227` after the prior day's edits) matched the actual file exactly, so every insertion point was found on the first grep with no adjustment needed. The `rtk` mangled-output warning did not trigger — plain `python3 -m pytest` output was clean throughout, so `rtk proxy` was never invoked. `git add` for exactly the four brief-listed files staged exactly those four and nothing else (`git status --porcelain` showed no stray untracked files before staging).

## Concerns

None concerning correctness of this task's deliverable. Two things worth flagging for the reviewer / for Task 2, not blocking:

1. The pre-existing repo commit author identity on this worktree is `Theo Jungeblut <theo@designitright.net>` (from local git config), distinct from the `userEmail` context (`theo.jungeblut@gmail.com`) — this is an existing worktree/repo config detail, not something this task touched or should touch.
2. As instructed, I did not touch `run.deferral_stall_days` (CCE-184) even though it is also missing from the schema and would be the same class of hazard — confirmed it is out of scope per the brief and left untouched.

No subagents were dispatched at any point in this task.
