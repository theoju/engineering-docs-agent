---
description: 'Explains how the nightly incremental create path became generator-aware so agent-authored architecture pages stop failing Tier-1 lint on missing description, source_files, and last_reviewed fields.'
source_files:
  - CHANGELOG.md
  - docs/superpowers/plans/2026-06-27-cce117-agent-authored-create-frontmatter.md
  - docs/superpowers/specs/2026-06-27-cce117-agent-authored-create-frontmatter-design.md
  - scripts/frontmatter_contract.py
  - scripts/orchestrator_runner.py
  - tests/orchestrator/test_agent_authored_create_frontmatter.py
  - tests/orchestrator/test_synthesize_description.py
last_reviewed: '2026-07-06'
status: draft
doc_kind: architecture
---

# Generator-aware frontmatter on the incremental create path

Every nightly `docs-agent-nightly` run was completing without a time-budget
kill, yet it kept coming back `(partial)`. The cause was Tier-1 lint: the
2026-06-26 run (PR #154) blocked 20 architecture pages with
`frontmatter_schema: missing required field(s): description, source_files,
last_reviewed` and `description_quality: missing or empty description`. The
agent re-authored the same pages every night and lint dropped them every
night — a permanent partial, not a transient one.

## Root cause

The `architecture/` section in `site.sections` is configured
`generator: agent-authored`, which routes it through
`AGENT_AUTHORED_REQUIRED = ("description", "source_files", "last_reviewed",
"status")` (`scripts/frontmatter_contract.py:14`) instead of the default
`("status", "sources", "synthesized_into")` set.

The incremental create path never consulted that routing. It called
`fmc.default_frontmatter_dict(...)` unconditionally
(`scripts/orchestrator_runner.py`, historically around line 1463), regardless
of which section generator owned the target page. `section_generator_for`
already existed and was already wired into the bootstrap path — it just
wasn't called from the nightly incremental authoring loop.

## The fix

The create branch in `orchestrator_runner.py` now checks
`fmc.section_generator_for(rel, config) == "agent-authored"` before building
`fm_template`. When it matches, it builds frontmatter with
`fmc.agent_authored_frontmatter_dict(...)`:

- `description` — synthesized by `_synthesize_agent_description(batch_summaries, hint=hint)`.
- `source_files` — `sorted(grounding)`, where `grounding` is the same
  `_pr_changed_files(batch_prs)` result already computed for the page-author's
  CCE-110 citation-grounding input. The two features now share one call.
- `last_reviewed` — `now[:10]`, the run's date.
- `status` — `"draft"`.

Edits are untouched: this only fires on `action == "create"`. An existing
page keeps whatever frontmatter it already has. Default-generator sections
(changelog, archive, api, or no `site:` block at all) keep calling
`fmc.default_frontmatter_dict(...)` exactly as before — nothing about this
change touches them.

## `_synthesize_agent_description`: deterministic by construction

`description_quality` turned out to be purely mechanical
(`min_words: 6`, `forbid_equal_to_title`, `forbid_trailing_colon` — no prose
heuristic). That meant an LLM wasn't required to satisfy it; a pure function
could guarantee it by construction instead, with no dependency on model
output for a lint-guarded field.

`_synthesize_agent_description(summaries, *, hint)` in
`scripts/orchestrator_runner.py`:

- Prefers the first non-empty `what_changed` across `summaries` (falls back
  to `why` only if no batch entry has `what_changed`); malformed entries
  (non-dict, `None` values) are skipped rather than raising.
- Pads deterministically toward the 6-word floor when the source text is
  short, and falls back to a hint-derived phrase when `summaries` is empty.
- Strips a trailing colon unconditionally, even if the source text ends in
  one.
- Never equals the slug-derived page H1 (`# {hint}`).

Same inputs always produce the same string — no clock, no RNG, no model
call. `tests/orchestrator/test_synthesize_description.py` pins all of this:
word-count floor, non-colon-termination, inequality with the title,
determinism across repeated calls, `what_changed`-over-`why` precedence, and
tolerance of malformed entries.

## The YAML side bug

`frontmatter_contract.py`'s `agent_authored_frontmatter_text` also single-
quotes the `description` value now, escaping embedded single quotes by
doubling them (`'` → `''`, the standard YAML single-quoted-scalar rule). This
closes a latent bug: an unquoted description containing `": "` (a colon
followed by a space) is invalid YAML on parse, which the dry-run page
synthesizer could have emitted before this fix landed. `source_files` is
still emitted as a YAML list (or `source_files: []` when `grounding` is
empty — a PR that changed no files is a valid, not an error, case).

## Scope

Out of scope for this change: the bootstrap path
(`scripts/orchestrator_runner.py`, bootstrap sections), which was already
generator-aware before this fix; a page-author contract change to let the
LLM refine the synthesized description (deferred — would need a floor-then-
refine design, tracked only as a possible future extension, not a ticket);
and pre-seeding the 20 pages that were blocked pre-fix, which isn't
necessary since they now author cleanly on the next nightly run.

## Known follow-ups

Two items called out in the PR are not yet done:

- The page-author contract doesn't yet guarantee the synthesized
  `description`/`source_files` survive verbatim on an agent-authored create —
  today's lint-drop is still the safety net if an LLM rewording falls below
  the word-count threshold.
- `_DESC_MIN_WORDS` mirrors the default `min_words: 6` constant rather than
  reading a host's `description_quality.min_words` override.

The PR's own test-plan item — confirming the next nightly authors the
previously-blocked architecture pages without `lint_block` — was unchecked
as of this change and should be verified once that run has happened.
