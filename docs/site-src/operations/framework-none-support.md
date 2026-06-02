---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/84
synthesized_into: []
---

# Framework-None Support

## Overview

`docs.framework: none` is a first-class configuration value for host repositories that have no static site generator (SSG). Before PR #84 (CCE-64), the plugin required an SSG to pass preflight; hosts without one had to scaffold a synthetic `mkdocs.yml` just to clear validation.

That workaround is no longer necessary. Set `framework: none` in your host config and the plugin operates normally — authoring, linting, and gap detection all run without a build pipeline.

## Configuration

Set `framework: none` in `.engineering-docs-agent/config.yml`:

```yaml
docs:
  framework: none
  docs_dir: docs/
  lens_paths:
    core: docs/site-src/
  agent_editable_paths:
    - docs/site-src/**
```

The `framework` key accepts three values: `mkdocs`, `docusaurus`, and `none`. Any other value is a validation error at config load time.

## Validation behaviour

Three files enforce the supported-value constraint:

- **`templates/config.schema.json`** — the JSON schema enum now includes `"none"` alongside `"mkdocs"` and `"docusaurus"`. Config load fails fast if an unknown value appears.
- **`scripts/preflight_host.py`** — the preflight check skips SSG-presence assertions entirely when `framework: none` is set. A missing build config is not an error.
- **`scripts/lint/framework_build.py`** — the framework-build lint rule skips rather than flags when `framework` is `none`. No lint warnings are emitted for missing build artefacts.

## Upgrade path

If you previously scaffolded a synthetic `mkdocs.yml` to pass preflight, remove it:

1. Change `framework: mkdocs` to `framework: none` in `.engineering-docs-agent/config.yml`.
2. Delete the synthetic `mkdocs.yml` and any `mkdocs`-specific CI steps you added purely to satisfy the plugin.
3. Re-run preflight to confirm:

   ```bash
   python3 scripts/preflight_host.py --config .engineering-docs-agent/config.yml
   ```

The plugin's authoring and linting capabilities are unaffected by the switch. Publish verification skips the build-pipeline poll for `framework: none` hosts — it won't wait on a deploy workflow that doesn't exist.

## Scope

This change is purely additive. Hosts using `mkdocs` or `docusaurus` are unaffected; their validation path is unchanged.

For the user-facing onboarding how-to (initial setup on a host with no framework), see `docs/host-onboarding/framework-none.md`.
