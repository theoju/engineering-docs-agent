---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/82
synthesized_into: []
---

# Onboarding a Hybrid-CI Host

A hybrid-CI host runs its primary test suite on one CI provider (e.g., CircleCI) while publishing docs via GitHub Actions. The plugin supports this split through the `publishing.ci_provider` config field introduced in PR #82 (CCE-58).

## When you need this

Use the hybrid-CI path when your host repo's primary CI is **not** GitHub Actions but you still want the docs-publish workflow to run on GitHub Actions. The canonical example is `theoju/advanced-data-import-system`: CircleCI owns the build and test pipeline; GitHub Actions owns the docs-publish step.

If your host uses GitHub Actions end-to-end, leave `ci_provider` unset — the default (`github`) is correct.

## Config field: `publishing.ci_provider`

Add the field to your host's `.engineering-docs-agent/config.yml` under the `publishing` block:

```yaml
publishing:
  ci_provider: circleci   # "github" | "circleci" — default: "github"
```

The field is additive and optional. Omitting it is equivalent to `ci_provider: github`.

## Host config template

A ready-to-use template for hybrid-CI hosts lives at `templates/hosts/`. Copy it into your host repo's `.engineering-docs-agent/` directory and fill in the blanks before running the setup skill.

## Worked example

The runbook at `docs/host-onboarding/advanced-data-import-system.md` walks through every setup step for `theoju/advanced-data-import-system`. Use it as a copy-pasteable reference for any host that follows the same CircleCI-primary / GitHub-Actions-publish split.

## Known limitation: publish-verifier does not yet act on `ci_provider: circleci`

Setting `ci_provider: circleci` is schema-valid, but the publish-verifier subagent currently only acts on the `github` provider path. If your host sets `ci_provider: circleci`, the verifier will skip the post-merge verification step rather than querying CircleCI for the pipeline result.

This is tracked in **CCE-63** (publish-verifier CircleCI provider support), which is currently in Backlog. Until CCE-63 ships, verify CircleCI publish runs manually after each docs-agent PR merges.
