---
status: draft
ticket: CCE-64
related: CCE-57, CCE-58
created: 2026-05-29
---

# CCE-64 — Framework=none as a first-class config value

## Goal

Make "no SSG framework" a valid, first-class configuration of the engineering-docs-agent plugin. A host repo whose docs are raw markdown rendered by GitHub (or by whatever the host already has) can adopt the plugin without scaffolding a fake mkdocs site to satisfy schema validation.

## Background

The plugin already implements most of the behavior — `framework_build` lint skips cleanly for non-mkdocs, `detect_pages_publishable` returns False for non-mkdocs — but the schema and the preflight code path block `framework: none` from being a valid config. The contradiction surfaced during CCE-57 onboarding: claude-code-self-assessment is a Next.js host with plain markdown docs and no SSG, so the bootstrap PR (#100) had to ship a synthetic `mkdocs.yml` + `requirements-docs.txt` purely to pass schema validation. That is busywork the plugin's own design philosophy says it should avoid.

CLAUDE.md, project-level conventions:

> Design every capability generic-first, convention-optimized.
> Degrade gracefully — when a host lacks a convention (no specs/plans, no Python package, no OpenAPI schema, no decision sources), the affected capability skips or falls back cleanly — it never errors and never emits an empty artifact.

The current behavior of `preflight_host.proposed_config()` (`scripts/preflight_host.py:41`) is the opposite of graceful: it silently coerces `framework=None` to `"mkdocs"`, then the `no_docs_framework` warning tells the user to install mkdocs. This spec makes the detected absence a valid steady state.

## Approach

**Approach 1 of the 2026-05-29 brainstorm: First-class `none` + capability auto-derivation.**

The brainstorm considered three approaches:

- (A) First-class `none` + capability auto-derivation (this spec)
- (B) Pluggable adapter pattern — rejected as premature (one branch ≠ adapter)
- (C) Capability flags — rejected as breaking the convention-optimized stance

Approach A is the minimum viable change that resolves the contradiction. It does not preclude evolution to (B) when a third framework with build-validation support lands.

## What changes

### 1. Config schema — `templates/config.schema.json`

Extend the `docs.framework` enum:

```json
"framework": {
  "type": "string",
  "enum": ["mkdocs", "docusaurus", "none"],
  "description": "SSG framework for the host's docs site. Use 'none' when the host has no SSG and renders raw markdown via GitHub or another mechanism. Docusaurus support is partial in v0.1; build validation is skipped for 'docusaurus' and 'none'."
}
```

This is additive — existing configs keep working.

### 2. Discovery — `scripts/setup_discover.py`

`detect_framework()` already returns `str | None`. No signature change. Behavior unchanged: returns `"mkdocs"`, `"docusaurus"`, or `None`.

`discover()` keeps emitting the `docusaurus_v0.1_unsupported` warning. The "no framework detected" notice is emitted by `preflight_host.compute_warnings()` (section 3 below), not here, so `discover()` itself needs no change.

`detect_pages_publishable(framework, ci)` stays as-is — it already returns False for any framework other than mkdocs, which now correctly includes `"none"`.

### 3. Preflight — `scripts/preflight_host.py`

Two changes:

**Line 41 (`proposed_config`)**: replace the silent coercion:

```python
# Before
"framework": framework or "mkdocs",
# After
"framework": framework or "none",
```

**Lines 94-106 (`compute_warnings`)**: the `no_docs_framework` block currently tells the user to install mkdocs or Docusaurus. With `none` as a valid choice, this is no longer a warning — it's an informational notice describing the resulting capability degradation. Replace with:

```python
if not discovery.get("framework"):
    warnings.append(
        {
            "code": "framework_none",
            "severity": "info",   # not "block" — this is a valid config
            "message": (
                "No mkdocs.yml or docusaurus.config.* found at the repo root. "
                "Config will write framework: none. The framework_build lint "
                "rule and the publish-verifier will skip cleanly; PR summaries, "
                "page authoring, and what's-new updates run normally. "
                "If you want strict build-time link checking, scaffold mkdocs "
                "(`mkdocs init`) and re-run preflight."
            ),
        }
    )
```

If `warnings[*].severity` is not currently a field, this spec introduces it as optional with two values (`"block"`, `"info"`); the existing `docusaurus_v0.1_unsupported` entry remains an info-level notice. Callers that don't read `severity` are unaffected.

### 4. Lint rule — `scripts/lint/framework_build.py`

Line 44: default fallback changes:

```python
# Before
framework = config.get("docs", {}).get("framework", "mkdocs")
# After
framework = config.get("docs", {}).get("framework", "none")
```

The `if framework == "mkdocs"` branch stays; the `else` branch already returns `(True, True, "framework={framework}; build validation not supported in v0.1")`. For clarity, special-case `none` with a tighter reason:

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

Severity stays `block` because the _rule_ is still block-severity; an individual `skipped` result with `ok=True` already short-circuits the block path.

### 5. Documentation — host configs and onboarding

- `templates/hosts/advanced-data-import-system.config.yml` stays on `framework: mkdocs` (no change — it has a real mkdocs.yml).
- The setup runbook (`docs/host-onboarding/*.md` template) gains a short section: "Choosing `framework: none`". Bullets: when it applies, what skips, how to upgrade later.
- The setup skill's prompt (`skills/engineering-docs-agent-setup`) — verify it doesn't hard-code `mkdocs|docusaurus`. If it does, add `none` to the prompt's enum hint so the LLM doesn't paper over a detected absence.

## What does NOT change

- Existing host configs with `framework: mkdocs` or `framework: docusaurus` — additive enum extension.
- `framework_build`'s severity (`block`).
- `detect_pages_publishable` — already returns False for non-mkdocs; that becomes the documented behavior for `none`.
- The orchestrator pipeline shape (source-collector → pr-summarizer → page-author → content-validator → gap-detector → notifier). Authoring still emits portable markdown that works in framework=none.
- Lint tiers other than `framework_build`. Tier-1 rules (link-check, frontmatter, etc.) run identically on raw-markdown hosts.

## Data flow

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
        └─→ framework_build: ok=True, skipped=True, reason="framework=none; no build validation applicable"
  └─→ publish-verifier checks publishing.base_url
        └─→ null → skipped with partial_reason="verify_skipped_no_base_url"
  └─→ PR opened with whats-new entry + summaries
```

## Error handling

- **Invalid framework value in config**: schema validation rejects at load time. No change to existing rejection path.
- **`framework: none` with a host that DOES have mkdocs.yml**: still works — the user chose to skip build validation; their choice. Document this in the runbook as the upgrade path.
- **`framework: mkdocs` with no mkdocs.yml**: existing behavior at `framework_build.py:25-26` returns `(True, True, "no mkdocs.yml in repo root")`. Unchanged. Possibly surface this as a one-time setup-skill warning, but out of scope here.
- **publish-verifier with `framework: none` but `publishing.base_url` set**: respect the user's intent — they have an external publish pipeline. Verify runs normally. (No code change; the verifier already drives off `base_url`.)

## Testing

New tests, all under `tests/`:

1. `tests/test_config_schema.py` (extend) — assert the schema accepts a config with `framework: none` and rejects a config with `framework: hugo` (or any other unknown value).
2. `tests/test_preflight_host.py` (new or extend) — given a fixture host with no mkdocs.yml and no docusaurus.config.\*, assert:
   - `proposed_config()["docs"]["framework"] == "none"` (not `"mkdocs"`)
   - `compute_warnings()` returns a `framework_none` notice with `severity: info`, and does NOT return `no_docs_framework`
   - `proposed_config()["publishing"]["base_url"] is None`
3. `tests/lint/test_framework_build.py` (extend) — given `docs.framework: none`, assert `ok=True`, `skipped=True`, `reason=="framework=none; no build validation applicable"`.
4. `tests/test_setup_discover.py` (extend) — assert `discover()` on a no-SSG fixture returns `framework=None` (unchanged) and that the discovered dict is consumed correctly by `proposed_config`.

Existing tests for `framework: mkdocs` and `framework: docusaurus` must continue to pass unchanged.

## Migration

**Plugin and existing hosts**: no migration. The change is additive at the schema level; existing host configs (`framework: mkdocs` / `framework: docusaurus`) continue to validate and behave identically. New host onboardings get `framework: none` by default when no SSG is detected.

**CCE-57 follow-up** (opt-in, separate piece of work — claude-code-self-assessment#100):

1. Land CCE-64 plugin change on `main`.
2. Push a follow-up commit (or new PR if #100 is already merged) on the host repo that removes `mkdocs.yml`, `requirements-docs.txt`, and the mkdocs install step from the nightly workflow, and flips `.engineering-docs-agent/config.yml` to `framework: none`.

## Out of scope

- Docusaurus build-validation parity. Still partial; framework_build still skips for docusaurus with the v0.1 disclaimer.
- Adapter-class refactor (Approach B from brainstorm). Revisit when a third framework with build-validation support lands.
- Capability flag exposure (Approach C). Revisit if a host needs to override a single capability (e.g. enable framework_build with a custom command).
- Setup skill UX improvements beyond the prompt enum hint.

## Risks

- **Documentation drift**: the plugin's setup guide and runbook currently assume mkdocs. If we change the schema without updating those docs, new adopters get confused. Mitigated by Task 5 above (docs update is part of this spec).
- **Existing v0.1 hosts inspect the config and assume framework is mkdocs|docusaurus**: low risk — the only code path that reads the value is `framework_build` (this spec updates it) and `setup_discover.detect_pages_publishable` (already handles non-mkdocs correctly).
- **Schema versioning**: the schema currently has no version field. Additive enum extension means consumers using older copies of the schema would reject `none`. Acceptable for v0.1; if we get to a place where the schema is published independently of the plugin, add a `$id` version field then.

## Success criteria

1. A host with no SSG can be onboarded by the setup skill or `preflight_host` and ends with a config that passes schema validation, no synthetic scaffold required.
2. A nightly run on such a host completes without errors and the PR body's `partial_reasons` clearly lists `framework_none` (or the verify-skip equivalent) — not a generic "build failed."
3. The CCE-57 host (claude-code-self-assessment) is migrated to `framework: none` without losing any working capability.

## References

- `scripts/preflight_host.py:35-69` — proposed_config (the silent coercion)
- `scripts/preflight_host.py:94-106` — compute_warnings (the wrong-direction warning)
- `scripts/lint/framework_build.py:44-52` — the lint default + skip path
- `scripts/setup_discover.py:8-15` — detect_framework (already returns Optional)
- `scripts/setup_discover.py:196-200` — detect_pages_publishable (already returns False for non-mkdocs)
- `templates/config.schema.json:17-21` — the schema enum to extend
- `CLAUDE.md` — "generic-first, convention-optimized" and "degrade gracefully" principles
- claude-code-self-assessment#100 — CCE-57 bootstrap PR (post-merge follow-up to drop mkdocs scaffold)
