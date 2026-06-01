---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/82
synthesized_into: []
---

# `publishing.ci_provider` — CI topology field

## What it is

`publishing.ci_provider` is an additive string field in the host config's `publishing:` block. It tells the agent which CI system actually triggers the docs-publishing workflow on the host.

```yaml
publishing:
  ci_provider: circleci   # or "github_actions" (default)
  target_branch: main
  workflow: publish-docs
```

When omitted, the field defaults to `github_actions`. You only need to set it explicitly when the host's publishing pipeline runs outside GitHub Actions.

## Why it exists

Some hosts gate user PRs with one CI system (e.g., CircleCI) while running docs publishing in a separate GitHub Actions workflow. The agent's post-merge publish-verifier needs to know which system to poll for a successful build. Without this field, the verifier always assumes GitHub Actions and produces false-negative or false-positive signals on hybrid-CI hosts.

`theoju/advanced-data-import-system` is the first such hybrid host: CircleCI runs the standard test suite on every PR; GitHub Actions publishes docs. The `publishing.ci_provider` field captures that distinction cleanly without restructuring the rest of the config.

## Schema

The field is additive — existing configs that omit it continue to work without change. The config loader in `scripts/state_io.py` treats an absent `ci_provider` as `"github_actions"`.

Accepted values as of PR #82:

| Value | Meaning |
|---|---|
| `github_actions` | Publishing runs via GitHub Actions (default). |
| `circleci` | Publishing runs via CircleCI (schema-complete; verifier support pending — see [CCE-63](#cce-63-status)). |

## CCE-63 status

**The `circleci` value is schema-complete but the verifier logic is not yet implemented.** If you set `ci_provider: circleci`, the schema validates cleanly and the config loads without error. However, the publish-verifier subagent does not yet query the CircleCI API — it will log a `NOT_IMPLEMENTED` warning and skip verification for that run.

CCE-63 (CircleCI publish-verifier support) is the follow-on backlog item that wires the verifier to the CircleCI Pipelines API. Until CCE-63 lands, hosts using `circleci` get no post-merge publish confirmation.

## Host template and onboarding runbook

PR #82 adds two reference artifacts for the `advanced-data-import-system` host:

- `templates/hosts/advanced-data-import-system.config.yml` — a copy-paste-ready config template with `ci_provider: circleci` set.
- `docs/host-onboarding/advanced-data-import-system.md` — a worked-example runbook. It references the generic comprehensive setup guide (`docs/site-src/setup-guide.md`, CCE-56) for steps that apply to all hosts, and calls out the CircleCI-specific steps explicitly.

Use the template as a starting point if you are onboarding another CircleCI host. The runbook shows you where the hybrid-CI topology diverges from the standard GitHub-Actions-only path.
