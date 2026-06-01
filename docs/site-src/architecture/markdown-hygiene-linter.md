---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/89
synthesized_into: []
---

# Markdown Hygiene Linter

The markdown hygiene linter (`scripts/lint/`) enforces structural and stylistic rules on all agent-authored and human-authored documentation. Rules are tiered: Tier-1 runs by default; Tier-2 and Tier-3 are opt-in per rule in the host config's `lint` block.

## Rule: `markdown_hygiene_structure`

`markdown_hygiene_structure` checks heading hierarchy — every heading level jump must be sequential (no skipping from `##` to `####`). The rule runs inside `check_path()` and emits a warning for each violation it finds.

## Fence-aware heading detection

Prior to CCE-68, the rule produced false positives whenever a fenced code block contained a `#`-prefixed line. A block such as:

````markdown
```python
# This is a comment
## Another comment
```
````

caused the linter to report spurious hierarchy-jump warnings because `HEADING_RE` matched those lines without knowing they were inside a fence.

The fix, landed in PR #89, makes `check_path()` fence-aware in two steps:

1. Scan the file once for all `FENCE_RE` matches and pair them into `(start, end)` character-offset spans.
2. For every `HEADING_RE` match, skip it if its character offset falls inside any of those spans.

The update is 13 lines inside `check_path()`. No other rules were changed.

## Regression tests

PR #89 added 39 lines of regression tests to the lint test suite. The tests cover:

- A fenced block whose body contains `# comment` and `## section` lines — zero violations expected.
- A document with a real heading hierarchy jump — violation expected.
- A document mixing fenced blocks with real heading jumps — only the real violations reported.

Run the full lint test suite with:

```bash
python3 -m pytest tests/test_lint.py -v
```

## How the rule is enabled

`markdown_hygiene_structure` is a Tier-1 rule. It runs automatically when `lint.tier1: default` is set in `.engineering-docs-agent/config.yml` — which is the default for all host repos. You do not need to name it explicitly unless you want to disable it.

## Invoking the linter

Run the linter directly against any set of Markdown paths:

```bash
python scripts/lint/lint_runner.py \
  --config .engineering-docs-agent/config.yml \
  --paths docs/**/*.md \
  --json
```

The `--json` flag emits structured output suitable for CI annotation. Without it, the runner prints human-readable warnings to stdout.
