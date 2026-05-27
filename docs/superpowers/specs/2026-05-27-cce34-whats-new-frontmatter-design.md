# CCE-34 — What's-New Frontmatter Preservation (as-built)

- **Status:** As-built. Shipped in PR #44 (`fix(CCE-34): preserve whats-new frontmatter on programmatic prepend`).
- **Date:** 2026-05-27
- **Ticket:** CCE-34
- **Related:** PR #44; spec `2026-05-26-cce34-item1-semantic-routing-design.md` (the work whose dry-run surfaced this bug).

## Context

This spec is retroactive. The fix already shipped; the document exists to capture _why_ the change was made and one durable architectural finding the fix exposed.

The bug surfaced during a no-API dry-run of the CCE-34 semantic-routing work. Running the orchestrator's programmatic path against a host whose `whats-new.md` already carried YAML frontmatter produced a file whose frontmatter was no longer at line 1.

## Problem & root cause

The orchestrator built a dated entry (`## <timestamp>` plus optional `### Gaps flagged`) and wrote it with a naive prepend — `entry + existing`. When `existing` began with a `--- ... ---` frontmatter block and a `# What's New` title, the new `## <date>` section landed **above** both. Frontmatter must sit at line 1 for the static-site tooling and for `archive_indexes.parse_frontmatter` to read it, so the naive prepend corrupted the file's structure.

## The fix (as built)

`scripts/orchestrator_runner.py:769` adds `_compose_whats_new(existing, entry)`, wired in at the call site `scripts/orchestrator_runner.py:1190` (`whats_new.write_text(_compose_whats_new(existing, entry))`), replacing `entry + existing`.

The algorithm:

1. Empty/whitespace `existing` → return `entry` unchanged.
2. Otherwise peel a leading `--- ... ---` frontmatter block via `existing.split("---", 2)` — the same delimiter convention as `archive_indexes.parse_frontmatter` (`text.split("---", 2)`), so the two helpers share assumptions.
3. Keep the header region (leading blanks plus a single `# ` title) up to the first `## ` dated section.
4. Insert `entry` immediately before that first `## ` section so entries stay reverse-chronological.
5. Reassemble as `preamble + header + entry + tail`.

**Graceful degradation:** with no frontmatter and no title, the result reduces to the prior `entry + existing` behavior, so hosts without frontmatter are unaffected.

## Testing (as built)

Three tests in `tests/orchestrator/test_pipeline_integration.py`:

- `test_compose_whats_new_preserves_frontmatter` (`:592`) — unit: frontmatter and `# ` title are preserved; the new entry lands before the first `## `.
- `test_compose_whats_new_no_frontmatter_prepends` (`:619`) — unit: degradation to the simple prepend.
- `test_whats_new_prepend_preserves_frontmatter` (`:632`) — integration through `run()` with a frontmatter'd `docs/site-src/whats-new.md` seeded via `_init_host(..., seed_files=...)`.

Full suite at fix time: 557 passed, 3 skipped.

## Known divergence / future work

The fix exposed a more durable finding than the bug itself: the system has **two** whats-new writers.

- **LLM skill path** — `skills/engineering-docs-agent/SKILL.md` step 9, the production nightly path. Authors the dated entry as prose. In the observed nightly run (commit `21ff6b7`) it placed the `## 2026-05-27` section correctly below `# What's New`, so the **live site was never corrupted** — but the skill carries no explicit frontmatter-preservation contract; that correctness is observed, not guaranteed.
- **Python script path** — `scripts/orchestrator_runner.py`, the programmatic / dry-run / test / documented-bootstrap path. Mechanical prepend; this is the path that carried the bug and that `_compose_whats_new` fixes.

These two writers can drift in output format and are unevenly tested. This spec records the divergence as an **open architectural question**. It does not prescribe a reconciliation — sharing a helper, collapsing to one writer, or converging the formats are all candidate future work for a separate brainstorm/spec, not decided here.

## Scope & non-goals

- **Severity:** a programmatic-path defect, not a live-site corruptor — production authoring goes through the LLM skill path, whose observed output places entries correctly.
- **Non-goals:** reconciling the two writers; changing skill-path authoring; redesigning the whats-new file format.

## Files changed (all in PR #44)

- `scripts/orchestrator_runner.py` — added `_compose_whats_new`; rewired the prepend call site.
- `tests/orchestrator/test_pipeline_integration.py` — added the three tests above (`_init_host` already supported `seed_files`).
