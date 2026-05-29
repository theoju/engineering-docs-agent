# CCE-43 — Skip Already-Processed Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution (recommended for this scope) or superpowers:subagent-driven-development for fresh-subagent-per-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect same-hour reruns that would reprocess an already-completed window and exit 0 cleanly before dispatching subagents, eliminating the working-tree collision documented in CCE-42's smoke-test 2/2 failure.

**Architecture:** One new pure-function helper `_remote_already_processed_window(repo_root, branch, our_head_sha) -> bool` in `scripts/orchestrator_runner.py`, plus one call site in `_main()` between `head_sha`/`now`/`current_run` setup and the source-collector dispatch. The helper fetches `origin/<branch>` and inspects its committed `state.json` via `git show`; strict head_sha equality is the only signal that triggers skip.

**Tech Stack:** Python 3.11+ stdlib (`subprocess`, `json`); pytest with `unittest.mock` for fixture-driven unit tests; the existing TDD pattern in `tests/orchestrator/test_open_or_append_pr.py`.

---

## File Structure

| File                                           | Change              | Purpose                                                                                                       |
| ---------------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------- |
| `scripts/orchestrator_runner.py`               | Modify (+~25 lines) | Add `_remote_already_processed_window` helper; add call-site check in `_main()` between line 855 and line 857 |
| `tests/orchestrator/test_open_or_append_pr.py` | Modify (+~70 lines) | Extend existing file with 4 helper unit tests using the existing `MagicMock`/`patch.object` pattern           |
| `skills/engineering-docs-agent/SKILL.md`       | Modify (+~3 lines)  | Document skip semantic: new procedure step 2.5 + new state-transitions bullet                                 |

No new files. The spec is already at `docs/superpowers/specs/2026-05-28-docs-agent-skip-already-processed-window.md` (committed at `694a95e`).

## Task Dependency Order

```
Task 1 (failing test for skip-match)
    → Task 2 (implement helper to make Task 1 pass)
        → Task 3 (3 more helper tests covering fallthrough modes)
            → Task 4 (wire helper into _main() call site)
                → Task 5 (update SKILL.md)
                    → Task 6 (full pytest + ship readiness)
```

Strict sequence — each task depends on the prior one.

---

## Task 1: Failing test — `_remote_already_processed_window` returns True when remote head_sha matches

**Files:**

- Modify: `tests/orchestrator/test_open_or_append_pr.py:269` (append at end of file)

The existing file ends at line 269 with a closing brace. Append a new section starting with a comment block delimiter matching the file's style.

- [ ] **Step 1: Write the failing test**

Append to the end of `tests/orchestrator/test_open_or_append_pr.py`:

```python


# CCE-43: skip same-hour reruns that already processed this window. The
# orchestrator must detect that origin/<branch> already advanced its
# committed state.json to our HEAD and exit 0 before dispatching
# subagents, avoiding the working-tree collision documented in CCE-42's
# smoke-test 2/2 failure (run 26608024227).


def _skip_predicate_subprocess_stub(
    *,
    fetch_rc: int,
    show_rc: int = 0,
    remote_head_sha: str | None = None,
    show_stdout_override: str | None = None,
):
    """Stub git fetch + git show for _remote_already_processed_window tests.

    - fetch (`git fetch origin <branch>`): returns fetch_rc
    - show (`git show origin/<branch>:.engineering-docs-agent/state.json`):
      returns show_rc; if remote_head_sha is provided, stdout is a valid
      state.json with that head_sha; show_stdout_override forces raw stdout.
    """
    if show_stdout_override is not None:
        show_stdout = show_stdout_override
    elif remote_head_sha is not None:
        show_stdout = (
            '{"version": "1", "last_successful_run": '
            f'{{"head_sha": "{remote_head_sha}", "completed_at": "2026-05-28T23:00:00+00:00"}}}}'
        )
    else:
        show_stdout = ""

    def _run(argv, **kwargs):
        if "fetch" in argv:
            return MagicMock(returncode=fetch_rc, stdout="", stderr="")
        if "show" in argv:
            return MagicMock(returncode=show_rc, stdout=show_stdout, stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    return _run


def test_helper_returns_true_when_remote_head_sha_matches_ours(tmp_path: Path):
    """When origin/<branch>'s state.json has last_successful_run.head_sha
    equal to our_head_sha, the predicate returns True (this window is
    already processed; the runner should skip)."""
    our_head_sha = "abc123def456abc123def456abc123def456abcd"
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_skip_predicate_subprocess_stub(
            fetch_rc=0,
            show_rc=0,
            remote_head_sha=our_head_sha,
        ),
    ):
        result = orun._remote_already_processed_window(
            tmp_path, "docs-agent/2026-05-28T23", our_head_sha
        )
    assert result is True, (
        f"expected helper to return True when remote head_sha matches; got {result}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest tests/orchestrator/test_open_or_append_pr.py::test_helper_returns_true_when_remote_head_sha_matches_ours -v
```

