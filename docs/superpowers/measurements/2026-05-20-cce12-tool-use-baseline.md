# CCE-12: Source-Collector Tool-Use Baseline — 5-Run Mode B Ceremony

> **⚠ PARTIAL SUPERSESSION — see [CCE-16 real baseline](2026-05-21-cce16-real-baseline.md).**
>
> The stream-json instrumentation infrastructure described in this baseline (forensic artifact capture, tool-use summary, DOCS_AGENT_DEBUG_DIR gate) is sound and remains in production. However, the conclusions classifying source-collector behavior into Category A / B / C are based on dispatches where the plugin manifest was rejected by the Claude CLI loader (the `author` field violated the schema), so every dispatch in this baseline ran as default Claude Code, not the source-collector agent. The classification distribution is real data about default Claude Code's response to the orchestrator's `<inputs>` framing, but should not be read as source-collector compliance behavior. See CCE-16.

**Jira:** [CCE-12](https://designitright.atlassian.net/browse/CCE-12)
**Branch:** `feat/CCE-12-source-collector-tool-use-diagnostics`
**Date:** 2026-05-20
**Dispatch window:** `a2a9dba273bf5ef82ef6d450d3eb44ee27e04681..b2cd07af5cdcf0482515fc757a6ee6def3af278d` on theoju/engineering-docs-agent
**PR filter:** `docs-agent/*`
**Diagnostic:** `DOCS_AGENT_DEBUG_DIR` set; stream-json dispatch path (CCE-12)

## Per-run summary

| Run | total_calls | by_name            | stop_reason | prs | jira_issues | category                |
| --: | ----------: | ------------------ | ----------- | --: | ----------: | ----------------------- |
|   1 |           0 | {}                 | end_turn    |   0 |           0 | A: zero tool calls      |
|   2 |           5 | {Bash: 3, Read: 2} | end_turn    |   0 |           0 | B: called and discarded |
|   3 |           0 | {}                 | end_turn    |   0 |           0 | A: zero tool calls      |
|   4 |           0 | {}                 | end_turn    |   0 |           0 | A: zero tool calls      |
|   5 |           0 | {}                 | end_turn    |   0 |           0 | A: zero tool calls      |

Raw artifacts: `2026-05-20-cce12-run<N>-source-collector.{stream.jsonl,stdout.txt,stderr.txt,prompt.txt,meta.json}` in this directory.

## Category definitions

- **A — Zero tool calls:** `total_calls == 0`. Agent emitted JSON without invoking any tool.
- **B — Called and discarded:** non-zero `total_calls`, non-trivial `result_chars` from at least one call, but `prs == []`. Agent saw real data and dropped it.
- **C — Legitimately empty:** non-zero `total_calls`, no errors, but the tool's own output was empty (e.g. `gh pr list` returned nothing for the window). `prs == []` is correct.
- **D — Tool errored:** any call has `is_error: true`. Agent's downstream behavior is moot until the tool itself works.

## Dominant pattern

Category A (zero tool calls) appeared in 4 of 5 runs. The source-collector agent completes in a single turn (~3–6 s) and returns the canonical empty JSON shape without ever invoking Bash or any other tool. This confirms the CCE-10 hypothesis: the agent is hallucinating a compliant response rather than executing its job. Run 2, the sole outlier, made 5 tool calls (3 Bash, 2 Read) across 6 turns and still returned `prs: []`, which shows the discarding behavior documented as Category B but does not disprove the dominant A pattern — a fresh session made it past the prompt but still failed to surface PR data.

The fix ticket should focus on the agent's system prompt: the current instructions are not strong enough to force tool invocation before returning a response. Adding an explicit "you MUST call `gh pr list` before producing output" guard — or restructuring the prompt as a mandatory checklist — is the most direct intervention.

## Follow-up ticket

File **CCE-13** with scope: "Harden source-collector system prompt to force tool invocation before output; add a prompt-level assertion that `prs` may only be `[]` if `gh pr list` returned no rows." CCE-12 itself closes once this doc is committed — it shipped the instrument, not the cure.
