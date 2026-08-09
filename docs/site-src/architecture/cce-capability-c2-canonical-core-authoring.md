---
description:
  How Capability C2 authors and maintains canonical core documentation
  pages using voice-matched synthesis and the source map.
source_files:
  - docs/site-src/core/**
  - docs/superpowers/**
  - scripts/audit_docs.py
  - scripts/lint/frontmatter_schema.py
  - scripts/source_map.py
  - agents/page-author.md
last_reviewed: "2026-08-09"
status: draft
doc_kind: architecture
---

# Capability C2: Canonical Core Authoring

Capability C2 is the part of the engineering-docs-agent pipeline responsible for writing and maintaining canonical core documentation pages. It runs as the `page-author` subagent and produces files under the `agent-authored` site section. Every page C2 touches carries a machine-verifiable frontmatter contract that downstream lint, source-map, and publish-verification stages depend on.

## What makes a page "C2 canonical"

A C2 page belongs to a site section whose `generator` is `agent-authored` in the host's `site.sections` config. That generator label is the switch that routes a page to the stricter frontmatter field set (see [Frontmatter contract](#frontmatter-contract) below).

The orchestrator determines which pages fall under C2 by calling `scripts/frontmatter_contract.py`. It resolves the longest-matching section path for a given page, reads that section's `generator` field, and returns `"agent-authored"` when it matches. Any page outside a declared `agent-authored` section uses the default (changelog-style) field set instead.

## Frontmatter contract

Agent-authored pages require four fields, defined as `AGENT_AUTHORED_REQUIRED` in `scripts/frontmatter_contract.py:AGENT_AUTHORED_REQUIRED`:

```
description    – one-line plain-text summary of the page
source_files   – list of glob patterns covering the source files this page documents
last_reviewed  – ISO-8601 date of the last agent review pass
status         – lifecycle stage (draft | stable | deprecated)
```

These differ from the default required fields (`status`, `sources`, `synthesized_into`). The `source_files` list is the key addition: it seeds the source map and drives change-detection logic that decides which pages need a new authoring pass.

Use `scripts/frontmatter_contract.py` to construct the dict programmatically, or `agent_authored_frontmatter_text` for the raw YAML block. Both functions are pure stdlib and never raise on valid input.

## The page-author agent

The `page-author` subagent (`agents/page-author.md`) is the runtime executor of C2. The orchestrator calls it with:

- `target_path` — absolute path of the page to write or edit.
- `action` — `"create"` for new pages, `"edit"` for updates.
- `summaries` — list of `pr-summarizer` outputs scoped to this page.
- `voice_samples` — recent pages from the same lens plus CLAUDE.md, loaded by `scripts/state_io.py`.
- `frontmatter_template` — the agent-authored field set pre-populated by the orchestrator.

The agent reads voice samples first to match tone, then drafts or patches the page. On `create` it writes a complete file with frontmatter. On `edit` it integrates new content into the existing heading structure rather than appending.

The agent returns a JSON object conforming to `agents/schemas/page_author.schema.json`. The `ok` field is the only required key; a `false` value with `error: "path_not_agent_editable"` means the orchestrator's editable-path filter blocked the write before any file was touched.

## Citation grounding and the dead-name rule

Step 3 of the `page-author` procedure grounds every claim in code the agent
actually read: `source_paths` names the files the summarized PRs touched, and
the agent may cite only files, symbols, and tests it confirmed exist. The
Tier-1 rule `scripts/lint/citation_exists.py` enforces this deterministically
— a backticked path or `path:symbol` token that doesn't resolve is a `block`
severity lint failure, not a suggestion.

That enforcement has a sharp edge on a C2 page: `citation_exists` lints the
whole page's prose, not the diff. A single stale citation left over from an
earlier pass blocks every future edit to that page, not only the one that
introduced it — the agent re-authors the page, the lint re-fails, the edit is
dropped, and the run flips `partial`. Six confabulated citations across five
architecture and operations pages did exactly this (CCE-132), silently
dropping edits on two separate nightly PRs before the corpus was swept clean.

Documenting that fix created its own trap. Explaining what a corrected
citation used to point at means naming the exact confabulated path in prose —
and `citation_exists` cannot distinguish "I claim this file exists" from "I
am naming a file that used to exist and no longer does." Step 3 now closes
that gap explicitly: when you document a rename or a corrected citation, put
the dead name inside a fenced code block and backtick only the surviving
name in prose. The three existing escape hatches — the `example/` namespace,
fenced metasyntactic placeholders, and `lint.citation_exempt_tokens` — each
cover a different case, but none covers "a real path quoted as history";
exempting the specific dead tokens would permanently blind the rule to a
genuine future confabulation of the same names (CCE-134).

This is LLM-mediated guidance, not a deterministic gate — a model that
ignores the fenced-block instruction still gets blocked by `citation_exists`,
the same as any other confabulation. If recurrence continues, CCE-135 is the
tracked escalation for a per-token `<!--lint-ignore-next-->` marker,
previously deferred as YAGNI. See
[Capability C — Canonical Core Citations](cce-capability-c-canonical-core-citations.md)
for the full `citation_exists`/`citation_line_free` lint mechanism.

## Source map integration

`scripts/source_map.py` scans every `.md` file under `docs_dir`, reads each page's `source_files` globs, and resolves them against `git ls-files` output. The result is a dual-view artifact written to `<docs_dir>/.doc-source-map.json`:

- `map` — source file → list of pages that cover it. Used by change-detection to enqueue the right pages when a source file changes.
- `patterns` — page → list of glob strings. Used by audit scripts to verify coverage completeness.

A page that omits `source_files` is silently skipped by the source map generator — it will never appear in `map` and will not be enqueued for re-authoring when its source changes. This is intentional for index or narrative pages that have no direct source binding.

When the source map records a skip reason (malformed frontmatter, `source_files` is not a list), it includes the page in the `skipped` ledger returned by `generate_source_map`. The orchestrator surfaces this in the run summary so you can find and fix broken pages without a full audit scan.

## Frontmatter validation

The Tier-1 lint rule `scripts/lint/frontmatter_schema.py` enforces the frontmatter contract. It calls `scripts/frontmatter_contract.py` to resolve each page's expected field set, then fails with `severity: block` on any missing required field.

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

The `docs.lens_paths` config must overlap with `agent_editable_paths` for every lens the agent reads. The invariant is validated at startup by `scripts/state_io.py`. A lens with no matching editable glob means the agent reads docs it can never update — `load_config_validated` will raise a `ConfigError` before any subagent runs.
