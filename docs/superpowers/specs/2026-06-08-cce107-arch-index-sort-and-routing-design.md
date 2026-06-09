# CCE-107 — Architecture index semantic sort + architecture-vs-archive routing

**Date:** 2026-06-08
**Ticket:** CCE-107 (follows CCE-106 section overviews, CCE-104 archive wiring, CCE-34 semantic routing)
**Status:** approved design

## Problem

CCE-106 gave every section a generated "In this section" overview, but two gaps remain on the architecture section specifically:

1. **Ordering is filename-lexicographic, not semantic.** `section_overview._scan_children` sorts children by `sorted(section_dir.glob("*.md"))` (`section_overview.py:54`). The architecture landing therefore lists 20 pages in an order that reads as noise — `CCE-10 < CCE-12 < CCE-23` by string luck, but `CCE-5` sorts _after_ `CCE-23` because the comparison is alphabetical-by-filename, not numeric or chronological.

2. **`architecture/` conflates two kinds of page.** It holds evergreen "how the system works" reference docs (schema enforcement, lint rules, data flows) _and_ point-in-time decision/investigation retellings that read like ADRs (`cce14-source-collector-prompt-hardening`, `cce15-source-collector-root-cause-sweep`). Meanwhile `archive/` already auto-indexes the raw spec/plan source artifacts (`archive/specs.md`, `archive/plans.md`). The `pr-summarizer` routing rule _already_ says "design decisions/ADRs → `archive/`" but has been authoring these retellings into `architecture/` anyway.

CLAUDE.md flags the routing change as one that "affects all future nightly runs" — the going-forward rule (§B1) is the sensitive part; the file moves (§B2) are mechanically low-risk.

## Decisions (locked during brainstorming)

| Question          | Decision                                                                                                                      |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Sort intent       | **Freshness** — reverse-chron by `last_reviewed:`, deterministic fallback, no-date sinks last                                 |
| Routing policy    | **Provenance split + migrate** existing mis-routed pages                                                                      |
| Routing mechanism | **Hybrid** — agent emits `doc_kind`; deterministic code maps `doc_kind → section`; same signal classifies pages for migration |

## Architecture

Two deliverables, sequenced so the low-risk one lands first.

### Deliverable A — semantic sort for directory-section overviews

Generic-first: this is the **default ordering for every directory-section overview** (architecture, operations, and any host's sections), not an architecture special-case.

- `_scan_children` (`scripts/section_overview.py:48-65`) is extended to parse each child's frontmatter (reusing `archive_indexes.parse_frontmatter`) alongside title/summary, compute a freshness key, sort, and return `(title, summary)` in sorted order. The public return shape is unchanged, so `render_directory_overview` and all callers are untouched.
- **Pure helper** `_freshness_key(frontmatter: dict, filename: str) -> str`:
  - returns `str(frontmatter["last_reviewed"])` when present and truthy — `str()` is mandatory: an unquoted `last_reviewed: 2026-05-28` parses to a `datetime.date`, and comparing that against the `""` fallback during sort would raise `TypeError`; `str(date(2026,5,28))` is still ISO `"2026-05-28"` and sorts chronologically;
  - else the `YYYY-MM-DD` captured by `archive_indexes.DATE_PREFIX` on the filename;
  - else `""` (no date known).
- **Ordering** — date descending (newest first), pages with no date last, title ascending as the stable tiebreak. Implemented as two stable passes:

  ```python
  children.sort(key=lambda c: c.title.lower())          # tiebreak, ascending
  children.sort(key=lambda c: c.freshness, reverse=True)  # newest first; "" sinks last
  ```

  Python's sort is stable, so the title order is preserved within equal freshness; `""` is the smallest string, so under `reverse=True` undated pages fall to the bottom.

### Deliverable B — `doc_kind` routing + migration

New unit **`scripts/doc_routing.py`** — pure functions, the deterministic seam the hybrid choice requires.

#### B1 — going-forward routing

- **Agent side.** `doc_targets[]` entries gain an optional `doc_kind` enum `"architecture" | "decision"`.
  - `agents/schemas/pr_summarizer.schema.json` — add `"doc_kind": { "type": "string", "enum": ["architecture", "decision"] }` to the `doc_targets` item properties (the object is `additionalProperties: false`, so the field must be declared; it stays out of `required` for backward compatibility).
  - `agents/pr-summarizer.md` step 6 documents the field: _an investigation, postmortem, ADR, roadmap, or release note is a `decision`; an evergreen "how it works today" reference is `architecture`. Omit when unsure (treated as `architecture`)._
  - The agent keeps choosing `page_hint` exactly as today.
- **Code side.** `doc_routing.route_create_hint(page_hint, doc_kind, archive_section, available_sections) -> str`:
  - if `doc_kind == "decision"` **and** `archive_section` is truthy **and** `archive_section in available_sections`: return `f"{archive_section}/{page_hint.rsplit('/', 1)[-1]}"` (rewrite the leading dir to the archive section, keep the filename);
  - else return `page_hint` unchanged.
  - `archive_section` is the leaf name of the section whose `generator == "archive-index"`, discovered via the existing `archive_indexes._find_archive_section(site_config)` — **no hardcoded `"archive"` string**, so it works on any host.
- **Wiring.** `orchestrator_runner.py` (the routing loop around `:1175-1187`) computes `archive_section` once from `config["site"]`, then applies `route_create_hint` to each target's `page_hint` before building `target_path`. Scoped to `action: create` only — edits keep their existing path (relocating an existing page is the migration's job, B2). `page-author` persists the resolved `doc_kind` into the page frontmatter so pages become self-describing for future re-classification.

#### B2 — one-time migration

