---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/84
synthesized_into: []
---

# Generic Host Framework Support

The plugin runs on any host repo — including hosts that have no static-site generator at all. `framework: none` is a first-class value in the config schema, not a fallback or an omission. This page describes the design contract that makes that true.

## The problem it solves

Before CCE-64, a host with no SSG had two bad options: omit `framework` and get coerced to `mkdocs` silently, or set it to an unrecognized value and get a schema validation error. Either path produced an incorrect config and a confusing failure. Onboarding `theoju/claude-code-self-assessment` (CCE-57) surfaced this gap directly.

## Schema contract

`templates/config.schema.json` defines the `framework` field as:

```json
"framework": {
  "type": "string",
  "enum": ["mkdocs", "docusaurus", "none"]
}
```

`none` is a peer of `mkdocs` and `docusaurus` in the enum — not a fallback, not a sentinel. Any config that omits `framework` entirely still fails schema validation; you must declare it explicitly.

The `publishing` block pairs naturally with `framework: none`: `base_url` and `build_workflow` both accept `null` (`type: ["string", "null"]`). The `preflight_host.py` scaffolder writes `null` for both when it detects no framework. A future `if/then/else` guard may enforce that `null` publishing fields are only valid alongside `framework: none`; for now, schema validation does not police the combination.

## Lint behavior

The `framework_build` Tier-1 lint rule skips with a structured reason when `framework` is `none`:

```
framework=none; no build validation applicable
```

This surfaces in the run digest as a clean skip, not a warning or failure. The rule's code path branches at the top of `scripts/lint/framework_build.py` before invoking any build toolchain.

All other Tier-1 lint rules — `stale_content`, `missing_frontmatter`, `broken_links`, `orphan_pages`, `voice_consistency`, `stub_detection` — run without modification regardless of `framework`.

## Preflight behavior

`scripts/preflight_host.py` writes `framework: none` directly when framework detection returns no match. It no longer falls through to `mkdocs` as an implicit default. The written value passes schema validation and produces a stable config that the orchestrator reads without mutation.

## Publish verifier behavior

The publish verifier skips when `publishing.base_url` is `null`. A host with `framework: none` and no publishing URL has no live URL to verify; the verifier logs a structured skip rather than an error. The nightly run completes normally.

## What the plugin still does on a framework=none host

Every stage except build-lint and publish-verification runs at full fidelity:

- `pr-summarizer` — reads Git and Jira, produces summaries.
- `page-author` — authors and edits pages with voice few-shot.
- `content-validator` — runs all applicable Tier-1 lint rules.
- `gap-detector` — flags non-trivial PRs with no spec or plan coverage.
- `notifier` — sends Slack and email digest.
- The What's New entry and the nightly PR are produced as normal.

The agent provides full documentation authoring value even when the host has no docs build pipeline.

## Upgrade path

When you add an SSG to a previously framework-none host, update `.engineering-docs-agent/config.yml`:

```yaml
docs:
  framework: mkdocs   # was: none

publishing:
  base_url: https://<owner>.github.io/<repo>/
  build_workflow: deploy.yml
```

Run `preflight_host.py` again or edit manually. The `framework_build` rule will start running on the next nightly cycle once the workflow file is committed.

## Related

- Operator reference: `docs/site-src/operations/framework-none.md`
- Host onboarding guide: `docs/host-onboarding/framework-none.md`
- Lint rule implementation: `scripts/lint/framework_build.py`
- Preflight scaffolder: `scripts/preflight_host.py`
- Config schema: `templates/config.schema.json` (`docs.framework` and `publishing`)
