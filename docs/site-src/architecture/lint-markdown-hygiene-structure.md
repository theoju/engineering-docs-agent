---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/89
synthesized_into: []
---

# Lint rule: markdown_hygiene_structure

`scripts/lint/markdown_hygiene_structure.py` is a **block-severity** Tier-1 lint rule. It catches two categories of structural defect that break MkDocs rendering or produce malformed HTML: unpaired code fences and heading-hierarchy jumps.

A separate sibling rule, `markdown_hygiene_lang.py`, handles the cosmetic (warn-severity) check for fences without a language tag. Splitting the two prevents a missing language tag from triggering the block-severity path and dropping the authored page.

## What the rule checks

**Unpaired fences** — the rule counts all `` ``` `` delimiters in the file. An odd total signals a missing opener or closer. The orchestrator treats this as a block error and will not publish the page.

**Heading hierarchy** — the rule walks `HEADING_RE` matches in source order and ensures each heading descends by at most one level (e.g., `##` may follow `#`, but `###` may not follow `#` directly). A jump triggers the `lint_block` outcome.

## Fence-aware heading detection (CCE-68)

Prior to PR #89, the rule ran `HEADING_RE` across the raw file text, including the contents of fenced code blocks. A `#`-prefixed line inside a YAML or Markdown example fence — e.g., `# lens and page mappings` — was counted as an H1 heading. The bootstrap-page pattern (`# H1` → `## H2` → fenced YAML with `# comment` → `### H3`) therefore appeared to jump from H1 to H3, triggering a false-positive block error on structurally valid documents. This was blocking the docs-agent nightly PR on CCSA.

The fix adds a 13-line change in `check_path()` (`scripts/lint/markdown_hygiene_structure.py:43–48`):

1. Pairs all `FENCE_RE` matches greedily into `(start, end)` offset ranges.
2. Defines `_in_fence(offset)` to test whether a character offset falls inside any such range.
3. Skips any `HEADING_RE` match where `m.start()` is inside a fenced region.

No new imports were added. The public signature of `check_path()` is unchanged.

## Known limitations

Indented code blocks (4-space prefix) and tilde-fenced blocks (`~~~`) are **not** masked. A `#` line inside those contexts will still be counted as a heading. This is consistent with pre-existing behaviour and is noted as out-of-scope in the CCE-68 spec.

## Test coverage

`tests/lint/test_markdown_hygiene_structure.py` has 7 passing tests. Two regression tests were added for CCE-68:

- `test_fenced_yaml_comment_does_not_trigger_hierarchy_jump` — the canonical bootstrap-page pattern; verifies `rc == 0`.
- `test_heading_inside_fenced_block_is_ignored` — a fenced Markdown example containing `# Document title`; verifies the subsequent real `### H3` is not flagged.

Run the suite:

```bash
python3 -m pytest tests/lint/test_markdown_hygiene_structure.py -v
```

## Post-merge validation

After landing PR #89, re-trigger the `docs-agent-nightly` workflow on CCSA. Fenced `#` patterns in agent-authored pages must no longer produce `lint_block` results. Check `.engineering-docs-agent/state.json` for `partial: false` and no `lint_block` entries in the run log.
