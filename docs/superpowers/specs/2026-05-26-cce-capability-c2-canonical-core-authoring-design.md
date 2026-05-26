# Capability C2 — Canonical Core authoring

**Status:** approved 2026-05-26 (brainstorm + 3-reviewer validation); implementation plan next.
**Jira:** CCE-26 (Capability C umbrella Story; CCE-23 Phase 2). A C2 sub-task is created at plan time, as C1 → CCE-27 was.
**Supersedes:** the "C2 — Canonical Core authoring" section of `docs/superpowers/specs/2026-05-25-cce-capability-c-canonical-core-citations-design.md` (lines ~93-116). That section sketched one-time authoring + an `audit_docs.py` nudge; this spec is C2's full, validated design and revises several of those choices.
**Builds on:** C1 (verified `file:line` citations, merged via PR #32) — C2's pages emit C1 pinned citations.
**Source:** generalized from ADIS (`advanced-data-importer`), whose hand-authored `docs/site-src/core/**` pages, `scripts/audit_docs.py`, and `scripts/build_doc_source_map.py` are the reference — reused where right, narrowed where ADIS's experience says an LLM cannot safely tread.

---

## Why this exists

Phase 1 (S/D/API/M) ships a themed, navigable site with a Decision Archive, API reference, and a file-level doc↔source map. C1 adds verified line-level citations. What is still missing is a **component-organized architecture narrative** under a `core` section that explains the system in present tense and cites its evidence.

ADIS is the reference implementation — and its decisive lesson is a warning, not a recipe. ADIS's core pages were **hand-authored and never regenerated**, because the durable value of those pages is not derivable from source code. `storage.md` alone carries seven `!!! danger` admonitions — the residue of shipped bugs (the `ANY()`-vs-expanding-`IN` defect, the connector/converter layering rule from a multi-day outage), none of which an LLM reading the current code could reconstruct. A "refine from source" pass would silently delete exactly the content worth keeping.

C2 therefore authors **honestly within the LLM's reach** and treats everything else as human territory: generate the mechanically-grounded skeleton (component map, `source_files` frontmatter, C1-pinned existence claims), leave rationale as explicit human stubs, and **never auto-rewrite** a page on drift — flag it.

## Decisions (locked)

| Axis                  | Decision                                                                                                                                                                                            |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Cadence**           | Explicit one-time bootstrap authoring + nightly **flag-only** drift surfacing.                                                                                                                      |
| **Decomposition**     | Detection → a `.doc-core-manifest.json` **artifact** (not `site:` config). Specs present → one page per spec; code-only → a **single** `system-overview` page (per-package decomposition deferred). |
| **Bootstrap surface** | Setup detects + writes the manifest (stdlib). A dedicated `run_bootstrap_core()` entry authors the declared-but-missing pages (agent dispatch).                                                     |
| **Authoring depth**   | Skeleton + C1-verified existence claims + `TODO(human): rationale` stubs. **No mermaid until C3** gates it.                                                                                         |
| **Drift posture**     | **Flag-only by default.** A `draft → reviewed` status lifecycle; `reviewed` pages are **never** auto-edited, only flagged.                                                                          |
| **Section identity**  | Driven by `generator: agent-authored`, **never** by the name `core`/`architecture`.                                                                                                                 |
| **Deferred from v1**  | `audit_docs.py`; per-package code-only decomposition; any diagram emission (waits on C3).                                                                                                           |

## Architecture — three deterministic seams + one agent seam

The work splits along the repo's existing stdlib-vs-agent line. Every behavior is detection/config-driven, never path-hardcoded.

1. **Manifest detection** — stdlib, in `setup_discover` / `site_structure`. `detect_core_manifest(repo_root, site_config, *, specs_dir=None)` decides the page set and each page's `source_files` globs, and writes `.doc-core-manifest.json` under `docs_dir`. Human-tunable before authoring. Runs at setup.
2. **Bootstrap authoring** — agent dispatch, via a new `run_bootstrap_core(repo_root, ...)` entry (its own `main()` subcommand / `--bootstrap-core`, **not** a flag threaded into the nightly `run()`). Authors each manifest page that has no file yet. Explicit, costed, idempotent (re-runs create only still-missing pages).
3. **Drift-update (flag-only)** — a new nightly orchestrator stage, slotted **after** M's `source-map` and C1's `verify-citations` stages, mirroring their best-effort posture. It intersects the manifest's core pages with the pages M/C1 flagged as drifted and surfaces them under a **"Core pages to review (drift)"** block in the What's-New entry and the notifier digest. It dispatches no authoring; it never edits a page.
4. **`audit_docs.py`** — **deferred.** M (file drift) and C1 (line drift) already surface per-run review needs; the cross-time churn nudge is a later addition if maintainers ask for it.

### Why these seams

`source_files` is the spine. M parses `source_files:` frontmatter into `.doc-source-map.json` (`scripts/source_map.py:_page_globs`); C1 scopes its fast path to changed pages via that map (`_changed_pages_from_map`). A manifest that writes `source_files` into each core page's frontmatter gets **both** file-drift (M) and line-drift (C1) detection for free, with zero new wiring. The drift-update stage is then a third sibling next to `compute_source_drift` and `compute_citation_drift`.

## The core manifest

A generated artifact, sibling to `.doc-source-map.json`, owned by `detect_core_manifest`:

```json
{
  "version": 1,
  "pages": [
    {
      "key": "api",
      "title": "API layer",
      "page": "core/api.md",
      "source_files": ["backend/app/api/**/*.py"]
    }
  ]
}
```

Storing this as an artifact — not a `pages:` sub-key under a `site:` section — is deliberate: the section schema sets `additionalProperties: false`, generated page→source mappings do not belong in operator-facing config, and the artifact mirrors the established `.doc-source-map.json` pattern. The `site:` `core` section stays its existing flat shape (`{key, path, title, generator: agent-authored}`).

### Detection rules

- **Specs present** (a `docs/superpowers/specs` or configured spec dir exists): one candidate page per spec, `source_files` seeded from the spec's own referenced paths where detectable, else the detected source root.
- **Code-only** (no specs): a **single** `system-overview` page whose `source_files` is the detected source root. Per-package decomposition is explicitly deferred — it multiplies failure modes on exactly the generic hosts the plugin targets.
- **Nothing detected**: no manifest, no `core` section emitted (skip, never empty).
- Entries whose globs match **zero** tracked files are dropped at build time (a page documenting nothing is never authored).
- Entries are emitted in a **deterministic sorted order**; colliding keys are disambiguated deterministically.

### Section identity

`detect_core_manifest` and both new stages locate the target section by scanning for `generator: agent-authored` (exactly as `setup_scaffold` already finds the `api-extract` section), then resolve its path via the section `path` / `resolve_lens`. The names `core` and `architecture` are never hardcoded — the default template ships an `architecture` section while the dogfood config uses `core`, and hardcoding either is the "found this repo's own directories" defect CLAUDE.md forbids.

## Frontmatter contract and the precursor lint fix

Core pages carry:

```yaml
---
description: <one-line purpose>
source_files:
  - path/to/file.py
last_reviewed: YYYY-MM-DD
status: draft
---
```

**Precursor (must land first, its own PR).** `scripts/lint/frontmatter_schema.py` is a Tier-1 **block** rule that hardcodes `REQUIRED_FIELDS = ("status", "sources", "synthesized_into")`. Because the orchestrator deletes pages that fail a block rule (`git checkout HEAD` / unlink), shipping C2's frontmatter as-is would make the pipeline **delete every core page it authors**. The rule must become **generator-aware**: a section with `generator: agent-authored` requires `{description, source_files, last_reviewed, status}`; the existing PR-changelog path keeps its current set. This is a shared-helper contract change — the rule, its test, its fixtures, and the orchestrator's two hardcoded `synthesized_into: []` literals move together in the precursor change.

`source_files` comes from the **manifest** (file granularity, for M). C1 pins (`path:line` + token, finer granularity) are the **agent's** job. Two granularities, two sources; the agent never invents the file mapping.

## Authoring model — honest within the LLM's reach

The `page-author` agent is reused unchanged; only its caller-supplied inputs differ. For a core page it authors:

- **Grounded skeleton:** the component's purpose, its place in the system, a `source_files`-backed inventory.
- **C1-pinned existence claims:** "`BaseConnector` is defined at `…:148` `<!--pin:class BaseConnector-->`", using **distinctive tokens** (signature fragments, class/def headers, constant names — never bare keywords) so the C1 verifier rarely reports `ambiguous`.
- **Explicit human stubs:** rationale, gotchas, and layering rules are emitted as `TODO(human): rationale` placeholders, not invented. This is the honest answer to the reviewers' finding that C1 grounds only existence, and that confident-but-unverifiable prose riding next to green-checked citations borrows false authority.
- **No mermaid.** Diagrams wait until the C3 render gate exists; until then C2 emits diagram-free pages. Shipping ungated diagrams reproduces ADIS's "missing diagrams" incident.

Authoring distills the source docs; it never reproduces them verbatim. `docs/superpowers/**` stays **read-only input** (the umbrella spec's permanent fix for the dogfood defect where the agent rewrote process specs in place); `site-src/core` joins `agent_editable_paths`.

## Drift posture — flag-only, with a status lifecycle

M-style drift is file-level glob matching: a one-line change to a mapped source flags the whole page. A regenerate/refine pass cannot re-derive a page's hard-won rules from that diff and would delete them. So the nightly stage **flags, never edits**:

- A core page whose mapped sources changed (M) or whose C1 citations went `gone`/`ambiguous` is listed under **"Core pages to review (drift)"** in the What's-New entry + digest — the same review-needed posture M and C1 already use.
- **Status lifecycle:** pages are authored `status: draft`. A human review flips `draft → reviewed`. The drift stage **writes nothing to pages** — it surfaces drifted pages (whatever their status) in the digest and lets the human decide whether to re-review or re-author. `reviewed` pages are never auto-edited; in fact no page is. There is no auto-authoring on drift in v1.

This matches what the original umbrella spec already implied (`audit_docs` as a nudge, not a rewriter) and preserves the accreted-rules content ADIS depends on. Re-authoring a drifted page is a deliberate, human-invoked act (re-run bootstrap for that page, or edit by hand) — not a nightly side effect.

## Config, schema, and the dogfood migration

- The `site:` `core`/agent-authored section keeps its existing flat shape; no schema change for the manifest (it is an artifact).
- A `core.drift` posture is fixed to flag-only in v1; no toggle ships (the safety property "never auto-edit `reviewed`" is non-optional, not a config knob).
- `last_reviewed: <today>` is written via an **injected `today`** (the run's existing timestamp), so bootstrap output is deterministic and testable.
- **Dogfood config migration (real work, not a one-liner):** the live `.engineering-docs-agent/config.yml` currently makes `docs/superpowers/**` editable, has no `site-src/core` editable glob, and points lens `core` at `docs/`. Aligning with this spec (core editable, specs read-only) requires updating `agent_editable_paths` and the lens path, re-satisfying `_validate_lens_paths_are_editable`.

## Generic-first and graceful degradation

- No detectable sources → no manifest → `core` section skipped, not emitted empty.
- Manifest globs matching nothing → entry dropped at build; never authored.
- A manifest page whose `source_files` were later deleted → flagged (sources gone), never edited — parallel to C1's `gone`.
- No citations on a page → C1 emits an empty ledger; nothing to flag.
- Bootstrap with an empty manifest → no-op.

## Error handling & verification

- **Detection** is deterministic and fully unit-tested.
- **Bootstrap** reuses the existing authoring path's containment + `agent_editable_paths` guards (no second path-safety check); a per-page dispatch failure records a partial reason and continues (mirrors the existing loop), never aborting.
- **Drift-update** is best-effort: an exception adds an info-only partial reason and never aborts the run.
- `mkdocs build --strict` (broken links / nav) and the content-validator lint tiers continue to gate authored pages. **Content quality is not unit-tested** — only scaffolding, frontmatter shape, and draft status are asserted.

## Testing strategy

Fixture-driven, arbitrary-host fixtures (not this repo's tree), production CLI dispatch monkeypatched. Required seams:

- **Inject `today`** so `last_reviewed` is pinnable.
- **Make the dry-run page synthesizer manifest-aware** so it writes the manifest's `source_files` into authored frontmatter — today it writes a canned body, so the per-page `source_files` assertion target does not yet exist.
- **A list-accumulating dispatch spy** so per-page dispatch can be asserted (the current capture keeps only the last call).

Tests:

- `detect_core_manifest`: specs-present fixture → per-spec manifest; code-only → single `system-overview`; empty → no manifest; empty-glob entry → dropped; deterministic ordering.
- Bootstrap (monkeypatched page-author): missing manifest pages created at their keys; frontmatter `source_files == manifest globs`, `status: draft`, injected `last_reviewed`; content not asserted; re-run → no duplicate dispatch (idempotent on file-exists).
- Drift-update stage: a changed mapped source / a `gone` C1 citation → the right page surfaces in What's-New + digest; **no dispatch occurs and no page is written** (flag-only); page bytes are byte-identical before/after the stage regardless of status.
- Precursor: `frontmatter_schema` accepts the agent-authored field set and still blocks the changelog path's missing fields.

## Scope boundaries

C2 authors the **single agent-authored core section** only; other lenses are untouched. Explicitly **not** in C2: the C3 diagram render gate; any mermaid emission (waits on C3); `audit_docs.py` (deferred); per-package code-only decomposition (deferred); and the dropped ADIS-isms — the 4-lens IA (Portfolio/Future-me/Ops/Onboarding), `synthesized_into`/promotion sets, and drift PNGs.

## Sequencing — four sub-plans, landed as separate green PRs

Matching the C1 stacked-branch pattern; each independently shippable and green:

1. **Frontmatter precursor.** Make `frontmatter_schema` generator-aware; update the rule, its test, fixtures, and the orchestrator's `synthesized_into` literals. Unblocks everything else.
2. **`detect_core_manifest`.** Stdlib detection → `.doc-core-manifest.json`; the three fixture shapes; empty-glob drop; deterministic ordering; setup writes it + adds nav + a `core/` index stub.
3. **`run_bootstrap_core`.** The dedicated authoring entry; manifest-aware dry-run synthesis; idempotent create-missing; reuses the authoring path guards; emits the C2 frontmatter + C1 pins + `TODO(human)` stubs (no diagrams).
4. **Drift-update stage.** The flag-only nightly sibling after M/C1; the `draft → reviewed` lifecycle and the never-auto-edit-`reviewed` safety property; What's-New + digest surfacing.

## Risks & open questions

- **Thin-source repos.** On a messy repo with sparse specs, C2's single overview page is honest but shallow. Accepted: the skeleton + `TODO(human)` stubs make the gaps explicit rather than papering over them with confident prose.
- **Manifest quality is the ceiling.** A poor auto-detected decomposition yields poor page buckets. Mitigation: the manifest is a human-tunable artifact reviewed before bootstrap authoring runs.
- **`draft → reviewed` plumbing.** The lifecycle adds a status value the lint/validator and any status-aware tooling must tolerate; scoped into sub-plan 4 with its own tests.
- **C1 ambiguity from authored tokens.** Distinctive-token guidance reduces but cannot eliminate `ambiguous` pins; C1 surfaces them as review-needed, so they are visible, not silent.
