---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/97
  - https://github.com/theoju/engineering-docs-agent/pull/93
synthesized_into: []
---

# Orchestrator

The orchestrator (`scripts/orchestrator_runner.py`) is the nightly entry point. It sequences the seven subagents, manages run state, and opens or updates the `docs-agent/YYYY-MM-DD` PR on the host repo.

## Staging changes

`_stage_docs_run_changes` prepares the git index before the PR step. It uses a deliberate three-step sequence that respects the host's `.gitignore`:

1. `git add -A .` — stages all tracked and untracked changes, honouring gitignore rules.
2. Diff probe — checks whether the index actually differs from `HEAD`.
3. Conditional `git restore --staged -- .docs-agent-plugin` — removes `.docs-agent-plugin/` from the index if it was picked up, keeping ephemeral plugin state out of the docs-agent PR.

The previous implementation used a direct pathspec that bypassed gitignore. On host repos that list `.docs-agent-plugin/` in their `.gitignore`, that caused `rc=1` and broke every nightly run (CCE-75).

All three subprocess calls surface non-zero return codes and stderr. Silent failures in git operations mask the actual cause of a broken run; every call must propagate its exit status.

## Partial-run observability

When `open_or_append_pr` exits with a non-zero status, the orchestrator writes all collected `partial_reasons` to stderr. Before this change (CCE-73), a failed run could exit 1 with no output at all, making triage dependent on manual `state.json` inspection.

The `partial_reasons` list is populated by `add_partial` calls throughout `run()`. The collection and `state.json` serialization are unchanged; only the stderr emission path was added.

If you see a non-zero exit from the orchestrator, check stderr first — the `partial_reasons` output will identify which stage(s) failed before inspecting `.engineering-docs-agent/state.json` or the ephemeral `current_run.json`.

CCE-74 is a queued follow-up that extends stderr emission to all `add_partial` call-sites inside `run()`, not just the PR-open path. This page will need a second pass once that lands.

## Run state

The orchestrator reads from and writes to two state files:

- `.engineering-docs-agent/state.json` — committed. `last_successful_run.head_sha` is the window anchor for the next nightly. It advances when the docs-agent PR merges.
- `.engineering-docs-agent/current_run.json` — gitignored, ephemeral. Written at every state-update for diagnostics and test observability.

A partial run (any `add_partial` call reached) still opens or updates the PR with `partial: true` in the body. The gap is visible to operators without requiring them to poll run logs.

## Invoking the orchestrator

Run against the local host without opening a PR:

```bash
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

For per-subagent raw-stdout diagnostics, set `DOCS_AGENT_DEBUG_DIR` before invoking:

```bash
DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug python3 scripts/orchestrator_runner.py --repo-root .
```

The nightly workflow (`.github/workflows/docs-agent-nightly.yml`) fires at 07:00 UTC. Trigger it manually with:

```bash
gh workflow run docs-agent-nightly.yml -f reason="<your reason>"
gh run watch
```
