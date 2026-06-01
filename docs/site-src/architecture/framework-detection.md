---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/84
synthesized_into: []
---

# Framework Detection and Capability Auto-Derivation

The plugin determines which site-generation capabilities to enable by detecting the host's static site generator (SSG) at setup time. This page describes the three components that implement that detection pipeline and how they coordinate.

## The three components

**`setup_discover.detect_framework()`** reads the host repo root and returns one of `'mkdocs'`, `'docusaurus'`, or `'none'`. It checks for the presence of `mkdocs.yml`, `docusaurus.config.js` (and its `.ts` variant), in that order. If neither is found, it returns `'none'`. The function never raises; it degrades to `'none'` when it cannot determine a framework.

**`preflight_host.proposed_config()`** takes the detection result and writes it directly into the proposed config block. Before PR #84, an absent-framework detection was silently coerced to `'mkdocs'`, creating a hidden assumption that every host has MkDocs. That coercion is gone. The function now emits `framework: none` as-is and logs an `info`-severity message rather than a `block` warning.

**`framework_build` (lint rule)** validates that the configured framework's build toolchain is present. When `framework: none` is set, this rule skips with the reason `framework_none_skipped` rather than failing or emitting a warning. The skip is surfaced in lint output so it is visible but not actionable.

## How capability auto-derivation works

The `framework` value gates the following behaviors:

| `framework` value | `framework_build` lint | Docs publish step |
|---|---|---|
| `mkdocs` | Runs; expects `mkdocs.yml` + `requirements-docs.txt` | Calls `mkdocs build` |
| `docusaurus` | Runs; expects `package.json` with Docusaurus dependency | Calls `npm run build` |
| `none` | Skipped (`framework_none_skipped`) | Skipped |

No other capability is gated on `framework`. Source collection, PR summarization, page authoring, gap detection, and Slack/email notification all run regardless of the framework value.

## Why `none` is a first-class value

The plugin's design principle is "degrade gracefully." A host with plain markdown docs and no SSG is a valid steady state, not a configuration error. Before this change, the schema's closed enum `['mkdocs', 'docusaurus']` forced such hosts to introduce a synthetic `mkdocs.yml` purely to pass schema validation. That added toolchain dependencies the host did not need or want.

Setting `framework: none` removes that requirement. The plugin still authors and lints docs pages; it simply skips the build-and-publish step.

## Config example

```yaml
# .engineering-docs-agent/config.yml
site:
  framework: none
  docs_dir: docs/
```

This is the minimum config for a host with no SSG. The plugin will read from `docs/` (or whatever `docs_dir` points to), author updates, and open a PR — but it will not attempt to build or publish a static site.

## Upgrade path

When you add an SSG to a host that started with `framework: none`, change the config value to match the new framework and commit the SSG config files (`mkdocs.yml` or `docusaurus.config.js`). The `framework_build` lint rule will activate on the next run and validate the toolchain is wired correctly.

See also: `docs/host-onboarding/framework-none.md` (shipped with PR #84) for the host-onboarding walkthrough, and `docs/site-src/operations/framework-none-config.md` for the operational runbook covering when to use `framework: none` and how to flip it later.
