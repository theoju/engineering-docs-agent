---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/156
synthesized_into: []
doc_kind: decision
---

# CCE-117: generator-aware frontmatter on the incremental create path

Every nightly `docs-agent-nightly` run was completing — no CCE-114 time-budget
kill — but landing marked `(partial)` anyway. The 2026-06-26 run (PR #154)
blocked 20 pages, all under `architecture/`, all with the same pair of Tier-1
failures:

- `frontmatter_schema: missing required field(s): description, source_files, last_reviewed`
- `description_quality: missing or empty description`

The pages never landed. The agent re-authored the same 20 targets — five
orchestrator pages plus ~15 others — every night, and lint dropped every one
of them, every time.

## Root cause

`architecture/` is configured `generator: agent-authored`, so pages there need
the citation-bearing field set: `description`, `source_files`,
`last_reviewed`, `status` (`AGENT_AUTHORED_REQUIRED` in
`scripts/frontmatter_contract.py:14`). Everything else keeps the historical
default set: `status`, `sources`, `synthesized_into`
(`DEFAULT_REQUIRED`, `scripts/frontmatter_contract.py:13`).

The incremental nightly create path never checked which set applied. It
always built `fmc.default_frontmatter_dict(...)`, regardless of the target
section's configured generator — the generator-aware machinery
(`fmc.section_generator_for`) was wired into the bootstrap path only, never
into the nightly incremental path. So every agent-authored create was missing
three required fields by construction, and lint blocked it on arrival.

## Fix

`scripts/orchestrator_runner.py` now calls
`fmc.section_generator_for(rel, config)` on the create path and branches:

- If the target section's generator is `agent-authored`, it builds
  `fmc.agent_authored_frontmatter_dict(...)` — `description` from a new
  deterministic helper (`_synthesize_agent_description`), `source_files` from
  `sorted(grounding)` (the same `_pr_changed_files(batch_prs)` grounding
  already computed for the CCE-110 citation guard), `last_reviewed` set to the
  run date, `status: "draft"`.
- Otherwise, it keeps the existing `fmc.default_frontmatter_dict(...)` call
  unchanged. Default-section pages are unaffected.

This is create-only: an `edit` action keeps whatever frontmatter the existing
page already has.

### Why a deterministic helper, not the LLM

`description_quality` is purely mechanical: minimum 6 words, must not equal
the page's H1, must not end in a colon. Nothing in the check evaluates prose
quality. Handing description synthesis to the page-author subagent would
reintroduce the exact failure mode this fix closes — a lint-guarded field
whose population depends on an LLM getting wording right on every run. The
chosen design instead builds the description from the batch's PR summaries
deterministically, so it satisfies all three invariants by construction, on
every run, with no model call in the loop.

### The YAML bug

`agent_authored_frontmatter_text` (the dry-run frontmatter synthesizer) now
single-quotes the `description` field. A synthesized sentence built from PR
`what_changed` text can contain a colon — unquoted, that turns the line into
invalid YAML the moment a summary happens to have one. Single quotes with
doubled-quote escaping keep the module stdlib-only, no `yaml` dependency
required to write frontmatter.

## What didn't change

The bootstrap path (`scripts/orchestrator_runner.py:938` and `:2106`) already
called `section_generator_for` correctly — this fix only closes the gap on
the incremental nightly path. An LLM-refined description on top of the
deterministic floor was considered and deferred: it would need a page-author
contract change and buys nothing that the mechanical lint check requires.

## Status as of this page

Two follow-ups from review are still open:

- Tightening the page-author contract so these deterministic frontmatter
  fields survive verbatim rather than being subject to rewrite.
- Making `_DESC_MIN_WORDS` read a host's `min_words` override instead of the
  hardcoded floor.

The observational acceptance criterion (AC4) is also still pending: the next
scheduled nightly run needs to confirm that the previously-blocked
architecture pages — `orchestrator.md`, `meta-orchestrator.md`, and roughly
18 others — now author without `lint_block`.
