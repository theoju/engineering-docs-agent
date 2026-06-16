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
last_reviewed: "2026-06-16"
---

# Lint Rules

The lint runner (`scripts/lint/lint_runner.py`) validates agent-authored Markdown before it reaches the docs site. Rules are tiered: **block** rules prevent a page from being published; **warn** rules surface in the PR review but do not block it.

All Tier-1 rules are enabled by default when the host repo sets `lint.tier1: default`. Tier-2 and Tier-3 rules are opt-in per rule in the host config.

## frontmatter rules

The `frontmatter` family enforces the fields that downstream pipeline stages depend on. Both rules run at block severity — a missing or malformed frontmatter block makes a page unpublishable and unindexable.

### frontmatter_schema (severity: block)

The `frontmatter_schema` rule validates that every agent-authored page carries the `AGENT_AUTHORED_REQUIRED` fields: `description`, `source_files`, `last_reviewed`, and `status`. Pages created before this contract existed would fail this check on every nightly pass, producing a `lint_block` partial reason that caused the orchestrator to drop the edit silently.

PR #135 retroactively added the missing fields to three legacy architecture pages (`bootstrap-fail-fast.md`, `index.md`, `lint-rules.md`) that predated the contract. Without that fix, those pages accumulated silently-dropped edits across multiple nightly runs, including the 2026-06-10T18 catch-up run (PR #134) where `index.md` was dropped for exactly this reason.

If you create a new page under an agent-editable path and the `frontmatter_schema` rule blocks it, the missing fields are always the same four: add `description` (a non-empty string), `source_files` (a list of repo-relative paths the page documents), `last_reviewed` (ISO date string), and `status` (`draft` or `published`).

### description_quality (severity: block)

The `description_quality` rule is registered as a Tier-1 default alongside `frontmatter_schema`. It blocks any page where the `description` field is absent, empty, or below a configurable minimum token count.

The rule fires during the post-write lint pass — after `dispatch_verified` confirms the artifact exists but before the PR is opened. Pages that fail are added to `partial_reasons` and flagged in the Slack/email digest rather than published with a thin description.

Because `description_quality` is Tier-1, it is **on by default**. Hosts that need to disable it must set `lint.tier1.description_quality: false` in their config. See [Bootstrap fail-fast mechanisms](bootstrap-fail-fast.md) for how `dispatch_verified` integrates with this rule.

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

## Running the linter

```bash
python scripts/lint/lint_runner.py \
  --config .engineering-docs-agent/config.yml \
  --paths docs/**/*.md \
  --json
```

The `--json` flag emits structured output suitable for CI annotation. Without it, the runner prints human-readable findings grouped by file and rule.
