---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/61
synthesized_into: []
---

# Lint Rules

The lint system validates agent-authored and human-authored docs before they land. Rules are organized in three tiers. Tier-1 runs by default when `lint.tier1: default` is set in your host config; Tier-2 and Tier-3 are opt-in per rule.

Run the linter against a path set:

```bash
python scripts/lint/lint_runner.py --config .engineering-docs-agent/config.yml --paths docs/**/*.md --json
```

The runner lives at `scripts/lint/lint_runner.py`. Each rule is a standalone script in `scripts/lint/`.

## Severity levels

A rule declares one of three severities:

- **`block`** — the page is removed from the agent's output and flagged in the PR. Use this for defects that break MkDocs rendering or produce corrupted output.
- **`warn`** — the issue is logged and surfaced in the PR body, but the page ships. Use this for probabilistic LLM slips that degrade quality without breaking the site.
- **`info`** — advisory only; never surfaces in CI.

## `markdown_hygiene` rules

The original monolithic `markdown_hygiene` rule was split into two distinct rules in PR #61 (CCE-46) after a dogfood-loop incident: `page-author` occasionally emits bare code fences without language tags — a probabilistic LLM slip — which triggered a `block`-level failure and caused entire pages to be dropped from the docs PR.

### `markdown_hygiene_lang`

**Severity:** `warn`

Checks that every opening code fence carries a language tag (e.g., ` ```python ` or ` ```bash `). Missing tags are a style defect; they do not prevent MkDocs from rendering the page.

Because `page-author` can omit language tags under certain generation conditions, this rule warns rather than blocks. The page still ships; the issue is visible in the PR body so a human reviewer can patch it.

### `markdown_hygiene_structure`

**Severity:** `block`

Checks for two structural defects that break MkDocs rendering:

1. **Unpaired fences** — an opening ` ``` ` with no matching close, or vice versa.
2. **Heading jumps** — skipping heading levels (e.g., `##` directly to `####`), which MkDocs parses incorrectly.

Either defect causes a block. The page is removed from the agent's output and flagged in the run's partial-reasons list.

## Adding a rule

Each rule is a Python module that exports a `check(path: str, content: str) -> list[LintResult]` function. Register it in `scripts/lint/lint_runner.py` under the appropriate tier. Write a failing pytest first, then implement.

Keep severity conservative: default to `warn` unless the defect demonstrably breaks the rendered site. You can always promote a `warn` to `block` after you observe false-positive rates in the dogfood loop.
