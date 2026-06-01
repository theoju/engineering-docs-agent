---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/84
synthesized_into: []
---

# Configuring `framework: none`

Set `docs.framework: none` in your host config when your repo has no docs build framework. This is a first-class value — the plugin treats it explicitly and degrades cleanly instead of guessing or silently coercing.

## When to use it

Use `framework: none` when your host repo does not run MkDocs, Docusaurus, or any other site-build step. Common cases include internal reference repos, CLI-tool repos without published docs, and repos mid-onboarding that haven't wired up a build yet.

Before PR #84, omitting the `framework` key or setting an unrecognized value caused the plugin to either error during preflight or silently fall back to `mkdocs`. Neither outcome is acceptable for a generic-host-first plugin.

## Config

In `.engineering-docs-agent/config.yml`:

```yaml
docs:
  framework: none
  lens_paths:
    core: docs/
  agent_editable_paths:
    - docs/**
```

The `framework` key accepts `none` alongside `mkdocs` and `docusaurus`. The JSON schema in `templates/config.schema.json` validates this at load time.

## Effect on lint

The `framework_build` Tier-1 lint rule skips when `framework: none` is set. It does not flag a violation and does not suppress the lint run. The lint output includes a clear skip reason so you know the rule was reached and intentionally bypassed, not silently omitted.

All other Tier-1 rules still run — `framework: none` only gates the build-specific check.

## Effect on preflight

`preflight_host.py` writes `framework: none` directly to the config rather than substituting a default. The written value round-trips cleanly through config load: you see exactly what you set, no transformation.

## Tests

Three new test cases cover this path:

- **Lint skip:** asserts `framework_build` produces a skip result (not a pass or fail) when `framework: none`.
- **Schema validation:** asserts `none` is accepted by the JSON schema and unknown values are still rejected.
- **Preflight write:** asserts `preflight_host.py` writes `framework: none` verbatim and does not override it.

Run them with:

```bash
python3 -m pytest tests/ -k "framework_none"
```

## Upgrading an existing host

If your host config currently omits `framework` or sets it to a non-standard value, add `framework: none` explicitly. No other changes are required. The next nightly run will pick up the new value at preflight and the lint skip will take effect immediately.
