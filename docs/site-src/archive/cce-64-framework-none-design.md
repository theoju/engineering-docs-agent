---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/84
synthesized_into: []
---

# CCE-64 — `framework: none` design rationale

This page captures the design decisions behind CCE-64, which elevated `docs.framework: none` from a silent coercion to a first-class config value. The user-facing how-to lives at `docs/host-onboarding/framework-none.md`; the operator reference is at `docs/site-src/core/operations/framework-none-support.md`.

## The problem

Before CCE-64, onboarding a host with no static site generator (SSG) required scaffolding a synthetic `mkdocs.yml` purely to pass preflight validation. The `preflight_host.proposed_config()` function at `scripts/preflight_host.py:41` silently coerced `framework=None` to `"mkdocs"`, then `compute_warnings()` told the user to install mkdocs. The plugin's own design principle — "degrade gracefully; never error, never emit an empty artifact" — was being violated at the entry point for new adopters.

This contradiction surfaced when onboarding `theoju/claude-code-self-assessment` (CCE-57), a Next.js repo whose docs are plain markdown with no SSG. The bootstrap PR was forced to add `mkdocs.yml` and `requirements-docs.txt` as build noise.

## The decision

Three approaches were considered on 2026-05-29:

- **(A) First-class `none` + capability auto-derivation** — chosen.
- **(B) Pluggable adapter pattern** — rejected as premature; there is only one branch of behaviour that needed new treatment.
- **(C) Capability flags** — rejected as inconsistent with the convention-optimised stance; hosts should not have to enumerate what they lack.

Approach A is the minimum-viable change. It does not block evolution to (B) when a third framework with build-validation support lands.

## What changed

### Config schema (`templates/config.schema.json`)

The `docs.framework` enum was extended from `["mkdocs", "docusaurus"]` to `["mkdocs", "docusaurus", "none"]`. The change is additive — existing configs keep working.

### Preflight (`scripts/preflight_host.py`)

Two targeted changes:

1. `proposed_config()` (line 41) — the coercion `framework or "mkdocs"` became `framework or "none"`. No new host gets a phantom mkdocs requirement.

2. `compute_warnings()` (lines 94–106) — the `no_docs_framework` warning (severity `block`) was replaced by a `framework_none` notice (severity `info`). The notice describes what skips — build validation and publish verification — and points to the mkdocs upgrade path for teams that want strict link checking later.

The `severity` field is now part of the warning schema. Callers that do not read it are unaffected; the existing `docusaurus_v0.1_unsupported` entry is retroactively an info-level notice.

### Lint rule (`scripts/lint/framework_build.py`)

The default fallback at line 44 changed from `"mkdocs"` to `"none"`. A dedicated branch was added:

```python
if framework == "mkdocs":
    ok, skipped, reason = run_mkdocs(Path.cwd())
elif framework == "none":
    ok, skipped, reason = (True, True, "framework=none; no build validation applicable")
else:
    ok, skipped, reason = (
        True, True,
        f"framework={framework}; build validation not supported in v0.1",
    )
```

The rule's severity stays `block`. An individual `skipped` result with `ok=True` already short-circuits the block path, so no host gets flagged for a deliberate `framework: none` choice.

## What did not change

- Existing host configs with `framework: mkdocs` or `framework: docusaurus` — additive enum extension only.
- `setup_discover.detect_pages_publishable()` — already returned `False` for non-mkdocs; that is now the documented behaviour for `none`.
- The nightly pipeline shape — authoring still emits portable markdown that works on any host.
- All Tier-1 lint rules other than `framework_build`.

## Data flow after CCE-64

```
host repo (no SSG)
  └─→ setup_discover.discover()
        └─→ framework: None
  └─→ preflight_host.proposed_config()
        └─→ writes: docs.framework: none
        └─→ writes: publishing.base_url: null, build_workflow: null
  └─→ preflight_host.compute_warnings()
        └─→ emits: framework_none (severity: info)

nightly run
  └─→ orchestrator loads .engineering-docs-agent/config.yml
  └─→ page-author emits markdown
  └─→ content-validator runs all lint rules
        └─→ framework_build: ok=True, skipped=True
  └─→ publish-verifier: base_url null → skipped
  └─→ PR opened with whats-new entry + summaries
```

## Migration

No migration required for existing hosts. The schema change is additive; `framework: mkdocs` and `framework: docusaurus` configs validate and behave identically.

The CCE-57 follow-up — switching `theoju/claude-code-self-assessment` from its synthetic mkdocs scaffold to `framework: none` — is a separate commit on the host repo after CCE-64 lands on `main`.

## Success criteria

1. A host with no SSG onboards via `preflight_host` and receives a valid config with `docs.framework: none` and no mkdocs scaffold.
2. A nightly run on that host completes cleanly; `partial_reasons` lists `verify_skipped_no_base_url` (not a generic build failure).
3. The CCE-57 host migrates to `framework: none` without losing any working capability.

## References

- `scripts/preflight_host.py:41` — the coercion that was corrected
- `scripts/preflight_host.py:94-106` — `compute_warnings`, now emitting `framework_none` info notice
- `scripts/lint/framework_build.py:44-52` — lint default + skip path
- `scripts/setup_discover.py:8-15` — `detect_framework` (already returned `Optional`)
- `templates/config.schema.json:17-21` — the extended enum
- `docs/superpowers/specs/2026-05-29-cce64-framework-none-first-class-design.md` — the full spec
- `CLAUDE.md` — "generic-first, convention-optimized" and "degrade gracefully" principles
