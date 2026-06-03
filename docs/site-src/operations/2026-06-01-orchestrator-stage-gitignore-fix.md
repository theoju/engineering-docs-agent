---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/97
synthesized_into: []
---

# Orchestrator Staging Fix: Adaptive `.gitignore` Detection (CCE-70 Regression)

**PR #97 · 2026-06-01 · P2 regression fix**

## Background

CCE-70 added a negative pathspec to prevent `.docs-agent-plugin/` internals from being staged during a docs-agent run. The staging call became:

```bash
git add -A -- ':!.docs-agent-plugin'
```

CCE-70 also recommended that host repos add `.docs-agent-plugin/` to their `.gitignore`. That recommendation turned out to break the staging step: when the directory is already gitignored, git rejects the negative pathspec with exit code 1 — `paths are ignored by one of your .gitignore files` — and the entire staging step fails.

## What changed

`_stage_docs_run_changes` in the orchestrator now detects at runtime whether `.docs-agent-plugin/` is covered by the host's `.gitignore` before choosing a strategy.

**When the directory is already gitignored** (the host followed CCE-70's recommendation), the function stages everything with `git add -A` and then un-stages the plugin directory:

```bash
git add -A
git restore --staged .docs-agent-plugin/
```

**When the directory is not gitignored**, the original CCE-70 negative-pathspec approach is used unchanged:

```bash
git add -A -- ':!.docs-agent-plugin'
```

Detection happens by running `git check-ignore -q .docs-agent-plugin/` and checking the exit code. No configuration change is required on your end.

## Impact

The fix is transparent. You do not need to change your `.gitignore`, your config, or your workflow. Both code paths produce the same outcome: the plugin directory is excluded from the docs-agent PR's staged changes.

If your host repo already has `.docs-agent-plugin/` in `.gitignore` and was hitting this failure, update the plugin to pick up the fix and the staging step will work correctly.

## Test coverage

`test_gitlink_exclusion.py` gained 147 lines covering both detection branches — gitignored and non-gitignored — plus the boundary conditions around `git check-ignore` exit codes. The production `_stage_docs_run_changes` path is exercised in the fixture-driven dry-run mode consistent with project conventions.
