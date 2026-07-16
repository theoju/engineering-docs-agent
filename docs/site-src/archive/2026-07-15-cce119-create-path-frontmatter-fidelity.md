---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/178
synthesized_into: []
doc_kind: decision
---

# CCE-119: Create-Path Frontmatter Fidelity (2026-07-15)

## Context

CCE-117 made the incremental authoring **create** path generator-aware: for an `agent-authored` section, the orchestrator deterministically synthesizes the required frontmatter (`description`, `source_files`, `last_reviewed`, `status`) so a new page clears Tier-1 lint instead of being dropped. That fix closed a recurring failure mode — 20 blocked architecture pages in one nightly run — but left two residuals, tracked as CCE-119 and split out of CCE-118.

**Item A — the production path trusted the LLM to write the frontmatter.** The orchestrator computed the deterministic `agent_fields` and handed them to `page-author` as `frontmatter_template`, but `agents/page-author.md` only instructed the LLM to "draft" frontmatter from the template — draft, not verbatim. The real page-author LLM writes the file to disk; the orchestrator never inspected what landed. A reworded `description` (below the word floor, or equal to the page's H1) or a dropped `source_files`/`last_reviewed` field would get the create lint-dropped again. The existing integration test only exercised the dry-run path, where the orchestrator itself writes the frontmatter — it proved the synthesis was lint-clean, not that a real dispatch preserves it.

**Item B — a duplicated constant could drift from host config.** `_synthesize_agent_description` hardcoded `_DESC_MIN_WORDS = 6`, mirroring `description_quality._DEFAULTS["min_words"]` without reading it. A host that raised `lint.tier1.description_quality.min_words` would still get a description padded only to 6 words, and the page would fail the host's own stricter floor.

Neither was a live failure — the content-validator lint-drop safety net still caught any regression — so this is hardening that closes the gap between "works in tests" and "holds on the real production dispatch path."

## Decision

| Item | Chosen | Rejected alternative |
| --- | --- | --- |
| **A** | Post-dispatch reconciliation: after an agent-authored create returns `ok`, the orchestrator overwrites the written file's frontmatter with the authoritative `agent_fields`, preserving the body. Both paths (production LLM write, dry-run synth) converge on the same deterministic writer. | Contract change alone. Still trusts the LLM's write; re-opens the LLM-dependence CCE-117 was chosen specifically to eliminate. |
| **B** | `resolve_min_words(config)` — a public wrapper over the existing `_resolve_config(config)["min_words"]` in `description_quality.py`. The synthesizer takes `min_words` as a required keyword and pads to it; `_DESC_MIN_WORDS` is deleted. | Keep the constant, add a test pinning it to the default. Only guards against drift from the default — a host override still breaks silently. |

This mirrors CCE-120 one level down: CCE-120 injected authoritative identity *into* a subagent's input; CCE-119 enforces authoritative frontmatter *onto* its output. Trust nothing the subagent authors about its own work — the same declare-then-discharge principle CLAUDE.md codifies for the SDD verification ladder.

## What changed

- **`_enforce_agent_frontmatter(path, agent_fields)`** (new, `scripts/orchestrator_runner.py`). Reads the written page, splits the leading `---` frontmatter block from the body using the same fence convention as `archive_indexes.parse_frontmatter`, and re-writes `agent_authored_frontmatter_text(**agent_fields) + body`. Idempotent; a file with no frontmatter block keeps its whole text as the body and gets the authoritative block prepended.
- **Callsite wiring.** After `if out.get("ok"):`, when `agent_fields is not None` and the target file exists, the orchestrator calls `_enforce_agent_frontmatter`. This runs on both paths: production (the LLM wrote the file — reconciliation corrects any deviation) and dry-run (the synth wrote the skeleton — reconciliation is a content no-op).
- **`agent_fields` decoupled from the `doc_kind` mutation.** The authoring loop used to write `doc_kind` directly onto `agent_fields` (`fm_template = agent_fields`); it now copies first (`fm_template = dict(agent_fields)`), so `agent_authored_frontmatter_text(**agent_fields)` at the reconciliation callsite never receives an unexpected `doc_kind` kwarg. `doc_kind` is routing-only — nothing reads it back from a page's frontmatter.
- **`agents/page-author.md` contract.** Procedure step 2 and the `frontmatter_template` input note now state, for an agent-authored create, that `description`, `source_files`, and `last_reviewed` must be emitted **verbatim** — do not reword, shorten, or drop them — because they are lint-guarded and the orchestrator's values are authoritative regardless (it reconciles the written page against them either way). Belt-and-suspenders now that reconciliation enforces it.
- **`resolve_min_words(config) -> int`** (new, `scripts/lint/description_quality.py`), a thin wrapper over `_resolve_config(config)["min_words"]`. The authoring loop resolves this once per run and threads it into `_synthesize_agent_description(summaries, *, hint, min_words)`, which now requires `min_words` and pads to it with a deterministic, repeatable filler loop that re-strips a trailing colon on every append (so the no-trailing-colon and not-equal-to-H1 invariants hold at whatever floor the host configures). `_DESC_MIN_WORDS` is deleted — `description_quality.py` is the single source of truth.

## Error handling / degradation

| Condition | Behavior |
| --- | --- |
| `action == "edit"` | Reconciliation skipped — create-only; edits keep their existing frontmatter. |
| Non-agent-authored section (`agent_fields is None`) | Reconciliation skipped; the default-template path is unchanged. |
| File missing after `ok` (should not happen) | Guarded by an existence check; skipped. |
| Written file has no frontmatter block | The helper treats the whole file as body and prepends the authoritative block. |
| Host raises `description_quality.min_words` | `resolve_min_words` returns the override; the synthesizer pads to it. |
| No `lint.tier1` override | `resolve_min_words` falls back to the rule's own default — same behavior as before. |

## Testing

All verification runs through the real consumer tools, not `test -f`: `frontmatter_schema.check_path` and `description_quality.check_path`/`check_fm` against pages written by the actual code paths under test.

- **Unit — `_enforce_agent_frontmatter`.** A file pre-written with deviating frontmatter (short `description`, missing `source_files`) — simulating a real LLM's bad production write — passes both lint consumers after enforcement; the body is preserved; a second call is a no-op. A file with no frontmatter block at all is also covered.
- **Integration — through `run()`.** The target file is pre-written with deviating frontmatter before the run, so the dry-run synth is skipped (`target_path.exists()`) and reconciliation is exercised end-to-end: the final page passes real Tier-1 lint and its `description` matches the synthesized value. This is the test that specifically proves fidelity at the production-dispatch seam, not only in dry-run.
- **Regression.** A default-section create still gets the default template untouched, unaffected by any of the above.
- **Unit — padding to an arbitrary floor.** `_synthesize_agent_description(..., min_words=12)` yields at least 12 words deterministically, with the same invariants (no trailing colon, not equal to the slug-derived H1) preserved at the higher floor.
- **Config resolution.** `resolve_min_words({})` equals the rule's own default; a host config raising `min_words` to 12 flows end-to-end through `run()` so an agent-authored create passes lint under the stricter floor.

Full `python3 -m pytest` is green.

## Out of scope

- The bootstrap path (already generator-correct; untouched).
- LLM-refined description prose (CCE-117 Option 3) — still deferred.
- Pre-seeding previously-blocked pages — unnecessary; they author naturally on the next run.
- Reconciling non-agent-authored or edit-path frontmatter — narrowly guarded out by design.

## See also

- CCE-117: the original agent-authored create frontmatter synthesis fix.
- CCE-120: orchestrator-injected identity into subagent input — the input-side counterpart to this output-side enforcement.
- `docs/superpowers/specs/2026-07-14-cce119-create-path-frontmatter-fidelity-design.md`: design spec.
- `docs/superpowers/plans/2026-07-14-cce119-create-path-frontmatter-fidelity.md`: implementation plan.
- `scripts/lint/description_quality.py`, `scripts/orchestrator_runner.py`, `agents/page-author.md`: the changed surfaces.
