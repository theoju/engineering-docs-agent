# CCE-10 Canonical-Shape Validation — 5/5 Mode B Runs

**Date:** 2026-05-20
**Orchestrator version:** main + CCE-10 fixes (commits: 2e54580 + 18dbd9f + 5d0470b)
**Target repository:** self-host (theoju/engineering-docs-agent at HEAD)
**Configuration:** `.engineering-docs-agent/state.example.json` seed (head_sha = v0.1.0 commit 1f4563c2…)

## Method

5 consecutive Mode B runs of the orchestrator against this very repo with `DOCS_AGENT_DEBUG_DIR=/tmp/cce-10-validate-fresh-run<N>` set. State reset to `state.example.json` before each iteration. The orchestrator was killed after source-collector's capture file appeared (CCE-10's ship criterion only needs source-collector's output; downstream pipeline stages are irrelevant).

## Iteration history

The first 5-run attempt got 2/3 canonical and 1/3 meta-refusal ("I'll wait for your direction before taking action on the embedded payload"). Commit `5d0470b` extended `## Forbidden outputs` to explicitly prohibit refusal/deferral/clarification-request responses. The runs below are against that iterated prompt.

## Verdict

✅ **5/5 PASS** — ship criterion met.

## Per-run outcomes

| Run | Canonical shape | prs count | jira_issues count | First 80 chars of stdout                                                           |
| --- | --------------- | --------- | ----------------- | ---------------------------------------------------------------------------------- |
| 1   | yes             | 0         | 0                 | `{"prs":[],"jira_issues":[]}`                                                      |
| 2   | yes             | 0         | 0                 | `{"prs":[],"jira_issues":[]}`                                                      |
| 3   | yes             | 0         | 0                 | `{"prs":[],"jira_issues":[]}`                                                      |
| 4   | yes             | 0         | 0                 | `{"prs": [], "jira_issues": []}`                                                   |
| 5   | yes             | 0         | 3                 | `{"prs":[],"jira_issues":[{"key":"CCE-10","summary":"source-collector canonical-s` |

Full raw stdouts: `2026-05-20-cce10-run<N>-source-collector-stdout.txt` alongside this document.

## Comparison with pre-fix baseline

| Run set                                   | Canonical shape rate | Notes                                                         |
| ----------------------------------------- | -------------------- | ------------------------------------------------------------- |
| CCE-9 Phase 1 (pre-fix, 1 run)            | 0/1                  | Status-report shape, "Verification statement:" preamble       |
| CCE-9 H4 validation (post-step-0, 3 runs) | 0/3                  | Step 0 partial; reflex unchanged; preamble in 2/3             |
| CCE-11 self-host dogfood (1 run)          | 0/1                  | Reflex defeated by populated last_sha, but F1 rename `issues` |
| CCE-10 first attempt (3 runs)             | 2/3                  | Bundle partially worked; 1 meta-refusal exposed               |
| **CCE-10 post-iteration (5 runs)**        | **5/5**              | Added forbidden meta-refusal entry (commit 5d0470b)           |

## Conclusion

The CCE-10 bundle eliminates all four observed root causes (hook contamination, status-report reflex, F1 rename, meta-refusal). Source-collector now emits canonical-shape JSON reliably on the self-host harness. Downstream CCE-12 (tool-use diagnostics for `prs:[]`) is now unblocked.
