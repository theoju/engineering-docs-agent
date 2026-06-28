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
last_reviewed: "2026-06-28"
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

## agent_authored_required (severity: block)

The `agent_authored_required` rule enforces the frontmatter contract on agent-authored pages. Any page that the nightly runner writes must carry three fields: `description`, `source_files`, and `last_reviewed`. Missing any one of them raises a `lint_block` partial reason and makes the run ineligible for CCE-101 auto-merge.

Pages written before the contract was codified will fail this check retroactively the first time the nightly runner touches them. The fix is to add the three fields directly in the frontmatter block. CCE-113 tracked three such pages in the `architecture/` lens (`bootstrap-fail-fast.md`, `index.md`, `lint-rules.md`) that accumulated `lint_block` partial reasons on every run until their frontmatter was brought into compliance (PR #135).

**`description`** — a one-sentence summary of what the page covers. The lint runner checks that it is a non-empty string.

**`source_files`** — a list of repo-relative paths the page's claims are grounded in. The runner checks that the list is present and non-empty; it does not verify that the files exist at lint time.

**`last_reviewed`** — an ISO-8601 date (`"YYYY-MM-DD"`) indicating when a human or the agent last confirmed the page is accurate. The runner checks the format but does not enforce a staleness threshold at Tier-1 (staleness is a Tier-2 opt-in).

## Running the linter

```bash
python scripts/lint/lint_runner.py \
  --config .engineering-docs-agent/config.yml \
  --paths docs/**/*.md \
  --json
```

The `--json` flag emits structured output suitable for CI annotation. Without it, the runner prints human-readable findings grouped by file and rule.
