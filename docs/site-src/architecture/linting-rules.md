---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/61
synthesized_into: []
---

# Linting Rules

The agent runs a tiered linting pipeline against every page it authors. Rules are grouped into three tiers: Tier 1 fires on every run, Tier 2 and Tier 3 are opt-in per rule in your host config.

## Tier 1 rules

Tier 1 is enabled by default when your config sets `lint.tier1: default`. All seven Tier-1 rules run on every page. The runner (`scripts/lint/lint_runner.py`) collects results per rule and applies each rule's severity to decide whether the run continues or halts.

## The `markdown_hygiene` split (PR #61)

The original `markdown_hygiene` rule is retired. It is replaced by two rules registered in `TIER1_DEFAULT`:

### `markdown_hygiene_lang` — severity `warn`

Fires when an opening code fence has no language tag (e.g. ` ``` ` instead of ` ```python `). A bare fence is sloppy but not structurally destructive: MkDocs renders it, pages stay linked, and downstream tools like syntax highlighters degrade gracefully.

Severity `warn` means the runner records the violation and continues. The page is authored and the PR is opened. You will see the warning in the lint summary, but a missing language tag does not block the docs-PR.

### `markdown_hygiene_structure` — severity `block`

Fires on two classes of defect that genuinely break MkDocs rendering:

- **Unpaired fences** — an opening ` ``` ` with no matching closing fence. MkDocs renders the rest of the page as a code block, which unlinks navigation, breaks search indexing, and corrupts surrounding content.
- **Heading-level jumps** — skipping heading levels (e.g., `##` followed immediately by `####`) in a way that breaks MkDocs's navigation tree construction.

Severity `block` halts the run for the affected page. The orchestrator drops the page from the PR rather than publishing structurally broken content.

## Why the split

A dogfood loop on PR #59 exposed the failure mode: Sonnet's probabilistic output occasionally emits bare fences without language tags. Under the old single `markdown_hygiene` rule — which was `block` severity — a language-tag miss caused the entire page to be dropped from the PR. Valid content was silently discarded because of a cosmetic defect.

The split applies the right severity to the right defect class. Language-tag misses are cosmetic; they get `warn`. Unpaired fences and heading-level jumps are structurally destructive; they stay `block`.

The file-rename approach follows the existing warn-rule precedent established by `duplicate_content`, `reading_grade`, and `sentence_variance`. No migration shim is needed: `grep` confirmed no external references to the old `markdown_hygiene` name before the rename landed.

## Rule registration

Both rules are registered in `TIER1_DEFAULT` in the lint runner. You do not need to add them explicitly to your config — `lint.tier1: default` picks them up automatically. Three tests cover the two new rules and runner registration; see `tests/test_markdown_hygiene_split.py` for the full fixture set.

## Severity reference

| Severity | Runner behavior |
|----------|----------------|
| `warn`   | Record violation, continue. Page is authored and included in the PR. |
| `block`  | Halt for the affected page. Orchestrator drops the page from the PR. |

The `block` severity is a page-level decision, not a run-level abort. Other pages in the same nightly run proceed normally.
