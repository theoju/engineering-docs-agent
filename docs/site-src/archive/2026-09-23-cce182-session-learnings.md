---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/281
synthesized_into: []
doc_kind: decision
---

# CCE-182: three operational learnings from the CCE-181 session

PR #281 records three learnings from the CCE-181 SDD session in `CLAUDE.md`. Each is folded into the entry it extends. None adds a new section.

## Spend the pre-flight scan on the plan's references

A plan cannot get an invention wrong. It can only leave it unbuilt. Every mention of an existing function, fixture, signature, path or count is a claim that can already be false when it is written. Nothing re-checks those claims before an implementer acts on them.

CCE-181 measured this. Five plan defects surfaced, and all five were in task text that referenced an existing artifact:

- a function that did not exist (`load_config`, actually `load_config_validated`);
- a fixture missing schema-required keys;
- three tests that did not exercise what they claimed;
- a stale expected test count;
- a stale two-arg signature.

The two tasks that invented new files had zero defects.

Before dispatching Task 1, grep every symbol, path and signature the plan names against the tree. Treat a stated count, or "as established in Task N", as a reference too. This lives in the SDD verification-ladder entry.

## Remove the worktree before running the pruner

`scripts/prune_merged_branches.py` cannot see a branch that a live worktree still holds. `gh pr merge --delete-branch` deletes the remote branch. It skips the local delete when the branch is checked out in a worktree. It prints the two-step cleanup and exits 0.

If you run the pruner at that point, it reports `nothing to prune: 0 branches matched`. That reads as "already clean" while a `[gone]` ref exists. The order is:

1. `git worktree remove <path>`
2. `git branch -D <branch>`

Use `-D`, not `-d`. A squash-merged branch is not an ancestor of `main`. Observed after PR #279 (CCE-181). This lives in the CCE-90 branch-pruning entry.

## A green exit code does not prove a test ran

`pytest.importorskip` reports the test as skipped. A skipped test leaves the job green. The exit code therefore says nothing about the failure mode a test dependency exists to prevent.

The discriminating signal is the skip count against a baseline. On PR #279, CI showed `1614 passed, 10 skipped` against `main`'s `1554 passed, 10 skipped`. The unchanged 10 showed the new test ran. An `importorskip` would have made it 11. The install log showing `markdown-3.10.3` corroborated it.

When a check exists to prove something is present, assert on a count that would move if it were absent. This lives in the CCE-127 app-token entry, next to the `continue-on-error` rewrite of `conclusion`, which is the same class of wrong-field-is-green failure.

## Context

The learnings came out of the CCE-181 work. There, `page-author` cited cross-repo paths, `citation_exists` blocked the page, and the deferral skip silently abandoned the PR. CCE-182 is the remediation session that recorded them.
