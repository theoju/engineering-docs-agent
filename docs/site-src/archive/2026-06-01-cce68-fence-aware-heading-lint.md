---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/89
synthesized_into: []
---

# CCE-68: Fence-Aware Heading Hierarchy Lint (2026-06-01)

The `markdown_hygiene_structure` Tier-1 lint rule was producing false-positive heading-hierarchy violations on structurally valid Markdown. This record captures the root cause, the fix, and the investigation path that surfaced it.

## Problem

The rule flagged an illegal heading jump whenever a `#`-prefixed line appeared inside a fenced code block. The canonical failure pattern is the bootstrap-page layout:

```markdown
# Page title          ← h1
## Overview           ← h2
```yaml
# this is a YAML comment
```
### Detail            ← h3 (valid under h2, not a jump)
```

The rule's `check_path()` function was matching `HEADING_RE` against every line without first checking whether the match fell inside a fence. The YAML comment matched as an h1, which made the subsequent h3 look like an illegal h1→h3 jump. The lint run failed; the nightly docs-agent PR on CCSA was blocked.

## Investigation

CCE-67's smoke test surfaced the failure. Early investigation misattributed it to a `page-author` output bug — the authored page's heading structure looked suspicious. Tracing the lint output character offsets back to the source file revealed the misattribution: `page-author` was producing correct Markdown; the lint rule was misreading it.

## Fix

A 13-line surgical change in `check_path()`:

1. Before iterating heading matches, scan the file once with `FENCE_RE` to build a list of `(start, end)` byte-offset ranges for all fenced blocks.
2. For each `HEADING_RE` match, check whether the match's character offset falls inside any of those ranges. Skip matches that do.

The fix is additive — no existing behavior changes for unfenced headings. Files with no fenced blocks take the same code path as before.

## Decision

Fence-range pre-computation was chosen over a stateful line-by-line parser because `check_path()` already works with regex matches over the full file string. Keeping the same structure meant minimal blast radius and a single coherent diff. A stateful parser would have required restructuring the function and expanding test surface.

## Impact

After the fix, the bootstrap-page pattern passes Tier-1 lint clean. The nightly docs-agent PR unblocks on host repos that use fenced YAML blocks with inline comments in their docs pages.

No rule behavior changes for any Markdown that does not contain fenced blocks with `#`-prefixed content.
