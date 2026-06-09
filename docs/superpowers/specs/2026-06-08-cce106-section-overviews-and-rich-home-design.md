---
title: "CCE-106 — Generated section overviews + rich home + repo_url"
status: draft
ticket: CCE-106
date: 2026-06-08
supersedes_gap: "bland home + empty section landings + no GitHub widget (holistic review 2026-06-08)"
---

# CCE-106 — Section overviews, rich home, repo_url

Phase 2b of the docs-site remediation roadmap. The 2026-06-08 holistic review
flagged that every section landing is a static `status: draft` stub —
**Architecture, API, Operations, and Decision Archive all render an empty
one-line placeholder** — the home page is a bare grid of cards with no real
content, and there is no "Edit this page" / GitHub link. This spec makes the
landing pages and home **self-populate, deterministically, clobber-safely**.

Depends on CCE-104 (the `site:` wiring + `run_site_generators` stage) and reads
CCE-105's `groups` for the API overview. CCE-105 lands first.

## The core constraint: a tested "never touch index.md" contract

Today the clobber-prevention contract is **filename-convention based**:
generators write _siblings_ (`archive/specs.md`, `api/contracts/foo.md`) and
**never** the section `index.md`, which is human/S-owned. This is locked in by
`tests/site/test_archive_generate.py` —
`test_generate_overwrites_stale_but_leaves_section_index` asserts the landing
stub is preserved byte-for-byte.

CCE-106 needs to put generated content _into_ those `index.md` landings. That
reverses the contract — so it must be reversed **surgically**: a generator owns
only a delimited block, and any human prose outside the block survives every
regeneration. The tested invariant is updated to assert exactly that.

## Deliverables

### 6a — Managed-region helper (the clobber-safe primitive)

A new pure helper module `scripts/managed_block.py`:

```python
MARKER = "docs-agent:overview"
START = f"<!-- {MARKER}:start -->"
END   = f"<!-- {MARKER}:end -->"

def upsert_managed_block(existing_text: str, block_body: str) -> str:
    """Return text with the START..END region's body replaced by block_body.
    If no region exists, append one (preceded by a blank line). Text outside
    the markers is preserved byte-for-byte. Pure: no I/O."""
```

Rules:

- Exactly one region per file; a second START before the first END is a
  malformed file ⇒ raise (caller records `info_only` partial, never crashes the
  run).
- Append path: if the file lacks a region, add `\n{START}\n{block_body}\n{END}\n`
  at end-of-file, preserving the author's existing content above.
- Idempotent: same `block_body` ⇒ identical output (the change-detection the
  caller uses to skip no-op writes).

This is the single point where the "never touch index.md" rule is reversed —
for the delimited block only.

### 6b — Schema: per-section `overview` opt-out

Add `"overview": { "type": "boolean", "default": true }` to
`site.sections[].properties` (`templates/config.schema.json`, which is
`additionalProperties: false`, so this is required). `overview: false` lets a
fully hand-authored landing disable the generated block. No new cross-field
validation needed beyond the schema default.

### 6c — The overview generator

A new deterministic generator `scripts/section_overview.py`:

```python
def generate_overviews(repo_root: Path, site_config: dict) -> dict:
    """For each section with overview != false, upsert a managed block into the
    section's index.md (or the section page for single-page sections). Returns
    {"written": [...], "skipped": [...]}. Best-effort per section."""
```

Block content is built per section _type_:

- **Directory sections (architecture, operations, archive):** scan the
  section's on-disk child `*.md` (exclude `index.md` and `_*`), read each
  child's `title` + first-line summary via
  `archive_indexes.parse_title_and_summary` + `_strip_inline_links`
  (`scripts/archive_indexes.py:97,41`), and render an "In this section" list:
  `- **<title>** — <summary>` plus a count footer (`_N pages · regenerated nightly_`).
- **API section (`generator: api-extract`):** the rendered mkdocstrings pages
  live only in the mkdocs build VFS, but the **source modules are on disk** at
  run time. So the API overview lists the **CCE-105 `groups`** by name with each
  group's real module count — computed by scanning the api section's source
  modules (the same `rglob` `gen_ref_pages` uses) and applying CCE-105's
  `assign_group` — plus links to the on-disk `contracts/` pages. It does not
  disk-scan `api/reference/` (build-time only). When CCE-105 has not landed (no
  `groups`), it degrades to a count of total modules + the contracts links.
- **Archive section:** after `generate_archive` runs, the on-disk category
  pages (`specs.md`, `plans.md`, …) ARE present, so the generic directory scan
  works; the footer reports per-category entry counts when cheaply available.

Empty section (no children) ⇒ a single-line "No pages yet." block, never an
error and never an empty file (degrade-gracefully).

### 6d — Reverse the clobber contract (update the test first)

