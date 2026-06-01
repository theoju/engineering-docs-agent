---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/88
synthesized_into: []
---

# Orchestrator

The orchestrator (`scripts/orchestrator_runner.py`) is the entry point for every nightly docs run. It coordinates the seven subagents, manages run state, and opens or appends to the `docs-agent/YYYY-MM-DD` PR on the host repo.

## Git staging

After the authoring subagents write their output, the orchestrator stages all changes with `_stage_docs_run_changes(repo_root)` (`scripts/orchestrator_runner.py:1742`).

The helper calls `git add .` with two exclude pathspecs:

```
':!.docs-agent-plugin'
':!.docs-agent-plugin/**'
```

This prevents the plugin checkout from being staged. When a host's CI workflow checks out the plugin into `.docs-agent-plugin/` (the standard layout used by `templates/workflow-run.yml`), git sees a nested repository. Without an explicit exclusion, a bare `git add .` registers that directory as a submodule gitlink (mode 160000) and contaminates the generated docs PR with a ghost submodule entry. The exclude pathspecs prevent that entirely.

Prior to this fix (CCE-70), the orchestrator used an unconstrained `git add .` at that call site. The bug surfaced during onboarding of two new hosts and was silent — the PR opened successfully, but the gitlink was committed alongside the authored docs.

## Belt-and-suspenders: host `.gitignore`

The setup skill (`/engineering-docs-agent:engineering-docs-agent-setup`) instructs new host onboardings to add `.docs-agent-plugin/` to the host's `.gitignore`. This provides a second layer of defense: if the exclude pathspec is somehow bypassed or the staging call is called from another path, git will already have the directory marked untrackable.

You do not need to add this entry manually if you ran the setup skill after PR #88 merged. For repos onboarded earlier, add it yourself:

```
# .gitignore (host repo)
.docs-agent-plugin/
```

## Nightly schedule

The orchestrator runs automatically at 07:00 UTC via `.github/workflows/docs-agent-nightly.yml`. You can also trigger it manually:

```bash
gh workflow run docs-agent-nightly.yml -f reason="<your reason>"
gh run watch
```

The `reason` input appears in the run summary alongside the post-run `state.json` snapshot.

## State and partial runs

The orchestrator writes run state to `.engineering-docs-agent/state.json` on success. `last_successful_run.head_sha` is the source of truth for the next nightly's window — it advances when the `docs-agent/YYYY-MM-DD` PR merges via normal git merge.

A partial run (any subagent skipped or errored) still opens the PR with `partial: true` in the body. Failures are recorded to `partial_reasons` in `state.json` and surfaced in Slack/email notifications. The run is never silent about gaps.

## Local invocation

Run the orchestrator locally against any host repo:

```bash
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

For per-subagent raw stdout, set `DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug` before invoking.
