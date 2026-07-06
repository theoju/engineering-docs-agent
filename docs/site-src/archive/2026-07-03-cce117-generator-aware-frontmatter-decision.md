---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/156
synthesized_into: []
doc_kind: decision
---

# CCE-117: generator-aware frontmatter on the incremental create path

**Ticket:** [CCE-117](https://designitright.atlassian.net/browse/CCE-117)

## Problem

Every nightly `docs-agent-nightly` run was completing without a time-budget kill, yet still landing marked `(partial)`. Tier-1 lint was blocking a large, recurring set of `architecture/` pages, every one with the same two failures:

- `frontmatter_schema: missing required field(s): description, source_files, last_reviewed`
- `description_quality: missing or empty description`

The `architecture/` section is configured `generator: agent-authored`, so it requires the citation-bearing field set — `description`, `source_files`, `last_reviewed`, `status` (`scripts/frontmatter_contract.py:14`). The incremental nightly authoring path, though, always built frontmatter from the default template (`fmc.default_frontmatter_dict`) regardless of which generator owned the target section. It never called `fmc.section_generator_for` to check. So every night the agent re-authored the same ~20 architecture pages, lint dropped every one of them for the missing fields, and the run reported partial again. The pages never landed on `main`.

## Decision

The orchestrator now synthesizes `description` deterministically instead of asking the LLM for it. Three options were on the table:

1. **Let the LLM write the description**, no floor — rejected. This reintroduces the exact failure mode: a lint-guarded field whose presence depends on model output.
2. **Orchestrator synthesizes the description** — chosen. `description_quality` turns out to enforce purely mechanical rules: `min_words: 6`, not equal to the page's H1, no trailing colon. Nothing in the check is a prose-quality heuristic, so a deterministic, summary-derived sentence satisfies it reliably every time.
3. **Synth floor + LLM refine later** — deferred. It would reuse whatever Option 2 builds, so it can be added without rework if a future need for LLM-polished descriptions materializes.

## What changed

In `scripts/orchestrator_runner.py`, the create path now branches on `fmc.section_generator_for(rel, config)`. When the target section's generator is `agent-authored`, it builds frontmatter via `fmc.agent_authored_frontmatter_dict(...)`:

- **`description`** — built by a new pure helper, `_synthesize_agent_description(summaries, hint=hint)`. It composes a sentence from the batch's PR `what_changed`/`title` text, padding deterministically from the page hint when that text is too short. By construction the result clears the 6-word minimum, never equals the slug-derived H1, and never ends in a colon — no LLM call is on the critical path for a field lint depends on.
- **`source_files`** — `sorted(grounding)`, the same `_pr_changed_files` grounding list already computed for the page-author's citation inputs (CCE-110). No new computation; the create path just reuses it.
- **`last_reviewed`** — the run date.
- **`status`** — `"draft"`, matching the bootstrap path's convention.

Sections whose generator is anything other than `agent-authored` (including no `site:` block at all) keep the exact behavior they had before: `fmc.default_frontmatter_dict`, unchanged. This only ever adds a branch — it never touches the default path.

The dry-run page synthesizer got the matching change: a new agent-authored page's skeleton is now written with `fmc.agent_authored_frontmatter_text(...)` instead of always falling back to `default_frontmatter_text()`.

A second, unrelated bug in the same area was fixed alongside it: `agent_authored_frontmatter_text` now single-quotes the `description` field (escaping embedded `'` as `''`). Before this, a synthesized description containing `": "` — plausible, since descriptions are built from PR summary prose — produced invalid YAML frontmatter. The single-quoting is defensive; it doesn't depend on the synthesis helper's output shape.

## Why this, not a page-author contract change

The `page-author` subagent already receives `source_paths` grounding and could in principle write a richer description itself. But `description_quality` gates on a field the LLM would author, and letting the model own it is exactly the failure this ticket closes. Deferring that path (Option 3 above) keeps today's fix small: it's a pure function, unit-testable without a model in the loop, and it doesn't require touching the page-author agent's contract at all.

## Scope and follow-ups

The bootstrap path (`scripts/orchestrator_runner.py`) was already generator-aware before this change — only the incremental create path was missing the branch. Editing an existing page keeps its current frontmatter untouched; this only applies when a batch results in a brand-new page.

Two items were called out as non-blocking follow-ups rather than shipped in this fix:

- Tighten the `page-author` contract so a synthesized `description`/`source_files` pair survives verbatim through authoring, rather than relying on today's lint-drop safety net to catch an LLM rewording that falls below threshold.
- Have the 6-word minimum read a host's `description_quality.min_words` override instead of mirroring the default constant directly.

The PR's test plan also calls for a post-merge observation: the next nightly run should author the previously-blocked architecture pages without a `lint_block`. That observation was unchecked as of this PR and should be confirmed once a nightly has run against it.
