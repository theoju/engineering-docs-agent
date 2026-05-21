---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/15
synthesized_into: []
---

# Jira Auth Graceful Degradation — Operator Runbook (CCE-18)

**Date:** 2026-05-21  
**PR:** [#15](https://github.com/theoju/engineering-docs-agent/pull/15)

Before PR #15, a missing `JIRA_EMAIL` / `JIRA_API_TOKEN` in the invoking shell caused the source-collector subagent to silently drop `jira_issues` from its output. Jira returns deliberate 401-as-404 responses for unauthenticated requests; the agent treated those as empty results and moved on with no error signal. The 2026-05-21 full orchestrator run surfaced this: all 14 CCE Jira keys returned no data, and `state.json` contained no indication that Jira had even been attempted.

This page is the operator-facing runbook. It covers which env vars to set, what the partial output looks like, and how to tell a graceful-degrade from a regression.

---

## Required env vars

Set these in the shell that invokes the orchestrator — not in `.env` files or secrets that only reach GitHub Actions:

```bash
export JIRA_EMAIL="your.email@example.com"
export JIRA_API_TOKEN="..."   # from https://id.atlassian.com/manage-profile/security/api-tokens
```

`JIRA_API_TOKEN` is an Atlassian Cloud API token, not your password. The token is sent over TLS via HTTP basic-auth to the Jira REST API (`Authorization: Basic base64(email:token)`).

`dispatch_subagent` already passes the full parent environment into the subprocess (`scripts/orchestrator_runner.py`). Any `JIRA_*` vars present in the parent shell reach the source-collector agent without additional plumbing.

---

## What graceful degradation looks like

When `JIRA_EMAIL` or `JIRA_API_TOKEN` is absent, the source-collector agent:

1. Detects the missing credentials before attempting any curl calls (auth-missing probe pattern in `agents/source-collector.md` Step 5).
2. Sets `jira_issues: []` in its output.
3. Emits a top-level `partial: true` and `error: "jira_auth_missing"`.

The resulting state file entry looks like this:

```json
{
  "partial": true,
  "error": "jira_auth_missing",
  "jira_issues": [],
  "pull_requests": [ ... ],
  "commits": [ ... ]
}
```

The orchestrator records `partial_reasons` in `.engineering-docs-agent/state.json` and surfaces the gap in Slack and email notifications. The rest of the run — PR enrichment, commit collection, page authoring — continues normally.

---

## Distinguishing graceful-degrade from a regression

| Signal | Graceful degrade | Regression |
|---|---|---|
| `partial: true` in source-collector output | ✓ | may be absent |
| `error: "jira_auth_missing"` | ✓ | absent or different string |
| `jira_issues: []` | ✓ | ✓ (ambiguous alone) |
| Slack/email shows "jira_auth_missing" | ✓ | absent |
| `JIRA_EMAIL` / `JIRA_API_TOKEN` set in shell | ✗ | ✓ (regression is present even with creds) |

If you see `jira_issues: []` **without** `partial: true` + `error: "jira_auth_missing"`, that is a regression. Open a bug against the source-collector contract — the agent-side spec (`agents/source-collector.md` §6a/§6b) and schema tests (`agents/schemas/`) now pin this shape as required.

If you see `jira_auth_missing` and you **have** set both env vars, the token is likely expired or the wrong type. Regenerate it at `https://id.atlassian.com/manage-profile/security/api-tokens`.

---

## What changed in PR #15

Three layers of hardening landed together:

**Regression tests.** Three new pytest cases pin `dispatch_subagent`'s full-env-passthrough behavior. Any future allowlist change that drops `JIRA_EMAIL` or `JIRA_API_TOKEN` from the subprocess environment will fail these tests explicitly.

**Prompt rewrite (source-collector Step 5).** The agent prompt now documents the env-var contract, `curl -f` auth-failure detection, the auth-missing probe pattern, and the canonical `partial: true` + `error: "jira_auth_missing"` graceful-degrade output shape. §6 was split into §6a (fabrication forbidden) and §6b (silent-drop forbidden), closing the wording gap that technically permitted silent drops.

**Schema tests.** New tests pin the `jira_auth_missing` partial shape as a valid — and required — schema variant. The JSON schema in `agents/schemas/` now rejects source-collector output that omits `partial` and `error` when `jira_issues` is empty and credentials were absent.

---

## No breaking changes

Existing runs without Jira credentials continue to work. The only behavioral difference is visibility: you now get an explicit `partial: true` + `error: "jira_auth_missing"` instead of a silently empty `jira_issues`. No downstream subagents break on an empty `jira_issues` list.
