---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/156
synthesized_into: []
doc_kind: decision
---

# CCE-117: generator-aware frontmatter on the incremental create path

**Date:** 2026-07-03
**Ticket:** CCE-117
**PR:** #156

## The problem

Every nightly run was completing — no time-budget kill, CCE-114 was healthy — but it kept landing marked **partial**. The cause was the same every night: Tier-1 lint blocked roughly 20 architecture pages with

- `frontmatter_schema: missing required field(s): description, source_files, last_reviewed`
- `description_quality: missing or empty description`

Those pages don't exist on `main`. The agent re-authors them every run, lint drops them, and the partial recurs.

## Root cause

The `architecture/` section is configured `generator: agent-authored`, so `frontmatter_contract.required_fields` (`scripts/frontmatter_contract.py:17-21`) requires `AGENT_AUTHORED_REQUIRED = ("description", "source_files", "last_reviewed", "status")` for any page in it, not the `DEFAULT_REQUIRED = ("status", "sources", "synthesized_into")` set that most pages get.

The incremental nightly authoring path never checked which set applied. It built `fm_template = fmc.default_frontmatter_dict(...)` unconditionally, regardless of the target section's generator — the same for the dry-run synth path that writes skeletons for brand-new pages. `section_generator_for` already existed and was already wired into the bootstrap path (the one-time site scaffold), but nobody had taught the nightly create path the same branch.

## The fix

`scripts/orchestrator_runner.py` now branches on `fmc.section_generator_for(rel, config)` before building frontmatter for a new page. When the target section's generator is `"agent-authored"`, the runner calls `fmc.agent_authored_frontmatter_dict(...)` instead of the default; every other generator (including `None`) keeps the old default-template behavior exactly. Edits are untouched — this only applies on the `create` branch, so an existing page's frontmatter is never rewritten.

Populating `description` without an LLM in the loop was the part that mattered. The design brainstorm ranked three options and picked deterministic synthesis in the orchestrator over having the page-author LLM write the field, or a synth-floor-plus-LLM-refine hybrid — both of the alternatives leave a lint-guarded field dependent on model output, which is the exact failure mode being fixed. The tiebreaker: `description_quality` is purely mechanical (minimum 6 words, must not equal the page's H1, no trailing colon) — no prose-quality judgment — so a deterministic, summary-derived sentence satisfies it reliably every time.

That synthesis lives in a new helper, `_synthesize_agent_description(summaries, *, hint)`, a sibling of `_synthesize_core_page`. It builds a one-line description from the batch's PR summaries (preferring the first non-empty `what_changed`, falling back to `title`), pads from `hint` when the summary text is too short to clear the word-count floor, and is deterministic and non-raising by construction — malformed summary entries are skipped rather than propagated.

The rest of the agent-authored fields are populated from data the runner already had on hand:

| field           | value                                     |
| --------------- | ------------------------------------------ |
| `description`   | `_synthesize_agent_description(...)`       |
| `source_files`  | `sorted(grounding)` — the same `_pr_changed_files` grounding CCE-110 already computes for author citations |
| `last_reviewed` | the run date |
| `status`        | `draft` |
| `doc_kind`      | re-attached when present on the target |

A second, smaller bug rode along in the same PR: `agent_authored_frontmatter_text` (the dry-run synth's YAML writer) now single-quotes the `description` field. A synthesized sentence built from PR summary prose can legitimately contain a colon-space sequence, which previously produced invalid YAML frontmatter. Single quotes are escaped by doubling per the standard YAML rule, so the module stays stdlib/yaml-free.

The dry-run path mirrors the production branch exactly, so the test suite exercises the real create-path behavior rather than a parallel code path that could drift.

## What this doesn't fix yet

Two follow-ups came out of review, neither blocking:

- The page-author contract doesn't yet guarantee the deterministic `description`/`source_files`/`last_reviewed` survive an LLM rewrite of the page verbatim — a future pass could clobber them.
- `_DESC_MIN_WORDS` mirrors the lint rule's default constant rather than reading a host's `min_words` override, so a host that raises the threshold in config could desync from the synth floor.

Confirming the previously-blocked architecture pages now author cleanly is a post-merge observation against the next scheduled nightly, not something this PR's test suite could assert directly.

## References

- Spec: `docs/superpowers/specs/2026-06-27-cce117-agent-authored-create-frontmatter-design.md`
- Plan: `docs/superpowers/plans/2026-06-27-cce117-agent-authored-create-frontmatter.md`
- `scripts/frontmatter_contract.py`
- `scripts/orchestrator_runner.py`
- Tests: `tests/orchestrator/test_agent_authored_create_frontmatter.py`, `tests/orchestrator/test_synthesize_description.py`
