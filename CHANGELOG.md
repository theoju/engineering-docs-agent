# Changelog

## [Unreleased]

### Added

- **docs-agent PR-body enrichment.** Nightly PRs now render a review-window header (baseline → current head SHA), file count by lens (with `other` bucket for non-lens paths), top-5 changed pages with `(+M more)` truncation, and an inline `partial_reasons` digest when the run is partial. Operators can review a nightly in <60s without opening the diff. The composer is pure (`_compose_pr_body`); back-compat preserved via optional kwargs with safe defaults. Tracker: CCE-89 D1.
- **docs-agent auto-close-stale policy ("freshest-only").** After a new nightly opens its PR, the orchestrator walks open `docs-agent/*` PRs and closes each one authored entirely by the bot with the comment `Auto-closing: superseded by #<new> (docs-agent freshest-only policy)`. PRs with any human-authored commit are left open for human resolution. Prevents the stale-PR pileup that accumulated 2026-05-30 to 2026-06-01 (6 PRs against a single stale baseline). All hygiene reasons are `info_only=True` — D2 failures cannot flip the run to partial. Tracker: CCE-89 D2.

### Changed

- **docs-agent nightly cron unpaused.** The `07:07 UTC` schedule is restored on `.github/workflows/docs-agent-nightly.yml` now that D1 + D2 provide the cadence floor. D3 (merge-gate decision: auto-merge vs operator-promote vs hybrid) remains open as a separate ticket; until it lands, the operator promotes each morning's PR manually after the enriched body provides the review signal. Tracker: CCE-89.

### Fixed

