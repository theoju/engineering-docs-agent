# CCE-119: create-path frontmatter fidelity — design

**Date:** 2026-07-14
**Ticket:** [CCE-119](https://designitright.atlassian.net/browse/CCE-119)
**Status:** approved
**Fix surface:** in-repo (`scripts/orchestrator_runner.py`, `scripts/lint/description_quality.py`, `agents/page-author.md`, tests). Ships via the plugin.
**Provenance:** two CCE-117 final-review residuals, split out of CCE-118 (2026-07-11). Neither is a live blocker — the content-validator lint-drop safety net still catches any regression — so this is hardening that closes the last two gaps in CCE-117's determinism guarantee.

## Problem

CCE-117 made the incremental authoring **create** path generator-aware: for an `agent-authored` section, the orchestrator deterministically synthesizes the required frontmatter (`description`, `source_files`, `last_reviewed`, `status`) so the new page clears Tier-1 lint instead of being dropped. Two residuals remain.

### Item A — the production path trusts the LLM to write the frontmatter

In production (`orchestrator_runner.py:1543-1576`) the orchestrator computes the deterministic `agent_fields` and hands them to `page-author` as `frontmatter_template`. But `agents/page-author.md:76` instructs the LLM to _"draft frontmatter from `frontmatter_template`"_ — **draft, not verbatim**. The real page-author LLM writes the file to disk; the orchestrator never inspects what landed. The LLM can reword `description` below the 6-word floor or equal to the H1, or drop `source_files`/`last_reviewed` — and the create is lint-dropped again.

The existing "passes Tier-1 lint" integration test (`tests/orchestrator/test_agent_authored_create_frontmatter.py:95`) only exercises the **dry-run** path, where the _orchestrator itself_ writes the frontmatter (`orchestrator_runner.py:1585-1596`, guarded `if dry_run_dir and not target_path.exists()`). The LLM never runs in that test. So the test proves the synthesis is lint-clean but **not** that a real dispatch preserves it. The two paths diverge on _who writes the frontmatter_: orchestrator (dry-run) vs. LLM (production). The production path's fidelity depends entirely on LLM cooperation — exactly the LLM-dependence on a lint-guarded field that CCE-117 Option 2 was chosen to eliminate, and exactly the "trust the subagent's own work" anti-pattern CLAUDE.md's declare-then-discharge principle forbids.

### Item B — `_DESC_MIN_WORDS` duplicates the lint default

`_synthesize_agent_description` hardcodes `_DESC_MIN_WORDS = 6` (`orchestrator_runner.py:979`), silently mirroring `description_quality._DEFAULTS["min_words"] = 6`. If a host raises `lint.tier1.description_quality.min_words`, the synthesizer still pads only to 6 and the page is dropped under the host's stricter floor. Two constants, one source of truth missing.

## Decision (brainstormed 2026-07-14)

Robust on both items.

| Item  | Chosen                                                                                                                                                                                                                                                                                                  | Rejected alternative                                                                                                           |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **A** | **A2 — post-dispatch reconciliation.** After an agent-authored create returns `ok`, the orchestrator overwrites the written file's frontmatter with the authoritative `agent_fields`, preserving the body. Both paths converge on the deterministic writer. The contract change is belt-and-suspenders. | A1 — contract change + cooperative seam test only. Still trusts the LLM's write; re-opens the LLM-dependence CCE-117 removed.  |
| **B** | **B-config — resolve `min_words` from config.** Add public `resolve_min_words(config)` to `description_quality.py`; the synthesizer pads to the resolved floor; delete `_DESC_MIN_WORDS`. One source of truth — drift is impossible.                                                                    | B-sync — keep the constant, add a test asserting it equals the default. Only guards the default; a host override still breaks. |

Rationale: A2 is the faithful completion of CCE-117's determinism intent and mirrors CCE-120 one level down (CCE-120 injected authoritative identity _into_ the subagent's input; CCE-119 enforces authoritative frontmatter _onto_ its output). B-config removes the coupling at its root rather than guarding a symptom.

## Architecture

Four changes. All guarded so every non-agent-authored path (edits, default sections) is byte-for-byte unchanged — generic-first, degrade-gracefully.

### Item A

1. **New helper `_enforce_agent_frontmatter(path, agent_fields, fmc)`** in `orchestrator_runner.py` (sibling to the create logic). Reads `path`, splits the leading frontmatter block from the body using the **existing** shared frontmatter parser (`parse_frontmatter` — do not hand-roll one, per the shared-helper rule), and re-writes `fmc.agent_authored_frontmatter_text(**agent_fields) + body`. Idempotent; safe when the file has no frontmatter (body then equals the whole file). Never raises on a well-formed page.

   _De-risking:_ the writer is the **exact** `agent_authored_frontmatter_text(**agent_fields)` call the dry-run synth already makes today (`orchestrator_runner.py:1590`, including `doc_kind` passthrough), so the only new surface is _when_ it runs, not _what_ it writes.

