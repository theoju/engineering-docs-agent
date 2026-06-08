---
title: "CCE-105 — API reference grouped by service/component + JSON-schema contracts"
status: draft
ticket: CCE-105
date: 2026-06-08
supersedes_gap: "API section flat + no contracts (holistic review 2026-06-08)"
---

# CCE-105 — Group the API reference + wire contracts

Phase 2a of the docs-site remediation roadmap (CCE-104 was Phase 1). Two gaps
from the 2026-06-08 holistic review:

1. **The API reference is flat.** `gen_ref_pages.py` emits one page per Python
   module under `scripts/`, in a single alphabetical literate-nav list — no
   service/component grouping. A reader scanning the API tab sees ~30 modules
   with no sense of which belong to the orchestrator, the generators, the lint
   engine, etc.
2. **Contracts never render.** `contracts_doc.generate_contracts`
   (`scripts/contracts_doc.py:91`) is built and unit-tested, but the live api
   section declares no `json-schema` extractor, so the JSON-schema contract
   pages (`agents/schemas/*.json` → human-readable pages) are never produced.

This spec extends the CCE-23 `api-extract` capability; it does **not** touch
section overviews, the home page, or `repo_url` (those are CCE-106).

## Current state (verified 2026-06-08)

- `gen_ref_pages.py` (repo root) is **template-filled at scaffold time** from
  `_GEN_REF_TEMPLATE` in `scripts/site_structure.py:165-196`, rendered by
  `apply_scaffold` (`scripts/site_structure.py:287-298`) with `scan_dir`,
  `path_root`, `out_root`. Its loop is a flat `Path(SCAN_DIR).rglob("*.py")` →
  `nav[ident_parts] = doc` → `nav.build_literate_nav()` (no grouping).
- `site.sections[]` in `templates/config.schema.json:117-148` sets
  `additionalProperties: false`. A new `groups` key is therefore **rejected by
  schema validation** until the schema lists it — this is a required change,
  not optional.
- `contracts_doc.generate_contracts(repo_root, site_config)` already locates the
  `api-extract` section, requires `"json-schema"` in its `extractors`, reads
  `*.json` from the section `sources`, and writes `<docs_dir>/<api>/contracts/<stem>.md`
  plus a `contracts/index.md`. It is already invoked by
  `orchestrator_runner.run_site_generators` (`scripts/orchestrator_runner.py:993`)
  — it simply no-ops today because the live config declares no extractor/sources.
- `_validate_api_sections` (`scripts/state_io.py:124`) already enforces:
  `api-extract` ⇒ non-empty `extractors`; repo-relative `sources`; `openapi`
  extractor ⇒ a repo-relative `openapi:` path. Group validation joins it here.

## Deliverables

### 2a — Schema: `groups` on `api-extract` sections

Add `groups` to `site.sections[].properties` in `templates/config.schema.json`:

```json
"groups": {
  "type": "array",
  "items": {
    "type": "object",
    "required": ["name", "modules"],
    "additionalProperties": false,
    "properties": {
      "name": { "type": "string", "minLength": 1 },
      "modules": { "type": "array", "items": { "type": "string", "minLength": 1 } }
    }
  }
}
```

`modules` entries are **glob patterns** matched against each module's
dotted/relative identifier (e.g. `lint/*`, `orchestrator_runner`,
`contracts_doc`). `groups` is **optional**; absent ⇒ today's flat behavior
(graceful degradation, the bare-host path).

### 2b — Grouped literate-nav in `gen_ref_pages.py`

Extend `_GEN_REF_TEMPLATE` (`scripts/site_structure.py`) so the rendered
`gen_ref_pages.py` carries a baked `GROUPS` mapping and builds a **two-level
nav**: each module is matched against the group globs (first match wins, in
config order); matched modules nest under `nav[(group_name, *ident_parts)]`;
unmatched modules fall under a final `"Other"` group. When `GROUPS` is empty the
loop is byte-for-byte today's flat behavior.

- Baking the map at scaffold time keeps the mkdocs build **hermetic** (the
  build process reads no config) — same pattern `apply_scaffold` already uses
  for `SCAN_DIR`/`PATH_ROOT`/`OUT_ROOT`.