- **diagram-gate required-check deadlock on non-docs PRs.** Removed the workflow-level `paths:` filter from `.github/workflows/docs.yml` and replaced it with an in-job `filter` step that diffs against the PR base / push parent and gates the expensive Playwright/mkdocs steps on a `relevant` output. Without this, GitHub skipped the workflow entirely on PRs that didn't touch the listed paths — the `diagram-gate` required status check never reported, and `mergeStateStatus` stayed BLOCKED forever (originating incident: PR #108). Same invariant as `actionlint.yml` (CCE-59): required status checks must never carry a workflow-level paths filter. Tracker: CCE-91.
- **Pages bootstrap on first host deploy.** Replaced `actions/configure-pages@v6 enablement: true` (a no-op on first deploy because the workflow's `GITHUB_TOKEN` lacks admin scope) with a setup-time `gh api -X POST repos/.../pages -f build_type=workflow` call from the new `scripts/enable_pages.py`. The setup skill's step 6c invokes it after writing the docs-pages workflow. Graceful fallback on all error paths — scaffolding never blocks on Pages bootstrap. Originating incident: `theoju/claude-code-self-assessment` PR #121 / CCE-81. Tracker: CCE-82.

## [0.2.0] — 2026-05-27

Consolidates the work merged since v0.1.4 (CCE-17 through CCE-34). The headline additions are a structured, publishable docs site; verified-citation and core-manifest authoring stages; a Playwright diagram-render CI gate; a generic GitHub Pages publish target; and discovery-driven semantic section routing for generated pages. No breaking changes to the host config surface; existing `.engineering-docs-agent/config.yml` files continue to load.

### Semantic section routing (CCE-34, item 1)

- The orchestrator scans each lens root for top-level section directories at runtime and passes them to the pr-summarizer as `available_sections`. Generated `action: create` pages now route into published sections (`operations/`, `architecture/`, `archive/`) instead of the removed `_agent-sandbox/` path, which was no longer in `agent_editable_paths` and silently dropped. Hidden directories are excluded from the scan (generic-first safety for arbitrary host repos).
- The pr-summarizer `lens` schema field opened from a hardcoded enum to any non-empty string; known-lens enforcement stays at runtime via `resolve_lens`. Scaffolded section stubs now carry descriptive bodies so the summarizer LLM gets clearer section-intent signal. Vestigial `docs/_agent-sandbox/.gitkeep` removed; stale `_agent-sandbox/**` references in `state_io.py` and the README aligned to `docs/site-src/**`.

### GitHub Pages publish target (CCE-32) + dogfood alignment (CCE-34)

- Generic, Actions-source GitHub Pages deploy capability: the setup skill scaffolds a `workflow-pages.yml` deploy template when `detect_pages_publishable` confirms the host builds docs, wires `publishing.target` / `build_command` / `site_dir`, and derives the base URL for the publish-verifier. Non-MkDocs hosts are supported via `publishing.build_command` + `site_dir`. This repo's own site now deploys to Pages from `docs/site-src/`.

### Diagram render gate (CCE-30)

- New required CI gate renders Mermaid diagrams via Playwright on docs changes and asserts per-page render success, with graceful skip when Playwright is absent and a pinned test that the agent runtime never imports Playwright.

### Structured docs site + authoring stages (CCE-23, CCE-26, CCE-28)

- Structured docs-site scaffolding, decision archive, source-map drift detection, and an API reference surface (CCE-23). Verified-citation enforcement and agent-authored frontmatter helpers (CCE-26). Core-manifest detection, a `--bootstrap-core` authoring mode, and a nightly core-drift update stage (CCE-28).

### Source-collector reliability (CCE-17, CCE-18, CCE-19)

- Fixes to the pr-summarizer page-hint contract, source-collector Jira auth, and the diff-window bound.

### CI hardening (CCE-6, CCE-31)

- Added `@pytest.mark.live` marker and a `conftest.py` default-skip hook: live real-LLM tests run only via `pytest -m live`. Two `dispatch_subagent` smoke tests (notifier, pr-summarizer) exercise the real dispatch path with different payload shapes. New `.github/workflows/release.yml` runs them on tag pushes only. Cost ~$1-3 per full pass; the default mocked suite stays free. (CCE-6)
- Bumped CI actions to Node-24-compatible majors (`checkout@v5`, `setup-python@v6`). (CCE-31)

## [0.1.4] — 2026-05-20

### Source-collector reliability investigation (CCE-9 — partial fix + diagnostic infrastructure)

This release ships two independently useful pieces from the CCE-9 systematic-debugging investigation, plus measurement evidence. The full source-collector reliability fix continues in CCE-10.

**Diagnostic instrumentation (lands fully).**

- New `DOCS_AGENT_DEBUG_DIR` env var on `scripts/orchestrator_runner.py`. When set, `dispatch_subagent` writes the full prompt, raw stdout, raw stderr, and meta (returncode + argv) for each subagent invocation to that directory, one file per artifact type. Off-contract LLM responses are now diagnosable without re-running and adding ad-hoc logging. Unset → byte-identical to v0.1.3.
- New unit tests at `tests/orchestrator/test_dispatch_debug_capture.py` (2 cases) lock the on/off behavior. Total suite: 163 passed (161 baseline + 2 new).

**Source-collector empty-`last_sha` guidance (lands; partial improvement).**

- Added explicit step 0 to `agents/source-collector.md` `## Procedure`: when `last_sha` is empty, return canonical `{"prs": [], "jira_issues": []}` and stop. Phase 1 evidence had shown the agent inventing a non-canonical `{"status": "idle", ...}` shape in this case.
- **Empirical result:** 3 Mode B runs against ADIS confirm the step 0 changes behavior — the agent now cites empty `last_sha` as its reason and early-exits — but it still emits the non-canonical `{"status": "idle", ...}` shape rather than the instructed `{"prs": [], "jira_issues": []}`. The step 0 is kept because the early-exit half is honored and the edit does no harm; the canonical-shape half awaits CCE-10.

**Systematic-debugging artifacts (committed for reference).**

- `docs/superpowers/measurements/2026-05-20-cce9-phase1-evidence.md` — original H4 confirmation + H1 refutation, with captured raw stdout.
- `docs/superpowers/measurements/2026-05-20-cce9-h4-validation.md` — null+evidence narrative from the 3-run validation, with two new orthogonal root causes identified (stop-verify hook contamination + agent's "status report" reflex overriding three explicit canonical-shape signals).
- Six raw-evidence artifact files (3× stdout, 3× state.json) alongside.

**Follow-up filed.**

- **CCE-10** — bundles hook-suppression + stronger canonical-shape forcing into one PR, using the new `DOCS_AGENT_DEBUG_DIR` capture as the measurement vehicle. See https://designitright.atlassian.net/browse/CCE-10.

No new runtime dependencies. No new configuration surfaces. Soft-fail contract from v0.1.1 preserved.

## [0.1.3] — 2026-05-20

### State hygiene (CCE-5)

- `state.current_run.partial_reasons` no longer carries forward across runs. The state-init block in `scripts/orchestrator_runner.py` now constructs a fresh `current_run` with `partial: false` / `partial_reasons: []` before checking the prior run for staleness; the `stale_current_run_cleared` diagnostic is preserved by writing into the fresh `current_run` via `add_partial`.
- Persistent root causes (e.g. a malformed agent contract) re-accumulate naturally on each run's own dispatches. Transient reasons (e.g. `schema_invalid: source-collector: ...`, `push_failed: ...`) now belong only to the run that produced them.
- New integration tests at `tests/orchestrator/test_state_carry_forward.py` (3 cases) lock the no-carry-forward contract. Existing stale-clear sentinel at `tests/orchestrator/test_pipeline_integration.py::test_stale_current_run_cleared_on_next_run` remains green.
- No new dependencies. No new configuration. Future opt-in carry-forward (none today) would require an explicit allowlist per the design spec.

## [0.1.2] — 2026-05-20

### Schema enforcement (CCE-4)

- New `dispatch_validated(name, inputs, *, dry_run_dir, cwd) -> tuple[dict | None, list[str]]` in `scripts/orchestrator_runner.py` composes `dispatch_subagent` with `contracts.validate_and_parse`. Off-contract LLM responses now surface as a specific `schema_invalid: <name>: <field-detail>` line in `state.current_run.partial_reasons` instead of being silently absorbed by `dict.get(...)` fallbacks.
- All nine subagent call sites (six in `orchestrator_runner.py`, two effective in `verify_runner.py`) consume the new tuple. The `if not reasons` guard ensures exactly one reason line per failed dispatch — specific schema reason if available, the existing generic `<name>_invalid: returned None` otherwise.
- All seven agent `.md` files gain an `## Output schema (canonical)` section containing the canonical JSON Schema from `agents/schemas/<name>.schema.json`. The schema is now authoritative in the agent system prompt itself, not just in code.
- New drift-prevention lint at `tests/agents/test_schema_md_sync.py` (parameterized over all 7 agents) asserts the `.md` schema block is JSON-equivalent to the `.json` file.
- New `dispatch_validated` boundary tests (4 cases) at `tests/orchestrator/test_dispatch_validated.py`.
- New end-to-end schema-invalid soft-fail integration test at `tests/orchestrator/test_schema_invalid_soft_fail.py` with `fakes_schema_invalid/` fixtures (the literal Mode-B observed wrong shape).
- No new runtime dependencies. No new configuration surfaces. Soft-fail contract from v0.1.1 preserved.

## [0.1.1] — 2026-05-20

### Foundation

- New `scripts/contracts.py`: typed dataclasses for all 7 subagent outputs + `validate_and_parse` against per-agent JSON schemas in `agents/schemas/`. _Runtime enforcement (wiring `validate_and_parse` into `dispatch_subagent`) is deferred to v0.1.2; the production dispatch still consumes raw dicts but tolerates malformed output via the None-return path added in B2._
- New `scripts/gh_client.py`: `GhClient` wraps all gh CLI calls with `GhResult` (ok/value/error). `FakeGhClient` for tests.
- New `scripts/state_io.py`: `load_config_validated` and `load_state_validated` hard-fail with exit 2 on schema violations. Also hosts `add_partial`, `cleanup_empty_parents`, `load_voice_samples`, `resolve_lens`.
- New per-subagent schemas in `agents/schemas/`.

### Contract fixes (Category A)

- A1: source-collector now receives `jira` input when configured.
- A2: source-collector's `jira_issues` are looked up per PR and passed as `jira_context` to pr-summarizer.
- A3, A4: voice samples (host CLAUDE.md + `voice.sample_paths`) passed to page-author and content-validator.
- A5: orchestrator constructs `pr_id` and passes it to gap-detector; agent echoes it back.
- A6: page paths pre-filtered against `agent_editable_paths` before any `mkdir`.

### Error handling (Category B + F)

- B1: PR-number parsing has 3-stage fallback (URL int → regex → pr_list_for_branch).
- B2: `dispatch_subagent` catches `JSONDecodeError`, `FileNotFoundError`, empty stdout — returns `None` and the caller adds a `partial_reason`.
- B3: verify_runner wraps subagent calls in `try/finally` so state.json is always written.
- B4: `git push` failures recorded as `push_failed: ...` partial reasons.
- B5: `pr_list_for_branch` catches non-JSON gh output.
- B6: zero-PR runs no longer write empty whats_new entries.
- B7, B8: source-collector and pr-summarizer `error`/`partial` fields propagated.
- F1: source-collector `partial: true` trips orchestrator's partial flag.
- F2: stale `current_run` (>24h old) cleared with `stale_current_run_cleared` reason.
- F3: branch names use hour precision (`docs-agent/YYYY-MM-DDTHH`).
- F4: empty parent directories cleaned up after blocked-create unlinks.
- F5: page-author dispatches batched per (lens, page_hint) target.

### Schemas (Category C)

- C1: config and state validated on load via `jsonschema`; hard-fail with exit 2.
- C2: `dismissed_gap_flags` schema describes the value semantics.
- C2: `current_run.started_at` required.
- Config schema accepts `lens_paths` dict form, `voice.sample_paths`, `lint.stub_paths`.

### Dead code & structural (Category D)

- D1: archive*indexes wired in via `archive_indexes.regenerate()`; empty subdirs emit `\_No entries yet.*`.
- D2: Docusaurus detection emits `docusaurus_v0.1_unsupported` warning; framework_build skip is now structured.
- D3: lint_runner CLI contract documented at top of `lint_runner.py`.
- D4, D5: `duplicate_content.py` and `reading_grade.py` now exit 1 on failure (was 2).
- D6: `diagrams.py` returns structured `(False, "file not found")` instead of raising.
- D7: `stub_redirect.py` reads paths from `lint.stub_paths` when `tier1: default`.

### Test coverage (Category E)

- ~37 new tests across `tests/contracts/`, `tests/gh/`, plus integration tests for partial-run paths, multi-PR runs, unsafe page paths, jira threading, voice samples, hour-precision branches, stale state cleanup, and gh-fixture-driven verify_runner production path.
- Final suite: 100+ tests (was 64 at v0.1.0).

### Item 3 — framework_build signaling

- `framework_build.py` result now includes `skipped: bool` and `reason: str` fields. `ok=true skipped=true` means "couldn't validate"; `ok=true skipped=false` means "build passed".

## v0.1.0 — 2026-05-19

Initial release.

### Plugin

- 7 specialized subagents (source-collector, pr-summarizer, gap-detector, page-author, content-validator, publish-verifier, notifier).
- Orchestrator skill + setup skill.
- Main authoring workflow + post-merge verify workflow.

### Lint

- Tier 1 (default-on, block): frontmatter_schema, internal_links, markdown_hygiene, footnotes, diagrams, framework_build, stub_redirect.
- Tier 2 (opt-in, block): banned_phrases, ai_tells, voice_consistency (LLM-based), terminology, second_person, paragraph_length.
- Tier 3 (advisory, warn): reading_grade, sentence_variance, duplicate_content (placeholder).

### Verification

- Tests for every lint rule (good + bad fixtures).
- Orchestrator integration tests using fake subagent outputs.
- E2E main-pipeline test with a fixture host repo.
- JSON schemas for config and state with validation tests.