2. **Callsite** — after `if out.get("ok"):` (`~:1582`), when `agent_fields is not None` and `target_path.exists()`, call `_enforce_agent_frontmatter(target_path, agent_fields, fmc)`. This runs on **both** paths:
   - production: the LLM wrote the file → reconciliation corrects any deviation;
   - dry-run: the synth wrote the skeleton → reconciliation is a content no-op.

   The existing dry-run synth block (`~:1585-1596`) still ensures a file exists for a fresh create; reconciliation then owns the frontmatter. (Agent-authored dry-run creates may write the body-only skeleton and let reconciliation prepend the frontmatter; the default-section branch is untouched.)

3. **Contract (`agents/page-author.md`)** — the `frontmatter_template` input description and Procedure step 2 gain: _for agent-authored creates, emit `description`, `source_files`, and `last_reviewed` **verbatim** from `frontmatter_template` — do not reword, shorten, or drop._ Belt-and-suspenders now that reconciliation enforces it; satisfies AC1.

### Item B

4. **`resolve_min_words(config) -> int`** — new public function in `scripts/lint/description_quality.py`, a thin wrapper over the existing `_resolve_config(config)["min_words"]` (additive; existing callers unchanged). `_synthesize_agent_description(summaries, *, hint, min_words)` gains the `min_words` keyword (an int) and pads to it with a **deterministic** loop (append neutral filler words until the count clears the floor), preserving the no-trailing-colon and ≠-H1 invariants. Delete `_DESC_MIN_WORDS`. The callsite (`~:1544`) passes `min_words=description_quality.resolve_min_words(config)`.

## Data flow (agent-authored create)

```
batch_summaries ─┐
                 ├─► agent_fields = agent_authored_frontmatter_dict(
grounding ───────┘        description=_synthesize_agent_description(
                              summaries, hint, min_words=resolve_min_words(config)),
                          source_files=sorted(grounding), last_reviewed=run_date)
                 │
                 ├─► frontmatter_template = agent_fields  ──► page-author dispatch
                 │                                              (LLM writes file, or dry-run synth)
                 └─► after ok: _enforce_agent_frontmatter(target_path, agent_fields, fmc)
                                  └─► file frontmatter := agent_authored_frontmatter_text(**agent_fields)
                                      (body preserved)  ──► content-validator / Tier-1 lint  ──► PASS
```

## Error handling / degradation

| Condition                                           | Behavior                                                                                         |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `action == "edit"`                                  | reconciliation skipped (create-only; edits keep existing frontmatter)                            |
| Non-agent-authored section (`agent_fields is None`) | reconciliation skipped; default template path unchanged                                          |
| File missing after `ok` (should not happen)         | guarded by `target_path.exists()`; skipped                                                       |
| Written file has no frontmatter block               | `parse_frontmatter` yields empty FM; body = whole file; helper prepends authoritative FM         |
| Host raises `min_words`                             | `resolve_min_words` returns the override; synthesizer pads to it                                 |
| No `lint.tier1` override                            | `resolve_min_words` falls back to `_DEFAULTS["min_words"]` (existing `_resolve_config` behavior) |

## Testing (TDD)

All via fixtures / real consumer tools; production CLI dispatch stays monkeypatched.

**Item A**

1. **Unit — `_enforce_agent_frontmatter` (the AC2 seam proof):** a file whose frontmatter would **fail** lint (short `description`, missing `source_files`). After enforcement, the real `description_quality.check_path` **and** `frontmatter_schema.check_path` **pass**; the body is preserved; a second call is a no-op (idempotent). Proves "the deterministic description provably survives to the written page" through the enforcement seam, with the actual consumer tools (per CLAUDE.md: verify with the consumer, not `test -f`).
2. **Integration — through `run()`:** pre-write the target with deviating frontmatter (simulating a real LLM's bad production write, so `target_path.exists()` skips the dry-run synth and reconciliation runs) → the final page passes real Tier-1 lint and its `description` equals the synthesized value.
3. **Regression:** a default-section create still receives the default template and is unaffected (existing `test_default_section_create_unaffected` stays green).

**Item B** 4. **Unit — padding to an arbitrary floor:** `_synthesize_agent_description(..., min_words=12)` yields ≥12 words deterministically (same input → same output), no trailing colon, ≠ the slug-derived H1; thin/empty/malformed-summary tolerance preserved at the higher floor. 5. **Config resolution:** `resolve_min_words({})` == `_DEFAULTS["min_words"]`; a host config with `lint.tier1.description_quality.min_words: 12` flows through the callsite so an agent-authored create passes lint under the stricter floor (integration through `run()`).

**Suite:** full `python3 -m pytest` green.

## Acceptance criteria (mapped to ticket)

- **Item A / AC1** — the `page-author` contract requires emitting `description`/`source_files`/`last_reviewed` verbatim for agent-authored creates. _(change 3)_
- **Item A / AC2** — the deterministic synthesized description provably survives to the written page, tested at the production-dispatch seam, not only dry-run. _(change 1–2; tests A1–A2)_
- **Item B / AC1** — the helper reads the resolved `description_quality.min_words` from config (falling back to the default). _(change 4; tests B4–B5)_

## Out of scope

- The bootstrap path (`orchestrator_runner.py:938`, `:2106`) — already generator-correct.
- LLM-refined description prose (CCE-117 Option 3) — still deferred.
- Pre-seeding previously-blocked pages — unnecessary; they author naturally on the next run.
- Reconciling non-agent-authored or edit-path frontmatter — out of scope by design (narrowly guarded).
