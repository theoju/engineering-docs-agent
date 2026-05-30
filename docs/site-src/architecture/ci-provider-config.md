---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/82
synthesized_into: []
---

# CI provider config (`publishing.ci_provider`)

## What the field does

`publishing.ci_provider` tells the plugin which CI system runs the docs-publish workflow on a given host. Valid values are `github` and `circleci`. The default is `github`.

The field lives under the `publishing:` block in `.engineering-docs-agent/config.yml`:

```yaml
publishing:
  build_workflow: docs-deploy.yml
  base_url: https://your-org.github.io/your-repo/
  ci_provider: github          # or circleci; default is github
  verify_timeout_seconds: 60
```

## Why it exists

Not every host runs a single CI system. A common hybrid pattern: CircleCI gates user PRs; a GitHub Actions workflow deploys the docs site. The `ci_provider` field captures which system publishes the docs so the publish-verifier can poll the right provider.

Without this field, the verifier would have to detect the CI system at runtime or assume GitHub Actions on every host. Declarative config is cheaper and easier to reason about.

## Current status: declarative only

As of PR #82 (CCE-58), `ci_provider` is parsed and stored but not yet load-bearing. The publish-verifier (`scripts/verify_runner.py`) polls GitHub Actions unconditionally today. CCE-63 wires `ci_provider` into `verify_runner.py` to add a CircleCI polling branch. Until then, setting `ci_provider: circleci` has no effect on runtime behavior.

Set the field to its correct value now so your config is accurate when CCE-63 ships.

## Hybrid-CI hosts

A hybrid-CI host uses one CI provider for code checks and another for docs publishing. The canonical example is `theoju/advanced-data-import-system`:

- CircleCI runs backend-lint, backend-test, frontend-test, and gcp-id-guard on every PR.
- A GitHub Actions workflow (`docs-deploy.yml`) publishes the docs site on merges to `main`.

For this host, `ci_provider` is `github` even though CircleCI is the primary CI. The field describes only the docs-publish provider, not the code-check provider.

## Branch-protection implications for hybrid-CI hosts

Docs-agent PRs go through the same branch-protection rules as any other PR. On a hybrid-CI host where CircleCI contexts are required checks, every docs-agent PR triggers CircleCI runs. Docs-only changes don't break backend tests, so the contexts pass — you just pay the CI minutes.

If CI cost is a constraint, you can scope the CircleCI required checks to exclude heads matching `docs-agent/*`. See the `advanced-data-import-system` onboarding runbook (`docs/host-onboarding/advanced-data-import-system.md`) for the concrete trade-off analysis and `gh` commands.

## Config contract

`ci_provider` is additive. Hosts that don't set it get `github` behavior, which is the only behavior wired today. The field does not affect any other config keys — `build_workflow`, `base_url`, and `verify_timeout_seconds` remain independent.

The `load_config_validated` function in `scripts/state_io.py` validates `ci_provider` against the `['github', 'circleci']` enum. Supplying an unknown value causes a validation error at load time, not at runtime.
