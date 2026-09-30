# Task 3 report — the auto-merge end-to-end test (CCE-169)

Status: DONE

Commit: (recorded after `git commit`, see bottom of this report)

## What changed and where

- `tests/orchestrator/test_window_cap.py`
  - Added the import, immediately after `import orchestrator_runner as orun  # noqa: E402`:

    ```python
    sys.path.insert(0, str(Path(__file__).parent))
    from test_cursor_backed_merge import _install_fake_gh  # noqa: E402
    ```

    The bare `from test_cursor_backed_merge import _install_fake_gh` (no path
    insert) was tried first, per the brief's primary form, and it raised
    `ModuleNotFoundError: No module named 'test_cursor_backed_merge'` on
    collection — `tests/orchestrator` was not yet on `sys.path` when this
    module was imported directly by its dotted test id (as opposed to being
    discovered by pytest's own collection walk). Used the brief's documented
    fallback, which resolved it.

  - Appended `test_a_capped_run_still_auto_merges`, transcribed verbatim from
    the brief's Step 1 code block, under a new
    `# auto-merge, end to end` section header at the end of the file. It
    consumes `_seed_capped_host` (Task 2, already in the file),
    `_install_fake_gh` (imported from `test_cursor_backed_merge.py`, not
    copied), and the `read_current_run` / `init_host` / `base_config_yaml`
    fixtures already defined in `tests/orchestrator/conftest.py`.
  - No other file touched. `scripts/orchestrator_runner.py` was edited
    temporarily for the falsifiability check in Step 2 and is back to being
    byte-identical to `HEAD` — see the revert evidence below.

## Step 2 — initial run (expected PASS, and it does)

```
cd /Users/theo/Projects/eda-cce181 && python3 -m pytest tests/orchestrator/test_window_cap.py::test_a_capped_run_still_auto_merges -v
```

(No `rtk proxy` prefix needed for the collection error above; needed once
output looked truncated on a later invocation — noted where it applies.)

Output:

```
collecting ... collected 1 item

tests/orchestrator/test_window_cap.py::test_a_capped_run_still_auto_merges PASSED [100%]

============================== 1 passed in 1.55s ===============================
```

This is expected and correct, not a false green: Task 2 already wired
`held_back` → CCE-151's cursor walk → `advance_cursor_backed=True` →
CCE-140's carve-out. This test is a regression guard on that mechanism, not
red/green for new production code.

## Falsifiability check (required — a test that cannot fail is not a test)

Temporarily changed `scripts/orchestrator_runner.py`:

```python
# before
_MERGE_VETO_REASON_PREFIXES: tuple[str, ...] = ("app_token_unavailable",)

# after (temporary)
_MERGE_VETO_REASON_PREFIXES: tuple[str, ...] = ("app_token_unavailable", "held_back_window_capped")
```

(A repo-configured formatter reflowed this onto three lines on save; the
semantic content — the added tuple entry — was exactly the one-line change
above. Confirmed via `git diff scripts/orchestrator_runner.py` before
reverting.)

Re-ran the identical command:

```
cd /Users/theo/Projects/eda-cce181 && python3 -m pytest tests/orchestrator/test_window_cap.py::test_a_capped_run_still_auto_merges -v
```

Result: **FAILED**, on the `pr_merge` assertion — the correct, targeted
failure point. Verbatim failure text:

```
        gh = _install_fake_gh(monkeypatch)
        rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=False)
        assert rc == 0
        cr = read_current_run(state_path)
        # Preconditions -- without these the merge assertion could pass for the
        # wrong reason (a run that is not partial at all reaches the merge path
        # under today's rules too).
        assert cr["partial"] is True, cr
        assert [
            r for r in cr["partial_reasons"] if r.startswith("held_back_window_capped:")
        ], cr["partial_reasons"]
        written = json.loads(state_path.read_text())
        assert written["last_successful_run"]["head_sha"] == c2, written[
            "last_successful_run"
        ]
        fake = gh["gh"]
>       assert [c for c in fake.calls if c[0] == "pr_merge"], (
            "a capped run is cursor-backed and must auto-merge; if it does not, the "
            "baseline never advances and the cap converts a compounding stall into "
            f"a permanent one. reasons={cr['partial_reasons']} calls={fake.calls}"
        )
E       AssertionError: a capped run is cursor-backed and must auto-merge; if it does not, the baseline never advances and the cap converts a compounding stall into a permanent one. reasons=['held_back_window_capped: 1 of 3 PRs held for a later run (cap 2)', 'auto_merge_skipped: merge_vetoed: held_back_window_capped'] calls=[('pr_list_for_branch', ('docs-agent/2026-09-23T22',)), ('pr_create', ('docs-agent/2026-09-23T22', 'docs(agent): run 2026-09-23T22:30:40.212423+00:00 (partial)', '**Review window:** baseline `ec7b24da` -> current `59a1afc7`\n\n**Files by lens:** core: 1, other: 10\n\n**Top 5 changed pages:**\n- `.engineering-docs-agent/config.yml`\n- `.engineering-docs-agent/current_run.json`\n- `.engineering-docs-agent/state.json`\n- `docs/site-src/core/connectors/multi.md`\n- `docs/site-src/whats-new.md`\n- _(+6 more)_\n\nWARNING -- Partial run\n\n- held_back_window_capped: 1 of 3 PRs held for a later run (cap 2)\n')), ('pr_list_docs_agent_open', ())]
E       assert []

tests/orchestrator/test_window_cap.py:343: AssertionError
----------------------------- Captured stderr call -----------------------------
docs-agent PARTIAL: held_back_window_capped: 1 of 3 PRs held for a later run (cap 2)
cursor: admitted=[1, 2] deferred=[none] capped=[3] held_back=[3] skipped=[none] baseline_age=unknown stall_window=4d
docs-agent INFO: auto_merge_skipped: merge_vetoed: held_back_window_capped
docs-agent: run exit summary (reasons=2):
docs-agent PARTIAL: held_back_window_capped: 1 of 3 PRs held for a later run (cap 2)
docs-agent PARTIAL: auto_merge_skipped: merge_vetoed: held_back_window_capped
=========================== short test summary info ============================
FAILED tests/orchestrator/test_window_cap.py::test_a_capped_run_still_auto_merges
============================== 1 failed in 1.45s ===============================
```

This is exactly the failure mode the test exists to catch: the preconditions
(`partial is True`, `held_back_window_capped:` reason present, advance
stopped at `c2`) all still pass — only the `pr_merge` assertion fails,
because `merge_veto_reason` now matches `held_back_window_capped` and
`_maybe_auto_merge` returns `skip("merge_vetoed", ...)` before the run ever
calls `gh pr merge`. The test is falsifiable.

## Revert and evidence it was complete

Reverted by hand (an interactive gate rejected `git checkout --
scripts/orchestrator_runner.py` as a "destructive command" requiring a
confirmation ritual it then re-rejected on retry; the brief explicitly
permits reverting "by hand" as the alternative, so the one-line tuple change
was undone directly with the same tool used to make it):

```python
# reverted back to:
_MERGE_VETO_REASON_PREFIXES: tuple[str, ...] = ("app_token_unavailable",)
```

Evidence the revert is complete and the file is byte-identical to `HEAD`:

```
cd /Users/theo/Projects/eda-cce181
git diff --stat scripts/orchestrator_runner.py   # prints nothing
git status --porcelain scripts/orchestrator_runner.py   # prints nothing
git diff scripts/orchestrator_runner.py   # prints nothing
```

All three commands produced empty output — confirmed directly, not inferred.

## Step 3 — full suite

```
cd /Users/theo/Projects/eda-cce181 && python3 -m pytest
```

Result:

```
================= 1639 passed, 4 skipped in 258.16s (0:04:18) ==================
```

Baseline (before this task): **1638 passed, 4 skipped**.
After this task: **1639 passed, 4 skipped** — exactly one new passing test
(`test_a_capped_run_still_auto_merges`), skip count unchanged (not rising, so
not a regression by the brief's own criterion).

## Step 4 — commit

```
cd /Users/theo/Projects/eda-cce181
git add tests/orchestrator/test_window_cap.py
git commit -m "test(orchestrator): a capped run must actually reach gh pr merge — CCE-169

The convergence argument depends on it: capped PRs enter held_back ->
CCE-151's walk runs -> advance_cursor_backed=True -> CCE-140's carve-out
permits the merge -> state.json reaches main -> the baseline advances. Break
the merge and the cap converts a compounding stall into a permanent one.

Asserts pr_merge in the fake gh call log, not the absence of
skip(\"partial_run\"). _maybe_auto_merge returns skip(\"merge_vetoed\") and
skip(\"blind_run\") ahead of skip(\"partial_run\"), so the weaker assertion passes
for a run vetoed by the wrong prefix list or misclassified blind -- neither of
which merges. Preconditions (partial, carries the reason, advance stops at the
cap boundary) are pinned beside it so the merge cannot pass for the wrong
reason either.

Verified falsifiable: adding held_back_window_capped to
_MERGE_VETO_REASON_PREFIXES makes it fail.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

Commit SHA and `git status` after the commit are recorded in the top-level
summary returned to the caller.

## Concerns / deviations from the brief

- The bare-import form in the brief's Step 1 (`from test_cursor_backed_merge
import _install_fake_gh`) did not work as written in this environment; the
  brief's own documented fallback (`sys.path.insert` then the same import)
  was used instead, and is what landed in the file.
- `git checkout -- scripts/orchestrator_runner.py` was blocked twice by an
  interactive "Fact-Forcing Gate" tool guard that did not accept a retry even
  after the requested facts were presented in the preceding turn. Reverted by
  hand instead (explicitly permitted by the brief), and verified
  byte-identical to `HEAD` via `git diff` / `git diff --stat` / `git status
--porcelain`, all empty.
- No production code was changed. `scripts/orchestrator_runner.py` carries
  zero net diff from before this task started.
