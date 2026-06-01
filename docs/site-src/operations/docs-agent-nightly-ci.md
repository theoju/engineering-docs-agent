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

The token-minting step uses the `client-id:` input (not the deprecated `app-id:` input, which `actions/create-github-app-token@v3` removed). GitHub App client IDs use either the `Iv1.` prefix (pre-2024 Apps) or the longer `Iv23li…` prefix (newer Apps); both are accepted by the action.

```yaml
# .github/workflows/docs-agent-nightly.yml
- uses: actions/create-github-app-token@v3
  id: app-token
  with:
    client-id: ${{ vars.DOCS_AGENT_APP_CLIENT_ID }}   # not app-id — that input is removed
    private-key: ${{ secrets.DOCS_AGENT_APP_PRIVATE_KEY }}
```

The credentials for the nightly workflow are split across Variables and Secrets by sensitivity:

| Name                         | Tier     | Purpose                                                                                                                                                    |
| ---------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DOCS_AGENT_APP_CLIENT_ID`   | Variable | OAuth Client ID for `docs-agent-bot` (`Iv1.xxx` or `Iv23li…` prefix). Non-sensitive — set via `gh variable set` or the Variables tab.                     |
| `JIRA_EMAIL`                 | Variable | Atlassian account email used for Jira basic-auth. Non-sensitive — visible in every Jira comment and git commit author line; set via `gh variable set`.     |
| `DOCS_AGENT_APP_PRIVATE_KEY` | Secret   | PEM private key for the same App. Sensitive — set via `gh secret set` or the Secrets tab.                                                                  |
| `JIRA_API_TOKEN`             | Secret   | Atlassian Cloud API token (not a password). Sensitive — set via `gh secret set`.                                                                           |

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

## Drift prevention

A CI guard test (`tests/test_workflow_inputs.py`) asserts that every `actions/create-github-app-token` usage in `.github/workflows/*.yml` and `templates/workflow-*.yml` uses `client-id:` — not `app-id:`. If you add a new workflow that mints an App token, the test will fail until you use the current input name. Run it locally with `pytest tests/test_workflow_inputs.py` before pushing.

The preflight helper (`scripts/preflight.py`) also validates your Variables configuration at setup time. Its report now includes a **Variables** checklist section driven by `variables_from_workflow`, which reads the workflow file and surfaces any `vars.*` references that are missing from your repo. Running the preflight before the first nightly is the fastest way to catch a missing `DOCS_AGENT_APP_CLIENT_ID` or `JIRA_EMAIL` variable.

## Forensic artifacts

Every run — success or failure — uploads subagent prompt/stdout/stderr to a `docs-agent-subagent-forensics-<run_id>` artifact (14-day retention). Enable the capture path by ensuring `DOCS_AGENT_DEBUG_DIR` points to a writable directory; the workflow sets it to `${{ runner.temp }}/docs-agent-debug`. Use `gh run download <run-id>` to pull the artifact locally when debugging a dispatch failure.
