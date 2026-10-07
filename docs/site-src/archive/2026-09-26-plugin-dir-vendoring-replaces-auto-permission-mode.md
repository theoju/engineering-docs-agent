---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/299
synthesized_into: []
doc_kind: decision
---

# Vendor `--plugin-dir` outside the worktree instead of using `--permission-mode auto`

Decision record for CCE-193 (PR #299). The PR title and squash commit say CCE-192 in error; CCE-192 is an unrelated source-collector payload ticket.

## Context

Every dispatch passes `--plugin-dir` so the Claude CLI can resolve agents. Claude Code refuses agent writes to plugin-owned files with a "sensitive file" denial. This repo is itself the plugin, so when the docs-agent documents its own repo the plugin root equals the worktree. Every page-author write was denied.

CCE-188 fixed that by passing `--permission-mode auto`. That mode clears the gate by asking a server-side classifier to approve each write.

## What broke

On nightly `36241035222` (2026-09-26) the classifier returned no verdict. The CLI treats that as a hard, non-retryable failure. All ten page-author dispatches failed and zero pages were authored. The baseline stayed frozen at `1718883f`, and PR #298 was left open as a partial run.

Re-measured the same day: `auto` produced no verdict and no file. `bypassPermissions` wrote the file.

## Decision

Remove the gate instead of negotiating with it. When the plugin root would shadow the worktree, the orchestrator points `--plugin-dir` at a copy of the plugin outside the worktree. No `--permission-mode` is passed on any path.

The CCE-188 diagnosis was correct. Only the remedy changed: the permission axis was the wrong axis, because it made every page write depend on a third party's ruling.

Consequences:

- Page writes no longer depend on a classifier verdict.
- `--agent page-author` still resolves from the vendored copy, and the `--allowedTools` allow-list is unchanged. It remains the security boundary.
- The copy is made once per process and cached, not once per dispatch.
- If the plugin manifest is missing, vendoring raises `cannot vendor plugin` rather than falling back to the plugin root. A silent fallback would reintroduce the shadowing.
- Host repos are unaffected. Their plugin lives in a `.docs-agent-plugin/` subdirectory, so docs are siblings of it and already writable. They get the installed plugin dir unchanged and no vendoring cost.

## Guards

`tests/orchestrator/test_plugin_dir_write_denial.py` pins the behavior:

- The shadowed dispatch must pass a `--plugin-dir` outside the worktree and no `--permission-mode`. The absence assertion matters. Re-adding a mode "to be safe" would bring back the dependency this change removes.
- The host-shaped dispatch must use the installed plugin dir unchanged and also pass no permission mode.
- A schema-valid `ok: false` from page-author must surface as a `page_author_error:` partial reason, not be swallowed. That test is the loudness half carried over from CCE-188.

The entry points are `_vendored_plugin_dir` and `_plugin_dir_shadows_worktree` in `scripts/orchestrator_runner.py`.
