# Structured Documentation-Site Generation — Design

**Date:** 2026-05-24
**Status:** draft (awaiting review)
**Ticket:** [CCE-23](https://designitright.atlassian.net/browse/CCE-23)
**Related:** dogfood full-run output (test branch `test/CCE-full-dogfood-2026-05-24`); reference site in `advanced-data-importer` (`docs/site-src/`).

---

## Why this exists (root cause)

A full dogfood run of engineering-docs-agent over the `v0.1.0..HEAD` window produced flat per-PR changelog pages under `docs/_agent-sandbox/`, the plain mkdocs theme, auto-discovered nav, and nothing else: no home, no architecture section, no diagrams, no API reference, no curated archive.

The reference — `advanced-data-importer` (ADIS) — is a Material-themed site under `docs/site-src/` with a section-nav + per-page ToC, a Canonical Core with mermaid diagrams, a published Decision Archive, and a doc↔source map. The investigation established the gap is not a bug: the two systems were built to produce different things. ADIS's structured site was **authored by hand and assembled by a generation toolchain**; only its _index pages_ and _source map_ are script-generated, and its Canonical Core pages were written by hand. engineering-docs-agent only ever produced an automated changelog.

This design closes the gap by expanding the agent's documentation model: a **configurable site structure** scaffolded at setup, deterministic generators for the parts that can be generated, and an honestly-scoped agent-authoring path for the parts that cannot.

## Goal

Turn engineering-docs-agent into a structured-site generator: setup scaffolds a configurable default information architecture (Material theme, navigable sections, home, API reference, Decision Archive); generators and the agent fill it; a host repo can adjust the structure at setup and later.

## Non-goals

- **Fully-correct auto-generated architecture docs.** The agent drafts architecture narrative + diagrams at `status: draft`; humans refine. ADIS authored these by hand and we will not pretend to fully automate them.
- **Language-agnostic API extraction.** Python first (covers this repo and ADIS's backend). Other languages are later work.
- **A bespoke nav system.** Nav derives from the directory tree via `awesome-pages`; we do not hand-maintain a central `nav:`.
- **Migrating ADIS.** ADIS is a reference only; nothing here changes it.

## The model: a configurable site structure

The host's `.engineering-docs-agent/config.yml` gains a `site:` block that defines the information architecture as an ordered list of sections. Each section names a directory (or page), a title, and an optional generator that populates it. Setup materializes this structure into `docs/site-src/`; generators and the agent fill the sections; `awesome-pages` `.pages` files (written by setup from the `site:` order) drive the mkdocs nav so structure equals directory layout.

Default structure ("Candidate A"): **Home · Architecture · API reference · Operations · Decision Archive · What's New.**

**Generic-first, convention-optimized.** The agent must run on _any_ repository. Every capability degrades gracefully on what a repo actually provides: the structure scaffold, the What's New changelog, and (per-language) API extraction work on any repo; the Decision Archive and Canonical Core are _markedly better_ on Claude Code / superpowers repos that carry `docs/superpowers/{specs,plans}`, and they **skip or fall back cleanly** when that convention is absent. Nothing here hard-requires the convention — detection drives the path taken.

### The `site:` config block

```yaml
site:
  docs_dir: docs/site-src # published site root (mkdocs docs_dir)
  theme: material
  sections:
    - { key: home, path: index.md, title: Home }
    - {
        key: architecture,
        path: architecture/,
        title: Architecture,
        generator: agent-authored,
      } # Phase 2 (C)
    - {
        key: api,
        path: api/,
        title: API reference,
        generator: api-extract,
        extractors: [python-mkdocstrings],
      } # auto-detected
    - { key: operations, path: operations/, title: Operations }
    - {
        key: archive,
        path: archive/,
        title: Decision Archive,
        generator: archive-index,
        sources:
          [
            docs/superpowers/specs,
            docs/superpowers/plans,
            docs/superpowers/measurements,
          ],
      }
    - {
        key: whats-new,
        path: whats-new.md,
        title: What's New,
        generator: changelog,
      }
```

Recognized `generator` values: `archive-index` (D), `api-extract` (API), `changelog` (existing per-PR pipeline), `agent-authored` (C), and none (a plain section setup stubs and the agent or a human fills). Unknown generators fail config validation.

## Capabilities

### S — Structure + setup engine (Phase 1)

The `/engineering-docs-agent-setup` skill scaffolds the `site:` structure into a host repo, idempotently:

- Generates `mkdocs.yml` — Material theme; features `navigation.sections`, `navigation.indexes`, `navigation.top`, `toc.permalink`, `search.suggest`, `content.code.copy`; `pymdownx.superfences` mermaid custom fence; `awesome-pages` plugin; `mkdocstrings` + `mkdocs-gen-files` + `literate-nav` when Python is detected.
- Creates `docs/site-src/` with one folder per section, an `index.md` stub per section, and `.pages` ordering files derived from the `site:` order.
- Writes `docs/site-src/index.md` — a grid-card Home hero linking to each section (depends on `md_in_html`).

A **structure-sync** mode reconciles scaffold ↔ config on re-run: it **adds** newly-configured sections and ordering, and **never clobbers** authored content. This is what makes per-repo customization ("adjust later") safe.

### D — Decision Archive (Phase 1)

Port ADIS's `scripts/generate_archive_indexes.py`. Reads the `sources` dirs from the `archive` section (`docs/superpowers/{specs,plans,measurements}`) plus any ADRs, parses each file's first heading (title) and first paragraph (summary), groups entries by ISO month newest-first, and emits `docs/site-src/archive/{specs,plans,measurements,adrs}.md` index pages with an "auto-generated; do not edit by hand" banner. Entries link to source. Regenerated on each agent run and exposed as a CLI/`make` target.

The `sources` are configurable, so a non-superpowers repo can point the archive at its own decision dirs (e.g. `docs/adr/`). If a repo has **no** archive sources, the Decision Archive section is **skipped**, not emitted empty.

### API — API reference section (Phase 1)

Setup wires deterministic extractors into `mkdocs.yml`; the API surface is extracted from code, never authored by the LLM:

- **Python → `mkdocstrings`** with `mkdocs-gen-files` + `literate-nav`: auto-generate one API page per module from the package tree, rendering signatures + docstrings.
- **HTTP → OpenAPI**: rendered in-site, enabled only when the repo exposes an OpenAPI schema (e.g. FastAPI). Opt-in per repo.
- **JSON-schema contracts**: render schemas such as this repo's `agents/schemas/*.json` to a contracts page (this repo's "public contract" surface).

The agent may author a short narrative intro per service/component; it does not author signatures.

### M — doc↔source map + drift (Phase 1)

Port ADIS's `scripts/build_doc_source_map.py`. Reads `source_files:` frontmatter from `site-src` pages and writes the inverse map `source-path → [page-paths]` to `docs/site-src/.doc-source-map.json`. When mapped source files change, the orchestrator surfaces the affected pages as gap-flags (review-needed), keeping pages honest against code drift.

### C — Canonical Core + diagrams (Phase 2)

C is **convention-aware** — it detects whether the repo carries the Claude Code / superpowers convention (specs + plans under `docs/superpowers/`) and picks its path accordingly:

- **Convention present (preferred path):** synthesize the existing specs/plans into component-organized Canonical Core pages, then reconcile against the current code — shift future-tense design language to present-tense system description, verify claims, add `file:line` citations (via the M source-map), and lift/adapt any mermaid diagrams already in those docs. This plays to the agent's demonstrated strength (cf. the dogfood reconciliation edits) and is the lower-risk path.
- **Convention absent (generic fallback):** scaffold the section and derive a best-effort draft from the codebase alone. Higher-risk; applies only to the slice the repo doesn't already document.

Either way, pages are marked `status: draft` for human refinement — reorganization (ticket/chronology → component), coverage gaps (components with no spec), and spec staleness all still want human eyes. The one hard, testable gate: a **diagram-render verification** step (port `scripts/verify_docs_diagrams.py`, Playwright Chromium against the built site) fails the build if any emitted mermaid block does not render. Content quality is not unit-tested.

## Orchestrator changes

- `page-author` output retargets to `site-src/` sections per the `site:` config, not flat `_agent-sandbox`.
- "What's New" remains the existing per-PR changelog pipeline, **demoted to one section** (`whats-new` generator).
- New pipeline stages: `archive-index` (D) and `source-map` (M). API extraction is a build-time mkdocs concern wired by setup, not an orchestrator stage.
- `agent_editable_paths` shift to the `site-src/` published areas; `docs/superpowers/` becomes **read-only input**. This permanently fixes the dogfood-run defect where the agent rewrote raw process specs in place.

## The `superpowers/` → `site-src/` split + migration

Adopt ADIS's split: `docs/site-src/` is the published `docs_dir`; `docs/superpowers/` stays the raw specs/plans/measurements that brainstorming and writing-plans produce, and is not published directly — only surfaced through the generated Decision Archive.

Migration for this repo: setup scaffolds `docs/site-src/`; the current `docs/_agent-sandbox/` changelog content maps to the `whats-new` section; `docs/superpowers/**` is left in place as archive input. The `lens_paths` concept folds into `site:` sections — each lens becomes (or maps onto) a section; `_validate_lens_paths_are_editable` is updated to validate sections against `agent_editable_paths` instead.

## Dependencies

- **Agent runtime stays stdlib + `pyyaml`.** The orchestrator and generators (archive-index, source-map) use only the standard library plus the already-present `pyyaml`.
- **mkdocs ecosystem is a documentation-build dependency, not an agent-runtime dependency.** `mkdocs-material`, `mkdocstrings[python]`, `mkdocs-gen-files`, `mkdocs-literate-nav`, `mkdocs-awesome-pages-plugin`, and (Phase 2) Playwright for diagram verification run at site-build time in the host repo's docs tooling, separate from the agent's Python runtime. They are declared in a docs-tooling requirements file the setup skill installs, justified here per the stdlib-first rule.

## Error handling & verification

- **Config validation** extends to the `site:` block: every section path is valid and under `docs_dir`; every `generator` is recognized; `archive` `sources` exist; `lens_paths` reconcile with sections; the existing editable-glob invariant holds for section paths.
- **`mkdocs build --strict`** is the build gate (catches broken links, missing nav targets).
- **Diagram-render verification** (Phase 2) gates any agent-emitted mermaid.
- **Lint tiers** (content-validator) continue to apply to authored pages.
- **Setup idempotency:** structure-sync never clobbers authored content; only adds scaffolding and ordering.

## Testing strategy

TDD throughout, fixture-driven (the existing dry-run pattern; production CLI dispatch monkeypatched):

- **S** — scaffolding produces the expected `site-src/` tree, `mkdocs.yml`, and `.pages` files; structure-sync re-run adds a new section without clobbering an authored page.
- **D** — archive generator produces the expected month-grouped index from fixture specs/plans/measurements.
- **API** — `mkdocs-gen-files` produces API pages from a fixture Python package; OpenAPI/contract paths render when their sources are present.
- **M** — source-map built correctly from `source_files:` frontmatter fixtures; drift flags the right pages.
- **C** — diagram-render gate passes for valid mermaid and fails for a deliberately broken fixture; narrative content is not asserted.
- **Build** — `mkdocs build --strict` succeeds on the scaffolded fixture site.

## Phasing & delivery

- **Phase 1 → `/ship`:** S + D + API + M. Deterministic, TDD-friendly foundation. Ships a themed, navigable, structured site with a real Home, published Decision Archive, and API reference.
- **Phase 2 → `/ship`:** C. Architecture authoring + diagrams, draft-scoped, with the diagram-render gate.

Both phases execute via subagent-driven-development. Phase 2 cannot block Phase 1.

## Risks & open questions

- **C quality is inherently unpredictable.** Mitigated by draft-status framing, the render gate, and shipping it separately.
- **Existing-repo migration churn.** Moving published docs to `site-src/` reorganizes this repo's docs; superpowers content is preserved as input, not deleted.
- **`lens_paths` reconciliation.** Folding lenses into sections touches `state_io.py` validation; needs care to avoid breaking existing config consumers (voice-load, gap-detection read paths).
- **mkdocstrings auto-nav recipe.** `gen-files` + `literate-nav` is the standard automatic API recipe but adds build-time deps and a small generation script; verify it works headless in CI.
- **Per-repo customization surface.** The `site:` block must be expressive enough to add/remove/rename sections without code changes; the schema above is the proposed minimum — revisit if hosts need nested sections or per-section themes.
