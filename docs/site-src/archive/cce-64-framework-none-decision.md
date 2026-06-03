---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/84
synthesized_into: []
---

# ADR: `docs.framework: none` as a first-class config value

**Tickets:** CCE-64, CCE-57  
**PR:** [#84](https://github.com/theoju/engineering-docs-agent/pull/84)  
**Date:** 2026-06-03  
**Status:** Accepted

## Context

CCE-57 onboarded `theoju/claude-code-self-assessment`, a JS/TS repository that ships no documentation framework. Every host had to present a real or synthetic mkdocs scaffold to pass preflight. For repos without mkdocs or Docusaurus this forced a scaffolding step that added noise and broke the "generic plugin" promise.

The root cause was a closed enum. `docs.framework` accepted only `mkdocs` or `docusaurus`. `detect_framework()` returning nothing had no valid mapping, so `preflight_host.py` fell back to constructing a synthetic mkdocs skeleton regardless of whether the host wanted one.

## Decision

Add `none` as an explicit third value in the `docs.framework` enum.

`preflight_host.py` now writes `framework: none` when `detect_framework()` returns nothing. No synthetic scaffold is created. The `framework_build` lint rule skips with an explicit logged reason (`framework: none — skipping build lint`) rather than erroring. The config JSON schema (`templates/config.schema.json`) permits `none` in the enum so validation passes at load time.

## Why not a silent default?

A silent fallback would leave `framework` absent from the config, forcing every downstream reader to treat a missing key as `none`. That scatters the `None`-check across callers. An explicit value in config is unambiguous, grep-able, and self-documenting. Any future rule that needs to branch on framework presence gets a clear signal without re-running detection.

## Consequences

**Positive:**
- The plugin runs on any host regardless of docs framework. No synthetic scaffold is imposed.
- `framework_build` lint rule degrades cleanly instead of erroring on a frameworkless host.
- Config schema validation passes on first run for new JS/TS or other non-framework hosts.
- A companion host-onboarding guide (`docs/host-onboarding/framework-none.md`) documents the end-to-end setup path for `framework: none` hosts.

**Negative / watch-outs:**
- Hosts that previously relied on the synthetic mkdocs scaffold being auto-created must now set `framework: none` explicitly or migrate to a real framework entry. Existing hosts with a written `framework: mkdocs` or `framework: docusaurus` are unaffected.
- The `framework_build` lint stage produces no output for `none` hosts. If you want build-time validation, you must provide your own CI step; the plugin will not scaffold one.

## Files changed

- `scripts/preflight_host.py` — writes `framework: none` when detection returns nothing.
- `templates/config.schema.json` — adds `"none"` to the `docs.framework` enum.
- `scripts/lint/rules/framework_build.py` — early-exit with explicit skip reason when `framework == "none"`.
- `docs/host-onboarding/framework-none.md` — new host-side onboarding guide (shipped on the host repo).

## Related

- Operations guide: `docs/site-src/core/operations/framework-none-onboarding.md`
- Originating ticket: CCE-57 (theoju/claude-code-self-assessment onboarding blocker)
- Design decision: CCE-64
