---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/66
  - https://github.com/theoju/engineering-docs-agent/pull/91
synthesized_into: []
---

# Nightly docs-agent CI

The nightly authoring pipeline runs automatically at 07:07 UTC via `.github/workflows/docs-agent-nightly.yml`. It computes the change window against `state.json`, dispatches the subagent pipeline, and opens or appends a commit to a `docs-agent/YYYY-MM-DD` branch. A partial run still opens the PR with `partial: true` in the body — no run goes silent.

## GitHub App token — why it matters

The default `GITHUB_TOKEN` GitHub injects into every workflow run is subject to a loop-prevention rule: any commit or PR it authors suppresses both `pull_request` and `push` event triggers. That means every PR the docs-agent opens would sit inert — your pytest and diagram-gate workflows never fire, and you'd need a manual empty-commit push to wake them up.

The workflow mints a GitHub App installation token instead (`actions/create-github-app-token@v3`, step id `app-token`). App-installation tokens are exempt from the suppression rule, so CI fires normally on docs-agent PRs.

The action uses the `client-id` input (not the deprecated `app-id`). If your workflow still references `app-id`, replace it with `client-id` — the upstream action dropped the old input in v3.

**Repository Variables** — non-sensitive values; set via `gh variable set` or the Settings → Variables tab:

| Name                       | Purpose                                                                                                   |
| -------------------------- | --------------------------------------------------------------------------------------------------------- |
| `DOCS_AGENT_APP_CLIENT_ID` | OAuth Client ID for `docs-agent-bot` (e.g. `Iv1.xxx` or `Iv23li...` depending on App age).               |
| `JIRA_EMAIL`               | Atlassian account email used as the basic-auth username for Jira API calls. Not a credential — it appears in Jira comments and git commit author lines. |

**Repository Secrets** — sensitive values; set via `gh secret set` or the Settings → Secrets tab:

| Name                         | Purpose                                    |
| ---------------------------- | ------------------------------------------ |
| `DOCS_AGENT_APP_PRIVATE_KEY` | PEM private key for the `docs-agent-bot` App. |
| `JIRA_API_TOKEN`             | Atlassian Cloud API token (not your password). Generate at `https://id.atlassian.com/manage-profile/security/api-tokens`. |
| `CLAUDE_CODE_OAUTH_TOKEN`    | OAuth token that authenticates the orchestrator's Claude CLI calls. |

The App is installed on this repo only and carries `contents:write` and `pull-requests:write` scopes, matching the workflow's `permissions:` block.

## Token scope: step-level `env:`, not job-level

The `GH_TOKEN` variable that hands the App token to the `gh` CLI **must** live at step-level `env:`, not job-level `env:`. GitHub's runtime validator rejects `steps.*` context expressions at job scope because the job-level environment is resolved before any step runs — the `app-token` step hasn't executed yet, so `steps.app-token.outputs.token` has no value to reference.

The correct placement is on the "Run nightly authoring" step:

```yaml
# .github/workflows/docs-agent-nightly.yml
- name: Run nightly authoring
  env:
    GH_TOKEN: ${{ steps.app-token.outputs.token }} # step-level: valid
  run: python3 scripts/orchestrator_runner.py --repo-root "$GITHUB_WORKSPACE"
```

Moving this reference to job-level `env:` (a common refactor instinct) causes the workflow to fail at validation time with a confusing `steps.*` context error. Keep it at step level.

The `actions/checkout` step also consumes the token — via `with.token: ${{ steps.app-token.outputs.token }}` — so `git push` from the runner uses the App credential. Both usages are valid at step scope because the `app-token` step runs before them.

## Triggering manually

```bash
gh workflow run docs-agent-nightly.yml -f reason="<your reason>"
gh run watch
```

The `reason` field is free text; it surfaces in the run summary alongside the post-run `state.json` snapshot. The `CLAUDE_CODE_OAUTH_TOKEN` secret must be present and well-formed (`sk-ant-oat…` prefix, >100 chars) — the workflow validates this before dispatching the pipeline.

## Concurrency

One authoring run at a time. The `concurrency.group: docs-agent-nightly` block queues additional triggers rather than cancelling them (`cancel-in-progress: false`). Two parallel runs racing on the same `docs-agent/YYYY-MM-DD` branch would produce conflicting commits.

## CI regression guard

A dedicated test (`tests/test_workflow_inputs.py`) parses `.github/workflows/docs-agent-nightly.yml` and asserts that `actions/create-github-app-token` uses `client-id`, not `app-id`, and that `JIRA_EMAIL` is wired as a Variable (`vars.JIRA_EMAIL`) rather than a Secret. The test fails fast on any accidental revert and is part of the default `pytest` suite — no special marker needed.

## Preflight variable check

`scripts/preflight_host.py` now includes a **Variables checklist** section in its onboarding report alongside the existing Secrets checklist. When you run preflight against a new host, it verifies that `DOCS_AGENT_APP_CLIENT_ID` and `JIRA_EMAIL` are set as Variables (not Secrets) and flags any that are missing or mis-tiered. Run it with:

```bash
python3 scripts/preflight_host.py --repo <owner/repo>
```

The report lists each expected Variable with a `✓` or `✗` and prints remediation commands for any gaps.

## Forensic artifacts

Every run — success or failure — uploads subagent prompt/stdout/stderr to a `docs-agent-subagent-forensics-<run_id>` artifact (14-day retention). Enable the capture path by ensuring `DOCS_AGENT_DEBUG_DIR` points to a writable directory; the workflow sets it to `${{ runner.temp }}/docs-agent-debug`. Use `gh run download <run-id>` to pull the artifact locally when debugging a dispatch failure.
