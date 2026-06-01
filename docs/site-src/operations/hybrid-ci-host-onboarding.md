---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/82
synthesized_into: []
---

# Hybrid-CI Host Onboarding

This page covers onboarding a host repo that uses two different CI systems: one for its primary checks (tests, build, lint) and a separate GitHub Actions workflow for docs publish. This split is the **hybrid-CI pattern**.

The first exercised host is `theoju/advanced-data-import-system` — a Python+TypeScript monorepo where CircleCI runs primary checks and GitHub Actions handles the docs publish step. Use that repo's [worked-example runbook](../../host-onboarding/advanced-data-import-system.md) alongside this page.

> **Limitation (current):** The `ci_provider` field introduced in PR #82 (CCE-58) is purely declarative. The publish-verifier still hard-codes GitHub Actions polling regardless of what `ci_provider` is set to. CCE-63 will make the field load-bearing and add the CircleCI polling path. When CCE-63 lands, update this page to reflect the new behavior.

## When to use this page

Use the hybrid-CI path if your host repo satisfies both conditions:

1. Primary CI (tests, lint, build) runs on a non-GitHub-Actions provider (e.g. CircleCI, Travis CI, Buildkite).
2. The docs publish step runs on GitHub Actions (via a `deploy.yml` or equivalent workflow that the plugin's publish-verifier polls).

If both CI stages are on GitHub Actions, follow the standard [setup guide](../setup-guide.md) — no hybrid-CI configuration needed.

## The `ci_provider` config field

Add `ci_provider` to your `.engineering-docs-agent/config.yml` under the top-level `site:` block:

```yaml
site:
  ci_provider: circleci   # "github" (default) | "circleci"
  # ... rest of your site block
```

**Default is `github`.** Omitting the field is equivalent to setting `ci_provider: github`.

The field currently accepts two values:

| Value | Meaning |
|-------|---------|
| `github` | Primary CI is GitHub Actions. Standard behavior. |
| `circleci` | Primary CI is CircleCI. Docs publish still goes through GitHub Actions (see Limitation above). |

The config loader validates this field at boot. An unrecognized value fails with a descriptive error from `load_config_validated`.

## Onboarding steps

Follow the standard [setup guide](../setup-guide.md) Parts 1–3, then apply the hybrid-CI additions below.

### 1. Start from the host config template

Copy the ready-made template from `templates/hosts/` in the plugin repo:

```bash
cp /path/to/engineering-docs-agent/templates/hosts/hybrid-ci-host.yml \
   .engineering-docs-agent/config.yml
```

The template includes `ci_provider: circleci` and a comment block explaining each field. Fill in your repo-specific values (docs framework, lens paths, Jira project key, Slack webhook, etc.).

### 2. Set `ci_provider`

In your copied `.engineering-docs-agent/config.yml`, confirm `ci_provider: circleci` is present under `site:`. The setup skill does not auto-detect CI provider — you must set this manually.

### 3. Keep the GitHub Actions docs-publish workflow

The publish-verifier polls the GitHub Actions workflow regardless of `ci_provider`. Your host repo must still have a docs-publish workflow on GitHub Actions (e.g. `.github/workflows/deploy.yml`). Set its name in your config under `site.publish_workflow`.

Your CircleCI config can continue to own tests, build, and any other checks. Only the docs-publish step needs to be on GitHub Actions for the verifier to function.

### 4. Run the fixture validator

The plugin ships a parametrized test that validates every file under `tests/fixtures/host_onboarding/` against the production `load_config_validated` contract:

```bash
python3 -m pytest tests/test_host_onboarding_fixtures.py -v
```

Add your host's config as a fixture under `tests/fixtures/host_onboarding/<your-host>.yml` and run the validator before submitting the onboarding PR. A failed assertion here means your config would be rejected at plugin boot.

### 5. Validate the first run

After secrets are in place and your onboarding PR merges, trigger the nightly workflow manually:

```bash
gh workflow run docs-agent-nightly.yml -f reason="initial hybrid-CI validation"
gh run watch
```

The run should complete without a `ci_provider`-related error. The publish-verifier will poll your GitHub Actions docs-publish workflow as normal.

## Worked example

`docs/host-onboarding/advanced-data-import-system.md` walks through the full onboarding for the first hybrid-CI host end-to-end: config diff, CircleCI pipeline structure, GitHub Actions deploy workflow wiring, and the validation steps actually run. Read it before filing your own onboarding PR.

## What changes in CCE-63

CCE-63 (backlog) will wire `ci_provider` into the publish-verifier so that:

- `ci_provider: circleci` causes the verifier to poll CircleCI's API for primary-check status before declaring the run successful.
- `ci_provider: github` continues the current GitHub Actions polling path.

When CCE-63 lands, update this page: remove the "Limitation" callout, document the CircleCI API polling behavior, and update step 3 to note that a GitHub Actions docs-publish workflow is no longer required for CircleCI hosts.
