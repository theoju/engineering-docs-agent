---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/98
synthesized_into: []
---

# Orchestrator staging: probe-then-restore

The orchestrator commits every docs run's output — state, What's New, and authored pages — as a single commit on the `docs-agent/YYYY-MM-HH` branch. The staging step that assembles that commit is `_stage_docs_run_changes` in `scripts/orchestrator_runner.py:1790`.

## Why a staging helper exists

The host's workflow checks out the plugin into `.docs-agent-plugin/` via `actions/checkout` (see `templates/workflow-run.yml`). That nested checkout looks like a submodule gitlink (mode `160000`) to git. A naïve `git add -A .` would include it in the docs commit.

Two host layouts exist and both must be handled without callers distinguishing between them:

- **Not gitignored:** `git add -A .` stages `.docs-agent-plugin` as a gitlink. The helper must remove it from the index.
- **Gitignored (CCE-75):** `git add -A .` silently skips the path. The helper must not attempt to unstage it — using a negative pathspec (`:!.docs-agent-plugin`) on a gitignored path causes git to abort with `paths are ignored by one of your .gitignore files`.

## How probe-then-restore works

The helper runs three git operations in sequence.

**Step 1 — add everything:**

```
git add -A .
```

This stages all working-tree changes, including `.docs-agent-plugin` if the path is not gitignored.

**Step 2 — probe the index:**

```
git diff --cached --name-only -- .docs-agent-plugin
```

The bare pathspec `-- .docs-agent-plugin` matches the gitlink entry exactly and any files under `.docs-agent-plugin/`. It does NOT match siblings like `.docs-agent-plugin-notes.md` — git pathspec requires an exact match or a prefix followed by `/`.

If the probe returns empty output, nothing under `.docs-agent-plugin` made it into the index (gitignored host layout). The helper returns immediately.

**Step 3 — conditional restore:**

```
git restore --staged -- .docs-agent-plugin
```

Only reached when the probe found something. `git restore --staged` reverts the index entry to match HEAD. This means:

- A new gitlink (no HEAD counterpart) is removed from the index.
- Pre-existing tracked content at `.docs-agent-plugin/` (committed before the plugin was adopted) is left as it was at HEAD — not staged for deletion.
- Mid-run modifications to tracked plugin content are reverted in the index, so they do not appear in the docs commit.

`git restore --staged` is chosen over `git rm --cached` precisely because `rm --cached` would delete any pre-existing tracked content from the index, breaking hosts that have legitimate files there.

## Behavioral guarantees

Two guarantees are pinned by tests in `tests/orchestrator/test_gitlink_exclusion.py`:

**Mid-run plugin mutations are dropped silently.** If an orchestrator bug or a misbehaving subagent writes to `.docs-agent-plugin/tracked-file.txt` during a run, `git add -A .` stages the change, the diff probe finds it, and `restore --staged` reverts the index entry to HEAD. The mutation is not committed. This is correct — docs runs should never touch the plugin tree on the runner — but the silent drop means such a bug would go unnoticed in the docs PR. The test `test_stage_docs_run_changes_drops_midrun_modifications_to_tracked_plugin_content` pins this behavior.

**The bare pathspec does not overselect siblings.** A reviewer suggested tightening the diff probe to `:(glob).docs-agent-plugin/**` to be more explicit. That rewrite would regress the helper: production gitlink entries sit at `.docs-agent-plugin` with no trailing slash, so the glob `/**` would not match the gitlink and the restore step would never fire. The test `test_stage_docs_run_changes_bare_pathspec_does_not_overselect_siblings` proves the bare form matches the gitlink but not sibling paths, and explicitly documents why the `:(glob)/**` alternative is wrong.

## Where this fits in the PR flow

`_stage_docs_run_changes` is called from `open_or_append_pr` (`scripts/orchestrator_runner.py:1935`) immediately after the branch checkout. A non-zero return code from the helper aborts the PR open and records a `git_add_failed` partial reason. The function signature is `(repo_root: Path) -> tuple[int, str]` — return code and stderr on failure, `(0, "")` on success.
