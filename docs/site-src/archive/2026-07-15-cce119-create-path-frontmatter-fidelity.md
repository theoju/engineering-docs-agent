---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/178
synthesized_into: []
doc_kind: decision
---

# CCE-119: create-path frontmatter fidelity

CCE-117 made the incremental authoring **create** path generator-aware: when the orchestrator creates a page in an `agent-authored` section, it computes the required frontmatter — `description`, `source_files`, `last_reviewed`, `status` — so the new page clears Tier-1 lint instead of being silently dropped. Final review on CCE-117 left two residuals open. Neither was a live failure; the content-validator's lint-drop safety net masked both. CCE-119 closes them.

## Item A: the production path trusted the LLM's write

The orchestrator computed the deterministic `agent_fields` and handed them to `page-author` as `frontmatter_template`. But the page-author contract only asked the subagent to "draft" frontmatter from that template — not to write it verbatim. On a real dispatch, page-author is an LLM that writes the file to disk, and the orchestrator never inspected what actually landed. Nothing stopped the LLM from rewording `description` below the lint floor, making it equal to the H1, or dropping `source_files`/`last_reviewed` entirely — which would get the create dropped by Tier-1 lint again.

The existing integration test only exercised the dry-run path, where the orchestrator itself writes the frontmatter skeleton and the LLM never runs. That proved the synthesis was lint-clean, not that a real dispatch preserves it. Production and dry-run diverged on *who writes the frontmatter* — exactly the "trust the subagent's own work" pattern CLAUDE.md's declare-then-discharge principle rules out.

**Fix — post-dispatch reconciliation.** After `page-author` returns `ok` for an agent-authored create, `orchestrator_runner.py` now calls a new helper, `_enforce_agent_frontmatter(path, agent_fields)`, that overwrites the written page's frontmatter block with the orchestrator's own `agent_fields`, preserving the body. It reads the file, splits off whatever leading `---` block is on disk (mirroring `archive_indexes.parse_frontmatter`'s fence convention), and re-prepends `frontmatter_contract.agent_authored_frontmatter_text(**agent_fields)`. It's idempotent, and safe against a file with no frontmatter block at all — the whole file just becomes the body.

This runs on both paths now: in production, the LLM wrote the file and reconciliation corrects any deviation; in dry-run, the synth wrote the skeleton and reconciliation is a content no-op. Both converge on the same deterministic writer.

The `page-author` subagent contract (`agents/page-author.md`) was also tightened as belt-and-suspenders: for an agent-authored create, it now explicitly requires emitting `description`, `source_files`, and `last_reviewed` verbatim from `frontmatter_template` — not reworded, shortened, or dropped — since the orchestrator's values are authoritative regardless.

A related latent bug was fixed in the same change: `agent_fields` is now kept as the pure four-field set (`description`, `source_files`, `last_reviewed`, `status`), and `doc_kind` — which is routing-only metadata, never read back from a page — is attached to a separate copy used for the `frontmatter_template` passed to page-author. Before this, `doc_kind` could have ended up mixed into `agent_fields` and passed to `agent_authored_frontmatter_text(**agent_fields)`, which doesn't accept that keyword — a `TypeError` waiting to happen the first time reconciliation ran on a page with a `doc_kind`.

## Item B: the description synthesizer hardcoded its word floor

`_synthesize_agent_description` padded a synthesized description to a hardcoded `_DESC_MIN_WORDS = 6`, silently mirroring the `description_quality` lint rule's own default. If a host raised `lint.tier1.description_quality.min_words` above 6, the synthesizer still only padded to 6, and the page would fail the host's stricter floor on the very next run.

**Fix — resolve the floor from config.** `scripts/lint/description_quality.py` gained a public `resolve_min_words(config)`, a thin wrapper over the rule's existing `_resolve_config(config)` that returns the effective `min_words` — the host's override under `lint.tier1.description_quality` if present, else the default. `_synthesize_agent_description` now takes `min_words` as a required keyword and pads deterministically to whatever floor it's given, still preserving the existing invariants (no trailing colon, description not equal to the slug-derived H1). The orchestrator resolves the floor once per run and passes it through. `_DESC_MIN_WORDS` is gone; there's one source of truth for the floor now, not two.

## Why this matters

Both gaps were dormant because the content-validator's lint-drop safety net would have caught a bad write and dropped the page rather than merging broken frontmatter. But "the safety net would have caught it" is not the same guarantee CCE-117 was meant to deliver: deterministic frontmatter that survives to the published page without depending on LLM cooperation. CCE-119 makes that guarantee hold on the production dispatch path the same way it already held on dry-run, and removes the last hardcoded constant that could silently drift from a host's lint config.

Scope was deliberately narrow: reconciliation only fires for agent-authored **creates** (edits keep their existing, possibly hand-curated frontmatter), and the bootstrap path — already generator-correct — was untouched.
