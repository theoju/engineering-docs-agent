---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/6
synthesized_into: []
---

# CCE-9: Debug Capture Infrastructure and Partial Source-Collector Fix

PR #6 (CCE-9) ships two independent changes: a new `DOCS_AGENT_DEBUG_DIR` diagnostic capture feature and a step-0 early-exit guard in the source-collector agent spec. Both are in production as of 2026-05-21.

## DOCS_AGENT_DEBUG_DIR — per-subagent debug capture

Set `DOCS_AGENT_DEBUG_DIR` to an absolute path before invoking the orchestrator runner. The runner writes four files per subagent invocation into that directory: the rendered prompt, raw stdout, raw stderr, and a metadata JSON (agent name, exit code, elapsed time).

When `DOCS_AGENT_DEBUG_DIR` is unset, the runner behaves byte-identically to v0.1.3. No new runtime dependencies were introduced.

To enable:

```bash
export DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

Captured files land as `<agent-name>.<sequence>.{prompt,stdout,stderr,meta.json}`. Use them to replay a subagent invocation locally or diff behavior across runs.

This is the primary measurement vehicle for diagnosing off-contract subagent responses. CCE-9's investigation was conducted entirely with it, and CCE-10 will use the same infrastructure for hook suppression testing.

## Source-collector step-0 early-exit (partial fix)

The source-collector agent was returning `{"status": "idle"}` instead of the canonical `{"prs": [], "jira_issues": []}` shape when `last_sha` was absent. `agents/source-collector.md` now includes an explicit step-0 instruction: if `last_sha` is empty, return the canonical empty response and halt.

The step-0 instruction shifts agent behavior but does not fully resolve the issue. Two root causes remain:

1. **Stop-verify hook contaminating stdout.** The hook emits text after the agent's JSON response, corrupting the stdout payload the orchestrator parses.
2. **Status-report reflex overriding canonical-shape instructions.** The agent's built-in completion signal (`{"status": "idle"}`) fires before the canonical-shape instruction is applied.

Both are forwarded to CCE-10.

## What CCE-10 will address

CCE-10 targets hook suppression (silencing the stop-verify hook in source-collector context) and stronger canonical-shape forcing (a prompt or wrapper change that overrides the status-report reflex). Until CCE-10 lands, empty `last_sha` runs will still emit a non-canonical shape; the orchestrator's existing fallback treats a missing `prs` key as an empty list, so no data is lost but `state.json` will log a parse warning.
