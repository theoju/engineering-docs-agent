---
description: How Capability C2 authors and maintains canonical core documentation pages using voice-matched synthesis and the source map.
source_files:
  - docs/site-src/core/**
  - docs/superpowers/**
  - scripts/audit_docs.py
  - scripts/build_doc_source_map.py
  - scripts/lint/frontmatter_schema.py
  - scripts/source_map.py
last_reviewed: '2026-05-28'
status: draft
---

# Capability C2: Canonical Core Authoring

Capability C2 is the part of the engineering-docs-agent pipeline responsible for writing and maintaining canonical core documentation pages. It runs as the `page-author` subagent and produces files under the `agent-authored` site section. Every page C2 touches carries a machine-verifiable frontmatter contract that downstream lint, source-map, and publish-verification stages depend on.

## What makes a page "C2 canonical"

A C2 page belongs to a site section whose `generator` is `agent-authored` in the host's `site.sections` config. That generator label is the switch that routes a page to the stricter frontmatter field set (see [Frontmatter contract](#frontmatter-contract) below).

The orchestrator determines which pages fall under C2 by calling `scripts/frontmatter_contract.py:section_generator_for`. It resolves the longest-matching section path for a given page, reads that section's `generator` field, and returns `"agent-authored"` when it matches. Any page outside a declared `agent-authored` section uses the default (changelog-style) field set instead.

## Frontmatter contract

Agent-authored pages require four fields, defined as `AGENT_AUTHORED_REQUIRED` in `scripts/frontmatter_contract.py:14`:

```
description    – one-line plain-text summary of the page
source_files   – list of glob patterns covering the source files this page documents
last_reviewed  – ISO-8601 date of the last agent review pass
status         – lifecycle stage (draft | stable | deprecated)
```

These differ from the default required fields (`status`, `sources`, `synthesized_into`). The `source_files` list is the key addition: it seeds the source map and drives change-detection logic that decides which pages need a new authoring pass.

Use `scripts/frontmatter_contract.py:agent_authored_frontmatter_dict` to construct the dict programmatically, or `agent_authored_frontmatter_text` for the raw YAML block. Both functions are pure stdlib and never raise on valid input.

## The page-author agent

The `page-author` subagent (`agents/page-author.md`) is the runtime executor of C2. The orchestrator calls it with:

- `target_path` — absolute path of the page to write or edit.
- `action` — `"create"` for new pages, `"edit"` for updates.
- `summaries` — list of `pr-summarizer` outputs scoped to this page.
- `voice_samples` — recent pages from the same lens plus CLAUDE.md, loaded by `scripts/state_io.py:load_voice_samples`.
- `frontmatter_template` — the agent-authored field set pre-populated by the orchestrator.

The agent reads voice samples first to match tone, then drafts or patches the page. On `create` it writes a complete file with frontmatter. On `edit` it integrates new content into the existing heading structure rather than appending.

The agent returns a JSON object conforming to `agents/schemas/page-author-output.json`. The `ok` field is the only required key; a `false` value with `error: "path_not_agent_editable"` means the orchestrator's editable-path filter blocked the write before any file was touched.

## Source map integration

`scripts/source_map.py:generate_source_map` scans every `.md` file under `docs_dir`, reads each page's `source_files` globs, and resolves them against `git ls-files` output. The result is a dual-view artifact written to `<docs_dir>/.doc-source-map.json`:

- `map` — source file → list of pages that cover it. Used by change-detection to enqueue the right pages when a source file changes.
- `patterns` — page → list of glob strings. Used by audit scripts to verify coverage completeness.

A page that omits `source_files` is silently skipped by the source map generator — it will never appear in `map` and will not be enqueued for re-authoring when its source changes. This is intentional for index or narrative pages that have no direct source binding.

When the source map records a skip reason (malformed frontmatter, `source_files` is not a list), it includes the page in the `skipped` ledger returned by `generate_source_map`. The orchestrator surfaces this in the run summary so you can find and fix broken pages without a full audit scan.

## Frontmatter validation

The Tier-1 lint rule `scripts/lint/frontmatter_schema.py` enforces the frontmatter contract. It calls `scripts/frontmatter_contract.py:section_generator_for` to resolve each page's expected field set, then fails with `severity: block` on any missing required field.

Run it directly against a set of paths:

```bash
python scripts/lint/frontmatter_schema.py \
  --config .engineering-docs-agent/config.yml \
  --paths docs/site-src/**/*.md \
  --json
```

The `--json` flag emits a machine-readable result object with `rule`, `severity`, and per-path `results`. A non-zero exit code means at least one path failed. The lint runner (`scripts/lint/lint_runner.py`) aggregates results across all enabled rules; `frontmatter_schema` is active by default when `lint.tier1: default` is set in the host config.

## Write-path boundaries

The orchestrator enforces `docs.agent_editable_paths` before handing a target path to `page-author`. Any path outside the configured globs is rejected at dispatch time — the agent never receives it. This is the safety boundary that prevents C2 from writing outside the docs tree, even if the `page-author` manifest page spec includes a broader `source_files` glob.

The `docs.lens_paths` config must overlap with `agent_editable_paths` for every lens the agent reads. The invariant is validated at startup by `scripts/state_io.py:_validate_lens_paths_are_editable`. A lens with no matching editable glob means the agent reads docs it can never update — `load_config_validated` will raise a `ConfigError` before any subagent runs.
