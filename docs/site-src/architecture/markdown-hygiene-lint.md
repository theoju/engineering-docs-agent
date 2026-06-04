---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/89
synthesized_into: []
---

# Markdown Hygiene Lint: Fence-Aware Heading Detection

The `markdown_hygiene_structure` lint rule enforces heading hierarchy across all agent-editable Markdown files. This page explains how the rule detects headings, why fenced-block masking exists, and what the CCE-68 fix changed.

## What the rule checks

The rule scans each file for `HEADING_RE` matches — lines that start with one or more `#` characters — and verifies that heading levels only increase by one step at a time. An H1 followed directly by an H3 is a violation; an H1 followed by an H2 followed by an H3 is not.

The check runs through `check_path()` inside the lint rule's implementation.

## The false-positive problem (CCE-68)

Before PR #89, `check_path()` applied `HEADING_RE` to the raw file text without regard for context. This caused false positives whenever a `#`-prefixed line appeared inside a fenced code block.

The concrete trigger: the bootstrap-page pattern used in CCSA includes a YAML block fenced by triple backticks. That block contains a comment line starting with `# comment`. The rule read it as an H1 heading, then flagged the real H3 that followed as an illegal H1→H3 skip — blocking the nightly run on structurally correct Markdown.

The bug was initially mis-attributed to the `page-author` subagent; CCE-67's CCSA smoke test surfaced the actual root cause in the lint rule.

## The fix: FENCE_RE-based range detection

PR #89 adds a 13-line surgical patch to `check_path()`:

1. **Collect fenced-block ranges first.** Before iterating over heading matches, the function applies `FENCE_RE` to the full file text and records the character-offset spans of every fenced block (opening fence to closing fence, inclusive).
2. **Skip headings inside a fenced range.** For each `HEADING_RE` match, the function checks whether the match's start offset falls inside any recorded fenced-block span. If it does, the match is discarded entirely — it is never presented to the hierarchy checker.
3. **Apply hierarchy validation only to real headings.** The remaining matches, all confirmed to be outside fenced blocks, go through the existing level-sequence check unchanged.

No public API changed. No imports changed. The fix is self-contained to `check_path()`.

## Regex roles

| Name | Role |
|------|------|
| `FENCE_RE` | Matches fenced code block delimiters (`` ``` `` or `~~~`). Used to build the exclusion range set before heading analysis. |
| `HEADING_RE` | Matches ATX headings (`# …` through `###### …`). Applied only to text that falls outside all fenced ranges. |

Keep these two patterns in sync if you ever expand fenced-block support (e.g., indented code blocks or HTML `<pre>` regions). The range-detection step must cover any syntax that legitimately contains `#`-prefixed lines.

## Tests

`tests/lint/test_markdown_hygiene_structure.py` covers this rule. Before PR #89 there were 5 passing tests. The PR added 2 regression tests:

- **A fenced block containing a `# comment` line must not trigger a hierarchy violation.**
- **The full bootstrap-page pattern (H1 → H2 → fenced YAML with `# comment` → H3) must pass cleanly.**

The suite now has 7 passing tests. Add a new test for any edge case you identify — fenced blocks containing multiple heading-like lines, nested fences, or files with no headings outside fences.

## Enabling the rule

`markdown_hygiene_structure` is a Tier-1 rule. Set `lint.tier1: default` in your host config to enable all 7 Tier-1 rules, including this one. You can also list it explicitly under `lint.rules` for fine-grained control. See `scripts/lint/lint_runner.py` and the host config schema for details.
