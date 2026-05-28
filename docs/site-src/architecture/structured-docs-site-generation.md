---
description: How the agent produces a navigable docs site by combining a per-run code-to-docs source map, frontmatter-driven archive indexes for ADRs/specs/plans, and a Mermaid render gate — each layer driven by config and detection, never by hardcoded paths.
source_files:
  - agents/schemas/*.json
  - docs/superpowers/**
  - scripts/build_doc_source_map.py
  - scripts/generate_archive_indexes.py
  - scripts/verify_docs_diagrams.py
last_reviewed: "2026-05-28"
status: draft
---

# Structured Docs Site Generation

The engineering-docs-agent produces a structured, navigable docs site by combining three layers: a per-run source map that links code to docs, archive indexes that make ADRs/specs/plans discoverable, and a diagram-verification pass that catches broken visuals before the PR lands.

## Source map

`scripts/build_doc_source_map.py` walks the host repo's source tree and emits a JSON map from source file paths to the doc pages that cover them. The orchestrator loads this map at the start of each run and uses it to narrow the page-author's scope — when a PR touches `backend/connectors/postgres.py`, the map tells the author which existing pages reference that file, so edits land in the right place instead of creating duplicate coverage.

The map is rebuilt on every run. It reads `docs.source_dir` from config to locate the docs tree and scans frontmatter `source_files` lists across all pages. Pages that declare no `source_files` are indexed but not linked to any code path; the gap-detector uses this signal when it flags PRs with no associated spec.

## Archive indexes

`scripts/generate_archive_indexes.py` generates the index pages for the archive lens — the listing of ADRs, specs, and plans under `docs/site-src/archive/`. It reads each archived document's frontmatter (`status`, `date`, `synthesized_into`) and emits a sorted, grouped index.

The script runs inside the authoring pipeline, after `page-author` completes. If a newly authored page is placed in the archive, the index is regenerated in the same commit so the listing never drifts out of sync.

Promoted archive pages follow the redirect-stub pattern: the original ADR/spec path retains a three-line stub pointing at its synthesis target, and the index entry links to the promoted location. `scripts/lint/stub_redirect.py` enforces that the stub format is intact on every lint run.

## Diagram verification

`scripts/verify_docs_diagrams.py` renders every Mermaid block in changed pages and checks that the output is non-empty and non-error. It runs as part of the Tier 1 `diagrams` lint rule. A page with a broken diagram fails the Tier 1 gate and is dropped from the PR rather than published in a broken state.

The script accepts `--site-dir` and `--source-dir` flags so it works against any docs framework layout the host configures. Playwright is the render backend; the script expects `playwright` to be installed in the CI environment where the verifier runs.

## Agent schemas

`agents/schemas/*.json` are JSON Schema files that codify the output contract for each subagent. The orchestrator validates subagent responses against these schemas before passing data downstream. A response that fails schema validation is treated like a subagent crash: the run is marked `partial: true` with a `partial_reasons` entry, and the affected steps are skipped.

Schema files are named after the agent they cover (e.g., `pr-summarizer.json`, `page-author.json`). Dataclasses in `scripts/contracts.py` mirror the schemas for typed access inside the orchestrator runner. When you add a field to a schema, update the corresponding dataclass and run `python3 -m pytest` to catch any callers that break.

## Specs and plans

`docs/superpowers/specs/` and `docs/superpowers/plans/` hold the design artifacts that drove the agent's implementation. The gap-detector reads this directory to verify that non-trivial PRs have a corresponding spec or plan. If the host repo has no `docs/superpowers/` tree, the gap-detector falls back to checking for any file matching `*spec*` or `*plan*` in the configured `sources.specs_paths` list; if that list is also absent, the detector skips the spec-presence check entirely.

These files are input to the agent but are themselves docs: they are versioned, have frontmatter, and appear in the archive index. The `synthesized_into` frontmatter field links a spec to the architecture page that absorbed it, and the index marks such entries as promoted.
