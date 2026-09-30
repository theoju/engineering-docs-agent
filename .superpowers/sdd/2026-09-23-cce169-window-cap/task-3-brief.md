## Task 3: The auto-merge end-to-end test

Closes spec test-plan item **6**. Separate from Task 2 because it needs the fake-`gh` harness and asserts a different property: that the cap does not accidentally make a run ineligible to merge. A reviewer could reasonably approve Task 2 and reject this.

**Files:**

- Modify: `tests/orchestrator/test_window_cap.py`

**Interfaces:**

- Consumes: `_seed_capped_host` from Task 2, and `_install_fake_gh` from `tests/orchestrator/test_cursor_backed_merge.py` (import it, do not copy).

### Why "did not return `partial_run`" is not enough

`_maybe_auto_merge` returns `skip("merge_vetoed", veto)` and then `skip("blind_run")` **before** it ever reaches `skip("partial_run")` (`scripts/orchestrator_runner.py:4426-4436`). So "did not return `partial_run`" is equally true of a run vetoed by a `held_back_window_capped` entry mistakenly added to `_MERGE_VETO_REASON_PREFIXES`, and of one misclassified `blind`. Neither merges, and both leave the cap inert. `pr_merge` in the fake call log is the assertion.

- [ ] **Step 1: Write the test**

Append to `tests/orchestrator/test_window_cap.py`. Add the import beside the existing ones at the top of the file. `tests/orchestrator/` is on `sys.path` under pytest's prepend import mode because `tests/` has no `__init__.py`; if the bare import fails, add the explicit path insert shown second.

```python
from test_cursor_backed_merge import _install_fake_gh  # noqa: E402
```

Fallback if that raises `ModuleNotFoundError`:

```python
sys.path.insert(0, str(Path(__file__).parent))
from test_cursor_backed_merge import _install_fake_gh  # noqa: E402
```

Do **not** copy the helper into this file — duplicating it means a future change to the fake `gh` client silently stops applying here.

```python
def test_a_capped_run_still_auto_merges(
    tmp_path, monkeypatch, init_host, base_config_yaml, read_current_run
):
    """If a capped run cannot merge, the cap accomplishes nothing.

    The whole convergence argument is: capped PRs enter `held_back` -> CCE-151's
    walk runs -> `advance_cursor_backed=True` -> CCE-140's carve-out
    (`if partial and not advance_cursor_backed`) permits the auto-merge ->
    state.json is promoted to the default branch -> the baseline advances -> the
    next run takes the next `cap` PRs. Break the merge and the baseline never
    moves, so the cap turns a compounding stall into a permanent one.

    `pr_merge` in the call log is the assertion. Nothing weaker distinguishes
    "the gate opened" from "the gate opened and something downstream closed it":
    _maybe_auto_merge returns skip("merge_vetoed") and skip("blind_run") BEFORE
    skip("partial_run"), so asserting the absence of the last one passes for a
    run vetoed by the wrong list or misclassified blind.
    """
    state_path, base, (c1, c2, c3), fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=2
    )
    # Safe to APPEND: unlike `run:`, the shared CONFIG_YAML has no `merge:`
    # block, so there is no duplicate key for PyYAML to silently drop. Same
    # append test_cursor_backed_merge._seed_merge_host performs.
    config_path = tmp_path / ".engineering-docs-agent" / "config.yml"
    config_path.write_text(
        config_path.read_text()
        + "\nmerge:\n  policy: auto\n  checks_grace_seconds: 0\n"
        + "  checks_timeout_seconds: 0\n"
    )
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
    assert [c for c in fake.calls if c[0] == "pr_merge"], (
        "a capped run is cursor-backed and must auto-merge; if it does not, the "
        "baseline never advances and the cap converts a compounding stall into "
        f"a permanent one. reasons={cr['partial_reasons']} calls={fake.calls}"
    )
```

- [ ] **Step 2: Run it, then prove it is falsifiable**

```bash
cd ~/Projects/eda-cce181 && python3 -m pytest tests/orchestrator/test_window_cap.py::test_a_capped_run_still_auto_merges -v
```

Expected: **PASS**, because Task 2 already wired the mechanism. That is correct — this test is a regression guard on Task 2's work, not red/green for new code. **A test that cannot be made to fail is not a test**, so prove it: temporarily change `scripts/orchestrator_runner.py:4343` to

```python
_MERGE_VETO_REASON_PREFIXES: tuple[str, ...] = ("app_token_unavailable", "held_back_window_capped")
```

re-run, and confirm it FAILS on the `pr_merge` assertion. Then revert:

```bash
cd ~/Projects/eda-cce181 && git checkout -- scripts/orchestrator_runner.py
```

`git checkout --` is safe here only because Task 2 is already committed. If you have uncommitted work in that file, undo the edit by hand instead.

- [ ] **Step 3: Confirm the revert and run the full suite**

```bash
cd ~/Projects/eda-cce181
git diff --stat scripts/orchestrator_runner.py   # expect: no output
python3 -m pytest
```

Expected: `git diff --stat` prints nothing, and the suite is green.

- [ ] **Step 4: Commit**

```bash
cd ~/Projects/eda-cce181
git add tests/orchestrator/test_window_cap.py
git commit -m "$(cat <<'EOF'
test(orchestrator): a capped run must actually reach gh pr merge — CCE-169

The convergence argument depends on it: capped PRs enter held_back ->
CCE-151's walk runs -> advance_cursor_backed=True -> CCE-140's carve-out
permits the merge -> state.json reaches main -> the baseline advances. Break
the merge and the cap converts a compounding stall into a permanent one.

Asserts pr_merge in the fake gh call log, not the absence of
skip("partial_run"). _maybe_auto_merge returns skip("merge_vetoed") and
skip("blind_run") ahead of skip("partial_run"), so the weaker assertion passes
for a run vetoed by the wrong prefix list or misclassified blind -- neither of
which merges. Preconditions (partial, carries the reason, advance stops at the
cap boundary) are pinned beside it so the merge cannot pass for the wrong
reason either.

Verified falsifiable: adding held_back_window_capped to
_MERGE_VETO_REASON_PREFIXES makes it fail.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