Per TDD, **change `test_generate_overwrites_stale_but_leaves_section_index`
first** so it asserts the new behavior: author prose _outside_ the markers is
preserved; the block _inside_ the markers is replaced. Rename to
`test_overview_replaces_block_preserves_author_prose`. Then implement 6a/6c to
make it pass. The archive/contracts generators continue to never write
`index.md` directly — only `section_overview` owns the managed block, keeping
ownership single-writer.

### 6e — Rich home

The root `index.md` gets the same managed-block treatment. `render_home`
(`scripts/site_structure.py:62`) is updated to emit an author-intro zone **plus
empty start/end markers**; `section_overview.generate_overviews` fills the home
block with a section directory (each non-home section: title + its overview
count, linking to the section landing). The grid-cards layout is preserved
inside the managed block. Existing scaffolded homes (no markers) get a block
appended via the helper's append path — no clobber.

### 6f — repo_url / edit_uri widget

`render_mkdocs_yaml` (`scripts/site_structure.py:224`) gains optional
`repo_url` / `edit_uri`, derived from the git origin (reuse the owner/repo
discovery already in `setup_discover`/`archive_indexes.resolve_repo_url_base`).
When no origin is resolvable, both are omitted — the Material "Edit this page"
and repo links simply don't render (degrade-gracefully, no error).

### 6g — Wiring

`section_overview.generate_overviews` is added to
`orchestrator_runner.run_site_generators` (`scripts/orchestrator_runner.py:966`)
**after** `generate_archive` and `generate_contracts` (so their generated pages
are on disk to list), best-effort with an `info_only` partial on exception
(matching the existing archive/contracts stages). It is **also** run at setup
scaffold time (after `apply_scaffold`) so a freshly-scaffolded site is populated
before the first nightly. Generated pages are committed by the run's existing
`git add -A`.

### 6i — Root literate-nav SUMMARY: surface the reference subtree in the nav

**Added after the CCE-105 review surfaced a pre-existing gap** (verified
2026-06-08): the API reference subtree never renders in the site nav — flat or
grouped. `gen_ref_pages.py` writes `api/reference/SUMMARY.md`, but the site's
`awesome-pages` nav driver cannot expand a subdirectory `SUMMARY.md`, so all 39
reference pages are orphans (reachable only by search/URL) and CCE-105's
grouping is invisible. Confirmed against the literate-nav docs + a spike:
literate-nav only expands a subdirectory `SUMMARY.md` when reached via an
explicit `nav:` **or a root `SUMMARY.md` cross-link** — not via `awesome-pages`.

**Decision (operator, 2026-06-08): make a generated root `SUMMARY.md` the single
nav driver, replacing `awesome-pages`.** `site_structure` generates
`<docs_dir>/SUMMARY.md` from the `site.sections` config, in config order:

- single-page sections → `* [Title](path.md)` (home, what's-new);
- directory sections → `* [Title](dir/index.md)` for the landing, with the
  reference cross-linked so literate-nav expands the **grouped**
  `api/reference/SUMMARY.md` under the API section, and `api/contracts/` listed.

Changes:

- `plan_scaffold` stops emitting `awesome-pages` `.pages` files and instead emits
  the root `SUMMARY.md` (idempotent: never clobber an authored SUMMARY).
- `render_mkdocs_yaml` drops the `awesome-pages` plugin; `literate-nav`
  (`nav_file: SUMMARY.md`) is the nav driver; `navigation.indexes` (already on)
  carries the section-index landings.
- Degrade-gracefully: a host with no api-extract section still gets a valid root
  SUMMARY of its sections; an empty section is simply a landing link.

**This is integration work with finicky plugin interaction — it is implemented
TDD-first against the real consumer:** a `mkdocs build --strict` test asserts the
grouped reference modules (e.g. a "Generators" group with `archive_indexes`)
appear in the rendered nav. The exact literate-nav cross-link syntax is settled
by making that test green, not by guesswork. Reuses the CCE-105 fixture
(`tests/fixtures/api/host`) extended with a second module so a named group + the
"Other" bucket are both rendered.

#### Revised mechanism (empirical, 2026-06-08) — generated mkdocs.yml `nav:`, not a root `SUMMARY.md`

A controller spike against the real consumer (`mkdocs build --strict`,
literate-nav 0.6.3 / mkdocs 1.6.1) established that a **root `SUMMARY.md`
markdown directory-link cannot expand the API reference subtree**: literate-nav
resolves a markdown SUMMARY's `[…](api/reference/)` link against the on-disk
`docs_dir`, but the reference pages exist only in the `mkdocs-gen-files` build
VFS — so the link is left unresolved ("unrecognized relative link") and the
grouped modules never reach the nav. The **same directory cross-link placed in
mkdocs.yml's `nav:` does expand** (it resolves against the Files collection,
which includes the VFS), surfacing the grouped reference, the contracts, and the
landing — `--strict` green.

