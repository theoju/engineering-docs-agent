---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/98
synthesized_into: []
---

# `_stage_docs_run_changes` — probe-then-restore mechanism

`_stage_docs_run_changes` (`scripts/orchestrator_runner.py:1790`) is the function that stages every run-emitted file change before the docs commit, while keeping the vendored plugin checkout at `.docs-agent-plugin/` out of that commit.

The function is called once per run from `open_or_append_pr` (`orchestrator_runner.py:1935`) after the docs branch is checked out and all subagent writes are complete.

## The three-step sequence

The function runs three git operations in order:

1. `git add -A .` — stages all working-tree changes under `repo_root`.
2. `git diff --cached --name-only -- .docs-agent-plugin` — probes whether the index contains any entry at or under `.docs-agent-plugin`.
3. `git restore --staged -- .docs-agent-plugin` — reverts the index back to HEAD for that path, but only if step 2 found anything.

The restore step is gated on the probe result. When the probe output is empty (the plugin directory was gitignored on this host and `git add` silently skipped it), the restore step is skipped entirely.

## Two host layouts handled uniformly

**Plugin directory not gitignored.** The host's `actions/checkout` step creates `.docs-agent-plugin/` as a real checkout. `git add -A .` sees it and stages its contents as a submodule gitlink (mode `160000`). The diff probe finds it, the restore step fires, and the gitlink is reverted from the index. The docs commit contains no reference to `.docs-agent-plugin/`.

**Plugin directory gitignored.** The host's `.gitignore` covers `.docs-agent-plugin/`. Git's tree walk silently skips it during `git add -A`, so nothing lands in the index for that path. The probe finds an empty diff, and the restore step is skipped. Behavior is identical from the outside.

## Why `git restore --staged` instead of `git rm --cached`

`git restore --staged` reverts the index entry to match HEAD — it does not delete from the index. If a host has real tracked content under `.docs-agent-plugin/` (a committed submodule registration in `.gitmodules`, or files that predate plugin adoption), restore preserves those entries by resetting them to their HEAD state. `git rm --cached` would remove them from the index entirely, which is not the intent.

## Mid-run mutations are silently dropped

If the orchestrator (or a subagent) modifies a tracked file under `.docs-agent-plugin/` during a run, `git add -A .` stages that modification, the probe detects it, and the restore step reverts the index entry back to HEAD. The mutation does not appear in the docs commit.

This is intentional: docs runs should not mutate the plugin tree on the runner. The downside is that an orchestrator bug touching plugin files would fail silently in the docs PR rather than loudly. The behavior is pinned by `tests/orchestrator/test_gitlink_exclusion.py`.

## Gitlink pathspec semantics

The diff probe and restore step use the bare pathspec `-- .docs-agent-plugin`. Git pathspec semantics for a bare literal are:

- **Exact match** — the path equals the spec exactly (matches the gitlink entry `.docs-agent-plugin`).
- **Prefix-followed-by-slash** — the path begins with `<spec>/` (matches any file inside the directory).

A path that only shares a string prefix — like `.docs-agent-plugin-notes.md` — does **not** match. The trailing slash is required for prefix matching.

This means the bare form is already correct for excluding the plugin tree without over-selecting siblings. A `:(glob).docs-agent-plugin/**` rewrite would actively regress the helper: the gitlink entry sits at `.docs-agent-plugin` with no trailing slash and would not match the `/**` glob.

The correct behavior is pinned by the anti-regression test `test_stage_docs_run_changes_bare_pathspec_does_not_overselect_siblings` in `tests/orchestrator/test_gitlink_exclusion.py`.

## Symlink assumption

All three git operations assume `.docs-agent-plugin/` is a real directory — the representation `actions/checkout@v5` produces. A symlink would change pathspec semantics for all three: `git add -A .` would recurse into the symlink target, and the diff probe and restore would match the link entry rather than its contents. There is no current handling for the symlink case.

## Anti-regression test coverage

Two tests in `tests/orchestrator/test_gitlink_exclusion.py` lock in the behaviors described above:

- `test_stage_docs_run_changes_drops_midrun_modifications_to_tracked_plugin_content` — sets up a repo with pre-tracked content under `.docs-agent-plugin/`, mutates it mid-run, calls the helper, and asserts the mutation is not staged while an authored docs page is.
- `test_stage_docs_run_changes_bare_pathspec_does_not_overselect_siblings` — injects a real gitlink via `git update-index --add --cacheinfo`, adds a sibling file sharing a string prefix, calls the helper, and asserts the sibling stays staged while the plugin tree does not.

These tests were added in PR #98 (CCE-75 polish) to convert latent risks — identified by the CCE-75 validator panel — into locked invariants with zero production-code behavior change.
