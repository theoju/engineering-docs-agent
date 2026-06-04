---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/84
synthesized_into: []
---

# `framework: none` — running the plugin without an SSG

Use `docs.framework: none` when your host repo has no static-site generator. Plain-markdown repos, Next.js apps that render docs in GitHub's web UI, and any repo where scaffolding mkdocs would serve no purpose are all valid targets.

Before PR #84 (CCE-64), `framework` was a closed enum of `["mkdocs", "docusaurus"]`. Host repos without an SSG had to scaffold a synthetic mkdocs site purely to pass schema validation — wasted infrastructure for a repo that never intended to publish a docs site. `framework: none` is now a schema-valid first-class value.

## Config

```yaml
docs:
  framework: none
  lens_paths:
    core: docs/
  agent_editable_paths:
    - docs/**

publishing:
  base_url: null          # null is valid and expected here
  build_workflow: null    # likewise
```

Both `publishing.base_url` and `publishing.build_workflow` accept `null` when `framework` is `none`. The schema (`templates/config.schema.json`) allows this combination; any other framework requires non-null values for both.

## What runs

All authoring and analysis capabilities run normally:

- **pr-summarizer** — summarises merged PRs from your configured sources.
- **page-author** — writes and edits docs pages with voice matching.
- **gap-detector** — flags non-trivial PRs with no corresponding spec or plan.
- **content-validator** — all enabled Tier-1 lint rules run; the What's New entry is produced as usual.
- **notifier** — Slack and email digest is sent.

The nightly docs-update PR is opened on your host repo exactly as it would be for an mkdocs host.

## What skips

Two components skip cleanly when `framework` is `none`:

- **`framework_build` lint rule** — skips with the reason `framework=none; no build validation applicable`. This appears in the run digest as a clean skip, not a failure. The skip is implemented via an explicit `elif framework == "none":` branch in `scripts/lint/framework_build.py`.
- **publish-verifier** — skips when `publishing.base_url` is `null`. No build pipeline to poll, no live URL to verify. The run completes without a publish-verification stage; this is expected and not reported as an error.

## Preflight behaviour

The preflight check (`scripts/preflight_host.py`) previously emitted a **block-severity** `no_docs_framework` warning for any config without a recognised framework. With `framework: none` now valid, the check instead emits an **info-severity** `framework_none` notice. The notice reads as a confirmation that the operator has intentionally opted out of SSG, not as a problem to fix. The run proceeds normally.

## Upgrade path to mkdocs

Add `framework: mkdocs` when you want build-time link checking or a published site at a stable URL.

1. Run `mkdocs new .` in the repo root.
2. Move your docs source into `docs/` if it isn't already there.
3. Edit `.engineering-docs-agent/config.yml`:
   - Set `docs.framework: mkdocs`.
   - Set `publishing.base_url` to your GitHub Pages URL.
   - Set `publishing.build_workflow` to your deploy workflow filename (e.g., `docs-pages.yml`).
4. Add an mkdocs install step to the nightly workflow so the `framework_build` lint rule can invoke `mkdocs build --strict`.
5. Run `claude /engineering-docs-agent-setup` — the setup skill will detect the new framework and scaffold the Pages workflow if it doesn't exist.

## Reference

- Schema: `templates/config.schema.json` — the `docs.framework` enum.
- Skip branch: `scripts/lint/framework_build.py` — the `elif framework == "none":` path.
- Preflight notice: `scripts/preflight_host.py` — `framework_none` info event.
- Design decision: `docs/site-src/archive/2026-05-29-cce64-framework-none-design.md` — Approach 1 of 3, rationale for first-class `none` over pluggable adapters or capability-flags.
