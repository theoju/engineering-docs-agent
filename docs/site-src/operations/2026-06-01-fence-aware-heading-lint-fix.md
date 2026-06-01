---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/89
synthesized_into: []
---

# Fence-aware heading lint fix (CCE-68)

The `markdown_hygiene_structure` rule now ignores `#`-prefixed lines that appear inside fenced code blocks. Before this fix, a YAML comment like `# lens and page mappings` inside a ` ```yaml ``` ` block was matched by `HEADING_RE` as an h1 heading, producing spurious heading-hierarchy-jump errors on pages that were structurally correct.

## What changed

The fix is confined to `check_path()` in the lint rule. It builds a list of `(start, end)` offset ranges from paired `FENCE_RE` matches over the raw file content, then skips any `HEADING_RE` match whose `.start()` falls inside one of those ranges. The change is 13 lines; there is no signature change and no new imports.

Two regression tests cover the fix:

- A fenced YAML block containing a `# comment` line — previously a false-positive h1.
- A fenced Markdown snippet containing a `## heading` line — previously a false-positive h2.

## User-visible impact

If you have pages where a fenced code block contains `#`-prefixed lines (YAML comments, shell comments, embedded Markdown examples), those pages will no longer trigger heading-hierarchy failures. You do not need to change any page content; the fix is entirely on the lint side.

The false-positive surfaced during CCE-67's smoke test: the lint stage blocked a bootstrap page authored as h1 → h2 → fenced YAML (with `# comment`) → h3. The lint rule read the YAML comment as an h1 and flagged the subsequent h3 as a hierarchy jump. The root cause was initially misattributed to page-author; CCE-68 corrected the attribution to the lint rule itself.

## Known gaps

Two fence styles are still unmasked:

- **Indented fences** (4-space-prefixed code blocks) are not detected by `FENCE_RE` and remain unmasked.
- **Tilde-style fences** (` ~~~ `) are also not detected.

Both are out of scope for this fix and tracked separately. If your pages use these styles and contain `#`-prefixed lines, the rule may still produce false positives.
