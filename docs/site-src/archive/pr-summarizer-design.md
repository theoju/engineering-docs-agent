---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/121
synthesized_into: []
doc_kind: decision
---

# PR Summarizer — Design Decisions

This page records the design rationale behind the `pr-summarizer` subagent (`agents/pr-summarizer.md`). It is an archive document: it explains *why* the agent is shaped the way it is, not *what it currently does*. For the current interface, see the agent definition directly.

## Role in the pipeline

The pr-summarizer sits between source collection and page authoring. It receives a single merged PR object plus linked Jira issues and produces a structured summary: `what_changed`, `why`, `breaking`, and a `doc_targets` list. The orchestrator feeds each target to the page-author subagent; the orchestrator never interprets the semantic content of the PR itself.

Keeping summarization as a discrete agent means the orchestrator stays routing-agnostic. The agent makes the language judgment; the orchestrator and downstream pure scripts act on the structured output.

## `doc_kind` field — decision rationale (CCE-107)

Before CCE-107, all `create` targets landed wherever the agent placed them — typically under `architecture/`. Decision-type pages (ADRs, design docs, postmortems) accumulated alongside evergreen reference pages, making intent ambiguous for readers and for the docs agent on subsequent runs.

CCE-107 added an optional `doc_kind` enum field to each `doc_target`:

- `architecture` — evergreen "how it works today" reference. Should stay current as the system evolves.
- `decision` — historical context captured at a point in time: why we chose X, postmortems, ADRs. Does not need updating as the system changes.

The field is optional. The agent emits it only when the PR's content makes the classification clear. The orchestrator treats a missing value as `architecture`.

## Hybrid routing: agent judgment + pure code

The original alternative was to let the agent pick the full target path — including the archive subdirectory name. That approach has two failure modes: the agent can hallucinate a path that doesn't exist, and routing decisions become non-reproducible (LLM non-determinism in page placement).

The chosen design splits the responsibility:

1. The agent emits a semantic judgment (`doc_kind`), not a filesystem decision.
2. A pure function — `scripts/doc_routing.py:route_create_hint` — maps that judgment to the correct section deterministically.

`route_create_hint` discovers the archive section via a generator marker (`<!-- docs-agent:archive-index -->`) embedded in the section's index page. It never uses a hardcoded directory name. On a bare host with no marker, it returns the hint unchanged — graceful degradation, no error.

This split makes routing unit-testable without mocking an LLM. The test surface is `scripts/doc_routing.py`; the agent's semantic call is validated by the JSON schema, not by path heuristics.

## Edit targets are never relocated

Routing applies only to `create` targets. If the agent emits `action: edit` for a page that already lives in `architecture/`, the orchestrator writes the edit in place. Moving an existing page would break existing links and `mkdocs build --strict` would reject stale references.

## One-time migration (CCE-107)

When CCE-107 landed, five decision pages had already been created under `architecture/`. They were moved to `archive/` as part of the same PR:

- `host-onboarding-guide.md`
- `pr-body-enrichment-design.md`
- `source-collector-design.md`
- `voice-and-style-design.md`
- `pr-summarizer-design.md` (this page)

All 20 existing origin pages were stamped with `doc_kind` in their frontmatter at the same time, giving the agent a consistent signal for future edit targets.

## Deferred work

`archive_indexes._find_archive_section` is currently private. Promoting it to a public API was noted as a minor follow-up in the CCE-107 PR notes. Until that happens, `doc_routing.py` calls through the public `archive_indexes.find_archive_section` wrapper rather than the private function directly.

## Related

- `agents/pr-summarizer.md` — current agent definition and output schema
- `scripts/doc_routing.py` — `route_create_hint` implementation
- `architecture/doc-routing.md` — evergreen reference for the routing interface and marker-discovery mechanism
- `architecture/engineering-docs-agent-overview.md` — pipeline stage overview including doc routing
