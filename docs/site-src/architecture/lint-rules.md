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
last_reviewed: "2026-06-19"
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

## Frontmatter rules and the `AGENT_AUTHORED_REQUIRED` contract

The lint runner enforces a set of required frontmatter fields on agent-authored pages. The rule is defined against the `AGENT_AUTHORED_REQUIRED` constant and demands `description`, `source_files`, `last_reviewed`, and `status` on every page the agent writes.

A missing field produces a `lint_block` finding — block severity. When the page-author subagent edits a page that lacks these fields, the orchestrator marks that page's result as partial. A partial page causes the entire docs-agent PR to carry `partial: true` in its body, which prevents CCE-101 auto-merge from firing.

The consequence is a recurring drop loop: the nightly run touches the page, hits `lint_block` on the missing frontmatter, drops the edit, opens a partial PR, and auto-merge skips it. The fix is to ensure the fields are present on every page before the agent first edits it. PR #135 retroactively added the required fields to three architecture pages that predated the contract.

If you add a new page manually, include all four fields. If you inherit a page from before the `AGENT_AUTHORED_REQUIRED` contract, add them before the next nightly run — otherwise the first agent edit will produce a partial PR.

## Running the linter

```bash
python scripts/lint/lint_runner.py \
  --config .engineering-docs-agent/config.yml \
  --paths docs/**/*.md \
  --json
```

The `--json` flag emits structured output suitable for CI annotation. Without it, the runner prints human-readable findings grouped by file and rule.
