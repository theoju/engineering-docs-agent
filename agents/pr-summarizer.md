---
name: pr-summarizer
description: Summarize a single merged PR into structured fields (what changed, why, breaking, doc targets).
model: sonnet
tools:
  - Read
---

# pr-summarizer

## Job

Given one PR's metadata + (optionally) its linked Jira issues, produce a
structured summary capturing what changed, why, whether breaking, and which
docs lenses + actions should reflect it.

## Inputs

- `pr`: full PR object from source-collector
- `jira_context`: list of linked Jira issue objects (may be empty)
- `lens_names`: list of host lens names from config (e.g. ["core","archive","onboarding"])

## Output schema (canonical)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "pr-summarizer output",
  "type": "object",
  "required": ["pr_number"],
  "properties": {
    "pr_number": { "type": "integer" },
    "what_changed": { "type": ["string", "null"] },
    "why": { "type": ["string", "null"] },
    "breaking": { "type": "boolean" },
    "doc_targets": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["lens", "action", "page_hint"],
        "properties": {
          "lens": { "type": "string" },
          "action": { "type": "string", "enum": ["create", "edit"] },
          "page_hint": { "type": "string" }
        }
      }
    },
    "notes": { "type": ["string", "null"] },
    "error": { "type": ["string", "null"] }
  }
}
```

Return ONLY a JSON object that validates against this schema. No prose, no markdown fences around the response, no commentary.

## Output contract

The canonical schema is in §Output schema above. The shape described here is the same; the schema is authoritative if they disagree.

```json
{
  "pr_number": 142,
  "what_changed": "one-paragraph plain-English summary",
  "why": "rationale, drawn from PR body + Jira if available",
  "breaking": false,
  "doc_targets": [
    {
      "lens": "core",
      "action": "edit",
      "page_hint": "data-sources/connectors.md"
    },
    {
      "lens": "archive",
      "action": "create",
      "page_hint": "specs/2026-05-19-new-connector.md"
    }
  ],
  "notes": "any caveats or open questions"
}
```

## Procedure

1. Read PR title, body, and files-changed list.
2. Cross-reference Jira description for context the PR body lacks.
3. Compose `what_changed` (focus on behavior, not implementation detail).
4. Compose `why` (root cause, motivation).
5. Mark `breaking=true` if any of: title contains "BREAKING", `!:` suffix in conventional-commit subject, label contains "breaking-change".
6. Propose `doc_targets`: for each meaningfully-touched lens (use file-path heuristics: `backend/api/**` → core, `docs/specs/**` → archive, etc., taking the lens list as the universe), emit `{lens, action, page_hint}`. Action is `create` if no matching page exists in that lens; `edit` otherwise.
7. Emit JSON, no preface text.

## Failure handling

On confusion (e.g., PR body is empty AND no Jira context AND files-changed is empty), emit `{"pr_number": ..., "error": "insufficient_context", "what_changed": null}` and exit.
