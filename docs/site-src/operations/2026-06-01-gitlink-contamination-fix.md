---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/88
synthesized_into: []
---

# Gitlink Contamination Fix (PR #88)

**Date:** 2026-06-01  
**Tracks:** CCE-70 (clean-nightly blocker)  
**Breaking:** No

## Problem

Every onboarded host was silently producing nightly PRs that included `.docs-agent-plugin` as a gitlink entry — an unintended submodule reference embedded in the diff. The runner's staging logic used `git add .` from the host repo root, which has no awareness of nested Git repositories. Git treats a nested `.git` directory as a submodule boundary and records it as a gitlink object rather than skipping it.

This affected all hosts onboarded via CCE-57 and CCE-58. The contamination was discovered as a side-effect of the CCE-67 content-validator path investigation.

## Root Cause

`git add .` with no pathspec restrictions will stage a nested Git repository as a gitlink. The plugin checkout lives at `.docs-agent-plugin/` inside the host repo root, which contains its own `.git` directory. When the nightly runner invoked `git add .`, Git recorded `.docs-agent-plugin` as a submodule entry in the index, and that entry propagated into every generated PR as noise.

## Fix

PR #88 extracted a dedicated helper, `_stage_docs_run_changes(repo_root)`, in the orchestrator runner. The helper passes an explicit pathspec exclude to `git add`:

```bash
git add -- . ':!.docs-agent-plugin/'
```

The `:!` prefix is Git's pathspec exclude syntax. It tells Git to add everything under the current directory _except_ the named path. The exclude applies before any gitlink detection, so `.docs-agent-plugin/` is never staged regardless of whether a `.gitignore` entry exists.

The runner now calls `_stage_docs_run_changes` in place of the bare `git add .` at every point in the nightly pipeline where docs changes are staged.

## Host Onboarding Checklist Update

The setup skill was updated to instruct hosts to add `.docs-agent-plugin/` to their `.gitignore`. This is a defense-in-depth measure: the pathspec exclude in `_stage_docs_run_changes` is the primary guard, but a `.gitignore` entry prevents the directory from appearing in `git status` output and avoids confusion when engineers inspect the repo manually.

Add this line to the host repo's `.gitignore`:

```
.docs-agent-plugin/
```

If you onboarded before 2026-06-01, verify the entry is present. Run `git status` at the repo root after a dry-run invocation and confirm `.docs-agent-plugin` does not appear in the output.

## Test Coverage

PR #88 added a test suite covering the gitlink exclusion path. Tests verify that `_stage_docs_run_changes` does not stage a nested `.git` directory when one is present under the repo root. All tests use the fixture-driven dry-run path; the Git operations are exercised against a temporary repo constructed in the fixture.
