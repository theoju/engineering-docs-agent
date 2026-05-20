# Changelog

## [0.1.1] — 2026-05-20

### Foundation

- New `scripts/contracts.py`: typed dataclasses for all 7 subagent outputs + `validate_and_parse` against per-agent JSON schemas in `agents/schemas/`.
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