Expected: FAIL with `AttributeError: module 'orchestrator_runner' has no attribute '_remote_already_processed_window'`

- [ ] **Step 3: Do NOT commit yet**

The test is failing as designed. We commit only when the test passes (after Task 2 implements the helper).

---

## Task 2: Implement `_remote_already_processed_window` helper

**Files:**

- Modify: `scripts/orchestrator_runner.py` (add helper function after the existing `branch_name` function at line 1371-1372)

- [ ] **Step 1: Add the helper function**

Locate `def branch_name(now_iso: str) -> str:` at `scripts/orchestrator_runner.py:1371`. Insert the new helper immediately AFTER `branch_name` and BEFORE `def open_or_append_pr(...)` (which starts at line 1375).

Add after line 1372:

```python


def _remote_already_processed_window(
    repo_root: Path, branch: str, our_head_sha: str
) -> bool:
    """True if origin/<branch>'s committed state.json shows it already
    advanced last_successful_run.head_sha to our_head_sha. In that case the
    docs-agent branch already holds the run we're about to redo, and
    proceeding would only collide on whats-new.md / state.json at checkout.

    Every failure mode (fetch failure, missing state.json, JSON parse error,
    schema drift) returns False so the runner proceeds normally — false
    positives would silently skip real work; false negatives just produce
    the existing checkout_failed partial reason.
    """
    fetch = subprocess.run(
        ["git", "-C", str(repo_root), "fetch", "origin", branch],
        capture_output=True,
        text=True,
    )
    if fetch.returncode != 0:
        return False
    show = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "show",
            f"origin/{branch}:.engineering-docs-agent/state.json",
        ],
        capture_output=True,
        text=True,
    )
    if show.returncode != 0:
        return False
    try:
        remote = json.loads(show.stdout)
        remote_head = remote.get("last_successful_run", {}).get("head_sha", "")
    except (json.JSONDecodeError, KeyError, AttributeError):
        return False
    return remote_head == our_head_sha
```

- [ ] **Step 2: Verify `json` import already exists**

Run:

```bash
grep -n "^import json" scripts/orchestrator_runner.py
```

Expected: returns at least one match (the module already imports `json` for other reasons). If no match, add `import json` to the imports block at the top of the file.

- [ ] **Step 3: Run the Task 1 test to verify it now passes**

Run:

```bash
python3 -m pytest tests/orchestrator/test_open_or_append_pr.py::test_helper_returns_true_when_remote_head_sha_matches_ours -v
```

Expected: PASS

- [ ] **Step 4: Run the full file's existing tests to verify no regression**

Run:

```bash
python3 -m pytest tests/orchestrator/test_open_or_append_pr.py -v
```

Expected: all tests pass (the existing 6 + the new 1 = 7 passes; no failures, no errors).

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_open_or_append_pr.py
git commit -m "$(cat <<'EOF'
feat(CCE-43): _remote_already_processed_window helper + skip-match test

The helper fetches origin/<branch> and reads its committed state.json
via `git show`; returns True only on strict head_sha equality with the
current HEAD. Every failure mode (fetch fail, missing state.json,
corrupted JSON, schema drift) returns False so the runner proceeds —
false positives would silently skip real work, which is the worst
outcome; false negatives just produce the existing checkout_failed
partial reason that operators already know how to resolve.

Test asserts the True path; fallthrough tests follow in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Add 3 fallthrough tests covering remaining failure modes

**Files:**

- Modify: `tests/orchestrator/test_open_or_append_pr.py` (append 3 more tests)

- [ ] **Step 1: Add `test_helper_returns_false_when_remote_head_sha_differs`**

Append after the test from Task 1:

```python


def test_helper_returns_false_when_remote_head_sha_differs(tmp_path: Path):
    """When origin/<branch>'s state.json has a DIFFERENT head_sha (S3
    retry-after-partial or S4 window-grew scenario), the predicate returns
    False so the runner proceeds and hits the existing checkout_failed
    handling if the collision occurs."""
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_skip_predicate_subprocess_stub(
            fetch_rc=0,
            show_rc=0,
            remote_head_sha="oldsha000000000000000000000000000000000",
        ),
    ):
        result = orun._remote_already_processed_window(
            tmp_path,
            "docs-agent/2026-05-28T23",
            "newsha111111111111111111111111111111111",
        )
    assert result is False, (
        f"expected False on differing remote head_sha; got {result}"
    )
```

