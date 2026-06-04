---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/82
synthesized_into: []
---

# `ci_provider` Config Schema Field

The `ci_provider` field identifies which CI system gates user PRs on the host repo. The docs-agent uses it to adapt publish-verification behavior to the host's actual topology.

## Field definition

```yaml
# .engineering-docs-agent/config.yml
ci_provider: github   # "github" | "circleci" — default: "github"
```

`ci_provider` is an additive, optional enum. Omitting it is identical to setting `github`. Existing host configs need no changes.

## Accepted values

| Value | Meaning |
|---|---|
| `github` | GitHub Actions is the primary CI. Branch-protection status checks reference GHA workflow runs. |
| `circleci` | CircleCI is the primary CI for user-PR gating. GitHub Actions is used only for the docs-publish workflow. |

## Why the field exists

Some hosts run a **hybrid topology**: CircleCI for code checks on every PR, GitHub Actions only for the docs publishing workflow triggered after merge. Without `ci_provider`, the plugin's publish-verifier would look for a CircleCI build in the GitHub Actions run list, find nothing, and report a false failure.

The first confirmed hybrid host is `theoju/advanced-data-import-system` (CCE-58). That repo's branch protection requires CircleCI checks to pass before merge; the docs-publish step remains a GitHub Actions workflow.

## Forward compatibility

`ci_provider` is **declarative-only today**. The config loader validates the value and stores it, but no runtime behavior branches on it yet. CCE-63 will make it load-bearing for the publish-verifier's provider selection logic. Setting it now means existing host configs will not require a schema break when CCE-63 lands.

## Config validation

`load_config_validated` (in `scripts/state_io.py`) rejects unknown enum values at load time. If you set `ci_provider: jenkins`, the orchestrator exits with a clear validation error before any subagent is dispatched.

The parametrized test fixture added in PR #82 (`tests/fixtures/host_configs/`) validates every host-onboarding config template through `load_config_validated`. Add your host's config file to that directory and it is automatically covered by the suite.

## Host config template

A copy-pasteable template is at `templates/hosts/hybrid-ci-host.yml`. Start there when onboarding a host with a CircleCI primary pipeline. The template pre-sets `ci_provider: circleci` and includes inline comments for every field that requires host-specific values.

## Related pages

- [Advanced Data Import System onboarding runbook](../operations/advanced-data-import-system-onboarding.md) — step-by-step operator guide for the first hybrid-CI host, including CircleCI branch-protection trade-offs.
- [Setup guide](../setup-guide.md) — general onboarding for all host types; the hybrid-CI subsection links here.
