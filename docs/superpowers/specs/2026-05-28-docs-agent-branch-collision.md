# CCE-42: docs-agent PR branch collision on same-hour reruns

**Ticket:** CCE-42
**Status:** Draft (awaiting user review)
**Related:** CCE-41 (SP-1 forensics, surfaced this), #321 (reframed)

## Problem

The nightly orchestrator opens a `docs-agent/YYYY-MM-DDTHH` branch and pushes its work. When two runs fire in the same hour — common during smoke-tests and during retry-after-failure — the second run's push is rejected with non-fast-forward because the local branch was created off `main`, ignoring the divergent remote state.

Concrete failure from workflow run [26606797927](https://github.com/theoju/engineering-docs-agent/actions/runs/26606797927):

- All 5 subagents (source-collector, pr-summarizer, page-author, content-validator, gap-detector) succeeded
- Local commit `c76f049` created on `docs-agent/2026-05-28T22` containing a real authored page
- `git push -u origin docs-agent/2026-05-28T22` rejected — remote tip `e22c623` from the 22:01 run (PR #54) has incompatible history
- Runner returned 1; PR not created or updated; authored content lost

## Goal

Same-hour reruns successfully append-commit to the existing remote branch and PR, matching the contract documented in `agents/engineering-docs-agent.md`:

> _"If a branch with that name exists AND has an open PR: `git checkout` it, add the new commits, `git push`. Append-commit, no force-push."_

## Architecture

One narrow change inside `open_or_append_pr` at `scripts/orchestrator_runner.py:1391`. No spec changes elsewhere; no schema changes; no subagent prompt changes.

The current flow:

```
checkout -B branch        # always from HEAD (main)
git add . && commit
push -u origin branch     # fails if remote exists with divergent SHA
```

New flow:

```
fetch origin branch       # silent; returncode 0 if remote exists, !=0 otherwise
if remote exists:
    checkout -B branch origin/branch    # local branch tracks remote tip
else:
    checkout -B branch                  # new branch off HEAD (existing behavior)
git add . && commit
push -u origin branch     # always fast-forward
```

The fetch result becomes the discriminator. No need for separate `ls-remote` (we already do that on failure for diagnostics; this pre-empts the failure entirely).

## Implementation

`scripts/orchestrator_runner.py:1391` (current 5 lines):

```python
checkout = subprocess.run(
    ["git", "-C", str(repo_root), "checkout", "-B", branch],
    capture_output=True,
    text=True,
)
```

Replaced by (~13 lines):

```python
fetch = subprocess.run(
    ["git", "-C", str(repo_root), "fetch", "origin", branch],
    capture_output=True,
    text=True,
)
if fetch.returncode == 0:
    checkout = subprocess.run(
        ["git", "-C", str(repo_root), "checkout", "-B", branch, f"origin/{branch}"],
        capture_output=True,
        text=True,
    )
else:
    checkout = subprocess.run(
        ["git", "-C", str(repo_root), "checkout", "-B", branch],
        capture_output=True,
        text=True,
    )
```

The existing `if checkout.returncode != 0:` error path stays untouched; either branch of the conditional binds the same `checkout` variable.

## Failure modes

| Mode                                                                                                | Behavior                                                                                         | Mitigation                                                 |
| --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------- |
| Remote branch exists, fast-forward works                                                            | Append-commit succeeds                                                                           | This is the fix                                            |
| Remote branch exists, push still rejected (rare race: another commit landed between fetch and push) | `push_refs_failed` partial reason                                                                | Existing handler at line 1418-1472 captures and records it |
| Remote branch doesn't exist (first run of the hour)                                                 | New branch from HEAD, push opens new PR                                                          | Same as today                                              |
| `git fetch` itself fails (network)                                                                  | Falls through to `else` branch — creates fresh branch                                            | Conservative; worst case is the old behavior               |
| Concurrent runs in the same workflow_dispatch hour                                                  | Workflow's `concurrency: docs-agent-nightly` with `cancel-in-progress: false` already serializes | No additional locking needed                               |

## Testing

**Unit test** in `tests/orchestrator/test_open_or_append_pr.py` (new file or extend existing):

- Set up a `tmp_path`-rooted bare git repo as "origin"
- Set up a `tmp_path`-rooted working repo with `origin` as remote
- Push an initial commit on `docs-agent/2026-05-28T22` to origin with a unique sentinel file
- Run `open_or_append_pr(working_repo, gh=stub, branch="docs-agent/2026-05-28T22", ...)`
- Assert: the new commit is on top of the existing remote SHA (verify by `git log --oneline origin/<branch>` post-push contains BOTH the sentinel commit AND the new docs commit)
- Assert: `pr_number` returned (via stubbed `gh.pr_list_for_branch` returning an existing PR)
- Assert: no `push_refs_failed` reason

The test uses a `subprocess`-driven git stub rather than mocking — the bug is in subprocess call shapes, so real git invocations are the only meaningful coverage.

**Manual smoke-test** post-merge:

1. Fire `gh workflow run docs-agent-nightly.yml --ref main`. Wait for completion.
2. Within the same hour, fire it again.
3. Confirm: second run's workflow ends with the runner step exit 0 (or a different partial reason — but NOT `push_refs_failed`).
4. Confirm: the docs-agent PR opened by the first run contains commits from both runs.

## Acceptance criteria

1. `scripts/orchestrator_runner.py:1391` updated with the fetch + conditional checkout pattern.
2. New unit test in `tests/orchestrator/` that fails on current main and passes after the fix.
3. Full pytest suite green (568 passed, 3 skipped — current main count).
4. Manual smoke-test: two same-hour `workflow_dispatch` fires, second one's runner step does not exit with `push_refs_failed`.
5. The docs-agent PR opened by the first fire contains commits from both runs.

## Out of scope

- **Reorganizing branch naming convention** (e.g. per-second precision). Rejected — adds complexity, doesn't address the append-commit contract violation.
- **Force-push handling**. The spec explicitly says _"Append-commit, no force-push."_ This fix honors that.
- **SP-2 / SP-3 / SP-4** from the #321 decomposition. CCE-41 forensics showed SP-2 and SP-3 are no longer needed (source-collector emits valid JSON in CI). SP-4 (integration test) is orthogonal to this fix.
- **`jira_auth_missing` partial signal**. Source-collector emits this when Atlassian credentials aren't configured in Actions. Separate concern.
- **Cleanup of stale PR #54** (the 22:01 run's PR). Best handled manually after this fix lands; the append-commit logic will work on whichever same-hour docs-agent branch exists.

## Risks

- **Race during the fetch-to-push window.** If another runner concurrently pushes a commit between this run's `fetch` and `push`, the push still fails with non-fast-forward. The workflow's `concurrency: docs-agent-nightly` group makes this nearly impossible in practice (cron + dispatch are serialized), but the existing `push_refs_failed` handler covers it cleanly if it ever happens.
- **Stale remote tracking refs.** `git fetch origin <branch>` updates `origin/<branch>` even if a previous run's local refs are stale. No special cleanup needed.

## Decomposition note

This is a single-file fix discovered by SP-1 (CCE-41) forensics. Scope is small enough that a separate plan document is optional; the implementation will follow TDD: failing test → fix → green test → /ship. Per-step execution lives in inline session conversation rather than a written plan.
