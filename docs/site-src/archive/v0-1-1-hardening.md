---
description: "The v0.1.1 stabilization release \u2014 tightening cross-stage typed\
  \ contracts, hardening state and frontmatter I/O for malformed input, rounding out\
  \ the GitHub client error paths, and completing the Tier-1 lint rule set. No new\
  \ capabilities; correctness only."
source_files:
- scripts/archive_indexes.py
- scripts/contracts.py
- scripts/gh_client.py
- scripts/lint/diagrams.py
- scripts/lint/duplicate_content.py
- scripts/lint/framework_build.py
- scripts/lint/lint_runner.py
- scripts/lint/reading_grade.py
- scripts/orchestrator_runner.py
- scripts/setup_discover.py
- scripts/state_io.py
- scripts/verify_runner.py
- templates/*.schema.json
- tests/contracts/test_contracts.py
- tests/contracts/test_state_io.py
- tests/gh/test_gh_client.py
- tests/orchestrator/test_pipeline_integration.py
- tests/orchestrator/test_verify_runner.py
- tests/setup/test_setup_discover.py
last_reviewed: '2026-05-28'
status: draft
doc_kind: decision
sources: []
synthesized_into: []
---

# v0.1.1 Hardening

v0.1.1 is a stabilization release. It tightens the contracts between pipeline stages, expands test coverage across the orchestrator and verification paths, and rounds out the Tier-1 lint rule set. No new capabilities are added; the focus is correctness under edge cases the initial release exposed.

## What changed

### Typed contracts and state I/O

`scripts/contracts.py` defines the dataclasses that cross subagent boundaries — `PRSummary`, `SourceCollectorOutput`, `PageAuthorOutput`, and the rest. v0.1.1 extends these with stricter field validation and ensures every field used by downstream stages is present and typed, not inferred from dict access.

`scripts/state_io.py` owns frontmatter parsing (`archive_indexes.parse_frontmatter`), state-file loading, and the lens-path / editable-path invariant check (`_validate_lens_paths_are_editable`). Hardening here covers two gaps: malformed YAML frontmatter now raises a structured error instead of propagating a bare `KeyError`, and the editable-path validator now accepts the bidirectional compatibility rule (glob anchor and lens path must share a path branch, in either containment direction).

### GitHub client

`scripts/gh_client.py` wraps the GitHub REST API for PR metadata and commit history. v0.1.1 adds retry logic on 5xx responses and normalises the `merged_at` field to UTC ISO-8601 regardless of what the API returns. `tests/gh/test_gh_client.py` covers the retry path and the timestamp normalisation with fixture-driven responses — no real network calls.

### Orchestrator pipeline

`scripts/orchestrator_runner.py` drives the seven-stage nightly pipeline. The hardening changes are:

- The `--no-pr` dry-run flag now propagates correctly through the `page-author` and `notifier` dispatch calls. Previously, the flag suppressed the GitHub PR open but still attempted to push a branch.
- Stage outputs are validated against their JSON schemas in `templates/*.schema.json` before being passed to the next stage. A schema mismatch surfaces as a pipeline error with the stage name and field path, not a cryptic downstream crash.
- `tests/orchestrator/test_pipeline_integration.py` adds an end-to-end fixture test covering the full seven-stage sequence in dry-run mode.

### Publish verification

`scripts/verify_runner.py` polls the host's GitHub Actions workflow after the docs PR merges and checks that the target pages are live. v0.1.1 fixes a race where `verify_runner` would mark a run successful if the workflow was still queued (not yet started). The runner now treats `queued` and `in_progress` states as pending rather than success, retrying up to the configured timeout.

`tests/orchestrator/test_verify_runner.py` covers the queued-state race, timeout expiry, and the happy path where the workflow completes within the polling window.

### Setup discovery

`scripts/setup_discover.py` detects the host repo's layout — framework type, docs directory, existing config — and scaffolds `.engineering-docs-agent/config.yml`. The hardening change adds detection for hosts where `docs/` exists but contains no Markdown files yet (e.g., a brand-new repo). Previously, the absence of `.md` files caused the framework detector to emit `unknown` and skip config generation.

`tests/setup/test_setup_discover.py` adds fixtures for the empty-docs case and for a monorepo where the docs directory is nested under a sub-package.

### Lint rules

The Tier-1 lint set is now complete. Four rules ship in this release:

| Script                              | Rule                 | What it checks                                                                                |
| ----------------------------------- | -------------------- | --------------------------------------------------------------------------------------------- |
| `scripts/lint/diagrams.py`          | `diagram_alt_text`   | Every Mermaid or image block has a non-empty alt/caption                                      |
| `scripts/lint/duplicate_content.py` | `duplicate_sections` | No two pages share an identical H2+ section heading within the same lens                      |
| `scripts/lint/framework_build.py`   | `framework_build`    | The docs framework (MkDocs, Docusaurus) builds without errors against the current source tree |
| `scripts/lint/reading_grade.py`     | `reading_grade`      | Body prose stays within the configured Flesch–Kincaid grade range                             |

Run all Tier-1 rules in one pass:

```bash
python scripts/lint/lint_runner.py \
  --config .engineering-docs-agent/config.yml \
  --paths docs/site-src/**/*.md \
  --json
```

The runner returns a non-zero exit code if any enabled rule fires, making it safe to gate in CI.

### JSON schemas

`templates/*.schema.json` now covers every subagent output shape. The orchestrator validates stage output against the matching schema at runtime (`scripts/orchestrator_runner.py`). If your subagent emits a field the schema doesn't recognise, the pipeline logs a warning but continues — unknown fields are not fatal. Missing required fields are fatal.

## Source file index

| File                                              | Role                                        |
| ------------------------------------------------- | ------------------------------------------- |
| `scripts/archive_indexes.py`                      | Frontmatter parsing, archive index helpers  |
| `scripts/contracts.py`                            | Typed dataclasses for inter-stage contracts |
| `scripts/gh_client.py`                            | GitHub REST API wrapper                     |
| `scripts/lint/diagrams.py`                        | Diagram alt-text lint rule                  |
| `scripts/lint/duplicate_content.py`               | Duplicate section heading lint rule         |
| `scripts/lint/framework_build.py`                 | Framework build lint rule                   |
| `scripts/lint/lint_runner.py`                     | Tier-1/2/3 rule runner                      |
| `scripts/lint/reading_grade.py`                   | Reading grade lint rule                     |
| `scripts/orchestrator_runner.py`                  | Seven-stage pipeline orchestrator           |
| `scripts/setup_discover.py`                       | Host repo layout detection                  |
| `scripts/state_io.py`                             | State file I/O, lens-path validation        |
| `scripts/verify_runner.py`                        | Post-merge publish verification             |
| `templates/*.schema.json`                         | Subagent output JSON schemas                |
| `tests/contracts/test_contracts.py`               | Contract dataclass unit tests               |
| `tests/contracts/test_state_io.py`                | State I/O and frontmatter parse tests       |
| `tests/gh/test_gh_client.py`                      | GitHub client fixture tests                 |
| `tests/orchestrator/test_pipeline_integration.py` | End-to-end dry-run pipeline test            |
| `tests/orchestrator/test_verify_runner.py`        | Verify runner edge-case tests               |
| `tests/setup/test_setup_discover.py`              | Setup discovery fixture tests               |
