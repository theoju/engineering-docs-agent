---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/77
synthesized_into: []
---

# Host Onboarding Runbook

Operator reference for adding a new host repo to the engineering-docs-agent pipeline. This page is the practitioner runbook — quick decisions, patterns, and failure modes. For the step-by-step tutorial with every screenshot and command, see [Setup Guide](../setup-guide.md).

## Before you start

Two things must already exist before you touch the host repo:

1. **Claude OAuth token** — run `claude setup-token` once per user account. The token starts with `sk-ant-oat`. Store it; you paste it into each host as `CLAUDE_CODE_OAUTH_TOKEN`.
2. **GitHub App** — register once at https://github.com/settings/apps. Required permissions: Contents (read/write), Pull requests (read/write), Issues (read-only). Download the `.pem` private key and note the Client ID (`Iv1.xxx` or `Iv23li...` format). See [Setup Guide §1.2](../setup-guide.md#12-register-the-github-app-once) for the exact form fields.

If you have done both, skip to [Per-host steps](#per-host-steps).

## Per-host steps

### 1. Install and scaffold

```bash
# from the host repo root
claude plugin marketplace add /path/to/engineering-docs-agent
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace
claude /engineering-docs-agent-setup
```

The setup skill detects the docs framework (MkDocs, Docusaurus, …), docs source directory, and lens structure. It writes:

- `.engineering-docs-agent/config.yml`
- `.engineering-docs-agent/state.json`
- `.github/workflows/docs-agent-nightly.yml`

Commit and push these before continuing.

### 2. Install the GitHub App on this repo

Go to https://github.com/settings/apps → your App → **Install App** → choose **Only select repositories** → select this host repo.

The App installation is what allows the nightly workflow to push `docs-agent/*` branches and have host CI fire on the resulting PRs. Without it, pull requests opened with the default `GITHUB_TOKEN` suppress downstream `pull_request` triggers (documented GitHub loop-prevention; CCE-45 root cause).

### 3. Set secrets and variables

Open the host repo's **Settings → Secrets and variables → Actions**.

**Secrets** (sensitive values, never in logs):

| Secret | Value |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | OAuth token from `claude setup-token` |
| `DOCS_AGENT_APP_PRIVATE_KEY` | Full `.pem` file contents including `-----BEGIN/END-----` lines |
| `JIRA_API_TOKEN` | Atlassian API token (optional; skip if not using Jira enrichment) |
| `SLACK_WEBHOOK_URL` | Incoming webhook URL (optional) |

**Variables** (non-sensitive, visible in logs for easier debugging):

| Variable | Value |
|---|---|
| `DOCS_AGENT_APP_CLIENT_ID` | GitHub App Client ID (`Iv1.xxx` or `Iv23li...`) |
| `JIRA_EMAIL` | Account email for the Jira token (optional) |

Without `JIRA_API_TOKEN` + `JIRA_EMAIL`, Jira enrichment is skipped. The run still opens a PR; `partial_reasons` will include `jira_auth_missing` so the gap is visible.

### 4. Branch protection

Require status checks on `main`. Minimum set:

- Your test workflow's job name (e.g. `pytest (3.11)`, `pytest (3.12)`)
- `actionlint` (if you've added the actionlint workflow — see [Optional: actionlint](#optional-actionlint))

The `strict=true` flag keeps branches up to date before merge. This is enforced via the CLI as:

```bash
gh api -X PATCH \
  repos/<owner>/<repo>/branches/main/protection/required_status_checks \
  --field strict=true \
  --field 'contexts[]=<your-test-job>'
```

### 5. Smoke-test the first run

```bash
gh workflow run docs-agent-nightly.yml -f reason="first-run smoke test"
gh run watch
```

**Success signals:**

- A `docs-agent/<YYYY-MM-DD>T<HH>` branch exists on the remote.
- A pull request is open authored by the GitHub App (e.g. `app/your-docs-agent-bot`), not `github-actions[bot]`.
- CI checks fire on that PR. If no checks fire, the App installation is missing or the token plumbing is wrong (see [Troubleshooting](#troubleshooting)).
- The PR body shows the run summary with an empty `partial_reasons` list (or explains what was skipped).

## Host patterns

### Pure GitHub Actions host

The standard path. The host's test suite, lint, and docs-agent all live in `.github/workflows/`. Branch protection gates on those workflow job names directly.

Reference: `theoju/engineering-docs-agent` (this repo is its own dogfood host).

### Hybrid CI host (CircleCI, Jenkins, Buildkite)

The docs-agent nightly workflow lives in GitHub Actions for cron-trigger simplicity. The host's primary CI remains on its existing provider.

For branch protection:
- Keep the primary CI checks required on user PRs as you normally would.
- Add the `actionlint` GitHub Actions workflow and require it. It runs in ~5s on every PR, so it works as a universal gate even when no workflow files changed (CCE-59: no `paths:` filter on `pull_request` trigger).
- The docs-agent's own nightly workflow does not need to be required on user PRs.

Reference: `theoju/advanced-data-import-system` (CCE-58).

### JavaScript / TypeScript host

The setup skill is framework-agnostic. For JS/TS hosts:

- Docusaurus is the most common detected framework; the skill handles it.
- The Python-specific test workflow scaffolding is skipped when no Python toolchain is detected.
- The docs-agent nightly workflow itself requires no Python in the host — it invokes the Claude CLI directly.

Reference: CCE-57 tracks the next onboarding, which exercises this path.

## Optional: actionlint

Highly recommended. Add `.github/workflows/actionlint.yml`:

```yaml
name: actionlint

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
    paths:
      - ".github/workflows/**"
      - ".github/actionlint.yml"

permissions:
  contents: read

jobs:
  actionlint:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v5
      - name: Download actionlint
        id: get_actionlint
        run: bash <(curl -sL https://raw.githubusercontent.com/rhysd/actionlint/v1.7.7/scripts/download-actionlint.bash) 1.7.7
      - name: Run actionlint
        run: ${{ steps.get_actionlint.outputs.executable }} -color
```

No `paths:` filter on `pull_request` is intentional. If `actionlint` is a required status check and it only runs on workflow-file changes, every other PR blocks at merge with "status check has not run yet" (CCE-59).

## Troubleshooting

### PR opens but no CI fires on it

The workflow is using `GITHUB_TOKEN` to push or create the PR. Default `GITHUB_TOKEN` suppresses `pull_request` and `push` event triggers (GitHub loop-prevention).

**Fix:** the nightly workflow must mint an App installation token in its first step and use it throughout. Check that `docs-agent-nightly.yml` has `actions/create-github-app-token@v3` as the first step and that both the checkout's `token:` input and the orchestrator step's `GH_TOKEN` env reference `${{ steps.app-token.outputs.token }}`. See `.github/workflows/docs-agent-nightly.yml` in this repo for the working pattern.

### workflow_dispatch returns HTTP 422 "Unrecognized named-value"

A `${{ steps.* }}` expression appears at job-env scope. GitHub resolves job-env before any step runs, so `steps.*` is unavailable there.

**Fix:** move the expression to step-env. Standard YAML parse (`yaml.safe_load`) does not catch this; actionlint does. This is the primary reason actionlint is recommended as a pre-merge gate (CCE-52).

### Run opens with `partial_reasons: [jira_auth_missing]`

`JIRA_API_TOKEN` and/or `JIRA_EMAIL` are not set, or the workflow's job-env block doesn't surface them.

**Fix:** set the secret and variable (step 3 above). Confirm the nightly workflow env block includes `JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}` and `JIRA_EMAIL: ${{ vars.JIRA_EMAIL }}`. Note `JIRA_EMAIL` is a repo **Variable**, not a Secret — it's non-sensitive and easier to debug when visible in logs.

### OAuth token assert fails ("OAuth token not configured")

The token pasted into `CLAUDE_CODE_OAUTH_TOKEN` may be the wrong type (`sk-ant-api…` console API key instead of `sk-ant-oat…` OAuth token), truncated, or missing.

**Fix:** the CCE-49 multi-stage assert emits a distinct `::error::` message for each failure mode. Re-run `claude setup-token` and paste the fresh output.

### Branch protection blocks merge with "head not up-to-date"

Expected behavior when `strict=true`. Merge `origin/main` into the PR branch, push, then re-attempt merge.

## Onboarding checklist

Copy this into a tracking issue for each new host.

**One-time (skip if already done):**

- [ ] `claude setup-token` — copy the `sk-ant-oat…` token.
- [ ] Register the GitHub App (Part 1.2 of setup guide).
- [ ] Download the App's private key (`.pem`).
- [ ] Note the App Client ID.

**Per host:**

- [ ] `claude plugin marketplace add …` + `claude plugin install …`
- [ ] `claude /engineering-docs-agent-setup`
- [ ] Commit `.engineering-docs-agent/` + `.github/workflows/docs-agent-nightly.yml` and push.
- [ ] Install the GitHub App on this repo (step 2 above).
- [ ] Set Secret `CLAUDE_CODE_OAUTH_TOKEN`.
- [ ] Set Secret `DOCS_AGENT_APP_PRIVATE_KEY`.
- [ ] Set Variable `DOCS_AGENT_APP_CLIENT_ID`.
- [ ] (Optional) Set Secret `JIRA_API_TOKEN` + Variable `JIRA_EMAIL`.
- [ ] (Optional) Set Secret `SLACK_WEBHOOK_URL` / SMTP creds.
- [ ] Add `.github/workflows/actionlint.yml` (recommended).
- [ ] Configure branch protection: test job + `actionlint` as required checks.
- [ ] `gh workflow run docs-agent-nightly.yml -f reason="first-run smoke test"`.
- [ ] Verify: App-authored PR opens, CI fires on it, `partial_reasons` is empty or expected.
