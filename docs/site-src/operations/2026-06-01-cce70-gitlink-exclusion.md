---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/88
synthesized_into: []
---

# Gitlink Exclusion Fix (CCE-70)

**Date:** 2026-06-01
**Affects:** All hosts onboarded via CCE-57/CCE-58
**Fixed in:** PR #88

## What happened

The nightly docs-agent workflow checks out the plugin into `.docs-agent-plugin/` using `actions/checkout@v5 path: .docs-agent-plugin`. After authoring, the orchestrator staged changes with a bare `git add .`. That swept up the nested checkout and committed `.docs-agent-plugin/` as a submodule gitlink (mode `160000`) into the host's docs-agent PR.

ADIS PR #394 confirmed the pattern: the merged PR contained a gitlink pointing at the plugin's HEAD SHA at run time. The gitlink drifts on every nightly run as the plugin advances.

The dogfood repo (this repo) was not affected — it has no nested checkout pattern.

The root cause: `actions/checkout@v5` with a `path:` argument creates a fully initialized git repository at that path. A bare `git add .` from the parent repo treats it as an unregistered submodule and stages the HEAD pointer rather than the files.

## What changed (PR #88)

`scripts/orchestrator_runner.py` now calls `_stage_docs_run_changes(repo_root)` instead of issuing a bare `git add .` during the docs-agent PR staging step.

The helper passes git's exclude pathspec so the nested checkout is never staged:

```bash
git add -- . ':!.docs-agent-plugin' ':!.docs-agent-plugin/**'
```

The setup skill (`skills/engineering-docs-agent-setup/SKILL.md`) was updated to write `.docs-agent-plugin/` into new hosts' `.gitignore` as belt-and-suspenders coverage.

Two regression tests lock in both the exclusion and the preservation of legitimate staged paths.

## What you need to do

### New hosts

No action required. The setup skill now writes `.docs-agent-plugin/` into `.gitignore` automatically.

### Existing onboarded hosts

If your docs-agent PR branch already contains a `.docs-agent-plugin/` gitlink, remove it before the next nightly run:

```bash
git rm --cached .docs-agent-plugin
git commit -m "fix: remove accidental .docs-agent-plugin gitlink (CCE-70 follow-up)"
```

Then add `.docs-agent-plugin/` to your `.gitignore` if it is not already there:

```bash
echo '.docs-agent-plugin/' >> .gitignore
git add .gitignore
git commit -m "chore: ignore .docs-agent-plugin nested checkout"
```

The host-side cleanup for ADIS is a separate follow-up PR and is not part of this plugin change.

### Verify the fix is active

After upgrading the plugin, confirm the helper is in place:

```bash
grep -n "_stage_docs_run_changes" scripts/orchestrator_runner.py
```

You should see the function definition and its call site at the staging step. If the grep returns nothing, your plugin version predates PR #88.

## Jira references

- **CCE-67** — surfaced the pattern during host PR history review
- **CCE-70** — tracks the staging fix (this change)
