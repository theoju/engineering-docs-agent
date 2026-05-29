---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/61
synthesized_into: []
---

# CCE-46: Markdown Hygiene Rule Split

**Date:** 2026-05-29  
**PR:** [#61](https://github.com/theoju/engineering-docs-agent/pull/61)  
**Jira:** CCE-46

## What changed

PR #61 splits the single `markdown_hygiene` lint rule into two distinct rules:

- **`markdown_hygiene_lang`** (severity `warn`) — flags code-fence opening lines that are missing a language tag (e.g., a bare ` ``` ` with no `python`, `bash`, etc.).
- **`markdown_hygiene_structure`** (severity `block`) — catches unpaired fences and heading-jump defects that break MkDocs rendering.

Both rules replace the old `markdown_hygiene` entry in `TIER1_DEFAULT`. The `lint_runner.py` script-path derivation is updated to resolve each new rule name. Three new tests cover each rule independently plus runner registration.

## Why it was necessary

The original single `markdown_hygiene` rule treated every hygiene violation as a hard failure, regardless of how severe the underlying issue was. A bare ` ``` ` fence emitted by the `page-author` agent (a probabilistic slip-up, not a structural defect) caused the lint runner to block the page. The entire page was then unlinked from the docs site, as observed in PR #59.

Separating cosmetic issues from structural defects fixes this without lowering the guard on rendering-breaking problems. Missing language tags now produce a `warn` — the page still ships. Unpaired fences and heading jumps still produce a `block` — they corrupt MkDocs output and must be fixed before the page lands.

## Design decision

The key insight is that severity must track actual blast radius. A missing language tag degrades syntax highlighting; it does not break navigation or the rendered page tree. An unpaired fence or a heading jump (e.g., `##` directly followed by `####`) can silently corrupt section anchors and MkDocs's left-nav tree.

Keeping them in a single rule forced a binary choice: tolerate structural defects or block on cosmetic ones. The split removes that tradeoff.

## Affected files

- `scripts/lint/lint_runner.py` — script-path derivation updated for the two new rule names.
- `scripts/lint/rules/markdown_hygiene_lang.py` — new rule, severity `warn`.
- `scripts/lint/rules/markdown_hygiene_structure.py` — new rule, severity `block`.
- `scripts/lint/__init__.py` (or `TIER1_DEFAULT` constant location) — old `markdown_hygiene` entry replaced by both new entries.
- Tests: three new pytest cases, one per rule plus runner registration.

## Migration

This change is non-breaking for host repos. If your config explicitly opts into `markdown_hygiene` via `lint.tier1: [markdown_hygiene]`, replace it with `[markdown_hygiene_lang, markdown_hygiene_structure]`. Hosts using `lint.tier1: default` pick up both rules automatically with no config change.
