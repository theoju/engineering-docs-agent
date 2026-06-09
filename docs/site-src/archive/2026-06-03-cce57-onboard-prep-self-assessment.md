---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
doc_kind: decision
---

# Decision: Dry-Run Fixture Pattern for CCSA Onboarding Prep (CCE-57)

**Date:** 2026-06-03  
**Ticket:** CCE-57  
**PR:** [#83](https://github.com/theoju/engineering-docs-agent/pull/83)

## Decision

Onboarding a new host repo — `theoju/claude-code-self-assessment` (CCSA) — starts with a dry-run fixture that captures the proposed plugin configuration. No writes go to the target repo until the fixture shape is reviewed and tests pass.

## Context

The engineering-docs-agent plugin runs against arbitrary host repos. Before it can generate nightly docs PRs for a host, the plugin config for that host must be correct: `lens_paths`, `agent_editable_paths`, `sources`, `extractors`, and the `docs_dir` must all resolve correctly against the host's actual tree.

Writing a bad config directly to the host is destructive. It can break an existing docs pipeline or leave partial state that is difficult to undo.

## What Was Done

PR #83 adds `_proposed_config_self_assessment()` to `scripts/preflight_host.py`. The function returns the full proposed config dict for the CCSA host. It does not touch the target repo.

Three unit tests in the PR validate the CCSA-specific config shape: that required keys are present, that `lens_paths` entries are covered by `agent_editable_paths` globs (the config invariant enforced by `_validate_lens_paths_are_editable`), and that the returned dict matches the expected structure.

A design spec and execution plan were added under `docs/superpowers/` as the primary source-of-truth records for this onboarding. This archive page surfaces the decision in the core lens for readers who do not traverse `superpowers/`.

## Rationale

The fixture pattern separates two concerns that are easy to conflate:

1. **Shape validation** — does the proposed config satisfy the plugin's invariants?
2. **Live application** — does writing this config to the target repo do the right thing?

Keeping them separate lets you iterate on shape in CI without touching the host. Once the fixture is stable and all tests pass, the actual onboarding write becomes a single, low-risk step.

This pattern is reusable. Any future host onboarding follows the same sequence: add a `_proposed_config_<host>()` fixture, write tests against it, get green CI, then apply.

## Relation to CCE-58

CCE-58 covers onboarding the ADIS host in parallel. The two onboardings share the same fixture pattern but are independent branches. Neither blocks the other.
