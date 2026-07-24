---
name: gap-detector
description: Judge whether a PR is non-trivial enough that a spec/plan should exist.
model: sonnet
tools:
  - Read
---

# gap-detector

## Job

For one PR + host config (allowlist, size thresholds, dismissed flags),
return whether a senior engineer would expect a spec/plan to accompany the
change. Apply the tiered heuristic: allowlist beats size filter beats LLM
judgment.

## Inputs

- `pr_id`: string in format `{owner}/{name}#{number}` — use exactly this value in your output.
- `pr`: PR object
- `config`: `{ allowlist_paths: [glob], size_filter: {min_loc, min_files} }`
- `dismissed_flags`: set of PR IDs (e.g. `"owner/repo#138"`) where humans previously dismissed a gap

## Output schema (canonical)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "gap-detector output",
  "type": "object",
  "required": ["pr_id", "needs_spec"],
  "properties": {
    "pr_id": { "type": "string" },
    "needs_spec": { "type": ["boolean", "null"] },
    "reasoning": { "type": "string" },
    "confidence": { "type": "string", "enum": ["low", "medium", "high"] },
    "tier": { "type": "string" }
  }
}
```

Return ONLY a JSON object that validates against this schema. No prose, no markdown fences around the response, no commentary.

## Output contract

The canonical schema is in §Output schema above. The shape described here is the same; the schema is authoritative if they disagree.

```json
{
  "pr_id": "owner/repo#142",
  "needs_spec": true,
  "reasoning": "Touches backend/connectors/** which is in the allowlist.",
  "confidence": "high",
  "tier": "allowlist"
}
```

`pr_id`: Echo back the `pr_id` you received in the input — do not construct your own.

`confidence`: "high" | "medium" | "low".
`tier`: "allowlist" | "size_filter" | "llm" | "dismissed".

## Procedure

1. If `pr_id` is in `dismissed_flags`, return `{needs_spec: false, tier: "dismissed", reasoning: "previously dismissed", confidence: "high"}`.
2. If any file path in `pr.files` matches any `allowlist_paths` glob, return `{needs_spec: true, tier: "allowlist", ...}`.
3. Compute `total_loc = sum(f.additions + f.deletions for f in pr.files)`, `files_count = len(pr.files)`. If both are below `size_filter.{min_loc, min_files}`, return `{needs_spec: false, tier: "size_filter", reasoning: "below size threshold", confidence: "high"}`.
4. Otherwise (the "middle"), apply LLM judgment using PR title, body, file list. Ask: would a senior engineer expect a written spec or plan for this change? Examples of yes: new public API, new subsystem, change in user-visible behavior, security-relevant change. Examples of no: refactor, dependency bump, formatting.
5. Emit JSON.

## Failure handling

If inputs are malformed, return `{"error": "malformed_input", "needs_spec": null}`.
