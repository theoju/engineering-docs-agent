---
description: "Doc routing is the mechanism that places newly authored pages in the right section of the docs site without baking section names into the code."
source_files:
  - scripts/doc_routing.py
  - scripts/archive_indexes.py
last_reviewed: '2026-06-09'
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/121
synthesized_into: []
---

# Doc Routing

Doc routing is the mechanism that places newly authored pages in the right section of the docs site without baking section names into the code. The pr-summarizer emits a `doc_kind` field on each create target; a deterministic pure module maps that field to a directory. Because the mapping uses no LLM logic, it is fully unit-testable.

## `doc_kind` values

The pr-summarizer assigns one of two values to `doc_kind` on each `doc_target`:

- `architecture` — evergreen reference content: current-state facts, system overviews, API contracts.
- `decision` — historical context: ADRs, design docs, rationale. These are write-once records of past choices.

When `doc_kind` is absent, the routing code treats the target as `architecture` and leaves the hint untouched.

## `route_create_hint` interface

`scripts/doc_routing.py:route_create_hint` is the routing entry point. Its signature:

```python
def route_create_hint(
    page_hint: str,
    doc_kind: str | None,
    archive_section: str | None,
    available_sections: list[str],
) -> str:
```

The function rewrites a `decision` target's hint to `"<archive_section>/<filename>"` when all three conditions hold:

1. `doc_kind == "decision"`
2. `archive_section` is not `None` (the host declares an archive section)
3. `archive_section` is present in `available_sections` (the directory exists on disk)

If any condition fails, the function returns `page_hint` unchanged. There are no side effects — no I/O, no agent calls. The orchestrator calls this function; it does not call back into the orchestrator.

Routing applies **only to create targets**. Edit targets are never relocated — `route_create_hint` is never called for an edit.

## Archive section discovery

The orchestrator resolves `archive_section` via `scripts/archive_indexes.py:find_archive_section` and `scripts/doc_routing.py:archive_section_leaf`.

`find_archive_section(site)` (`archive_indexes.py:208`) scans `site["sections"]` for the first entry whose `generator` field equals `"archive-index"`. It returns the whole section dict or `None`. The match is on the generator marker, never on a literal directory name — a host that names its archive directory `historical/` or `decisions/` works identically.

`archive_section_leaf(site_config)` (`doc_routing.py:21`) wraps `find_archive_section` and returns just the trailing path component (e.g., `"archive"` from `"docs/site-src/archive"`). This is the string passed to `route_create_hint` as `archive_section`.

## Bare-host degradation contract

A host with no archive-index section in its config produces `archive_section = None`. In that case, `route_create_hint` returns `page_hint` unchanged for every target, including `decision` kinds. No error is raised; no partial reason is logged.

A host that declares an archive section in config but whose archive directory does not exist yet on disk will have `archive_section` absent from `available_sections`. The same unchanged-hint path applies. The routing degrades silently in both cases — a decision page lands where the agent chose rather than in an archive section that cannot receive it.

## Section overview ordering

Directory-level `index.md` pages list child pages ordered by freshness. The sort is a two-pass stable sort in `section_overview._scan_children`:

1. Pages with a `last_reviewed` frontmatter date, newest date first.
2. Pages with no date, sorted by title as a tiebreaker.

This replaced the prior filename/title ordering. A page updated last week no longer sits behind a page with an alphabetically earlier name that has not been reviewed in months.

## Orchestrator wiring

The orchestrator threads `doc_kind` from the pr-summarizer's `doc_target` through to the page-author:

1. The pr-summarizer emits `doc_kind` on each `doc_target` in its output.
2. For create targets, the orchestrator calls `route_create_hint` to get the final path hint.
3. The orchestrator passes `doc_kind` into the page-author's `frontmatter_template` so the authored page carries the field.

The page-author writes `doc_kind` into the frontmatter but does not apply routing logic itself — routing is resolved before the page-author is called.

## Related pages

- `architecture/engineering-docs-agent-overview.md` — full pipeline stage table and system overview
- `archive/pr-summarizer-design.md` — pr-summarizer design, including the `doc_kind` field addition
