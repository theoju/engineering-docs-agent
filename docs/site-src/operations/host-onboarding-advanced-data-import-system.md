---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/82
synthesized_into: []
---

# Host Onboarding: advanced-data-import-system

Runbook for onboarding `theoju/advanced-data-import-system` as an engineering-docs-agent host. This is the first external host using a **hybrid CI** setup: the docs-publish workflow runs on CircleCI rather than GitHub Actions. Tracked under CCE-58.

## What's different about this host

Most hosts publish via GitHub Actions. `advanced-data-import-system` uses CircleCI for its publish pipeline. The plugin-side groundwork accounts for this, but one component — the publish-verifier's CircleCI provider — is not yet shipped (CCE-63, currently in Backlog). Until CCE-63 lands, publish verification for this host runs in degraded mode: the verifier skips the pipeline-status check and marks the run `partial: true` with `error: "publish_verifier_provider_unsupported"`.

## Plugin-side changes (PR #82)

PR #82 laid the groundwork. Nothing in it requires changes to the host repo — it ships entirely on the plugin side.

**Config template.** A host-specific config template lives at `templates/hosts/advanced-data-import-system.yml`. Copy it to `.engineering-docs-agent/config.yml` in the host repo and fill in the blanks (Jira project key, docs directory, Slack webhook URL).

**Schema update.** The config JSON schema (`agents/schemas/config-schema.json`) now accepts `ci_provider: circleci` as a valid value under `publishing`. Set this in the host config so the orchestrator routes to the correct publish-verifier branch at runtime.

**Test fixtures.** Fixture coverage for the onboarding flow lives under `tests/fixtures/hosts/advanced-data-import-system/`. The fixtures exercise the hybrid-CI detection path end-to-end in dry-run mode — run `python3 -m pytest tests/ -k advanced_data_import` to verify locally.

**Host onboarding doc.** A `docs/host-onboarding/advanced-data-import-system.md` file was added in this PR. That file lives outside the core lens root and is not agent-editable; this operations page is the canonical runbook within the lens.

## Onboarding steps

Complete these in order. Steps 1–3 are standard and covered in the [setup guide](../setup-guide.md); only the CircleCI-specific steps are detailed here.

1. **Standard plugin install.** Follow Parts 1–2 of the setup guide to register the GitHub App and install it on the host repo.

2. **Copy the config template.**
   ```bash
   cp templates/hosts/advanced-data-import-system.yml \
      /path/to/advanced-data-import-system/.engineering-docs-agent/config.yml
   ```
   Set `ci_provider: circleci` and fill in `publishing.pipeline_slug` with the CircleCI pipeline identifier for the host's docs-publish job.

3. **Set repo secrets.** The host repo needs `CLAUDE_CODE_OAUTH_TOKEN` and `GH_APP_PRIVATE_KEY` as standard. No CircleCI-specific secrets are required on the GitHub side until CCE-63 ships.

4. **Validate the config.**
   ```bash
   python3 scripts/orchestrator_runner.py \
     --repo-root /path/to/advanced-data-import-system \
     --no-pr
   ```
   A clean dry-run confirms schema validation passes and the orchestrator can load the host config.

5. **Acknowledge partial publish verification.** Until CCE-63 ships, nightly run summaries will show `partial: true` for this host when publish verification is attempted. This is expected. The `partial_reasons` field in `state.json` will contain `publish_verifier_provider_unsupported`. Monitor the CircleCI build manually until the integration is complete.

## Pending work

**CCE-63** — publish-verifier CircleCI provider support. This is the remaining blocker for full operational status on this host. Once CCE-63 ships, update the host config to point `publishing.verifier_poll_interval` and `publishing.pipeline_slug` at the live CircleCI job, then remove the `partial` acknowledgment note from this page.

**Architecture page.** The hybrid CI pattern warrants a dedicated architecture doc. That page should be authored once CCE-63 ships and the pattern is fully validated on this host.

## Reference

- Config template: `templates/hosts/advanced-data-import-system.yml`
- Test fixtures: `tests/fixtures/hosts/advanced-data-import-system/`
- Host onboarding doc (outside lens): `docs/host-onboarding/advanced-data-import-system.md`
- Jira: [CCE-58](https://designitright.atlassian.net/browse/CCE-58) (onboarding), [CCE-63](https://designitright.atlassian.net/browse/CCE-63) (CircleCI publish-verifier)
- Prerequisite host setup guide: CCE-56 / [setup-guide.md](../setup-guide.md)
