---
description: "This page documents the authoritative output shapes for the three agents at the core of the nightly docs pipeline: source-collector, pr-summarizer, and page-author."
source_files:
  - scripts/contracts.py
  - scripts/state_io.py
last_reviewed: '2026-06-09'
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/80
synthesized_into: []
---

# Agent Contracts

This page documents the authoritative output shapes for the three agents at the core of the nightly docs pipeline: **source-collector**, **pr-summarizer**, and **page-author**. Read it before modifying any agent's prompt or schema — several fields were deliberately removed after a scope creep audit (CCE-34, PR #80), and this page records why.

The canonical schema for each agent lives in its `.md` file under `agents/`. The dataclass view is in `scripts/contracts.py`. If those three sources disagree, the `.md` schema wins.

---

## source-collector

The source-collector fetches merged PRs and linked Jira issues for a given SHA window. Its output feeds every downstream agent.

### Required output shape

```json
{
  "prs": [
    {
      "number": 142,
      "url": "https://github.com/owner/repo/pull/142",
      "title": "...",
      "body": "...",
      "merge_sha": "abc123",
      "merged_at": "2026-06-01T10:00:00Z",
      "author": "octocat",
      "files": ["scripts/foo.py", "docs/bar.md"],
      "labels": [],
      "jira_keys": ["CCE-34"]
    }
  ],
  "jira_issues": [],
  "error": null,
  "partial": false
}
```

The `files` array contains **paths only** — no line counts, no diff hunks, no per-file stats. Truncate to 200 entries if the PR touches more files than that.

### Removed field: `diff_stats`

`diff_stats` (lines added/deleted per file) was removed in PR #80. It added ~200 tokens per PR to the payload with zero downstream benefit — the orchestrator and all downstream agents ignored it. Do not add it back.

If you need diff-level analysis for a specific capability, fetch it lazily inside that capability rather than including it in the collector's universal output.

---

## pr-summarizer

The pr-summarizer takes one PR object from source-collector plus optional Jira context and produces a structured summary for the page-author.

### Required output shape

```json
{
  "pr_number": 142,
  "what_changed": "one-paragraph plain-English summary",
  "why": "rationale, drawn from PR body and Jira if available",
  "breaking": false,
  "doc_targets": [
    {
      "lens": "core",
      "action": "edit",
      "page_hint": "architecture/orchestrator.md"
    }
  ],
  "notes": null,
  "error": null,
  "partial": false
}
```

### `files_touched` → paths-only, capped at 50

Before PR #80, the `files_touched` field description was loose enough that the agent occasionally ingested entire file contents when summarizing large PRs. The field is now explicitly paths-only, and the agent prompt enforces `max_files: 50`.

If you see a pr-summarizer output whose `doc_targets` look obviously wrong — sections that don't match the PR — check whether the agent read more than 50 file paths. The cap exists to prevent full-content ingestion from drowning the actual PR title and body.

The `files` array from source-collector is the input; the summarizer does not emit a `files_touched` field of its own.

---

## page-author

The page-author writes or edits a single docs page given a list of pr-summarizer summaries and voice samples.

### Required output shape

```json
{
  "path": "docs/site-src/core/connectors.md",
  "action": "edit",
  "diff_summary": "Added 2 paragraphs on the new connector; updated frontmatter sources list.",
  "ok": true,
  "error": null
}
```

### Removed field: `cross_references`

An early version of the page-author output template included a `cross_references` section meant to link related pages. It was removed in PR #80 because:

- The orchestrator never read it.
- The linter had no rule for it.
- State-advancement logic (`scripts/state_io.py`) ignored it.

It was aspirational scaffolding with no wiring. Do not add it back unless you also wire it into at least one consumer (linter rule, orchestrator index step, or state-advancement check).

---

## What NOT to add

The table below summarizes the fields removed in CCE-34. Adding any of these back without first adding a downstream consumer is a contract violation.

| Agent | Field | Reason removed |
|---|---|---|
| source-collector | `diff_stats` | ~200 tokens/PR, zero consumers |
| pr-summarizer | (unrestricted `files_touched`) | Caused full-content ingestion on large PRs |
| page-author | `cross_references` | Never read by orchestrator, linter, or state logic |

If you are auditing a new field for inclusion, apply the same test: does at least one downstream component read this field and act on its value? If not, leave it out.
