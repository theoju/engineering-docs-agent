---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/97
synthesized_into: []
---

# Orchestrator Git Staging

The orchestrator's `_stage_docs_run_changes` function is responsible for staging the docs changes it authors before opening or updating a PR. This page explains the three-step staging sequence it uses and why the simpler pathspec-exclusion approach cannot work on all host repos.

## The problem: negative pathspecs collide with `.gitignore`

The orchestrator checks out `.docs-agent-plugin/` into the host repo's working tree during a run. That directory must never appear as a staged change — it would pollute the docs PR with an unrelated gitlink or binary blob.

An earlier implementation excluded it with a negative pathspec:

```bash
git add -A -- ':!.docs-agent-plugin'
```

This fails on any host that gitignores `.docs-agent-plugin/`. Git's pathspec layer treats any explicitly named path as "explicitly mentioned," which triggers its gitignore-aware safety check even for negative patterns. The result is `rc=1` and a hard failure in the staging step, as observed on the ADIS host repo (run 26773177931, CCE-75).

The negative pathspec approach is fundamentally incompatible with gitignored plugin directories. You cannot work around this by adjusting the pathspec syntax; the collision is at the git layer.

## The three-step staging sequence

CCE-75 replaced the pathspec with a sequence that is safe regardless of the host's `.gitignore` configuration:

1. **`git add -A .`** — Stage everything using git's gitignore-aware logic. Git skips files that `.gitignore` covers without error, so this succeeds whether `.docs-agent-plugin/` is ignored or tracked.

2. **Diff probe** — Run `git diff --cached --quiet` (or equivalent). If there are no staged changes, the orchestrator short-circuits and skips the PR step without error.

3. **`git restore --staged -- .docs-agent-plugin`** — Semantically revert the plugin directory's index entry to `HEAD`. This preserves any content that was legitimately pre-tracked (e.g., a `.gitmodules`-registered submodule) while removing anything the current run added. Only runs when step 1 produced staged output.

The sequence is implemented in `scripts/orchestrator_runner.py` inside `_stage_docs_run_changes`.

## Why `git restore --staged` instead of `git reset`

`git restore --staged -- <path>` restores the named path's index entry to the HEAD tree object without touching the working tree. For a submodule, this means the gitlink stays at HEAD's recorded commit — the staging step leaves pre-tracked submodule pointers undisturbed. `git reset HEAD -- <path>` behaves identically for normal files but is less explicit about intent; `git restore --staged` signals that the goal is "put the index back to HEAD for this path," not "undo all staged changes."

## Error propagation

All three subprocess calls propagate non-zero return codes and `stderr` to the caller. Prior to CCE-75 the staging function swallowed failures silently, making debugging live runs difficult. If any step fails you will now see the subprocess's stderr in the orchestrator log.

## Background

CCE-70 introduced the original exclusion logic to stop the plugin checkout from being committed as a gitlink into host PRs. CCE-75 patches the mechanism to be safe on hosts that gitignore the plugin directory. The post-fix end-to-end verification on ADIS was still pending at merge time; treat this page as the canonical reference for the current design intent.
