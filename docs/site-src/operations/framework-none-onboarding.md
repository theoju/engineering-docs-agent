---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/84
synthesized_into: []
---

# Onboarding a host with `framework: none`

Use `framework: none` when the host repo has no documentation framework — no MkDocs config, no Docusaurus tree, nothing for `detect_framework()` to find. This is the correct value for JS/TS repos, raw mono-repos, and any host that wants the agent to produce and manage Markdown files without owning a build pipeline.

## When `framework: none` applies

The setup skill (`/engineering-docs-agent:engineering-docs-agent-setup`) calls `detect_framework()` during preflight. If detection returns nothing, `preflight_host.py` writes `framework: none` into `.engineering-docs-agent/config.yml` automatically. You don't need to set this by hand unless you're editing the config directly.

If you are editing by hand, the valid values are `mkdocs`, `docusaurus`, and `none`. The schema at `templates/config.schema.json` accepts all three.

## What changes at runtime

With `framework: none`, the agent skips the `framework_build` lint rule. The rule produces an explicit skip reason in the lint output rather than a failure — no lint errors fire, and the run is not marked partial because of a missing build step.

Everything else runs normally: PR summarization, page authoring, gap detection, Slack/email digest, and publish verification all proceed. The `framework_build` skip is the only behavioral difference.

## What does not run

The agent will not attempt to invoke `mkdocs build`, `docusaurus build`, or any equivalent. It also will not scaffold a synthetic docs-build wrapper. If you later add a real framework to the host, update `framework:` in the config and re-run setup to register the build step.

## Publish verification

Without a build pipeline, the publish-verification stage (`post_publish_verifier.py`) has nothing to verify server-side. Configure `publishing.verify: false` in the host config to suppress verification warnings:

```yaml
publishing:
  verify: false
```

If your host builds docs through a separate CI workflow that is not framework-managed (e.g., a custom `npm run docs` step), you can still wire verification by setting `publishing.verify_url` to the live URL and `publishing.workflow_name` to the workflow that publishes it. The verifier checks the URL for a `200` after the workflow completes regardless of `framework:`.

## Minimal config example

```yaml
docs:
  framework: none
  lens_paths:
    core: docs/
  agent_editable_paths:
    - docs/**
publishing:
  verify: false
```

This is the smallest valid config for a `framework: none` host. The lens path and editable glob must satisfy the invariant enforced by `_validate_lens_paths_are_editable` in `scripts/state_io.py`: every `lens_paths` entry must be covered by at least one `agent_editable_paths` glob.

## Upgrading from a synthetic mkdocs scaffold

If you previously onboarded using the synthetic-scaffold workaround (adding a bare `mkdocs.yml` just to pass preflight), switch to `framework: none`:

1. Remove or archive the synthetic `mkdocs.yml`.
2. Set `framework: none` in `.engineering-docs-agent/config.yml`.
3. Set `publishing.verify: false` unless you have a real publish workflow to verify against.
4. Run the nightly agent or trigger it manually to confirm the run completes without lint errors.

No doc content migration is needed — the agent reads and writes the same Markdown files regardless of framework.