- [ ] **Step 2: Add `test_helper_returns_false_when_remote_branch_absent`**

Append:

```python


def test_helper_returns_false_when_remote_branch_absent(tmp_path: Path):
    """When `git fetch origin <branch>` fails (rc != 0; branch doesn't
    exist remotely OR network failure), the predicate returns False so
    the runner proceeds normally — first-run-of-hour case."""
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_skip_predicate_subprocess_stub(fetch_rc=128),
    ):
        result = orun._remote_already_processed_window(
            tmp_path, "docs-agent/2026-05-28T23", "somehead00000000000000000000000000000000"
        )
    assert result is False, (
        f"expected False when fetch fails; got {result}"
    )
```

- [ ] **Step 3: Add `test_helper_returns_false_when_remote_state_json_corrupted`**

Append:

```python


def test_helper_returns_false_when_remote_state_json_corrupted(tmp_path: Path):
    """When origin/<branch>'s state.json exists but is not valid JSON
    (corrupted file, schema drift, partial write), the predicate returns
    False so the runner proceeds. Never false-skip on parse errors."""
    with patch.object(
        orun.subprocess,
        "run",
        side_effect=_skip_predicate_subprocess_stub(
            fetch_rc=0,
            show_rc=0,
            show_stdout_override="{not valid json at all",
        ),
    ):
        result = orun._remote_already_processed_window(
            tmp_path, "docs-agent/2026-05-28T23", "somehead00000000000000000000000000000000"
        )
    assert result is False, (
        f"expected False on corrupted JSON; got {result}"
    )
```

- [ ] **Step 4: Run all four helper tests**

Run:

```bash
python3 -m pytest tests/orchestrator/test_open_or_append_pr.py -k "_remote_already_processed_window or helper_returns" -v
```

Expected: 4 passes, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add tests/orchestrator/test_open_or_append_pr.py
git commit -m "$(cat <<'EOF'
test(CCE-43): fallthrough coverage for _remote_already_processed_window

Three tests for the three "return False" branches in the helper:
- remote head_sha differs from ours (S3/S4)
- remote branch absent (first run of the hour)
- remote state.json corrupted (parse error)

All three exercise the rule "never false-skip"; the helper always
defers to the existing checkout path when it can't confirm a match.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Wire helper into `_main()` call site

**Files:**

- Modify: `scripts/orchestrator_runner.py:855-857` (insert between `prior_run` block and `jira_payload` line)

Per the spec §Architecture > Call site: the insertion point is after `head_sha`, `now`, and `state["current_run"]` are all set, and before the first `dispatch_validated` call. Concretely: between line 855 (the end of the `prior_run` staleness check) and line 857 (`jira_payload = config.get(...)`).

- [ ] **Step 1: Insert the skip-check block**

Use Edit to insert between the existing line `        except ValueError:` / `            pass` (line 854-855) and `    jira_payload = config.get("sources", {}).get("jira")` (line 857).

The Edit:

```python
# old_string (anchor — match the empty line between blocks)
            except ValueError:
                pass

    jira_payload = config.get("sources", {}).get("jira")

# new_string
            except ValueError:
                pass

    # CCE-43: same-hour rerun guard. If origin/<docs-agent-branch>'s
    # committed state.json already advanced last_successful_run.head_sha
    # to our HEAD, the same window has already been processed. Proceeding
    # would mutate whats-new.md and state.json in the working tree with
    # content that differs from origin/<branch>, and the subsequent
    # checkout in open_or_append_pr would refuse (CCE-42 layer 3).
    if _remote_already_processed_window(repo_root, branch_name(now), head_sha):
        print(
            f"Skipped: origin/{branch_name(now)} already advanced "
            f"state.head_sha to {head_sha[:8]}; this window already "
            f"processed in this hour.",
            file=sys.stdout,
        )
        return 0

    jira_payload = config.get("sources", {}).get("jira")
```

- [ ] **Step 2: Verify `sys` is imported**

Run:

```bash
grep -n "^import sys" scripts/orchestrator_runner.py
```

Expected: returns at least one match. If empty, add `import sys` to the imports block.

- [ ] **Step 3: Run the full test suite for the orchestrator module**

Run:

```bash
python3 -m pytest tests/orchestrator/ -v
```

Expected: all tests pass (no regressions from the wiring).

