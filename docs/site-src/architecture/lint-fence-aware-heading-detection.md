---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/89
synthesized_into: []
---

# Fence-Aware Heading Detection in the Lint Subsystem

The `markdown_hygiene_structure` Tier-1 lint rule checks heading hierarchy across a document. Before PR #89, it applied `re.MULTILINE` over the full document text without filtering fenced code blocks. Any `#`-prefixed line inside a YAML or code fence was matched as a heading, producing spurious hierarchy violations.

## The Problem

The CCSA smoke test introduced by CCE-67 exercised the bootstrap page, which contained a YAML fence with `# comment` lines. Those lines triggered a false `h1→h3` jump warning. The warning blocked downstream post-merge verification, making the entire run appear to fail when the document structure was actually valid.

CCE-68 tracked the root cause: the linter had zero awareness of fenced code regions. Any `#`-prefixed content inside a fence — YAML comments, shell shebang lines, markdown code examples — was an inadvertent false positive.

## The Fix

PR #89 introduces `FENCE_RE`, a compiled regex that identifies fenced-block character ranges (both backtick fences and tilde fences) in the raw document text. The heading-detection pass then checks whether each `HEADING_RE` match offset falls inside any fence span. If it does, the match is skipped.

The result: only real headings — those outside all fences — contribute to the hierarchy check.

## Implementation Details

Fence detection runs once per document before the heading scan. It produces a list of `(start, end)` integer pairs representing fenced regions. Each `HEADING_RE` match supplies a `match.start()` offset; a simple range membership test determines whether to include it.

No third-party dependencies were added. The implementation uses stdlib `re` exclusively, consistent with the project's stdlib-first policy.

## Effect on Existing Rules

Only `markdown_hygiene_structure` is affected. The other six Tier-1 rules operate on line-split or token-level representations that are not subject to the same raw-offset ambiguity.

## When to Extend This Pattern

If you add a new lint rule that operates on raw document text via `re.MULTILINE`, apply the same fence-exclusion guard. The pattern is: compile `FENCE_RE`, collect fence spans once, then filter your match list before processing. Rules that operate on pre-parsed line arrays (after splitting on `\n`) are not affected — fenced lines remain distinguishable in that representation through other means.
