# CCE-43: skip same-hour reruns that already processed this window

**Ticket:** CCE-43
**Status:** Draft (awaiting user review)
**Related:** CCE-41 (forensics infrastructure, surfaced this), CCE-42 (branch-collision fix, exposed this as the next layer), #321 (umbrella)

## Problem

The orchestrator advances `last_successful_run.head_sha` on every run that gets past subagent dispatch (`scripts/orchestrator_runner.py:1199-1204`). It also mutates the working tree at two earlier points: `whats-new.md` is prepended (line 1192) and authored pages are written by `page-author` during dispatch. All of this happens _before_ `open_or_append_pr` calls `git checkout -B <branch> origin/<branch>` (line 1404-1406, post-CCE-42).

When two runs fire in the same hour against the same docs-agent branch, the second run's working tree carries modifications to `whats-new.md` and `state.json` that conflict with the content already on `origin/docs-agent/YYYY-MM-DDTHH`. Git's `checkout` refuses to overlay tracked-file modifications onto a divergent target ref. The runner exits 1; no commit, no append, no useful output.

Concrete failure from workflow run [26608024227](https://github.com/theoju/engineering-docs-agent/actions/runs/26608024227) (the post-CCE-42-merge smoke-test 2/2):

- All 5 subagents (source-collector, pr-summarizer, page-author, content-validator, gap-detector) succeeded
- Runner reached `open_or_append_pr`
- `git fetch origin docs-agent/2026-05-28T23` returned rc=0 (branch exists from run 1/2's PR #57)
- `git checkout -B docs-agent/2026-05-28T23 origin/docs-agent/2026-05-28T23` refused: working tree had divergent `whats-new.md` and `state.json`
- Runner returned 1; subagent work wasted

This is **layer 3** of the #321 onion — layer 1 was OAuth token expiry (manual rotation), layer 2 was branch SHA collision (CCE-42), and this is the working-tree file collision that remains after CCE-42's fetch-then-checkout takes effect.

## Goal

Same-hour reruns of an already-processed window detect the duplication **before** dispatching subagents, log a clear skip message, and exit 0. Wasted subagent calls and runner exit 1 disappear for the most common case (smoke-test pair, cron+dispatch collision).

Out of scope: retry-after-partial (S3) and window-grew-between-runs (S4) — those keep today's behavior (collision causes `checkout_failed` partial reason; operator merges the open docs-agent PR and re-fires).

## Architecture

One new helper plus one call-site change. Both in `scripts/orchestrator_runner.py`.

### New helper: `_remote_already_processed_window`

```python
def _remote_already_processed_window(
    repo_root: Path, branch: str, our_head_sha: str
) -> bool:
    """True if origin/<branch>'s committed state.json shows it already
    advanced last_successful_run.head_sha to our_head_sha. In that case the
    docs-agent branch already holds the run we're about to redo, and
    proceeding would only collide on whats-new.md / state.json at checkout."""
    fetch = subprocess.run(
        ["git", "-C", str(repo_root), "fetch", "origin", branch],
        capture_output=True, text=True,
    )
    if fetch.returncode != 0:
        return False  # remote branch absent OR network failure — proceed
    show = subprocess.run(
        ["git", "-C", str(repo_root), "show",
         f"origin/{branch}:.engineering-docs-agent/state.json"],
        capture_output=True, text=True,
    )
    if show.returncode != 0:
        return False  # remote branch lacks state.json (pre-CCE-40 era) — proceed
    try:
        remote = json.loads(show.stdout)
        remote_head = remote.get("last_successful_run", {}).get("head_sha", "")
    except (json.JSONDecodeError, KeyError, AttributeError):
        return False  # corrupted/unknown shape — proceed (never false-skip)
    return remote_head == our_head_sha
```

### Call site

In `_main()`, after `head_sha = subprocess.run(["git", "rev-parse", "HEAD"], ...)` is computed and `branch = branch_name(now)` is set, but **before** the first `dispatch_validated` call (source-collector dispatch around line 870). On `True`, print a clear log line and return 0 without dispatching anything or writing state.

```python
if _remote_already_processed_window(repo_root, branch, head_sha):
    print(
        f"Skipped: origin/{branch} already advanced state.head_sha to "
        f"{head_sha[:8]}; this window already processed in this hour.",
        file=sys.stdout,
    )
    return 0
```

`GhClient` is instantiated only at line 1209 — after subagent dispatch and state writes — so the skip path cannot reference it. The skip message intentionally omits the PR number; the operator can look it up via `gh pr list --head <branch>` if needed. Keeping the skip path independent of the `gh` client also avoids an extra network call on every run start.

### Predicate choice: strict equality

The predicate uses `remote_head == our_head_sha`, not `>=` or `git merge-base --is-ancestor`. Rationale: SHAs aren't ordered. Without a `merge-base` call, we cannot know whether a different head_sha means ahead, behind, or divergent. Equality is the only safe "yes, same work" signal — false positives (skipping work that should run) are bad; false negatives (running work that could have been skipped) just produce the existing `checkout_failed` partial reason that operators already know how to resolve.

## Failure modes

| Mode                                                                         | Predicate returns | Behavior                                                                                                                  |
| ---------------------------------------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Remote branch absent (first run of hour)                                     | `False`           | Proceed; first run of hour creates branch                                                                                 |
| Remote branch exists, no `state.json` (pre-CCE-40 carryover branch)          | `False`           | Proceed; legacy branches don't carry state                                                                                |
| Remote `state.json` is corrupted or has unknown schema                       | `False`           | Proceed; never false-skip                                                                                                 |
| Remote `head_sha` equals our HEAD                                            | `True`            | Skip with log message, exit 0                                                                                             |
| Remote `head_sha` differs from our HEAD (S3 retry-partial or S4 window-grew) | `False`           | Proceed; existing `checkout_failed` handling applies if collision occurs                                                  |
| Network failure on fetch (DNS, timeout, etc.)                                | `False`           | Proceed; pessimistic default — let the real run try and fail loudly rather than silently skipping when we couldn't verify |
| Concurrent runs in the same workflow_dispatch hour                           | N/A               | Workflow's `concurrency: docs-agent-nightly` with `cancel-in-progress: false` already serializes runs                     |

## Testing

Four unit tests in `tests/orchestrator/` (new file `test_skip_already_processed.py` or extending `test_open_or_append_pr.py`):

1. `test_skips_when_remote_state_head_sha_matches_ours`: monkeypatch `subprocess.run` so `git fetch` returns rc=0 and `git show origin/<branch>:.engineering-docs-agent/state.json` returns a valid JSON document with `last_successful_run.head_sha == our_head_sha`. Also monkeypatch `dispatch_validated` to track call count. Run `_main()`. Assert: return code == 0, call count == 0, log contains "Skipped".
2. `test_proceeds_when_remote_state_head_sha_differs`: same stubbing but with a different remote head_sha. Assert: `dispatch_validated` is called.
3. `test_proceeds_when_remote_branch_absent`: `git fetch` returns rc=128. Assert: `dispatch_validated` is called.
4. `test_proceeds_when_remote_state_json_corrupted`: `git show` returns invalid JSON. Assert: `dispatch_validated` is called.

All four use the existing TDD pattern from `test_open_or_append_pr.py` (`MagicMock` + `patch.object(orun.subprocess, "run", ...)`).

**Manual smoke-test post-merge:**

1. Confirm `state.json` on `main` reflects the latest merged docs-agent PR
2. Fire `gh workflow run docs-agent-nightly.yml --ref main`. Wait for completion (should open a new docs-agent PR or extend an existing same-hour one)
3. Within the same hour, fire it again
4. Confirm: second run's workflow ends with the runner step **exit 0**, and the run log contains the `"Skipped: origin/..."` line
5. Confirm: only one docs-agent PR exists for that hour (the first run's); no duplicate authored content, no `checkout_failed` partial reason

## Acceptance criteria

1. `scripts/orchestrator_runner.py` gains `_remote_already_processed_window` helper matching the body in §Architecture.
2. `_main()` calls the helper after `head_sha`/`branch` are set and before the first `dispatch_validated`, returning 0 on `True` with the prescribed log line.
3. Four unit tests from §Testing exist and pass; the skip-case test fails on the pre-fix codebase and passes after.
4. Full pytest suite green.
5. `skills/engineering-docs-agent/SKILL.md` updated to document the new skip semantic in the procedure section (between "Read state" and "Dispatch source-collector"). The state-transitions section gets a new bullet: "If `origin/<branch>` already advanced its `last_successful_run.head_sha` to our `HEAD`, exit 0 without dispatching subagents."
6. Manual smoke-test: two same-hour `workflow_dispatch` fires. Second run's runner step exits 0 and logs `"Skipped: origin/..."`.
7. Only one docs-agent PR exists for the hour; no duplicate authored content.

## Out of scope

- **Auto-recovery for S3 (retry-after-partial) and S4 (window-grew)**. Today's behavior (checkout collision → `checkout_failed` partial reason → operator merges PR and re-fires) is preserved. A future ticket can add stash/pop (Option A in brainstorming) or restructure write-after-checkout (Option C) if these scenarios become common.
- **A `--force-rerun` flag** to bypass the skip predicate. Not needed today; deleting the docs-agent branch and re-firing achieves the same.
- **Notifier dispatch on skip**. A no-op shouldn't generate digest spam.
- **Layer 4 (`GITHUB_TOKEN`-opened PRs don't trigger CI checks)**. Surfaced today during PR #57 merge but orthogonal to working-tree handling. Track separately.

## Risks

- **Stale `origin/<branch>` reference**. If `git fetch` succeeds but the local refs are stale (impossible in practice — fetch updates the ref), the predicate could read old content. Mitigated by always invoking `fetch` immediately before `show`.
- **`state.json` schema drift**. If a future change renames `last_successful_run.head_sha` without migrating, the predicate silently returns `False` (proceed). The runner then collides at checkout as today. Caught by the existing test suite's schema invariants (CCE-40 validates load shape) and the `checkout_failed` log line.
- **Race with PR merge**. If the open same-hour PR merges to main between the runner reading state and computing window, the window shrinks to empty (the existing CCE-40 short-circuit returns early). The new predicate adds no new race.

## Decomposition note

Single-file change (one helper + one call site) with four small unit tests. Per CCE-42's precedent, no separate plan document is needed; implementation follows TDD: failing test → fix → green test → /ship. Per-step execution lives in inline session conversation rather than a written plan.
