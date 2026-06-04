---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/84
synthesized_into: []
---

# Design Record: `docs.framework: none` (CCE-64)

**Date:** 2026-05-29  
**Ticket:** CCE-64  
**PR:** [#84](https://github.com/theoju/engineering-docs-agent/pull/84)  
**Status:** Landed

## Context

Host repos without a static-site generator couldn't adopt the plugin without scaffolding a synthetic mkdocs site. The `docs.framework` enum in `templates/config.schema.json` only accepted `"mkdocs"` and `"docusaurus"`. Any host that set no framework — or tried to set an explicit opt-out — failed schema validation at plugin boot.

The immediate trigger was CCE-57 (`theoju/claude-code-self-assessment`), a Next.js app that keeps plain-markdown docs and has no desire to run a separate SSG. Requiring mkdocs installation just to pass preflight validation contradicts CLAUDE.md's "degrade gracefully" principle. The plugin's internal code already contained skip paths for non-mkdocs frameworks; the problem was that those paths were unreachable from a valid config.

## Options Considered

Three approaches were evaluated before CCE-64:

**Approach 1 — First-class `"none"` value with capability auto-derivation** *(chosen)*  
Add `"none"` to the enum. Every capability that touches framework-specific behaviour checks `if framework == "none"` and skips cleanly. The preflight warning becomes an info-severity notice, not a blocker. No new config surface beyond the single enum value.

**Approach 2 — Pluggable adapter pattern**  
Define an abstract `FrameworkAdapter` interface and ship `MkDocsAdapter`, `DocusaurusAdapter`, and `NullAdapter` implementations. Config dispatches to the right adapter at boot. This gives a clean extension point for future SSGs but adds a class hierarchy and an indirection layer before there is a third real framework in production. Deferred as premature.

**Approach 3 — Per-capability feature flags**  
Add boolean flags (`publishing.enabled`, `lint.framework_build.enabled`, etc.) that hosts toggle individually. This gives maximum granularity but forces hosts to specify every opt-out explicitly, makes the config surface wider, and breaks the convention that capabilities auto-degrade based on what the host provides. Rejected as convention-breaking.

## Decision

Approach 1 landed in PR #84. The changes are:

- `templates/config.schema.json`: `docs.framework` enum extended to `["mkdocs", "docusaurus", "none"]`.
- `scripts/lint/framework_build.py`: explicit `elif framework == "none": return` skip branch before the mkdocs-specific lint logic.
- `scripts/preflight_host.py`: the `no_docs_framework` warning (block severity) replaced with a `framework_none` notice (info severity). A missing framework is still surfaced; it's no longer a hard stop.
- `publishing.base_url` and `publishing.build_workflow`: both fields accept `null` when `framework` is `"none"`.
- `docs/host-onboarding/framework-none.md`: operator-facing guide covering when to choose `framework: none`, which capabilities run vs. skip, and the upgrade path to mkdocs.

## What Was Deferred

Two hardening items were explicitly deferred out of scope for CCE-64:

**JSON Schema `if/then/else` guard.** A stricter schema could enforce that `publishing.base_url` must be non-null when `framework != "none"`. Adding `if/then/else` to the schema is valid JSON Schema draft-07 but makes the schema significantly harder to read. The existing runtime preflight check (`scripts/preflight_host.py`) catches misconfigured publishing blocks at boot. The guard is left for a future schema-hardening pass.

**`contracts.py` `PreflightWarning` dataclass.** The current preflight emits plain dicts. Formalising the warning shape into a typed dataclass in `scripts/contracts.py` would improve type safety across preflight callers but is a cross-cutting refactor touching multiple capabilities. It was not included in this PR to keep the diff focused and reviewable.

Both items have no user-visible behaviour impact today. If a future PR touches preflight warning shapes, the dataclass refactor belongs in that same change.

## Follow-up

A follow-up PR against `theoju/claude-code-self-assessment` will drop the synthetic mkdocs scaffold from that repo and flip its config to `framework: none`. That PR will validate the operator experience end-to-end. The `operations/framework-none.md` page may receive an edit once that PR lands if the upgrade path needs adjustment based on real usage.
