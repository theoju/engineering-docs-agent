---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/290
synthesized_into: []
doc_kind: decision
---

# CCE-187: control-character-tolerant parsing of agent output

## Decision

The orchestrator parses subagent output in tiers. It tries a strict `json.loads` first. If that fails, it retries with `strict=False`, which accepts raw control characters (a literal newline or tab) inside string values. The fallback runs only after the strict parse fails, so well-formed output never takes it.

The tier applies to every field of every agent. It is not specific to Jira or to the source-collector.

## Incident

Nightly run 36080301431 was classified blind with `source_collector_invalid: returned None`. The source-collector subagent had succeeded: return code 0, empty stderr, and about 93 KB of structurally complete stdout. The output would not parse.

The Jira description of `CCE-75` carried six raw newline bytes and one unescaped double quote. Strict JSON rejects the newlines. `strict=False` accepts them but still rejects the quote. The brace-walking rescue in `scripts/orchestrator_runner.py:_rescue_json_object` also failed, because the stray quote desynchronized its string-state tracking.

A blind classification freezes the watermark and blocks auto-merge (CCE-144). The run was blind even though the agent did its job.

The failure was stochastic. Run 36007491599 collected the same window a day earlier and parsed cleanly, because the agent picked a shorter description for the same issue. The agent contract bounds `description` to 1,000 characters, and the agent obeyed that bound. Every guard enforced *bounded*; none enforced *well-formed*. Prompt discipline cannot close that gap.

## Why accepting control characters is safe

JSON's ban on raw control characters inside strings is a wire-format rule, not a semantic one. A real newline where `\n` was meant carries the same information. The tier accepts the byte and rewrites nothing, so it cannot change content.

## What changed

- `scripts/orchestrator_runner.py:_parse_agent_payload` runs the tiers in order: strict parse, then `strict=False`, then the prose rescue. A control-character-only payload records the reason `control_chars_tolerated: <agent>`.
- The terminal parse inside `_rescue_json_object` also uses `strict=False`. Without it, a payload with both a prose preamble and a raw newline stays blind.
- The reason travels on the existing `out_reasons` channel next to `prose_contamination_rescued`. It is info-only and adds no new `add_partial` call site.

Ordering is asserted by the tests. A prose-contaminated payload still reports `prose_contamination_rescued`, not the control-character reason. A fenced payload and a clean payload record no reason at all. `out_reasons` may be `None`.

## The residual: unescaped quotes

`strict=False` does not help with an unescaped `"` inside a string value. When PR 290 landed, that fault stayed open for `prs[].body` and `prs[].title`, roughly 43% of the measured corruption surface. No cheap repair was safe, because rebalancing quotes inside string values can silently alter content. It was tracked as CCE-189.

The tiers are deliberately separate. The control-character tier is non-destructive. A quote repair is not, so a control-character-only payload must be credited to the tolerance tier and never rewritten.

CCE-189 has since added a repair tier. The two-fault fixture is now recovered with the reason `unescaped_quotes_repaired: source-collector`. If that fixture's reason ever reads `control_chars_tolerated`, the tiers have been reordered.

## Tests

`tests/orchestrator/test_dispatch_control_char_tolerance.py` pins this behavior against `tests/orchestrator/fixtures/cce187_invalid_escaping_source_collector.json`, the production payload kept byte-for-byte. The control-character-only case is derived from that fixture by escaping only the quote, so the six raw newlines are the real ones.

## Related

- Design record, including the planned move of Jira enrichment into the orchestrator: `docs/superpowers/specs/2026-09-24-cce187-design.md`.
- Raw measurement: `docs/superpowers/specs/2026-09-24-cce187-evidence.md`.
