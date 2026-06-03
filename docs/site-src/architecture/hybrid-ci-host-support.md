---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/82
synthesized_into: []
---

# Hybrid-CI Host Support

A **hybrid-CI host** uses one CI provider for its primary build pipeline and a second provider — GitHub Actions — for the docs-agent publish step. The first host of this class is `theoju/advanced-data-import-system`, which runs CircleCI for all application CI checks and GitHub Actions for docs publishing.

## The `ci_provider` field

The `.engineering-docs-agent/config.yml` schema now accepts an optional `publishing.ci_provider` field:

```yaml
publishing:
  ci_provider: circleci   # "github_actions" (default) | "circleci"
  workflow: docs-publish
```

The field is validated against an enum at config-load time. Omitting it defaults to `github_actions`, so existing hosts require no migration.

## Current status: schema-valid, not yet load-bearing

`ci_provider: circleci` passes schema validation but the publish-verifier does not yet dispatch against CircleCI's API. The verifier's provider-dispatch path still assumes GitHub Actions regardless of the config value.

**CCE-63** (currently in Backlog) makes CircleCI polling load-bearing in the publish-verifier. Until that ticket lands, onboarding a CircleCI host proceeds normally — the docs-agent authors and opens the PR — but post-merge publish verification is skipped for that host.

## Configuring a CircleCI host

Use the host config template added in PR #82. The key differences from a GitHub Actions host:

1. Set `publishing.ci_provider: circleci`.
2. List your CircleCI branch-protection contexts under `publishing.required_contexts`. For `theoju/advanced-data-import-system` these are `backend-lint`, `backend-test`, `frontend-test`, and `gcp-id-guard`.
3. Keep `publishing.workflow` pointing to the GitHub Actions workflow that runs the docs publish step — the hybrid model keeps the docs-publish action on GitHub Actions even when primary CI is elsewhere.

```yaml
publishing:
  ci_provider: circleci
  workflow: docs-publish
  required_contexts:
    - backend-lint
    - backend-test
    - frontend-test
    - gcp-id-guard
```

## Test fixture coverage

The test suite includes a fixture set for this host class under `tests/fixtures/hybrid_ci_host/`. The fixture exercises:

- Schema validation of `ci_provider: circleci` (accepted) and `ci_provider: jenkins` (rejected).
- Config load for the host's `.engineering-docs-agent/config.yml` template.
- The verifier's skip-path when `ci_provider` is not `github_actions` and CCE-63 is not yet resolved.

Run the fixture suite with:

```bash
pytest tests/ -k hybrid_ci
```

## What changes when CCE-63 lands

Once CCE-63 ships, the publish-verifier will poll the CircleCI Pipelines API instead of the GitHub Actions workflow API for hosts with `ci_provider: circleci`. The config schema and fixtures committed in PR #82 are already shaped for that path — no config migration is needed on the host side.
