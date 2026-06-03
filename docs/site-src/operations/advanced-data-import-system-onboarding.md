---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/82
synthesized_into: []
---

# Onboarding: theoju/advanced-data-import-system

`theoju/advanced-data-import-system` is the first **hybrid-CI host** registered with the engineering-docs-agent plugin. It uses CircleCI as its primary CI provider and GitHub Actions exclusively for the docs-publish step. This page describes what the plugin prepared, what you need to configure on the host side, and one known gap to be aware of before you enable publish-verification.

## What "hybrid-CI" means here

Most host repos run all CI on GitHub Actions: branch-protection checks come from Actions workflows, and the publish-verifier polls the same provider. `advanced-data-import-system` is different — its branch-protection required-status checks come from CircleCI jobs. The docs-publish step still runs on GitHub Actions (a `deploy.yml` workflow), so the nightly authoring run and PR-open path work without changes, but the publish-verifier needs to know which provider to poll for gate status.

The `publishing.ci_provider` field in the host config communicates this split. Set it to `circleci` for this host.

## Plugin-side preparation (PR #82)

PR #82 landed the following before the host was registered:

- **Host config template** — a `.engineering-docs-agent/config.yml` template pre-populated with the four CircleCI branch-protection contexts this repo uses: `backend-lint`, `backend-test`, `frontend-test`, and `gcp-id-guard`. Copy it as a starting point and adjust the `repo`, `jira`, and `publishing` blocks to match your environment.
- **Schema extension** — the `publishing.ci_provider` enum in the shared JSON schema now accepts `github_actions` (default) and `circleci`. Any other value fails schema validation at config load.
- **Test fixtures** — a fixture set under `tests/fixtures/hosts/advanced-data-import-system/` exercises config loading, schema validation, and the presence of the required CircleCI context names. Run `pytest tests/ -k advanced_data_import` to confirm the fixtures pass against the current codebase.

## Configuring the host repo

Complete these steps in the `theoju/advanced-data-import-system` repository:

1. **Copy the config template.** Place `.engineering-docs-agent/config.yml` at the repo root. The template is in `docs/site-src/operations/` of the plugin repo (alongside this page).
2. **Set `publishing.ci_provider: circleci`.** This tells the publish-verifier which provider to poll once CCE-63 is implemented (see the gap note below).
3. **Add the required secrets.** The nightly workflow needs `CLAUDE_CODE_OAUTH_TOKEN`. If Jira enrichment is enabled, also set `JIRA_EMAIL` and `JIRA_API_TOKEN`. See the [setup guide](../setup-guide.md) for the full list.
4. **Register branch-protection contexts.** Confirm that your CircleCI project reports these four context names exactly as shown — the publish-verifier will match against them literally once CCE-63 is load-bearing:
   - `backend-lint`
   - `backend-test`
   - `frontend-test`
   - `gcp-id-guard`
5. **Run the setup skill.** From the host repo root: `claude /engineering-docs-agent-setup`. The skill runs `setup_discover.py` detection and writes the initial `state.json`.
6. **Validate the config.** The plugin loads and schema-validates the config at boot. Check for errors by running the orchestrator in dry-run mode: `python3 scripts/orchestrator_runner.py --repo-root . --no-pr`.

## Known gap: publish-verifier does not yet poll CircleCI (CCE-63)

`ci_provider: circleci` is schema-valid today but **not yet load-bearing** in the publish-verifier dispatch path. The verifier still defaults to polling GitHub Actions. CCE-63 (tracked in the `Claude-Code-Extensions` Jira project at `https://designitright.atlassian.net`) covers the CircleCI polling logic.

Until CCE-63 is merged, publish-verification for this host will report a no-op result rather than a real green/red gate. The nightly authoring run and PR-open path are unaffected — the gap is limited to the post-merge verification stage.

Watch CCE-63 for status. When it lands, no host-side config change is needed; the `ci_provider` field you set in step 2 above is all the verifier needs to route correctly.

## Relationship to CCE-56

CCE-56 produced the comprehensive setup guide at [docs/site-src/setup-guide.md](../setup-guide.md). The steps in that guide apply to this host without modification. This page is the host-specific supplement — it captures the hybrid-CI context, the CircleCI branch-protection context names, and the CCE-63 gap that the generic guide does not cover.
