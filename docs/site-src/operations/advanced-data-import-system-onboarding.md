---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/82
synthesized_into: []
---

# Onboarding `theoju/advanced-data-import-system`

This page is the operator runbook for onboarding `theoju/advanced-data-import-system` as an engineering-docs-agent host. It is the first host using a **hybrid-CI** model: CircleCI runs primary checks; GitHub Actions runs the docs publish step. Use this page alongside the [setup guide](../setup-guide.md) — the setup guide covers the generic install path, this page covers every hybrid-CI-specific decision.

## What "hybrid-CI" means here

The plugin's publish-verification step watches a GitHub Actions workflow by name. In a pure GitHub Actions host, primary CI and docs publish run in the same provider. In a hybrid host, primary CI lives in CircleCI and the publish is a thin GitHub Actions workflow that the docs agent dispatches against and polls.

You set `publishing.ci_provider: circleci` in the host config to tell the plugin which provider owns primary checks. The publish-verifier still targets GitHub Actions. The two values are independent.

## Config field: `publishing.ci_provider`

Add this block to `.engineering-docs-agent/config.yml`:

```yaml
publishing:
  ci_provider: circleci   # "github" (default) | "circleci"
  base_url: https://theoju.github.io/advanced-data-import-system
  build_workflow: docs-publish.yml
```

`ci_provider` is an additive enum field. Omitting it is equivalent to `github`. The plugin schema validates the value; an unknown string causes a load-time error with a descriptive message.

`base_url` and `build_workflow` follow the same nullable semantics as every other host: leave them `null` during initial bootstrap, fill them in once the publish workflow exists. See the setup guide Part 3 for that lifecycle.

A complete config template lives at `templates/hosts/advanced-data-import-system.config.yml`. Copy that file to your host repo as `.engineering-docs-agent/config.yml` and edit the three `# TODO` markers.

## Step-by-step install

### 1. Copy the config template

```bash
cp templates/hosts/advanced-data-import-system.config.yml \
   /path/to/advanced-data-import-system/.engineering-docs-agent/config.yml
```

Fill in `repo_owner`, `repo_name`, and the three `publishing` values before committing.

### 2. Seed `state.json`

Copy `.engineering-docs-agent/state.example.json` to `.engineering-docs-agent/state.json` in the host repo. Set `last_successful_run.head_sha` to the current HEAD commit of the host's default branch:

```bash
git -C /path/to/advanced-data-import-system rev-parse HEAD
# paste that SHA into state.json → last_successful_run.head_sha
```

### 3. Register the GitHub App and secrets

Follow setup guide Part 2 (GitHub App registration) and Part 3 (repo secrets). The required secrets are unchanged for hybrid hosts: `CLAUDE_CODE_OAUTH_TOKEN`, `GH_APP_ID`, `GH_APP_PRIVATE_KEY`, and `DOCS_AGENT_CONFIG_PATH` if your config is not at the default location.

### 4. Add the GitHub Actions publish workflow

Even though primary CI runs in CircleCI, docs publish must run in GitHub Actions. Add a workflow file (e.g., `.github/workflows/docs-publish.yml`) to the host repo. Set its `name:` field to match whatever you put in `publishing.build_workflow`. A minimal example:

```yaml
name: docs-publish
on:
  workflow_dispatch:
    inputs:
      ref:
        required: true
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ inputs.ref }}
      - run: make docs-publish   # or your actual publish command
```

The docs agent dispatches this workflow by name after the docs-PR merges, then polls the run status to confirm publication.

### 5. Configure branch protection

This is the main hybrid-CI trade-off. Your CircleCI checks are not GitHub status checks visible to GitHub's branch protection rules by default — you need a CircleCI-GitHub integration that posts status checks back to the PR. Without that:

- GitHub's "Require status checks to pass before merging" cannot gate on CircleCI results.
- The docs agent's PR will still open and be mergeable (CircleCI doesn't gate it).

Two options:

**Option A — CircleCI GitHub status integration (recommended).** In your CircleCI project settings, enable "GitHub Checks" or configure the `github-notify` orb. CircleCI posts a status check for each job. Add those check names to the branch protection rule for the docs-agent branch pattern (`docs-agent/*`). This is the same safety level as a pure GitHub Actions host.

**Option B — Documentation-only guard.** Merge docs PRs manually after visually confirming CircleCI passed. Simpler to set up, but relies on operator discipline. Label docs PRs with `requires-circleci-review` as a reminder.

The plugin does not enforce which option you pick. Set `publishing.ci_provider: circleci` either way; it controls how the plugin labels CI context in notifications, not what it blocks on.

## Smoke-test criteria

After the install is complete, run the dry-run smoke test:

```bash
python3 scripts/orchestrator_runner.py \
  --repo-root /path/to/advanced-data-import-system \
  --no-pr
```

A passing smoke test produces:
- No `error` or `partial: true` in the stdout summary.
- A `current_run.json` written to `.engineering-docs-agent/current_run.json` with `status: ok`.
- No write attempts outside the configured `agent_editable_paths` glob (the runner logs would show `path_not_agent_editable` if this occurred).

If Jira enrichment is enabled and you see `partial: true` with `error: "jira_auth_missing"`, set `JIRA_EMAIL` and `JIRA_API_TOKEN` in your shell before re-running. That partial state does not block the publish path.

## Fixture and test coverage

A host-onboarding fixture at `tests/fixtures/hosts/advanced-data-import-system/` mirrors the on-disk shape the user commits. A fixture-integrity test validates that the fixture and the config template stay in sync. If you update the config template, run `python3 -m pytest tests/test_host_fixtures.py` to confirm the fixture reflects your changes.

Schema validation tests for the `ci_provider` enum live in `tests/test_config_schema.py`. The valid values are `github` and `circleci`; the test asserts that an unknown value (`"jenkins"`, for example) produces a `ConfigValidationError` at load time.

## Known limitations

The publish-verifier does not yet act on `ci_provider: circleci` beyond labeling. Generalized CircleCI polling (waiting for CircleCI runs rather than only GitHub Actions) is tracked in **CCE-63** (Backlog). Until that lands, the verifier's post-merge check still polls the GitHub Actions `build_workflow`, which is correct for this host because the publish step is GitHub Actions regardless of `ci_provider`.

When CCE-63 ships, a follow-up doc target will update this page and the architecture config-schema page.
