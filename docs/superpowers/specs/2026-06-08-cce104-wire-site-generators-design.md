---
title: "CCE-104 — Wire the site: block + deterministic generators into setup & orchestrator"
status: draft
ticket: CCE-104
date: 2026-06-08
supersedes_gap: "rendered docs site empty (holistic review 2026-06-08)"
---

# CCE-104 — Wire `site:` + deterministic generators

Phase 1 of the docs-site remediation roadmap. This is a **wiring** change: the
site-based generators (CCE-23 capability D archive, capability API contracts)
are already built and unit-tested, but nothing connects them to a running host.
The new capabilities (API service/component grouping, generated section
overviews, routing revisit) are tracked separately as CCE-105 / CCE-106 / CCE-107
and are explicitly **out of scope** here.

## Root cause (verified 2026-06-08)

Two independent disconnections, each sufficient on its own to leave the rendered
site empty:

1. **The live host config has no `site:` block.** The full information
   architecture (sections + archive `sources` + api `extractors`) lives only in
   `templates/site.default.yaml` and was never persisted into
   `.engineering-docs-agent/config.yml`. `site:` is schema-optional
   (`templates/config.schema.json` top-level `required` omits it), so the config
   validates while every generator does `if not config.get("site"): return` and
   silently no-ops (`archive_indexes.generate_archive`, `contracts_doc.generate_contracts`,
   `core_manifest`).
2. **The orchestrator never calls the spec generators.** `orchestrator_runner.run`
   invokes only the legacy pre-S `archive_indexes.regenerate()`, gated on a
   per-lens `archive_index: true` flag this host never sets.
   `generate_archive` / `generate_contracts` are imported and called nowhere.

## Deliverables

### 1a — Live host config gains a `site:` block

Add a `site:` block to `.engineering-docs-agent/config.yml` mirroring
`templates/site.default.yaml` (under the `site:` key), with the archive section's
`sources` pointing at `docs/superpowers/{specs,plans,measurements}` and
`docs_dir: docs/site-src`. Must pass `state_io.load_config_validated`
(`_validate_site_sections` + `_validate_api_sections`).

### 1b — Setup persists `site:` (generic plugin)

`preflight_host.proposed_config(discovery)` returns a `site:` block so the setup
skill writes it into every host's config. The block is **convention-optimized,
degrade-gracefully**: `docs_dir` = discovered `source_dir`; standard sections;
archive `sources` derived from discovery's decision sources, defaulting to the
superpowers convention paths (`generate_archive` skips missing sources cleanly,
so a bare host degrades without error). The setup `SKILL.md` step that writes
`config.yml` is updated to name the `site:` block.

### 1c — Orchestrator runs the generators (generic plugin)

A new `run_site_generators(repo_root, config, state)` in `orchestrator_runner`
runs the deterministic generators when `config.get("site")` is present:

- `archive_indexes.generate_archive(repo_root, config["site"])`
- `contracts_doc.generate_contracts(repo_root, config["site"])` (no-op until a
  section declares the `json-schema` extractor — CCE-105)

It is **best-effort**: any generator exception records an `info_only` partial and
never blocks the PR (matches the source-map / citation stages). Generated pages
land in `docs/site-src/` and are committed by the run's existing `git add -A`.
The legacy `regenerate()` path is **retained** for hosts with no `site:` block
(graceful degradation), and is skipped when `site` is present. The helper is
wired into `run()` at the current "Archive index regeneration" point.

### 1d — Verify end-to-end

Run `generate_archive` against the live config to populate
`docs/site-src/archive/{specs,plans,measurements}.md`, then `mkdocs build --strict`
to confirm the new pages + nav entries pass the real consumer tool (per the
plugin's "verify with the real consumer, not `test -f`" invariant).

## Test plan (TDD)

- `proposed_config` includes a `site:` block with the standard sections and an
  archive section whose `sources` are present (RED → GREEN).
- `run_site_generators` writes `archive/<category>.md` for each existing source
  in a fixture host, records nothing when `site` is absent, and survives a
  generator raising (records an `info_only` partial, returns cleanly).
- The live `.engineering-docs-agent/config.yml` loads green through
  `load_config_validated` and exposes the archive sources.
- Full `python3 -m pytest` green; `mkdocs build --strict` green.

## Out of scope (later phases)

- Rich home (intro / read-next / project links) and `repo_url` widget — CCE-106.
- Generated section overviews — CCE-106.
- API service/component grouping + enabling the `json-schema`/OpenAPI extractors
  — CCE-105.
- Architecture index + architecture-vs-archive routing — CCE-107.

## Acceptance criteria

1. `.engineering-docs-agent/config.yml` has a valid `site:` block; `load_config_validated` passes.
2. `preflight_host.proposed_config` emits a `site:` block; setup `SKILL.md` names it.
3. `run_site_generators` is wired into `run()`, runs the generators when `site` is present, degrades to the legacy path when absent, and is best-effort.
4. `docs/site-src/archive/{specs,plans,measurements}.md` exist and are populated.
5. `mkdocs build --strict` passes; full pytest green.