- [ ] **Step 4: Local dry-run verification (smoke that the wiring doesn't crash)**

Run:

```bash
DOCS_AGENT_DEBUG_DIR=/tmp/cce43-local python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

Expected: runs to completion. Either the new skip block triggers (rare on local) or the normal flow runs and emits stub subagent output to `/tmp/cce43-local`. Crucially: no `NameError: name '_remote_already_processed_window' is not defined`, no syntax error, no unhandled exception in the new code path.

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py
git commit -m "$(cat <<'EOF'
feat(CCE-43): skip same-hour reruns in _main() before subagent dispatch

If origin/<docs-agent-branch> already advanced its committed
state.json head_sha to our HEAD, log a skip message and return 0
before any dispatch_validated call. Avoids wasted subagent work for
the smoke-test pair / cron+dispatch collision pattern that today
exits 1 with checkout_failed.

S3 (retry-after-partial) and S4 (window-grew) intentionally don't
hit the skip path — the helper returns False on a head_sha mismatch
— so they retain the existing checkout_failed partial reason. See
the spec's "Out of scope" section for the operator playbook.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Update `skills/engineering-docs-agent/SKILL.md`

**Files:**

- Modify: `skills/engineering-docs-agent/SKILL.md:39-45` (State transitions section)
- Modify: `skills/engineering-docs-agent/SKILL.md:51-64` (Procedure section)

- [ ] **Step 1: Add new bullet to State transitions section**

Use Edit to add a bullet at the end of the State transitions list (after the existing line that ends `"...self-healing."` at line 45).

```markdown
# old_string

- If PR open fails: persistent state still has the advanced `last_successful_run` written locally, but nothing reaches main. The next run reads the unchanged committed state and retries the same window — self-healing.

## Error handling

# new_string

- If PR open fails: persistent state still has the advanced `last_successful_run` written locally, but nothing reaches main. The next run reads the unchanged committed state and retries the same window — self-healing.
- CCE-43: if `origin/<docs-agent-branch>`'s committed `state.json` already advanced `last_successful_run.head_sha` to our `HEAD`, exit 0 without dispatching subagents. The window was already processed in this hour (e.g., smoke-test pair, cron + dispatch collision). No state advance, no PR mutation, no notifier digest.

## Error handling
```

- [ ] **Step 2: Insert new procedure step and renumber the rest**

Use Edit to insert a new numbered step between step 2 (`head_sha = ...`) and step 3 (`Compose inputs for source-collector`).

Use Edit to renumber the entire procedure list. The full edit:

```markdown
# old_string

2. `head_sha = $(git rev-parse HEAD)`.
3. Compose inputs for `source-collector`; dispatch. Parse JSON output.
4. For each PR in parallel (batch in groups of 5 to limit fan-out): dispatch `pr-summarizer`. Collect outputs.
5. Aggregate doc_targets per lens.
6. For each lens (parallel) and each target within the lens (serial): dispatch `page-author`. Collect outputs.
7. Dispatch `content-validator` on the union of authored/edited paths. For each block-failure, undo the page change via git and remove the path from the run's contribution; record the failure in `partial_reasons` and the digest.
8. For each PR (parallel): dispatch `gap-detector`, skipping those in `dismissed_gap_flags`. Collect verdicts.
9. Prepend a dated entry to `whats_new_file` summarizing the bullet list (PR summaries + gap flags).
10. Write `state.json` with `current_run.partial`, `current_run.partial_reasons`, and head_sha.
11. Open or append-commit to the docs-agent PR (see "PR handling" below).
12. Compose digest and dispatch `notifier`.

# new_string

2. `head_sha = $(git rev-parse HEAD)`.
3. CCE-43: check whether `origin/docs-agent/YYYY-MM-DDTHH`'s committed `state.json` already shows `last_successful_run.head_sha == head_sha`. If so, log a skip message and exit 0 — the window was processed by an earlier run this hour.
4. Compose inputs for `source-collector`; dispatch. Parse JSON output.
5. For each PR in parallel (batch in groups of 5 to limit fan-out): dispatch `pr-summarizer`. Collect outputs.
6. Aggregate doc_targets per lens.
7. For each lens (parallel) and each target within the lens (serial): dispatch `page-author`. Collect outputs.
8. Dispatch `content-validator` on the union of authored/edited paths. For each block-failure, undo the page change via git and remove the path from the run's contribution; record the failure in `partial_reasons` and the digest.
9. For each PR (parallel): dispatch `gap-detector`, skipping those in `dismissed_gap_flags`. Collect verdicts.
10. Prepend a dated entry to `whats_new_file` summarizing the bullet list (PR summaries + gap flags).
11. Write `state.json` with `current_run.partial`, `current_run.partial_reasons`, and head_sha.
12. Open or append-commit to the docs-agent PR (see "PR handling" below).
13. Compose digest and dispatch `notifier`.
```

This renumbers every step from 4 onward by +1 so the new CCE-43 step at position 3 doesn't cause duplicate numbering. The diff is larger than minimal but the rendered output reads cleanly.

- [ ] **Step 3: Run pytest to verify no test depends on the SKILL.md format**

Run:

```bash
python3 -m pytest tests/ -v -k "skill or SKILL" 2>&1 | tail -20
```

Expected: no test failures. Most likely zero tests match the filter; SKILL.md content isn't typically test-asserted.

- [ ] **Step 4: Commit**

```bash
git add skills/engineering-docs-agent/SKILL.md
git commit -m "$(cat <<'EOF'
docs(CCE-43): SKILL.md documents same-hour rerun skip semantic

New procedure step 2.5 (check origin/<branch>'s state.json before
subagent dispatch) and new state-transitions bullet describing the
exit-0 path. Aligns the skill's public contract with the runner's
new short-circuit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Full pytest suite + ship readiness

**Files:** none modified — verification only.

- [ ] **Step 1: Run the FULL test suite**

Run:

```bash
python3 -m pytest -v 2>&1 | tail -30
```

Expected: the final summary line reads something like `=== 572 passed, 3 skipped in 12.34s ===` (current main reports 568 passed; we're adding 4 new tests → 572). Zero failures. Zero errors. Skipped count unchanged from baseline.

If anything fails: STOP. Do not proceed to /ship. Diagnose using `/systematic-debugging`.

- [ ] **Step 2: Verify branch state**

Run:

```bash
git status && git log --oneline main..HEAD
```

Expected:

- `git status`: clean working tree, branch `fix/CCE-43-skip-already-processed`
- `git log`: should show 4 new commits beyond main (spec + 3 implementation commits + SKILL.md). The spec commit `694a95e` was committed first, then Tasks 2/3/4/5 each commit.

The exact commit list (ordered oldest → newest beyond main):

1. `docs(CCE-43): spec — skip same-hour reruns...` (already committed at `694a95e`)
2. `feat(CCE-43): _remote_already_processed_window helper + skip-match test` (Task 2)
3. `test(CCE-43): fallthrough coverage for _remote_already_processed_window` (Task 3)
4. `feat(CCE-43): skip same-hour reruns in _main() before subagent dispatch` (Task 4)
5. `docs(CCE-43): SKILL.md documents same-hour rerun skip semantic` (Task 5)

- [ ] **Step 3: Surface ship readiness to the user**

Print to chat:

> ✅ CCE-43 implementation complete and committed on `fix/CCE-43-skip-already-processed`. Pytest: 572 passed / 3 skipped / 0 failed. Ready for `/ship`.
>
> Want me to invoke `/ship` now?

DO NOT auto-invoke `/ship`. The user explicitly drives shipping per session policy. They'll respond with `yes` (or equivalent) before /ship runs.

---

## Out of scope (do not implement in this plan)

- **Integration test of `_main()` short-circuit.** Setting up `_main()` requires mocking config, state load, gh client, and every subagent — far heavier than the wiring justifies. The 4 helper unit tests + manual smoke-test cover the actual behavior.
- **Auto-recovery for S3 (retry-after-partial) and S4 (window-grew).** Per the spec, these intentionally keep today's `checkout_failed` behavior. Operator merges the open docs-agent PR and re-fires.
- **`--force-rerun` flag.** Not needed today; deleting the docs-agent branch achieves the same.
- **Notifier dispatch on skip.** No-op shouldn't generate digest spam.
- **Layer 4 (`GITHUB_TOKEN`-opened PRs don't trigger CI checks).** Surfaced today during PR #57 merge but orthogonal. Track separately.

## Post-merge actions (after `/ship` and merge)

The plan ends at "ready for /ship." The post-merge phase is the smoke-test from spec §Testing > Manual smoke-test:

1. Fire `gh workflow run docs-agent-nightly.yml --ref main`. Wait for completion.
2. Within the same hour, fire it again.
3. Confirm: second run's runner step exits 0 with log containing `"Skipped: origin/..."`.
4. Confirm: only one docs-agent PR exists for that hour.
5. Transition CCE-43 → Done on Jira (requires user authorization).
6. Re-check CCE-42's AC §4: with CCE-43 landed, smoke-test 2/2 should now succeed → transition CCE-42 → Done.

These are session-conversation actions, not plan tasks.