- The matcher is a small pure helper, `assign_group(ident, groups) -> str`,
  defined in `scripts/site_structure.py` and **duplicated into the rendered
  template** (the template can't import from the plugin at build time). Unit
  tests target the `site_structure` copy; a template-sync test asserts the two
  stay identical (same pattern as `sdd-fidelity-gate` doc/impl sync).
- Glob match uses `fnmatch.fnmatchcase` against both the dotted ident
  (`a.b.c`) and the path-form (`a/b/c`) so a `lint/*` glob matches a
  `lint.lint_runner` module.

`apply_scaffold` passes the api section's `groups` (default `[]`) into
`_GEN_REF_TEMPLATE.format(...)` as a serialized literal.

### 2c — Turn contracts on (live host)

In `.engineering-docs-agent/config.yml`, add to the `api` section:

```yaml
extractors:
  - python-mkdocstrings
  - json-schema
sources:
  - agents/schemas
groups:
  - name: Orchestrator
    modules: [orchestrator_runner, state_io, contracts, run_*]
  - name: Generators
    modules:
      [
        archive_indexes,
        contracts_doc,
        core_manifest,
        site_structure,
        gen_ref_pages,
      ]
  - name: Lint
    modules: [lint/*]
  - name: Setup
    modules: [setup_*, preflight_host, scaffold_*, enable_pages, derive_*]
  # ungrouped modules fall under "Other"
```

The exact group membership is finalized during implementation by enumerating
`scripts/*.py`; the spec fixes the _shape_, not the final module list. This
makes `generate_contracts` produce `docs/site-src/api/contracts/*.md` from
`agents/schemas/*.json` on the next run.

### 2d — Setup proposes groups + contracts (generic plugin)

`preflight_host._proposed_site` (`scripts/preflight_host.py:38`) gains
`json-schema` in the api `extractors` and a `sources` default. Group proposal
is **convention-optimized, degrade-gracefully**: derive a default `groups` from
discovered top-level `scripts/` subdirectories when any exist; emit `groups: []`
(flat) when the source tree is flat. `agents/schemas` is proposed as a contract
source only when that directory is detected — a bare host gets no contracts and
no error.

### 2e — Validation extends `_validate_api_sections`

In `scripts/state_io.py`, validate (beyond what JSON Schema covers): each group
`name` is unique within the section; `modules` is non-empty per group. A
malformed `groups` raises at `load_config_validated`, consistent with the
existing api/site cross-field checks.

### 2f — Verify end-to-end

Run `generate_contracts` against the live config to populate
`docs/site-src/api/contracts/`, render the grouped `gen_ref_pages.py`, then
`mkdocs build --strict` to confirm the grouped nav + contract pages + nav
entries pass the real consumer tool (the plugin's "verify with the real
consumer, not `test -f`" invariant).

## Test plan (TDD)

- `assign_group`: first-match-wins ordering; dotted vs path-form glob (`lint/*`
  matches `lint.lint_runner`); unmatched ⇒ `"Other"`; empty groups ⇒ every
  module ⇒ `"Other"`-free flat path (RED → GREEN).
- Rendered `gen_ref_pages.py` template sync: the in-template `assign_group`
  byte-matches the `site_structure` reference (drift test).
- `render_mkdocs_yaml`/`apply_scaffold`: groups serialize into the rendered
  `gen_ref_pages.py`; flat config renders the unchanged template.
- Schema: a config with well-formed `groups` validates; a group missing
  `modules` / with a duplicate `name` fails `load_config_validated`.
- `_proposed_site`: api section includes `json-schema` extractor; groups
  derived from a fixture host with `scripts/` subdirs; flat fixture ⇒ `groups: []`.
- `generate_contracts` against an `agents/schemas`-style fixture writes one page
  per schema + `contracts/index.md` (existing tests extended for the live wiring).
- Full `python3 -m pytest` green; `mkdocs build --strict` green.

## Out of scope (other phases)

- Section overviews, rich home, `repo_url`/`edit_uri` widget — CCE-106.
- Architecture index + architecture-vs-archive routing — CCE-107.
- OpenAPI/`render_swagger` enablement (no HTTP API on this host today).

## Acceptance criteria

1. `templates/config.schema.json` accepts a well-formed `groups`; rejects
   malformed groups via schema + `_validate_api_sections`.
2. The rendered `gen_ref_pages.py` produces a grouped literate-nav when `groups`
   are declared and the unchanged flat nav when they are not; `assign_group` is
   unit-tested and template-sync-tested.
3. The live `.engineering-docs-agent/config.yml` api section declares the
   `json-schema` extractor + `agents/schemas` source + `groups`, and loads green
   through `load_config_validated`.
4. `preflight_host.proposed_config` emits the extractor + degrade-gracefully
   groups; bare-host fixture stays flat with no contracts.
5. `docs/site-src/api/contracts/*.md` exist and are populated; the API nav is
   grouped; `mkdocs build --strict` passes; full pytest green.
