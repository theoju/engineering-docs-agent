---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/84
synthesized_into: []
---

# Running without an SSG (`framework: none`)

Set `docs.framework: none` in `.engineering-docs-agent/config.yml` when your host repo has no static-site generator. A Next.js app that renders markdown through GitHub's web UI is the canonical example — no `mkdocs.yml`, no `requirements-docs.txt`, no build pipeline.

Before PR #84 the config schema only accepted `"mkdocs"` or `"docusaurus"`. Host repos without an SSG were forced to create dummy SSG scaffolding purely to pass schema validation. `framework: none` is now a first-class, valid value.

## What you set in config

```yaml
docs:
  framework: none
```

Leave `publishing.base_url` and `publishing.build_workflow` unset (or explicitly `null`). The preflight script (`scripts/preflight_host.py`) emits `null` for both fields automatically when `framework=none`.

## What runs

All authoring and validation stages run normally:

- `pr-summarizer`, `page-author`, `gap-detector`, `notifier`
- `content-validator` with all enabled Tier-1 lint rules
- The nightly PR and What's New entry are produced as usual

## What skips

The `framework_build` lint rule (`scripts/lint/framework_build.py`) emits a clean skip — not a failure — with the reason `framework=none; no build validation applicable`. The run digest reports this skip explicitly so it's visible without triggering an alert.

The publish-verifier also skips when `publishing.base_url` is `null`. No post-merge URL check fires.

## When to upgrade

Stay on `framework: none` as long as you're comfortable reading docs in GitHub's markdown viewer and don't need strict build-time link checking.

Upgrade to `framework: mkdocs` when you want:

- Strict cross-reference validation at build time — mkdocs catches broken inter-page links before they land.
- A published docs site at a stable URL (GitHub Pages, Vercel, etc.).

To upgrade:

1. Run `mkdocs new .` in the repo root (or `pip install mkdocs && mkdocs new .`).
2. Move docs into `docs/` if they aren't already.
3. Edit `.engineering-docs-agent/config.yml`: set `framework: mkdocs`, set `publishing.base_url` to your GitHub Pages URL, and set `publishing.build_workflow` to your deploy workflow filename.
4. Add an mkdocs install step to the nightly workflow so the `framework_build` lint rule can run.

## Known gap

The config schema does not yet prevent `{framework: mkdocs, base_url: null}`. An `if/then/else` guard will be added when a second non-mkdocs framework with publish support ships. Until then, setting `framework: mkdocs` with a null `base_url` is your responsibility to avoid.

## Reference

- Schema: `templates/config.schema.json` — the `framework` enum now includes `"none"`.
- Lint rule: `scripts/lint/framework_build.py` — skip path for `framework=none`.
- Preflight: `scripts/preflight_host.py` — null-out logic for `publishing.*` fields.
- Host-onboarding guide: `docs/host-onboarding/framework-none.md`
