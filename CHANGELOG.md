# Changelog

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
