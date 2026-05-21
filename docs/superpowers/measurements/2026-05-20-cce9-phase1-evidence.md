# CCE-9 Phase 1 Evidence — Systematic-debugging root-cause investigation

**Date:** 2026-05-20
**Orchestrator version:** v0.1.3 (commit 9a386bf)
**Target repository:** advanced-data-importer at commit c36f53b
**Instrumentation:** working-tree patch to `dispatch_subagent` that writes raw stdout/stderr/prompt/meta to `$DOCS_AGENT_DEBUG_DIR` when set. Productized in Task 1 of this plan.

## Method

One Mode B orchestrator run against ADIS with `DOCS_AGENT_DEBUG_DIR=/tmp/cce9-phase1-debug` set. ADIS state reset to `{"version": "1"}` before the run.

## Captured stdout from source-collector (verbatim)

```json
{
  "status": "idle",
  "reason": "No baseline SHA provided (last_sha empty) — cannot compute commit delta for documentation impact analysis. No docs-agent/* branches found requiring processing. Verified: zero file modifications this invocation; the 25 working-tree files (1 modified, 24 untracked) pre-exist this orchestrator run per prior session state.",
  "branches_scanned": 0,
  "commits_analyzed": 0,
  "files_modified": 0,
  "prs_opened": 0,
  "jira_issues_touched": 0
}
```

Full prompt, raw stdout, and meta are alongside this document (`*-prompt.txt`, `*-stdout.txt`, `*-meta.json`).

## Analysis

The response shape matches **neither** of the two contract blocks in `agents/source-collector.md` v0.1.3:

- Not the canonical `## Output schema (canonical)` (lines 29-64) which requires top-level `prs` and `jira_issues` arrays.
- Not the legacy `## Output contract` (lines 66-99) which shows the same `prs`+`jira_issues` shape.

Instead the agent invented a third "telemetry / idle status" shape with keys `status`, `reason`, `branches_scanned`, `commits_analyzed`, `files_modified`, `prs_opened`, `jira_issues_touched`.

The agent's `reason` field cites the root cause verbatim: **"No baseline SHA provided (last_sha empty) — cannot compute commit delta for documentation impact analysis."**

## Hypothesis ranking (revised after Phase 1)

| #      | Original ranking | Phase 1 evidence verdict                                                                                                                                                                                                   |
| ------ | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **H4** | least likely     | **CONFIRMED.** Agent self-reports `last_sha` empty as the trigger. Procedure section of source-collector.md assumes a non-empty `last_sha` (step 1 resolves `last_sha → merged_at`); no fallback for the no-baseline case. |
| H1     | most likely      | Refuted. Removing the legacy `## Output contract` block would change nothing: agent is following neither block.                                                                                                            |
| H2, H3 | mid-ranked       | Cannot be assessed from this evidence alone, but H4 is independently sufficient to explain the failure.                                                                                                                    |

## Implication for CCE-9 scope

The fix is one paragraph added to `agents/source-collector.md` `## Procedure` directing the agent to emit `{"prs": [], "jira_issues": []}` (canonical empty) when `last_sha` is empty. Removing the legacy `## Output contract` block (the original H1 plan) is independent cleanup, not part of CCE-9's fix scope.

Estimated effort reduction vs original H1 plan: ~2 hours saved (10 Mode B runs avoided; null-result revert avoided).
