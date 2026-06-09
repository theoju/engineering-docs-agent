---
description: "The pr-summarizer agent is the first subagent the orchestrator dispatches each nightly run."
source_files:
  - agents/pr-summarizer.md
  - scripts/orchestrator_runner.py
last_reviewed: '2026-06-09'
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/89
synthesized_into: []
---

# PR Summarizer Agent

The `pr-summarizer` agent is the first subagent the orchestrator dispatches each nightly run. It receives one merged PR at a time and produces a structured JSON summary that downstream agents — `page-author`, gap-detector, and the what's-new writer — consume.

## What it does

The agent reads a PR's title, body, and files-changed list, optionally cross-references linked Jira issues, and emits:

- `what_changed`: one plain-English paragraph describing the behavior change.
- `why`: the motivation, drawn from the PR body and Jira when available.
- `breaking`: `true` if the PR title contains `BREAKING`, uses a `!:` conventional-commit suffix, or carries a `breaking-change` label.
- `doc_targets`: one entry per documentation page that should be created or updated as a result of this PR.

It returns raw JSON to stdout. The orchestrator parses stdout with `json.loads`; any prose or markdown fencing in the output breaks the run.

## Contract

The agent spec lives at `agents/pr-summarizer.md`. The authoritative JSON schema is at `agents/schemas/pr-summarizer-output.json`. The schema is the source of truth if they disagree.

The canonical output field names are `doc_path` and `operation` — not `target_path` and `action`. PR #89 (CCE-65) resolved a divergence where the spec used `target_path`/`action` while the schema used `doc_path`/`operation`. Both files are now unified on `doc_path` + `operation`. If your consumer was coded against the old names, update it.

Each `doc_targets` entry carries:

| Field | Type | Notes |
|---|---|---|
| `lens` | string | Must be one of the host's configured lens names. |
| `action` | `"create"` \| `"edit"` | Whether the page already exists. |
| `page_hint` | string | Lens-relative path, ends in `.md`, no leading slash, no lens-path prefix. |
| `doc_kind` | `"architecture"` \| `"decision"` | Optional. Defaults to `architecture` if omitted. |

`page_hint` is a documentation path, never a source-tree path. A PR that touches `scripts/orchestrator_runner.py` produces a hint like `architecture/orchestrator.md`, not `scripts/orchestrator_runner.py`.

## Forbidden outputs

The schema enforces several hard constraints on `page_hint`:

- Must end in `.md`.
- Must not start with a leading slash.
- Must not end in a source extension (`.py`, `.json`, `.yml`, `.ts`, etc.).

Beyond schema validation, the orchestrator's editable-path guard will silently drop any target outside `agent_editable_paths`. Emitting `_agent-sandbox/` or `api/reference/` targets is also forbidden — the former is no longer an editable path, and the latter is auto-generated at build time.

## Inputs

The orchestrator passes:

- `pr`: the full PR object from the source-collector.
- `jira_context`: list of linked Jira issue objects (may be empty).
- `lens_names`: the host's configured lens names.
- `available_sections`: a dict mapping each lens name to the list of top-level section directories currently under that lens root. The agent uses this to pick a `page_hint` that lands in an existing section rather than inventing a new one.

## Failure handling

When the PR body is empty, Jira context is absent, and the files-changed list is empty, the agent emits:

```json
{"pr_number": 123, "error": "insufficient_context", "what_changed": null}
```

Partial summaries — where some fields are populated but others are not — set `"partial": true` in the output. The orchestrator logs partials and continues; a partial summary still drives `doc_targets` routing.
