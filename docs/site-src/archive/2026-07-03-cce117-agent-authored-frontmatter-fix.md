---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/156
synthesized_into: []
doc_kind: decision
---

# Decision: Generator-Aware Frontmatter on the Incremental Create Path (CCE-117)

**Date:** 2026-07-03  
**PR:** [#156](https://github.com/theoju/engineering-docs-agent/pull/156)  
**Tickets:** CCE-117

## Problem

Every nightly run completed without a time-budget kill (CCE-114 is healthy), but was still marked `(partial)`. The 2026-06-26 run (PR #154) blocked 20 pages, all with the same two Tier-1 lint failures:

- `frontmatter_schema: missing required field(s): description, source_files, last_reviewed`
- `description_quality: missing or empty description`

Five orchestrator pages plus roughly fifteen others never landed on `main`. The agent re-authored them every night, and lint dropped them every night. The partial recurred indefinitely.

## Root cause

`scripts/frontmatter_contract.py:14` defines two required field sets, keyed by a site section's configured generator:

- `DEFAULT_REQUIRED = ("status", "sources", "synthesized_into")`
- `AGENT_AUTHORED_REQUIRED = ("description", "source_files", "last_reviewed", "status")`

The `architecture/` section is configured `generator: agent-authored`, so its pages need the second set. The generator-aware machinery already existed and was correctly wired into the **bootstrap** path (`scripts/orchestrator_runner.py:938` and `:2106`), but the **incremental nightly create path** hardcoded the default template regardless of the target section's generator — it never called `fmc.section_generator_for(rel, config)`. Any new page created under `architecture/` on the incremental path got `status`/`sources`/`synthesized_into` and nothing else, which is exactly the shape Tier-1 lint rejects for that section.

## Decision

Branch the incremental create path on `fmc.section_generator_for(rel, config)`, same as the bootstrap path already does, and add one new deterministic helper to make the `description` field satisfiable without an LLM in the loop.

Three options were weighed for populating `description`:

| Option | Verdict | Reason |
|---|---|---|
| **2. Orchestrator synthesizes it deterministically** | **chosen** | Minimal complete fix; unit-testable; no LLM dependence on a lint-guarded field. |
| 3. Synth floor + LLM refine | deferred | Adds prose polish but requires a page-author contract change and non-determinism; the synth floor it would reuse is exactly what option 2 builds, so it can be layered on later with zero rework. |
| 1. LLM writes it, no floor | rejected | Reintroduces the exact failure mode — a guarded field whose population depends on model output. |

The tiebreaker: `description_quality` is purely mechanical (`min_words: 6`, `forbid_equal_to_title` against the page H1, `forbid_trailing_colon`). No prose-quality heuristic exists, so a deterministic, summary-derived sentence satisfies it reliably every time.

## What changed

**New helper — `_synthesize_agent_description(summaries, *, hint)`** in `scripts/orchestrator_runner.py`, sibling to `_synthesize_core_page`. Pure and deterministic (same inputs, same output; no clock or RNG). It prefers the first non-empty `what_changed` (falling back to `why`) across the batch's summaries, composes a sentence, pads with a fixed descriptive clause when the source text is under six words, and strips any trailing colon. Malformed summary entries (non-dicts, `None` fields) are skipped rather than raising.

**Production template branch** (`scripts/orchestrator_runner.py` around the batch-authoring loop): when the target is a `create` and `fmc.section_generator_for(rel, config) == "agent-authored"`, the runner builds `agent_fields` via `fmc.agent_authored_frontmatter_dict(description=_synthesize_agent_description(...), source_files=sorted(grounding), last_reviewed=run_date, status="draft")`. `grounding` is the same `_pr_changed_files(batch_prs)` set already computed for CCE-110's citation grounding, so `source_files` cites real repo paths the summarized PRs touched — no separate lookup. Every other generator, including no generator at all, keeps the unconditional `fmc.default_frontmatter_dict(...)` path unchanged. Edits are untouched regardless of section: this only fires on `create`.

**Dry-run synth fix.** `fmc.agent_authored_frontmatter_text` had a latent bug: it interpolated `description` into the YAML block unquoted. A synthesized description built from `what_changed` text routinely contains a colon (e.g. `"Covers <topic>: <what_changed>."`), which is not valid unquoted YAML scalar syntax. The fix single-quotes the value and escapes embedded single quotes by doubling them (the standard YAML single-quoted scalar rule), keeping the module stdlib/yaml-library-free.

## Edge cases

| Condition | Behavior |
|---|---|
| `section_generator_for` returns `None` or a non-agent-authored generator | Default template, unchanged |
| Batch's PRs touched no files (`grounding` empty) | `source_files: []` — valid per `agent_authored_frontmatter_dict` |
| Empty or thin `summaries` | Deterministic hint-derived fallback, still ≥6 words and not equal to the slug title |
| Malformed summary entries | Helper skips them silently; never raises |

## Test coverage

Unit tests for `_synthesize_agent_description` (`tests/orchestrator/test_synthesize_description.py`) pin word-count floor, non-equality with the slug-derived H1, trailing-colon stripping even when the source text ends in one, determinism, empty-input fallback, malformed-entry tolerance, and that `what_changed` wins over `why` when both are present.

Integration tests (`tests/orchestrator/test_agent_authored_create_frontmatter.py`) cover the RED→GREEN case per the CLAUDE.md verification invariant — run the incremental path against a fixture host with an `agent-authored` section, then invoke the real Tier-1 consumers (`frontmatter_schema.check_path`, `description_quality.check_path`) on the resulting file, not `test -f`. One test locks that the single-quoting fix is genuinely exercised by asserting the written file contains a single-quoted `description:` value with an embedded colon. A regression test confirms a default-section host is unaffected: `source_files:` never appears in its output, and `status`/`sources`/`synthesized_into` still do.

## Relationship to CCE-110

This fix is orthogonal to CCE-110's factual-accuracy work but shares its grounding computation. CCE-110 added `_pr_changed_files` grounding so the page-author and the `citation_exists` lint rule could check prose against real repo paths. CCE-117 reuses that same `grounding` set to populate `source_files` for agent-authored pages — it doesn't add new grounding, it fixes the frontmatter shape so pages carrying that grounding can actually pass lint and land on `main`. Applying accuracy checks to the previously-blocked architecture pages' content was not possible before this fix, because those pages never existed on `main` to check.

## Scope

Out of scope for this change: the bootstrap path (already generator-correct), an LLM-refined description (deferred option 3, layers on this helper with no rework), and pre-seeding the 20 previously-blocked pages — the fix lets them author naturally on the next nightly run instead.
