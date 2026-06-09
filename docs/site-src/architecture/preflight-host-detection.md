---
description: "The preflight script (scripts/preflight_host.py) runs during engineering-docs-agent-setup to discover what a host repo already has before generating a config."
source_files:
  - scripts/preflight_host.py
last_reviewed: '2026-06-09'
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/82
synthesized_into: []
---

# Preflight Host Detection

The preflight script (`scripts/preflight_host.py`) runs during `engineering-docs-agent-setup` to discover what a host repo already has before generating a config. It probes the filesystem for known artifact types — OpenAPI schemas, package files, test directories — and pre-populates the setup questionnaire with what it found.

## OpenAPI schema detection

When you run setup on a host that already carries an OpenAPI schema, the preflight script detects it automatically. `_setup_question_openapi` checks common schema locations and pre-selects `yes` when a match is found. You are not asked to locate the schema manually.

`_proposed_config` uses the detected path to populate the `sources` block in the generated config. The emitted config is immediately usable — no placeholder substitution required after setup completes.

## Detection before config generation

Detection runs before any questions are presented. This ordering matters: answers to later questions — which lenses to enable, which extractors to activate — depend on what the preflight found. A schema presence changes whether the API-extractor capability is offered as opt-in or already active.

The detection step is read-only. It never writes files, modifies the host repo, or issues network calls. The preflight stage is dry-run by design.

## Unit test coverage

Four tests cover the detection logic added in PR #82:

- No schema present → question defaults to `no`.
- Schema at a standard path → question pre-selects `yes`.
- Detected path flows into `_proposed_config` → `sources` block populated correctly.
- Multiple candidate paths present → first match wins, deterministic output.

## Extending detection

To add detection for a new artifact type, follow the same pattern used for OpenAPI:

1. Add a probe function in `scripts/preflight_host.py` that returns the detected path or `None`.
2. Pass the result into the relevant `_setup_question_*` function as a default.
3. Thread the value through `_proposed_config` if it affects the generated `sources` or `extractors` block.
4. Add unit tests for the absent and present cases, plus the flow into the proposed config.

Detection functions must be pure filesystem reads — no subprocess calls, no network, no side effects.
