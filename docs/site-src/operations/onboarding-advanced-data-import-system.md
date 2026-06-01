---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/82
synthesized_into: []
---

# Onboarding: advanced-data-import-system (hybrid-CI host)

`theoju/advanced-data-import-system` is the first host repo that uses a **hybrid-CI topology**: user PRs are gated by CircleCI, but docs publishing runs via GitHub Actions. This page is the operator runbook for that onboarding. The generic setup walkthrough lives at [docs/site-src/setup-guide.md](../setup-guide.md); read that first if you haven't already.

## Topology

User-facing CI (test, lint, build) runs on CircleCI. The engineering-docs-agent publishes docs via a separate GitHub Actions workflow. The agent itself never touches CircleCI — it only reads merged PRs and writes to the docs-agent branch through the GitHub API.

The `publishing.ci_provider` config field tells the agent which CI system to poll when verifying that a published docs PR went live. For this host it is set to `github_actions`.

```yaml
publishing:
  ci_provider: github_actions
```

The `circleci` value is schema-valid but the verifier logic for it is not yet implemented (see [CCE-63](#known-gap-cce-63-circleci-publish-verifier)).

## Apply the host config template

A ready-to-copy config template lives at `templates/hosts/advanced-data-import-system.config.yml` in the plugin repo. Copy it into the host repo:

```bash
cp templates/hosts/advanced-data-import-system.config.yml \
   <host-repo-root>/.engineering-docs-agent/config.yml
```

Open the file and fill in every `# REPLACE` placeholder — at minimum:

- `sources.github.repo` — the full `owner/repo` slug.
- `sources.jira.project_keys` — the Jira project key(s) the host uses.
- `docs.docs_dir` — path to the MkDocs source root inside the host repo.
- `publishing.github_pages_url` — the live site URL used by the publish-verifier.

Leave `publishing.ci_provider: github_actions` as-is unless the host's publishing pipeline changes.

## Seed the state file

Copy the state seed template into the host repo:

```bash
cp .engineering-docs-agent/state.example.json \
   <host-repo-root>/.engineering-docs-agent/state.json
```

Set `last_successful_run.head_sha` to the SHA of the commit you want the first nightly run to treat as its baseline. The agent collects all PRs merged _after_ this SHA.

## Validate the config

From the host repo root, run:

```bash
python3 scripts/orchestrator_runner.py --repo-root . --no-pr --validate-only
```

The config loader calls `_validate_lens_paths_are_editable` at boot. Any lens path not covered by an `agent_editable_paths` glob fails fast here — fix the globs before wiring up the nightly workflow.

## Wire up the nightly workflow

Copy `.github/workflows/docs-agent-nightly.yml` from the plugin repo into the host repo's `.github/workflows/`. Add the required secrets to the host repo:

| Secret | Purpose |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Authenticates the `claude` CLI in the nightly runner |
| `GH_DOCS_PR_TOKEN` | GitHub token with PR-write access for opening the docs-agent PR |
| `JIRA_EMAIL` | Jira auth (skip if `sources.jira.enabled: false`) |
| `JIRA_API_TOKEN` | Jira auth (skip if `sources.jira.enabled: false`) |

## Test fixtures

Fixtures for this host live under `tests/fixtures/hosts/advanced-data-import-system/`. The fixture suite validates both the `publishing.ci_provider` schema field and the runbook's expected directory structure. Run them with:

```bash
pytest tests/ -k advanced_data_import_system -v
```

All fixture tests are dry-run; no network calls, no LLM, no cost.

## Known gap: CCE-63 (CircleCI publish-verifier)

The `publishing.ci_provider: circleci` value is accepted by the config schema and will not cause a validation error. However, the publish-verifier has no CircleCI implementation yet — it will skip verification and log a warning rather than checking build status.

If the host's publishing pipeline ever migrates to CircleCI, set `ci_provider: circleci` in the config and track [CCE-63](https://designitright.atlassian.net/browse/CCE-63) for when the verifier gains CircleCI support. Until CCE-63 lands, publish verification is a no-op for `circleci` hosts.
