---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/84
synthesized_into: []
---

# `framework: none` — design rationale

PR #84 (CCE-57) widened the `docs.framework` enum from `["mkdocs", "docusaurus"]` to include `"none"` as a first-class value. This page captures why the change was needed, what it does, and what to expect when you set it.

## Why the closed enum was a problem

The original schema required every host to name a static site generator. Hosts without one — e.g. a Next.js app that ships plain Markdown docs alongside source code — had no legal value to use. The workaround was to scaffold a synthetic `mkdocs.yml` and `requirements-docs.txt` purely to satisfy schema validation. That scaffolding served no functional purpose and contradicted the plugin's core principle: degrade gracefully when a host lacks a convention; never force a host to fake one.

CCE-57 surfaced this concretely during onboarding of `theoju/claude-code-self-assessment`. The repo needed a synthetic MkDocs skeleton solely for schema compliance. A follow-up PR drops that scaffold once `framework: none` is in place.

## What changed

**Schema.** The enum in the config schema now accepts `"none"` alongside `"mkdocs"` and `"docusaurus"`.

**Build checks skipped.** `framework_build.py` detects `framework: none` and skips the site-build step entirely. No `mkdocs build`, no `npm run build`, no missing-binary error.

**Preflight checks skipped.** `preflight_host.py` skips the framework-specific preflight checks (e.g. `mkdocs.yml` presence, `requirements-docs.txt` presence) when `framework` is `none`. The remaining preflight checks — config validity, editable-paths coverage, lens-path invariant — still run.

**Lint.** Build-gated lint rules that require a rendered site are skipped. Doc-source lint rules (Tier-1 through Tier-3 applied to `.md` files) still fire normally.

## What you set in config

```yaml
docs:
  framework: none
  docs_dir: docs/
  lens_paths:
    core: docs/site-src/
  agent_editable_paths:
    - docs/site-src/**
```

Setting `framework: none` is the complete change. No other keys are required or disallowed because of it.

## What the plugin still does

`framework: none` disables build-pipeline integration. Everything else operates normally:

- Source collection (Git, PRs, Jira) runs unchanged.
- PR summarization, page authoring, and gap detection run unchanged.
- The docs-agent PR is opened against the host repo as usual.
- Lint runs against the Markdown source files.
- Publish verification is skipped (there is no build to verify). The run is **not** marked `partial` for this reason — skipping a stage that was never applicable is not a gap.

## Design principle

The plugin is driven by detection, not assumptions. When a host lacks a convention, the relevant capability skips cleanly rather than erroring or demanding synthetic scaffolding. `framework: none` makes that principle explicit in the config schema: the absence of a static site generator is a valid, declared state, not a misconfiguration.

See the host-onboarding guide at `docs/host-onboarding/framework-none.md` for the step-by-step walkthrough.
