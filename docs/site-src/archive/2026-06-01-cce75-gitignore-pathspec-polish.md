---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/98
synthesized_into: []
---

# CCE-75 follow-up: gitignore pathspec polish (PR #98)

**Date:** 2026-06-01  
**Ticket:** CCE-75  
**PR:** [#98](https://github.com/theoju/engineering-docs-agent/pull/98)  
**Type:** Hardening — zero behavior change

## Context

PR #97 fixed CCE-75: `_stage_docs_run_changes` in `orchestrator_runner.py` crashed with `git` exit code 1 when a host repo gitignored `.docs-agent-plugin/`. The root cause was a negative pathspec (`:!.docs-agent-plugin`) that git promotes to "explicitly mentioned," which then triggers the gitignore safety check and aborts.

PR #97 replaced the negative pathspec with a two-branch detection strategy. PR #98 is a zero-behavior-change follow-up that closes three gaps flagged by an adversarial review of that fix.

## What PR #98 added

### Inline documentation

Three inline comments were added to `_stage_docs_run_changes` (`orchestrator_runner.py:1790`) to pin behavior that is correct but non-obvious:

**Mid-run modifications.** If an orchestrator bug modifies tracked content under `.docs-agent-plugin/` during the run, `git add -A .` stages those changes. The diff probe fires, the restore step reverts the index to HEAD, and the mutation is silently dropped from the docs PR. The PR still succeeds. The comment calls this out so future readers understand why the restore step exists and what it hides.

**Gitlink matching scope.** The diff probe (`git diff --cached --name-only -- .docs-agent-plugin`) matches any staged entry whose path starts with `.docs-agent-plugin` — the gitlink itself and any file at `.docs-agent-plugin/foo`. The comment makes the intentional prefix-match explicit.

**Symlink handling.** If your host has a symlink at `.docs-agent-plugin` rather than the real directory created by `actions/checkout@v5`, `git add -A .` recurses into the symlink target, and the diff probe and restore match the link path rather than the target's contents. The comment marks this as undefined behavior: the nightly workflow template never creates a symlink here, but a host that does must handle it separately.

### Regression test suite

`tests/orchestrator/test_gitlink_exclusion.py` (176 lines) covers all six scenarios for `_stage_docs_run_changes`:

- Gitignored plugin directory: `git add` skips it, restore step is skipped.
- Non-gitignored plugin directory staged as a gitlink: diff probe fires, restore reverts the index.
- Mid-run modification to tracked plugin content: staged by `git add`, then reverted by restore.
- `git add` failure: function returns nonzero immediately.
- `git diff` failure: function returns nonzero immediately.
- `git restore` failure: function returns nonzero immediately.

### Plan document

A structured plan capturing the adversarial-review findings was added to `docs/superpowers/plans/`. It records the three documented edge cases, why each is acceptable (or undefined), and what the regression suite covers.

## Design rationale: two-branch detection vs. simpler fallback

The alternative considered for CCE-75 was a simple try/except or a `--ignore-errors` flag on the `git add` call. Both were rejected for the same reason: they suppress genuine errors alongside the gitignore-triggered exit.

The two-branch detection strategy works instead:

1. Run `git add -A .` with no pathspec exclusion. Gitignored paths are skipped silently; non-gitignored paths (including `.docs-agent-plugin/` staged as a gitlink) are staged normally.
2. Probe with `git diff --cached --name-only -- .docs-agent-plugin`. If the probe returns output, `.docs-agent-plugin/` was staged and must be reverted.
3. Run `git restore --staged -- .docs-agent-plugin` to revert only that entry. `git restore` rather than `git rm --cached` preserves any pre-existing tracked content at that path (e.g., a committed submodule registration).

This strategy has no false positives (a gitignored plugin directory produces zero probe output), no false negatives (a staged gitlink always produces probe output), and fails loudly on any git subprocess error rather than swallowing it.

The inline comments added by PR #98 are the permanent record of this reasoning. Future refactors should read `_stage_docs_run_changes` (`orchestrator_runner.py:1790`) and the test file (`tests/orchestrator/test_gitlink_exclusion.py`) together before touching the staging logic.
