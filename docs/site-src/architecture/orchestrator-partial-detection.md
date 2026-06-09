---
description: "The orchestrator marks a run as partial when it cannot confidently determine that all inputs were gathered and all subagents completed successfully."
source_files:
  - scripts/orchestrator_runner.py
  - docs/site-src/setup-guide.md
last_reviewed: '2026-06-09'
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/99
synthesized_into: []
---

# Orchestrator Partial-Detection

The orchestrator marks a run as **partial** when it cannot confidently determine that all inputs were gathered and all subagents completed successfully. Partial runs still open a PR — the gap is visible, not silent — but the state cursor (`state.json.last_successful_run`) does not advance until the PR merges.

This page describes the two mechanisms that govern partial detection and how they interact.

## Stderr capture in `dispatch_verified`

When a subagent exits non-zero, the orchestrator records a `PartialReason`. Before PR #99, the reason contained only the exit code. The stderr of the failing subagent was discarded.

`dispatch_verified` now captures stderr and appends it to the `PartialReason` message. You get the full diagnostic text — not just `exit code 1` — in the PR body and in `current_run.json`. This matters when a subagent fails due to a downstream tool error (a failing `mkdocs build`, a bad API response, a schema validation failure): those messages are now surfaced instead of swallowed.

No behavior change for subagents that exit zero. The change is purely additive — more signal on the failure path.

## Empty-window detection in `_is_partial_output`

The source-collector returns a JSON object. Two shapes are superficially identical:

| Shape | Meaning |
|---|---|
| `{"prs": [], "jira_issues": [], "error": null}` | Genuine empty window — no activity since the last run |
| `{"prs": [], "jira_issues": [], "error": null}` | Silent tool failure — the collector ran but gathered nothing due to an undetected error |

Before PR #99, `_is_partial_output` treated both as a clean empty window and advanced the state cursor. A misconfigured GitHub token, a Jira connectivity blip, or a quota exhaustion could produce the second shape with no error field, and the orchestrator would silently skip the window.

`_is_partial_output` now treats `{"prs": [], "jira_issues": [], "error": null}` as a partial result. The run opens a PR flagged partial, and a human decides whether the window was genuinely quiet or whether the collector failed silently. The state cursor only advances on merge.

This is a conservative choice: some genuine empty windows will produce a partial PR that an operator needs to dismiss. That cost is preferable to silently advancing the cursor on a failed collection.

## How the two mechanisms compose

Both mechanisms write to `PartialReason` entries in the run state. The orchestrator aggregates all reasons and sets `partial: true` in the PR body if any reasons exist. You can inspect the full list in `.engineering-docs-agent/current_run.json` under `partial_reasons`.

A run is fully green only when:

1. All subagents exit zero (no stderr-capture reasons).
2. The source-collector returns at least one `pr` or `jira_issue`, or explicitly signals an empty window in a way the orchestrator can verify.

If either condition fails, the run is partial. The PR stays open for operator review. The nightly the next day re-collects from the same baseline SHA until the partial PR merges.

## Reference

- PR #99 — CCE-74: partial-detection hardening (stderr capture + empty-window guard)
- `scripts/orchestrator_runner.py` — `dispatch_verified` and `_is_partial_output`
- `docs/site-src/setup-guide.md` — full list of partial-mode failure modes and recovery steps
