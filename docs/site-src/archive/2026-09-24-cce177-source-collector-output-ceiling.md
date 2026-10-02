---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/285
synthesized_into: []
doc_kind: decision
---

# CCE-177: bound source-collector output, refuse token-limit splits

## Decision

Bound what `source-collector` emits, and refuse any answer the Claude CLI split across two turns at its output-token ceiling. The agent contract in `agents/source-collector.md` now caps `prs[].body` and `jira_issues[].description` at 1,000 characters each. `scripts/orchestrator_runner.py` now records `output_token_limit_truncated: <agent>` and returns no output when it sees the split.

## Context

On 2026-09-18, 09-20 and 09-23, source-collector's output failed schema validation with `'prs' is a required property`. The run was classified blind under CCE-144, exited 1, and froze the watermark. Three of the last six nightlies failed this way.

## Root cause

The agent's answer was correct on all three nights. The orchestrator discarded half of it.

1. The agent emitted about 160KB of valid JSON, which crosses the CLI's 64,000-output-token ceiling mid-object.
2. The CLI injected a synthetic user turn (`isSynthetic: true`, text beginning `Output token limit hit`) and the model finished the JSON in a second assistant message.
3. `_extract_final_assistant_text` keeps only the last assistant message. The half carrying `{"prs": [` was thrown away.
4. The tail fragment starts mid-string, so strict parsing fails. The JSON rescue path returns the first balanced object in the tail, which is one Jira issue and has no `prs` key.

The trigger was per-item verbosity, not window size. The 09-17 run (pass) and the 09-20 run (fail) collected the identical 15 PRs and 30 Jira issues. The failing run copied roughly 3.4x more prose into each `body` and `description`, and its total payload was 2.9x larger. Nothing in the contract bounded either field.

Ruled out: prose contamination (the JSON was well-formed, just split), a code regression (no commits landed between the 09-18 and 09-20 failures), and window growth. Window growth is also not what CCE-169's window cap addresses, because that cap trims the orchestrator's work list after the agent has already emitted its answer.

## What shipped

**A. A character budget in the agent contract.** Each `body` and `description` is at most 1,000 characters in total. A longer value is cut at 988 characters and ends in `…[truncated]`, so a cut value is exactly 1,000. The budget includes the marker. An earlier draft said "cut at N, append marker", which made a cut value N+12 long and contradicted the Step 6 checklist. Steps 3, 5 and 6 of the agent file now state the same total.

Replaying the 09-23 payload (20 PRs, 38 issues) through the cap gives 80,249 characters, about half the measured ceiling of roughly 160,000 characters. A 2,000-character cap came to 137,628, about 86%, and was rejected for lack of headroom. The ceiling is about 2.5 characters per token on this payload, not the 4 a rule of thumb suggests.

**B. Detect the split and refuse it.** `dispatch_subagent` looks for the synthetic marker turn together with more than one assistant message carrying text. When both are present it records `output_token_limit_truncated: <agent>` through the existing reasons collector and returns `None`. The reason inherits each call site's CCE-144 classification, so it is blind for source-collector and degraded where the site passes `degraded=True`. No new classification code was added.

Refusing matters as much as detecting. A tail fragment that happened to parse and validate would otherwise be accepted as the whole answer, and the run would advance the watermark past PRs it never documented. That is the CCE-151 class of harm.

**C. A schema-valid failure payload.** The agent's unrecoverable-Git-failure path used to return `{"error": "git_unrecoverable: <reason>"}`, which has neither required key and produces the byte-identical `'prs' is a required property` message. It now returns `{"prs": [], "jira_issues": [], "partial": true, "error": "git_unrecoverable: <reason>"}`. The logs can now tell the two failures apart.

## Measured findings worth keeping

- **The second detector condition is inert.** More than one assistant message with text was true on all seven runs examined, passing and failing. The marker alone discriminates: 3 true positives, 0 false positives, 4 true negatives. The condition stays as documentation of intent.
- **Narrowing the detector was rejected.** The proposal was to require the marker after the last tool call. It misses the 09-18 run, where the ceiling hit while the final answer was already being emitted, and the agent then made four more tool calls and resumed the same truncated JSON. A false positive costs one night and is recoverable. A false negative costs a consumed window permanently. Re-propose only with evidence of a production false positive.
- **Detection only works when the event stream exists.** The stream is captured only when `DOCS_AGENT_DEBUG_DIR` is set. Without it, B never fires and behaviour is unchanged. A therefore carries more weight than B, because the budget applies on every host. Whether plain `--print` mode returns the concatenation or only the last turn is unverified.

## Rejected alternatives

- **Schema `maxLength`.** A schema rejects what is already emitted. Because source-collector `schema_invalid` is blind, it would turn a sometimes-failure into a deterministic one.
- **Reassembling the split answer.** Concatenation recovered 2 of the 3 failed nights. The 09-18 continuation contained 14 invalid JSON escapes and an unescaped inner quote. A join can also yield parseable but garbled text, the CCE-141 class. Deferred to its own spec.
- **Raising `maxOutputTokens`.** It moves the cliff, and 64,000 is already the maximum.
- **Emitting references instead of bodies.** The right long-term answer, tracked as CCE-183.

## Known limitations

- Jira issue count is unbounded. In the capped replay the 38 issues were 46,097 of the 80,249 characters, so a window with many more linked issues can still hit the ceiling. B covers that case.
- At the three looping call sites (pr-summarizer, page-author, gap-detector), the new reason names the agent but not the item. Ten truncated pages collapse into one digest line. This degrades triage, not safety, and a follow-up is open.

## Verification

The failure is stochastic, so one green nightly proves nothing. Watch for:

- No `prose_contamination_rescued: source-collector` line.
- `output_token_limit_truncated: source-collector` if the ceiling is crossed anyway. That is B working, not a regression.
- `body` and `description` values no longer than 1,000 characters, a cut one ending in `…[truncated]`.

Coverage lives in `tests/agents/test_source_collector_output_budget.py` and `tests/agents/test_source_collector_failure_payload.py`. Trimmed real production streams are under `tests/fixtures/cce177/`, described in `tests/fixtures/cce177/README.md`.

## Related

The raw forensic artifacts expire 14 days after each run, starting around 2026-10-02. The surviving measurements are in `docs/superpowers/specs/2026-09-23-cce177-evidence.md`, and the full design is in `docs/superpowers/specs/2026-09-23-cce177-source-collector-output-ceiling-design.md`. For how a failed source-collector surfaces in a run, see `docs/site-src/operations/step-summary-observability.md`.

Related tickets: CCE-144 (blind vs degraded), CCE-151 (consuming an undocumented window), CCE-141 (detect, never repair), CCE-183 (unbounded agent payloads).
