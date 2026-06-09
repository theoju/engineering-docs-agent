---
description: "scripts/content_validator.py checks generated doc pages against the agent specification contracts before the orchestrator commits them."
source_files:
  - scripts/orchestrator_runner.py
last_reviewed: '2026-06-09'
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/87
synthesized_into: []
---

# Content Validator

`scripts/content_validator.py` checks generated doc pages against the agent specification contracts before the orchestrator commits them. It validates that page output conforms to the output schema declared in each agent's `.md` spec file and the corresponding JSON Schema in `agents/schemas/`.

## Plugin-relative spec resolution

The validator resolves agent specification files from the plugin's own checkout directory, **not** the host repo's working directory. The plugin install location is read from the `PLUGIN_DIR` environment variable, which defaults to `~/.claude/plugins/engineering-docs-agent/`.

This matters because the plugin runs against arbitrary host repositories. A host repo does not contain the plugin's `agents/` tree — only the dogfood repo does. Resolving spec files relative to `cwd` silently skipped validation on every non-dogfood host, and raised `FileNotFoundError` when the path existed but pointed into a wrong tree. CCE-67 tracked this regression.

Set `PLUGIN_DIR` to override the default when you install the plugin to a non-standard path:

```bash
PLUGIN_DIR=/opt/plugins/engineering-docs-agent python3 scripts/orchestrator_runner.py
```

## Schema parsing

The validator parses each agent's output schema via `_parse_schema`. If a JSON Schema object node lacks a `properties` key (e.g., a bare `{"type": "object"}` schema), the parser now skips property enumeration rather than raising a `KeyError`. This handles the valid case where an object schema declares only a type constraint with no named properties.

## What gets validated

For each generated page, the validator checks:

- Required frontmatter keys are present and non-empty.
- The page `action` field (`create` or `edit`) matches what the orchestrator requested.
- Any structured fields declared in the agent spec's output schema conform to their type constraints.

Validation failures are surfaced as warnings in the orchestrator's run summary, not hard errors. A partial validation failure still allows the PR to open — the failure is flagged in the PR body's `partial_reasons` list so the operator can triage it.

## Failure modes

| Failure | Behavior |
|---|---|
| `PLUGIN_DIR` path does not exist | Logs a warning; skips spec-file validation for all agents |
| Agent `.md` spec file missing under `PLUGIN_DIR` | Skips validation for that specific agent; continues with others |
| JSON Schema `properties` key absent | Skips property-level checks; still validates top-level `type` |
| Required frontmatter key missing | Emits a `WARN` entry in the run summary; PR opens as partial |