Mechanically low-risk: no architecture page cross-links another (verified by grep), and the only inbound link is `index.md → architecture/index.md` (the _section_, not any page). Both `architecture/` and `archive/` are directory sections whose nav entries auto-pull directory contents, so no nav edits are needed.

Steps, per page classified `decision`:

1. `git mv docs/site-src/architecture/<page>.md docs/site-src/archive/<page>.md`.
2. Stamp `doc_kind:` frontmatter on **all** 20 architecture-origin pages (decision pages get `decision`, the rest `architecture`) so the going-forward signal is consistent and the pages are self-describing.
3. Regenerate both section overviews (`generate_overviews`) — the moved pages drop out of `architecture/index.md`'s managed block and appear in `archive/index.md`'s.
4. `mkdocs build --strict` as the real-consumer gate (the published-artifact verification mandated by CLAUDE.md — not `test -f`).

The migration is idempotent: re-stamping `doc_kind` and re-moving already-moved pages is a no-op.

#### Proposed page classification

5 move to `archive/`, 15 stay in `architecture/`:

| Page                                                                      | doc_kind                       | Confidence |
| ------------------------------------------------------------------------- | ------------------------------ | ---------- |
| `cce14-source-collector-prompt-hardening`                                 | decision (investigation)       | high       |
| `cce15-source-collector-root-cause-sweep`                                 | decision (postmortem)          | high       |
| `cce5-9-batch-prep-roadmap`                                               | decision (roadmap/history)     | high       |
| `v0-1-1-hardening`                                                        | decision (release notes)       | high       |
| `2026-05-29-orchestrator-fence-strip`                                     | decision (dated PR#75 note)    | medium     |
| `cce12-source-collector-tool-use-diagnostics`                             | architecture (live capability) | medium     |
| `cce6-7-8-batch`                                                          | architecture (dispatch spine)  | medium     |
| `bootstrap-fail-fast`                                                     | architecture (live safeguards) | medium     |
| capability C / C2 / C3                                                    | architecture                   | high       |
| `cce10-source-collector-canonical-shape`                                  | architecture                   | high       |
| `cce23-api-reference`, `cce23-decision-archive`, `cce23-source-map-drift` | architecture                   | high       |
| `cce4-schema-enforcement`                                                 | architecture                   | high       |
| `cce32-github-pages-publish-target`                                       | architecture                   | high       |
| `lint-rules`, `structured-docs-site-generation`, `engineering-docs-agent` | architecture                   | high       |

## Data flow

```
nightly: source-collector → pr-summarizer (emits doc_targets[].doc_kind)
   → orchestrator: route_create_hint(page_hint, doc_kind, archive_section, available_sections)
   → page-author writes page (+ doc_kind frontmatter) at the resolved target
   → generate_overviews rebuilds each section's "In this section" block,
        ordered by _freshness_key (last_reviewed desc, undated last)
```

## Error handling & graceful degradation

- Missing `last_reviewed` **and** no filename date-prefix → page sorts last; never raises (`parse_frontmatter` already degrades malformed YAML to `{}`).
- `doc_kind` absent (legacy agent output, or a bare host whose agent doesn't emit it) → treated as `architecture`; `route_create_hint` returns the hint unchanged. Backward-compatible.
- No `archive-index` section configured on a host → `archive_section` is `None`; decision-kind pages keep the agent's hint. Generic-first: nothing hard-requires the archive convention.
- Migration is idempotent (re-runnable without duplication).

## Testing

TDD throughout; production dispatch monkeypatched in unit tests (per repo convention).

- **`tests/site/test_doc_routing.py`** (new) — `decision` → archive rewrite; `architecture`/unknown/absent → unchanged; no archive section → unchanged; non-default archive section name honored (generic); filename preserved across rewrite.
- **`tests/site/test_section_overview.py`** (extend) — freshness order: `last_reviewed` descending; filename date-prefix fallback; undated page sinks last; title ascending tiebreak among equal dates; malformed frontmatter degrades (skipped, not raised).
- **`tests/schemas/`** + existing `test_schema_md_sync` — `doc_kind` enum accepted/rejected; agent `.md` ↔ schema stay in sync.
- **Orchestrator dry-run** (monkeypatched dispatch) — a `doc_targets` entry with `doc_kind: "decision"` resolves its `target_path` under the archive section.
- **Real consumer** — `mkdocs build --strict` exits 0 on the post-migration tree and after overview regeneration.

## Acceptance criteria

1. Architecture (and every directory-section) overview lists children newest-`last_reviewed`-first, undated last, title-tiebroken — verified by unit test and visible on the regenerated dogfood site.
2. `doc_routing.route_create_hint` is a pure, unit-tested function; `doc_kind == "decision"` routes to the archive-index section by generator marker (no hardcoded name).
3. `pr_summarizer.schema.json` accepts the optional `doc_kind` enum and the agent `.md` documents it; schema-sync test passes.
4. The orchestrator routes a `decision`-kind create target to the archive section in a dry-run test.
5. The 5 classified decision pages are moved to `archive/`; all 20 origin pages carry a `doc_kind:` frontmatter; both section overviews regenerate correctly.
6. `mkdocs build --strict` is green after the migration and after overview regeneration.
7. Bare-host degradation holds: absent `doc_kind`, absent `last_reviewed`, and absent archive section each fall back cleanly with no error and no empty artifact.

## Out of scope (YAGNI)

- Config-driven `doc_kind → section` mapping beyond the single decision→archive override (the fixed mapping + generator-marker discovery suffices).
- Topic/category sub-grouping within `architecture/` (was an alternative; not chosen).
- Re-routing on `action: edit` (only `create` is routed; existing-page relocation is the one-time migration).
- Status-grouped ordering (all pages are currently `draft`; collapses to plain freshness).
