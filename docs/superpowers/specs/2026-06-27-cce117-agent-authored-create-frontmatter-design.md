# CCE-117: generator-aware frontmatter on the incremental create path — design

**Date:** 2026-06-27
**Ticket:** [CCE-117](https://designitright.atlassian.net/browse/CCE-117)
**Status:** approved
**Fix surface:** in-repo (`scripts/orchestrator_runner.py` + a pure helper + tests). Ships via the plugin.

## Problem

Every nightly `docs-agent-nightly` run completes successfully (no time-budget kill — CCE-114 is healthy) but is marked **(partial)** because Tier-1 lint blocks a large set of architecture pages. The 2026-06-26 run (PR #154) blocked **20 pages**, all with:

- `frontmatter_schema: missing required field(s): description, source_files, last_reviewed`
- `description_quality: missing or empty description`

The five orchestrator pages plus ~15 others do not exist on `main`; the agent re-authors them each night and they are dropped by lint, so they never land. The partial recurs every night.

## Root cause

The `architecture/` section is configured `generator: agent-authored`, so its pages require `AGENT_AUTHORED_REQUIRED = (description, source_files, last_reviewed, status)` (`scripts/frontmatter_contract.py:14`).

The incremental nightly authoring path hardcodes the **default** template regardless of section generator:

- `scripts/orchestrator_runner.py:1463` → `fm_template = fmc.default_frontmatter_dict(...)` — unconditional. It never calls `fmc.section_generator_for(rel, config)` to select the agent-authored field set.
- The dry-run synth for new pages (`scripts/orchestrator_runner.py:1504-1508`) likewise always writes `fmc.default_frontmatter_text()`.

The generator-aware machinery exists but is wired only into the **bootstrap** path (`:938`, `:2106`). The incremental create path was never taught the branch.

## Decision (brainstormed 2026-06-27)

**Option 2 — the orchestrator deterministically synthesizes `description`.** Ranking was Option 2 ≻ 3 ≻ 1.

| Option                          | Verdict    | Reason                                                                                                                                                                                      |
| ------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **2. Orchestrator synthesizes** | **chosen** | Minimal complete fix; deterministic and unit-testable; no LLM-dependence on a lint-guarded field; no agent-contract change.                                                                 |
| 3. Synth floor + LLM refine     | deferred   | Adds LLM prose polish but costs a page-author contract change + non-determinism; the synth floor it would reuse is exactly what Option 2 builds, so it can be added later with zero rework. |
| 1. LLM writes it (no floor)     | rejected   | Reintroduces the exact failure mode — a guarded field whose population depends on the LLM. Dominated by Option 3 (we build the dry-run synth regardless).                                   |

The tiebreaker was what `description_quality` actually enforces. It is **purely mechanical** (`description_quality.py:29-33`): `min_words: 6`, `forbid_equal_to_title` (vs the page H1), `forbid_trailing_colon`. No prose-quality heuristic exists — so a deterministic, summary-derived synthesis satisfies it reliably, and Option 3's only advantage evaporates.

## Architecture

Three changes plus one new pure helper. All driven by `fmc.section_generator_for(rel, config) == "agent-authored"`; every other generator keeps today's behavior exactly (graceful, generic-first).

1. **`_synthesize_agent_description(summaries, *, hint)` — new pure helper** in `scripts/orchestrator_runner.py` (sibling to `_synthesize_core_page`). Deterministic; never raises. Builds a one-line description from the batch's PR summaries (`what_changed`/`title` fields), falling back to a hint-derived phrase when summaries are thin. Guarantees the three `description_quality` invariants by construction (see contract below).
2. **Production template (`~:1462-1473`)** — branch on the section generator:
   - `agent-authored` → `fm_template = fmc.agent_authored_frontmatter_dict(description=_synthesize_agent_description(batch_summaries, hint=hint), source_files=sorted(grounding), last_reviewed=run_date, status="draft")`, then re-attach `doc_kind` if present.
   - otherwise → unchanged `fmc.default_frontmatter_dict([pr urls])`.
3. **Dry-run synth (`~:1504-1508`)** — for a new agent-authored page, write `fmc.agent_authored_frontmatter_text(description=…, source_files=…, last_reviewed=run_date, status="draft")` + the skeleton; otherwise the current `default_frontmatter_text()`. The skeleton H1 stays `# {hint}`; the synthesized description is summary-derived, so it cannot equal that H1.

### Frontmatter values for an agent-authored create

| field           | value                                                      | source                                                       |
| --------------- | ---------------------------------------------------------- | ------------------------------------------------------------ |
| `description`   | summary-derived sentence (≥6 words, ≠ H1, no trailing `:`) | `_synthesize_agent_description`                              |
| `source_files`  | `sorted(grounding)`                                        | `_pr_changed_files(batch_prs)` — already computed at `:1480` |
| `last_reviewed` | run date                                                   | `now[:10]` (the `now` already bound at `:1252`)              |
| `status`        | `draft`                                                    | constant (matches bootstrap)                                 |
| `doc_kind`      | preserved when present                                     | `doc_kind_by_target`                                         |

## Description synthesis contract

`_synthesize_agent_description(summaries: list[dict], *, hint: str) -> str`

- **Deterministic** — same inputs yield the same string (no clock/RNG). Pure; never raises on malformed input.
- **Source order:** prefer the first non-empty `what_changed` (or `title`) across `summaries`; compose a sentence such as `"Covers <topic>: <what_changed>."` — but never emit a trailing colon.
- **Invariant 1 (`min_words: 6`):** pad deterministically from `hint` + a fixed descriptive clause when the summary text is shorter than 6 words, so the result always clears the threshold.
- **Invariant 2 (`forbid_equal_to_title`):** the result is a full sentence derived from summary prose, structurally distinct from the slug-derived H1 (`# {hint}`); the helper additionally guards against degenerate equality.
- **Invariant 3 (`forbid_trailing_colon`):** strip/avoid a terminal `:`.

## Edge cases / degradation

| Condition                                      | Behavior                                                         |
| ---------------------------------------------- | ---------------------------------------------------------------- |
| `section_generator_for` returns `None`/default | default template (unchanged)                                     |
| Empty `grounding` (PRs touched no files)       | `source_files: []` — valid per `agent_authored_frontmatter_dict` |
| Empty/thin `summaries`                         | deterministic hint-based fallback, still ≥6 words and ≠ H1       |
| Malformed summary entries                      | helper skips them; never raises                                  |

## Testing (TDD)

All via the fixture-driven dry-run path; production CLI dispatch stays monkeypatched.

1. **Unit — `_synthesize_agent_description`:** word count ≥6; output ≠ a slug-derived title; no trailing colon; determinism (same input → same output); thin/empty-summary fallback; malformed-entry tolerance.
2. **Integration — RED→GREEN:** a fixture host whose `architecture/`-style section is configured `generator: agent-authored`. Run the incremental authoring path (dry-run) so it **creates** a new page there, then invoke the real lint consumers (`frontmatter_schema` + `description_quality`) on the result. Assert it is **blocked before** the fix and **passes after** (per CLAUDE.md: verify with the actual consumer tool, not `test -f`).
3. **Regression:** a default-section page still receives the default template (`status`/`sources`/`synthesized_into`) and is unaffected.
4. **Suite:** full `python3 -m pytest` green.

## Acceptance criteria (mapped to ticket)

1. A new page authored into an `agent-authored` section on the incremental path carries `description`, `source_files`, `last_reviewed`, `status` and passes Tier-1 `frontmatter_schema` + `description_quality`. _(AC 1)_
2. Pages in default sections are unaffected. _(AC 2)_
3. A regression test reproduces the block pre-fix and passes post-fix. _(AC 3)_
4. Verifiable on the next nightly: the previously-blocked architecture pages author without `lint_block`. _(AC 4 — observational, post-merge.)_

## Out of scope

- The bootstrap path (`:938`, `:2106`) — already generator-correct.
- A page-author contract change for LLM-refined descriptions (Option 3 — deferred; reuses this helper if ever needed).
- Pre-seeding the 20 blocked pages — unnecessary; the fix lets them author naturally on the next run.
