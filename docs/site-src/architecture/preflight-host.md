---
description: "scripts/preflight_host.py is the gate between a proposed host configuration and a live onboarding write."
source_files:
  - scripts/preflight_host.py
last_reviewed: '2026-06-09'
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
---

# Preflight Host: Proposed-Config Fixture Pattern

`scripts/preflight_host.py` is the gate between a proposed host configuration and a live onboarding write. Before the plugin touches a new host repo, the preflight module validates and dry-runs the full config shape. No mutations reach the target until the preflight passes.

## The proposed-config fixture

Each new host onboarding adds a dedicated fixture function to `scripts/preflight_host.py` that returns the complete proposed plugin configuration for that host. PR #83 introduced `_proposed_config_self_assessment()` for the `theoju/claude-code-self-assessment` host.

The fixture encapsulates every field the plugin's `site:` config block expects: `sources`, `extractors`, `docs_dir`, lens paths, editable paths, and any host-specific overrides. Keeping the proposed config in a named function — rather than inlining it at the call site — lets you test the shape independently of any live write.

Three unit tests in the same PR validate the CCSA-specific fixture:
- That the returned config has all required top-level keys.
- That `lens_paths` and `agent_editable_paths` satisfy the plugin's coverage invariant (every lens path is covered by at least one editable glob).
- That the fixture is dry-run safe: no filesystem writes, no network calls.

## How it gates live onboarding

The lifecycle is:

1. **Fixture authoring.** You add `_proposed_config_<host>()` and its unit tests in a PR. The PR is dry-run only — the target host repo is not touched.
2. **Review.** The PR lands; the tests confirm the config shape is valid. This is the review gate.
3. **Onboarding write.** A follow-on step (or the setup skill) reads the fixture and writes the config to the target host. The write cannot precede step 2 because the fixture function doesn't exist yet.

This two-phase approach means the config shape is reviewed and tested before it ever reaches the host. A misconfigured `agent_editable_paths` glob caught at step 1 costs a PR review cycle; the same error at step 3 would trigger live writes to the wrong paths.

## Parallel onboarding tracks

PR #83 (CCE-57) ran in parallel with CCE-58, which onboards ADIS as a separate host. Each host gets its own fixture function; they don't share state. The pattern scales: add one fixture function and three tests per host, keep them in `scripts/preflight_host.py`, and the review cycle stays consistent regardless of how many hosts the plugin manages.

## Design artifacts

The spec and execution plan for CCE-57 live under `docs/superpowers/` and are the authoritative source-of-truth for implementation decisions. This architecture page covers the fixture pattern itself; for the rationale behind specific config choices for `theoju/claude-code-self-assessment`, see the corresponding spec file in `docs/superpowers/specs/`.
