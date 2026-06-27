---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/61
  - https://github.com/theoju/engineering-docs-agent/pull/135
synthesized_into: []
doc_kind: architecture
description: How the tiered lint runner validates agent-authored Markdown — block vs warn severities, the Tier-1 default rule set, and per-rule opt-in for Tiers 2 and 3.
source_files:
  - scripts/lint/lint_runner.py
last_reviewed: "2026-06-27"
---

# Lint Rules

The lint runner (`scripts/lint/lint_runner.py`) validates agent-authored Markdown before it reaches the docs site. Rules are tiered: **block** rules prevent a page from being published; **warn** rules surface in the PR review but do not block it.

All Tier-1 rules are enabled by default when the host repo sets `lint.tier1: default`. Tier-2 and Tier-3 rules are opt-in per rule in the host config.

## markdown_hygiene rules

The `markdown_hygiene` family covers code fences and heading structure. It is split into two modules so that structural issues remain blocking while cosmetic issues only warn.

### markdown_hygiene_structure (severity: block)

`scripts/lint/markdown_hygiene_structure.py` catches structural problems that break MkDocs rendering:

- **Unpaired fences** — an opening triple-backtick with no matching closing fence causes MkDocs to misparse everything that follows.
- **Heading jumps** — skipping heading levels (e.g., jumping from `##` to `####` without a `###` in between) produces malformed navigation trees.

Either finding blocks the page from being published.

### markdown_hygiene_lang (severity: warn)

`scripts/lint/markdown_hygiene_lang.py` flags code fences that have no language tag (bare ` ``` ` with no identifier). Missing language tags suppress syntax highlighting but do not affect rendering or navigation, so the rule is warn-only.

The page-author agent non-deterministically emits bare fences. Treating a missing language tag as a block-severity error caused false-positive publish blocks — pages that were structurally sound but rejected because of a cosmetic fence issue. Downgrading this check to `warn` eliminates those blocks while keeping the feedback visible in the PR.

## Why the split matters

Before this split, a single `markdown_hygiene` rule ran at block severity for all hygiene checks. One bare ` ``` ` fence emitted by the agent was enough to prevent an entire page from reaching the docs site. The structural checks (unpaired fences, heading jumps) deserve block severity; the language-tag check does not.

The new module boundary makes the severity intent explicit and gives you a clear place to add future warn-only checks without touching the blocking rule.

## Agent-authored frontmatter requirement

Pages managed by the nightly pipeline must carry three agent-authored frontmatter fields: `description`, `source_files`, and `last_reviewed`. The Tier-1 lint runner checks for these fields on any page under an agent-editable path.

A page missing any of these fields causes the runner to emit a `lint_block` partial reason. The consequence is immediate: the page-author subagent's edit for that page is silently discarded, and the entire nightly run is marked `partial: true`. The run summary surfaces a `lint_block` entry in the partial reasons — but because the PR is still opened, the failure is easy to miss in the day-to-day flow.

This was the root cause of a recurring issue in PR #134: three legacy architecture pages predated the agent-authored contract (CCE-113) and lacked these fields. Every nightly run that touched those pages produced a `lint_block` partial, which also prevented the CCE-101 auto-merge gate from advancing (auto-merge requires a non-partial run).

The fix is always the same: add `description`, `source_files`, and `last_reviewed` to the page's frontmatter. Once present, the Tier-1 lint runner passes the page through normally. Use the date the fields were added as the initial `last_reviewed` value; subsequent nightly runs update it when the page is touched.

## Running the linter

```bash
python scripts/lint/lint_runner.py \
  --config .engineering-docs-agent/config.yml \
  --paths docs/**/*.md \
  --json
```

The `--json` flag emits structured output suitable for CI annotation. Without it, the runner prints human-readable findings grouped by file and rule.