The implementation therefore takes this spec's **named fallback** ("an explicit
`nav:` for the reference subtree"), generalized to all sections and **generated
from config** (so nothing is hand-maintained — the original intent holds):
`render_mkdocs_yaml` emits a `nav:` block from `site.sections` in config order —
`- <Title>: <dir>/` for directory sections (literate-nav recurses the directory,
auto-including child pages and the nested grouped reference `SUMMARY.md`) and
`- <Title>: <page>.md` for single-page sections. `literate-nav` stays the nav
engine (CCE-106 6i part 1); `plan_scaffold` stops emitting `awesome-pages`
`.pages` and emits **no** root `SUMMARY.md`. A single `- API reference: api/`
entry was verified to pull the grouped reference (`Math`/`Other`), the
`contracts/` pages, and the `index.md` landing under `--strict`.

**Known residual (benign, follow-up):** `mkdocs-gen-files` writes
`api/reference/SUMMARY.md` into the VFS; literate-nav consumes it for the nav but
(0.6.3) still renders it as a stray `api/reference/SUMMARY/` page that is **not a
nav entry** and does **not** break `--strict`. It is immune to `exclude_docs`
(applied before gen-files adds the file). Acceptance criterion 7 is adjusted to
assert what is real and meaningful: the grouped reference renders in the nav and
the reference `SUMMARY` is not a reachable nav entry. Cleanly suppressing the
stray render is deferred (would need a custom gen-files/`on_files` hook).

### 6h — Verify end-to-end

Run `generate_overviews` against the live config to populate every section
landing + the home block, regenerate the root `SUMMARY.md`, then
`mkdocs build --strict` to confirm the overviews, the grouped reference nav, and
all links pass the real consumer tool.

## Test plan (TDD)

- `upsert_managed_block`: create-when-absent (append path preserves prose);
  replace-when-present (prose above + below survives); idempotent re-run;
  malformed double-START raises (RED → GREEN).
- `generate_overviews`: directory section lists children with titles +
  summaries + count; `overview: false` section is skipped; empty section ⇒
  "No pages yet." not an error; best-effort on a child that fails to parse.
- API overview: built from CCE-105 `groups` + on-disk `contracts/`, not from
  `api/reference/`.
- **Updated clobber test:** author prose outside the markers preserved; block
  inside replaced (the renamed former `..._leaves_section_index` test).
- Home: managed block holds the section directory; author intro above it
  survives regeneration.
- `repo_url`/`edit_uri`: rendered into mkdocs.yml from a fixture origin; omitted
  cleanly when no origin.
- `run_site_generators` runs overviews after archive/contracts and records an
  `info_only` partial (not a hard failure) when the generator raises.
- **Root SUMMARY:** `plan_scaffold` emits a root `SUMMARY.md` in section order
  (not `awesome-pages` `.pages`); idempotent (never clobbers an authored
  SUMMARY); `render_mkdocs_yaml` drops `awesome-pages` and keeps `literate-nav`.
- **Real-consumer nav guard (CCE-105 unblock):** `mkdocs build --strict` over
  the grouped fixture renders the grouped reference modules in the nav (a named
  group + the "Other" bucket) and emits **no** orphan `api/reference/SUMMARY/`
  page. This is the discriminating test the 6i syntax is implemented against.
- Full `python3 -m pytest` green; `mkdocs build --strict` green.

## Out of scope (other phases)

- API service/component grouping + JSON-schema contracts — CCE-105 (dependency).
- Architecture index ordering + architecture-vs-archive routing (CCE-34) — CCE-107.
- Agent-authored / voice-matched prose overviews — explicitly deferred; the
  author-prose zone above the managed block is where a human (or a future agent
  stage) adds narrative. This spec ships the deterministic block only.

## Acceptance criteria

1. `scripts/managed_block.py` exists, is pure, unit-tested for create/replace/
   preserve/idempotent/malformed.
2. `templates/config.schema.json` accepts `overview: false`; the generator skips
   those sections.
3. `scripts/section_overview.py` upserts a clobber-safe block into every
   eligible section landing + the home; author prose outside the markers is
   preserved (proven by the updated former clobber test).
4. mkdocs config carries `repo_url`/`edit_uri` when a git origin exists and
   omits them cleanly otherwise.
5. `generate_overviews` is wired into `run_site_generators` (after
   archive/contracts) and setup scaffold, best-effort.
6. Every section landing + the home render populated content;
   `mkdocs build --strict` passes; full pytest green.
7. A generated mkdocs.yml `nav:` (per-section directory cross-links, config-order)
   drives the nav via `literate-nav` (`awesome-pages` removed; no hand-maintained
   nav); the grouped API reference subtree renders in the nav under its CCE-105
   groups, proven by a `mkdocs build --strict` real-consumer test. The reference
   `SUMMARY` is not a reachable nav entry (the stray gen-files VFS render is a
   documented benign residual). See "Revised mechanism (empirical, 2026-06-08)".
