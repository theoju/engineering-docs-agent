---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/104
synthesized_into: []
---

# GitHub CLI + Subagent Gotchas

Two repeatable failure modes surfaced during the CCE-83 meta-orchestrator work. Both are silent: the orchestrator gets a result that looks plausible, parses it incorrectly or not at all, and proceeds on bad data. Neither shows up without an end-to-end integration test.

## `gh pr checks --json` field names

`gh pr checks <N> --json` returns objects with **`name`**, **`state`**, and **`bucket`** — not `statusCheckRollup` or `conclusion`. Any orchestrator or skill polling check status must use the correct field names:

```js
// green
c.state === 'SUCCESS' || c.bucket === 'pass'

// red
c.state === 'FAILURE' || c.bucket === 'fail'
```

The non-JSON `gh pr checks` text output uses yet another vocabulary (`pass` / `fail` / `pending` printed in columns). Do not mix field names across the two output modes.

`statusCheckRollup` and `conclusion` come from `gh pr view --json statusCheckRollup`, which is a different command and a different shape. Using those names against `gh pr checks --json` output returns `undefined` silently — JavaScript doesn't throw on missing keys.

**Reference:** CCE-83 meta-orchestrator plan iter-3, Task 15 Step 2.

## `gh pr view --json` through a subagent

When you pass `gh pr view --json <fields>` through a subagent, the subagent wraps the output in markdown fences or adds prose commentary. `JSON.parse` on that result throws.

Fix this one of two ways:

**Option A — explicit instruction in the prompt:**

> Return only the raw JSON output from `gh pr view` (no surrounding prose).

**Option B — defensive parse in the caller:**

```js
let parsed;
try {
  parsed = JSON.parse(subagentOutput);
} catch {
  parsed = SENTINEL_FALLBACK;
}
```

The same pattern applies to any `--json` CLI consumer routed through a subagent. Never assume model output of a shell command is directly parseable — the model's default behavior is to be helpful and explain what it's doing.

**Reference:** CCE-83 meta-orchestrator plan iter-3, Tasks 16/17 Step 1.

## General rule

Any time you feed `--json` CLI output through a subagent and then parse the result programmatically:

1. Demand raw output explicitly in the prompt, and
2. Verify the field names against `gh <command> --json` (not against a similar command).

Silent failures from both modes compound. A wrong field name returns `undefined`; a markdown-wrapped response throws on parse. Neither produces an error message that points to the real cause.
