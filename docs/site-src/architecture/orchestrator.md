---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/98
  - https://github.com/theoju/engineering-docs-agent/pull/93
synthesized_into: []
---

# Orchestrator

The orchestrator (`scripts/orchestrator_runner.py`) is the nightly pipeline entry point. It loads config and state, dispatches seven subagents in sequence, stages the resulting doc changes into a branch, and opens or appends to a `docs-agent/YYYY-MM-DD` pull request.

A partial run (any subagent failure, missing Jira auth, out-of-window PR, etc.) still opens the PR rather than silently exiting — the `partial: true` body flag makes the operational gap visible in both the PR and `state.json`.

## Run lifecycle

1. Load config from `.engineering-docs-agent/config.yml` and state from `state.json`.
2. Dispatch `source-collector` to gather PRs, commits, and Jira issues since the last successful run's `head_sha`.
3. Dispatch `pr-summarizer` for each merged PR in the window.
4. Dispatch `gap-detector`, `page-author`, `notifier`, and `publish-verifier` in order.
5. Call `open_or_append_pr` to commit the staged changes and push the branch.
6. Save `state.json` with updated `last_successful_run.head_sha` on success.

## Failure visibility: `open_or_append_pr` and `_record_failure`

`open_or_append_pr` (`orchestrator_runner.py:1897`) has six fast-fail paths — checkout failure, staging failure, push failure, PR creation failure, and two auth-check failures. Before CCE-73, each of these paths captured subprocess stderr into an in-memory `partial_reasons` list but wrote nothing to stdout or stderr. Python block-buffers stdout under GitHub Actions; if the process exited at one of these paths the workflow log showed only `Process completed with exit code 1`.

The fix introduces two helpers:

**`_record_failure` (`orchestrator_runner.py:1880`)** — appends a `(reason, info_only)` tuple to the local `reasons` list AND immediately flushes the reason to `sys.stderr`. Every fast-fail in `open_or_append_pr` now calls this instead of building the tuple inline. The stderr line appears in the raw CI log instantly, not at buffered-flush time.

**`_redact_credentials` (`scripts/stderr_emit.py:43`)** — strips `https://user[:token]@host` credential patterns before any reason reaches stderr or `partial_reasons`. The pattern (`_CREDENTIAL_URL_RE`) is anchored to HTTP/HTTPS URLs only; git-protocol URLs (`git@github.com:…`) are unaffected and pass through verbatim.

Both helpers are exercised by `tests/test_open_or_append_pr.py` (314 lines). The credential-redaction assertion is at line 779 of that file.

After `open_or_append_pr` returns, `run()` prints all redacted `partial_reasons` to stderr before returning 1. The `partial_reasons` list is also persisted to `state.json` and, when `$GITHUB_STEP_SUMMARY` is set, appended to the GitHub Actions step summary via `_write_step_summary`.

## Staging doc changes: `_stage_docs_run_changes`

`_stage_docs_run_changes` (`orchestrator_runner.py:1790`) stages all run-emitted file changes, excluding the vendored plugin checkout at `.docs-agent-plugin/`.

The host's nightly workflow checks out the plugin into `.docs-agent-plugin/` via `actions/checkout`. If that directory were staged into the docs commit, it would appear as a gitlink (mode `160000`) — or as a foreign tree of files — depending on the host's gitignore configuration.

The function uses a two-branch detection strategy:

**Branch 1 — `.docs-agent-plugin/` is NOT gitignored.** `git add -A .` stages the nested checkout as a gitlink. The function then runs `git diff --cached --name-only -- .docs-agent-plugin` to probe whether anything under that path was staged. When the probe returns output, `git restore --staged -- .docs-agent-plugin` reverts the index entry to match HEAD. This is CCE-70.

**Branch 2 — `.docs-agent-plugin/` IS gitignored (e.g. hosts using ADIS).** Git's tree walk silently skips gitignored paths during `git add -A`. The diff probe finds nothing staged under `.docs-agent-plugin/`, so the restore step is skipped entirely. This is CCE-75. The prior implementation used a negative pathspec (`:!.docs-agent-plugin`) which git promotes to "explicitly mentioned", triggering the gitignore safety check and exiting with code 1 — exactly the bug CCE-75 fixed.

`git restore --staged` is used rather than `git rm --cached` so that any real tracked content at `.docs-agent-plugin/` — a pre-existing submodule registration in `.gitmodules`, or files committed before the plugin was adopted — is preserved. Restore reverts the index to match HEAD; it does not delete from the index.

### Edge cases

**Mid-run modifications.** If an orchestrator bug modifies tracked content under `.docs-agent-plugin/` during the run, `git add -A .` stages those changes. The diff probe then sees output under `.docs-agent-plugin/` and triggers the restore step. The restore reverts the index entry to HEAD. The modified plugin files are silently dropped from the docs PR. This is correct because docs runs should never mutate the plugin tree, but an orchestrator bug of this kind would be non-obvious — the PR succeeds and the mutation disappears. Regression coverage: `tests/orchestrator/test_gitlink_exclusion.py`.

**Gitlink matching scope.** The diff probe (`git diff --cached --name-only -- .docs-agent-plugin`) matches the path prefix `.docs-agent-plugin`, not just exact paths. Any staged entry whose path starts with `.docs-agent-plugin` — including a gitlink at `.docs-agent-plugin` itself, or any file at `.docs-agent-plugin/foo` — causes the restore step to fire. This is intentional: the function's contract is to exclude everything under that tree.

**Symlink handling.** The three git operations (`add -A`, `diff --cached`, `restore --staged`) all assume `.docs-agent-plugin` is a real directory as created by `actions/checkout@v5`. A symlink at that path changes pathspec semantics: `git add -A .` would recurse into the symlink target, and the diff probe and restore would match the link path rather than the target's contents. The nightly workflow template does not create a symlink here; if your host repo has one, `_stage_docs_run_changes` behavior is undefined for that case.

### Regression tests

`tests/orchestrator/test_gitlink_exclusion.py` (176 lines, added in PR #98) covers:

- Gitignored plugin directory: `git add` skips it, restore step is skipped.
- Non-gitignored plugin directory staged as a gitlink: diff probe fires, restore reverts.
- Mid-run modification to tracked plugin content: staged by `git add`, then reverted by restore.
- `git add` failure: function returns nonzero immediately.
- `git diff` failure: function returns nonzero immediately.
- `git restore` failure: function returns nonzero immediately.

## Credential redaction

`_redact_credentials` lives in `scripts/stderr_emit.py` (CCE-74) rather than `orchestrator_runner.py`. This is a leaf module: it imports only stdlib (`sys`, `re`) and must not import from `state_io` or `orchestrator_runner` to avoid import cycles. Any future module that needs redacted stderr writes should import from `stderr_emit`, not re-implement the pattern.

The `_CREDENTIAL_URL_RE` pattern and substitution are identical to the pre-CCE-74 version in `orchestrator_runner.py:1832` so that existing test assertions (e.g. `"<redacted>" in err` at `tests/test_open_or_append_pr.py:779`) see no behavioral change.

## Observability

Set `DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug` before invoking the orchestrator to persist per-subagent raw NDJSON event streams (`<agent>.stream.jsonl`) and tool-use summaries (`<agent>.meta.json`). The `emit_log` and `emit_stderr` helpers in `scripts/stderr_emit.py` lock `flush=True` across all diagnostic writes so buffering cannot drop output even when the process exits abruptly.
