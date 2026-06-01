---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/82
synthesized_into: []
---

# `ci_provider` Config Field

The `ci_provider` field declares which CI system a host repo uses as its primary pipeline. It was added in PR #82 (CCE-58) to support hybrid-CI host onboarding — hosts where one CI system runs checks and a different one handles docs publish.

## Values

```yaml
ci_provider: github   # default — GitHub Actions for all pipelines
ci_provider: circleci # CircleCI primary CI, GitHub Actions for docs publish
```

The field is an enum with two accepted values: `github` and `circleci`. The default is `github`, which matches every host onboarded before CCE-58.

## Current behavior

`ci_provider` is **purely declarative** in the current release. The publish-verifier (`scripts/publish_verifier.py`) still polls GitHub Actions unconditionally regardless of this field's value. Setting `ci_provider: circleci` has no runtime effect yet.

CCE-63 (backlog) will wire the field into the publish-verifier to select the correct polling path — GitHub Actions or CircleCI — at runtime.

## Where it lives in config

Add `ci_provider` at the top level of your `.engineering-docs-agent/config.yml`:

```yaml
ci_provider: circleci

site:
  docs_dir: docs/site-src
  # ...
```

The field is optional. Omitting it is equivalent to `ci_provider: github`.

## Schema enforcement

The field is validated by `load_config_validated` (in `scripts/state_io.py`). Passing an unrecognized value raises a `ConfigValidationError` at agent startup — the run will not proceed with an invalid enum.

The parametrized test at `tests/fixtures/host_onboarding/` exercises every fixture against `load_config_validated`. Any new host-onboarding fixture you add under that directory is automatically covered.

## Host template

A copy-pasteable config template for hybrid-CI hosts lives at `templates/hosts/`. Use it as the starting point when onboarding a repo with CircleCI as primary CI.

## Related pages

- [Hybrid-CI host onboarding](../operations/hybrid-ci-host-onboarding.md) — step-by-step guide for hosts with split CI providers.
- Setup guide Part 4 — contains a cross-reference link to the hybrid-CI pattern.
