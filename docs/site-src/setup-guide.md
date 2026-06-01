# Setup Guide

End-to-end walkthrough: from zero to a working `engineering-docs-agent` nightly docs-PR pipeline on a new host repo.

This guide replaces the older minimal setup notes. If you're returning after the rewrite, the structure now splits global (per-user, one-time) setup from per-host (per-repo) setup, and the troubleshooting section covers every partial-mode failure shipped through CCE-45/49/52/53.

## Quick map

| Section       | What you do                              | Where                                 |
| ------------- | ---------------------------------------- | ------------------------------------- |
| Prerequisites | Sanity-check your environment            | Local                                 |
| Part 1        | One-time setup, reused across every host | Claude CLI + GitHub UI + Atlassian UI |
| Part 2        | Per-host onboarding                      | Host repo + GitHub UI                 |
| Part 3        | Validate the first run                   | GitHub Actions                        |
| Part 4        | Per-language host notes                  | Reference                             |
| Part 5        | Optional add-ons                         | Host repo                             |
| Part 6        | Troubleshooting                          | Reference                             |
| Part 7        | Setup checklist                          | Copy-paste                            |

## Prerequisites

- **Claude Code CLI** installed and authenticated. Run `claude --version` to confirm.
- A **GitHub host repo** where you want auto-generated docs.
- **Admin access** to the host repo (you'll set repo secrets, install a GitHub App, and configure branch protection).
- The host repo has (or will have) a **docs site** — `mkdocs`, `Docusaurus`, or another supported framework. The setup skill auto-detects.

## Part 1 — One-time setup (per Claude Code user)

You do these steps once. They apply across every host repo you onboard.

### 1.1 Get a Claude OAuth token

The Claude CLI reads an OAuth token (slot distinct from console API keys). Generate one:

```bash
claude setup-token
```

The output starts with `sk-ant-oat`. Copy it — you'll paste it into each host repo's secrets in Part 2.

> **Why OAuth and not an API key?** The Claude CLI reads the OAuth slot. Console API keys (`sk-ant-api…`) do not authenticate the CLI. The CCE-49 assert in `release.yml` and `docs-agent-nightly.yml` catches this paste-error with a distinct error message if you ever mix them up.

### 1.2 Register the GitHub App (once)

This GitHub App (commonly named `docs-agent-bot` or similar) is what mints installation tokens that allow the nightly workflow to push docs-agent branches AND have host-repo CI fire on them. The default `GITHUB_TOKEN` suppresses both `pull_request` and `push` event triggers on commits it makes — App installation tokens are exempt. See CCE-45 for the full root-cause analysis.

You register the App once. You then install it on each host repo individually (Part 2.3).

1. Open https://github.com/settings/apps and click **New GitHub App**.
2. **GitHub App name**: pick something memorable, e.g. `<your-username>-docs-agent-bot`. The name has to be globally unique.
3. **Homepage URL**: any URL you control, e.g. your GitHub profile.
4. **Webhook**: uncheck **Active** (no webhooks needed; the workflow polls via cron).
5. **Repository permissions**:
   - **Contents**: Read and write (for `git push` of docs-agent branches)
   - **Pull requests**: Read and write (for `gh pr create` + append-commits)
   - **Issues**: Read-only (for gap-detector reading linked issues)
6. **Organization permissions**: none.
7. **Account permissions**: none.
8. **Where can this App be installed?**: Only on this account.
9. Click **Create GitHub App**.
10. On the App's General page, scroll to **Private keys** → click **Generate a private key**. A `.pem` file downloads. Keep it safe.
11. Note the **Client ID** at the top of the General page. You'll need it as the `DOCS_AGENT_APP_CLIENT_ID` repo Variable in each host. The format depends on when the App was registered: pre-2024 Apps use `Iv1.xxxxxxxxxxxxxxxx` (16 hex chars after a period); newer Apps use `Iv23li...` (~20 chars, no period). Either is valid — paste the value verbatim. The numeric App ID is no longer used — `actions/create-github-app-token@v3` authenticates via the Client ID.

### 1.3 (Optional) Atlassian API token

Skip if you don't use Jira. If you do, the source-collector subagent enriches PRs with linked Jira issue summaries.

1. Open https://id.atlassian.com/manage-profile/security/api-tokens
2. Click **Create API token** and name it `engineering-docs-agent`.
3. Copy the token. You'll paste it into each host as the `JIRA_API_TOKEN` Secret. Your account email goes in the `JIRA_EMAIL` repo Variable (Variable, not Secret — emails are not sensitive and Variables show up plainly in logs for debugging).

## Part 2 — Per-host setup

Do these steps once per host repo you want auto-doc generation on.

### 2.1 Install the plugin

In the host repo's working directory:

```bash
claude plugin marketplace add /path/to/engineering-docs-agent
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace
```

If installing from a remote marketplace URL, substitute the URL for the path.

### 2.2 Run the setup skill

From the host repo's working directory:

```
claude /engineering-docs-agent-setup
```

The skill auto-detects:

- Docs framework (`mkdocs`, `Docusaurus`, …)
- Docs source directory (`docs/`, `docs/site-src/`, …)
- Lens information architecture
- Jira opt-in / config

It then asks you a small number of questions (notifications, voice preferences, gap-detection allowlist, Tier-2 lint opt-ins).

Outputs (committed to the host repo):

- `.engineering-docs-agent/config.yml` — host config (framework, paths, Jira project keys, voice samples, publishing target)
- `.engineering-docs-agent/state.json` — durable state, source of truth for the next nightly's window
- `.engineering-docs-agent/state.example.json` — seed template (in case someone clones the repo and needs to bootstrap)
- `.github/workflows/docs-agent-nightly.yml` — the cron workflow

Commit and push. The workflows will appear on GitHub but won't run successfully yet because secrets aren't set.

### 2.3 Install the GitHub App on this repo

This is the per-repo install of the App you registered in Part 1.2.

1. Open https://github.com/settings/apps and click your App.
2. Left sidebar → **Install App** (not **Installations**).
3. Click the green **Install** button next to your account (e.g. `theoju`).
4. Choose **Only select repositories**, type the host repo's name, select it.
5. Click **Install**.
6. Verify: https://github.com/<owner>/<repo>/settings/installations should show your App.

You don't need to copy the installation ID — `actions/create-github-app-token@v3` derives it at runtime from the App Client ID, private key, and repo name.

### 2.4 Configure repo secrets and variables

Open the host repo's **Settings → Secrets and variables → Actions**. You'll add some entries on the **Secrets** tab and others on the **Variables** tab — sensitive values (tokens, private keys) go in Secrets; non-sensitive identifiers (Client IDs, emails) go in Variables so they're visible in workflow logs for easier debugging.

**Secrets** (Settings → Secrets and variables → Actions → **Secrets** tab → New repository secret):

| Secret                                      | What it is                                                                                                              | Where to get it      | Required?                   |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | -------------------- | --------------------------- |
| `CLAUDE_CODE_OAUTH_TOKEN`                   | The Claude CLI OAuth token (starts with `sk-ant-oat`)                                                                   | Part 1.1             | **Yes**                     |
| `DOCS_AGENT_APP_PRIVATE_KEY`                | The contents of the `.pem` file downloaded in Part 1.2 step 10 (entire file, including the `-----BEGIN/END-----` lines) | Part 1.2 step 10     | **Yes**                     |
| `JIRA_API_TOKEN`                            | Atlassian Cloud API token                                                                                               | Part 1.3             | Only if Jira enrichment     |
| `SLACK_WEBHOOK_URL`                         | Slack incoming-webhook URL                                                                                              | Your Slack workspace | Only if Slack notifications |
| `SMTP_SERVER`, `SMTP_USER`, `SMTP_PASSWORD` | SMTP creds                                                                                                              | Your email provider  | Only if email notifications |

**Variables** (Settings → Secrets and variables → Actions → **Variables** tab → New repository variable):

| Variable                   | What it is                                                       | Where to get it        | Required?               |
| -------------------------- | ---------------------------------------------------------------- | ---------------------- | ----------------------- |
| `DOCS_AGENT_APP_CLIENT_ID` | The GitHub App's OAuth Client ID (e.g. `Iv1.xxx` or `Iv23li...`) | Part 1.2 step 11       | **Yes**                 |
| `JIRA_EMAIL`               | The email associated with the Jira token                         | Your Atlassian account | Only if Jira enrichment |

Without `JIRA_API_TOKEN` + `JIRA_EMAIL`, the source-collector skips Jira enrichment cleanly and the run is marked partial with `source_collector_error: jira_auth_missing`. The PR still opens — partial-mode is the operational-visibility surface, not a hard failure.

### 2.5 Branch protection (recommended)

Branch protection is per-host, not per-plugin. The recommended baseline matches what `theoju/engineering-docs-agent` uses on its own `main` branch.

**Required status checks (UI):**

1. Open https://github.com/<owner>/<repo>/settings/branches
2. **Add branch protection rule** → branch name pattern `main`
3. ☑ **Require status checks to pass before merging**
4. ☑ **Require branches to be up to date before merging**
5. Add these checks (start typing the name in the search box):
   - Whatever name your test workflow's job uses (e.g. `pytest (3.11)`, `pytest (3.12)`)
   - `actionlint` (if you're using the actionlint workflow — see Part 5)
6. Click **Create**.

**Required status checks (CLI):**

```bash
gh api -X PATCH \
  repos/<owner>/<repo>/branches/main/protection/required_status_checks \
  --field strict=true \
  --field 'contexts[]=pytest (3.11)' \
  --field 'contexts[]=pytest (3.12)' \
  --field 'contexts[]=actionlint'
```

Note: this is `PATCH`, not `PUT`. The endpoint replaces the contexts list — include every existing required check in the call or you'll lose them.

## Part 3 — Validate

### 3.1 First nightly fire (manual dispatch)

```bash
gh workflow run docs-agent-nightly.yml -f reason="first-run smoke test"
gh run watch
```

The workflow run takes 5–15 minutes depending on PR/Jira window size.

### 3.2 What success looks like

After the workflow completes:

1. A new branch `docs-agent/<YYYY-MM-DD>T<HH>` exists on the remote.
2. A pull request is open against `main`, authored by your App (e.g. `app/your-docs-agent-bot`).
3. CI checks fire on the PR (this is the CCE-45 fix paying off — App-token PRs trigger downstream workflows; default `GITHUB_TOKEN` PRs do not).
4. If `partial_reasons` is empty, the PR body shows the run summary. If non-empty, the PR body starts with a `WARNING — Partial run` block listing why.

### 3.3 First production nightly

The cron is configured in `.github/workflows/docs-agent-nightly.yml` (default `7 7 * * *` UTC — see CCE-39). The next fire after that timestamp will produce a docs-agent PR automatically.

If a PR for the same date already exists, the runner append-commits to it (per CCE-43).

## Part 4 — Per-language host notes

### Python hosts (the well-trodden path)

The dogfood host (`theoju/engineering-docs-agent`) is Python. Most invariants are validated here:

- On this dogfood host: test runner is pytest, with workflows that gate on `pytest (3.11)` + `pytest (3.12)`. The setup skill does not mandate pytest — other hosts may use different runners.
- The orchestrator prefers stdlib where feasible. PyYAML is the one external runtime dep.
- Voice samples load from `voice.sample_paths` in config, with `CLAUDE.md` appended when present (per `scripts/state_io.py`).

### JavaScript / TypeScript hosts

The plugin is generic-first per CLAUDE.md. Behavior is driven by detection + config, not hardcoded paths.

Open considerations for JS/TS hosts (tracked in CCE-57):

- The setup skill should detect Node/Bun/Deno toolchains and skip the Python-specific test workflow scaffolding.
- The docs framework detection covers `mkdocs` and `Docusaurus`; pure JS/TS hosts more commonly use Docusaurus.

### Hybrid CI (CircleCI, Jenkins, Buildkite, …)

The docs-agent nightly workflow lives in GitHub Actions for cron-trigger simplicity. The host's primary CI can remain on whatever provider you use.

For branch-protection purposes:

- The host's primary checks (CircleCI etc.) stay required on user PRs.
- `actionlint` should be required if you add the workflow. Post-CCE-59 it fires on every PR (~5s), so it works as a universal gate even on PRs that don't touch workflow files.
- The docs-agent's own workflows do not need to be gated on user PRs.

This is the path used by `theoju/advanced-data-import-system` (tracked in CCE-58).

## Part 5 — Optional add-ons

### actionlint pre-merge gate

Recommended. Catches GitHub Actions context-scoping bugs that pure YAML schema validation misses (see CCE-45 PR #65 → #66 hot-fix loop and CCE-52 for the rationale).

Add `.github/workflows/actionlint.yml`:

```yaml
name: actionlint

on:
  pull_request:
    # CCE-59: NO paths: filter on pull_request. actionlint is a required
    # status check; if it doesn't run, GitHub treats the check as "not
    # yet passing" and blocks merge on every non-workflow PR. Runs ~5s
    # so the cost of running on every PR is negligible.
    branches: [main]
  push:
    # post-merge runs on main only when workflows actually change
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

Then add `actionlint` to the required status checks (Part 2.5).

### Slack notifications

Set `SLACK_WEBHOOK_URL` (Part 2.4) and enable `notifications.slack.enabled: true` in `.engineering-docs-agent/config.yml`.

### Email notifications

Set `SMTP_SERVER` + `SMTP_USER` + `SMTP_PASSWORD` (Part 2.4) and enable `notifications.email.enabled: true` in config.

### Jira enrichment opt-in

Set `JIRA_API_TOKEN` + `JIRA_EMAIL` (Part 2.4) and enable `sources.jira.enabled: true` + `sources.jira.project_keys: ["YOUR"]` in config.

## Part 6 — Troubleshooting

### Symptom: no docs-agent PR appears after a workflow run

- Check the workflow run log for failures.
- The runner's pre-flight asserts will catch most missing-secret problems with distinct messages.

### Symptom: PR opens but no CI fires on it

Root cause: the workflow is using the default `GITHUB_TOKEN` for `git push` / `gh pr create`. Default `GITHUB_TOKEN` suppresses both `pull_request` and `push` event triggers on commits it makes (documented loop-prevention).

**Fix:** wire the GitHub App token through (CCE-45). The workflow's first step should mint the token via `actions/create-github-app-token@v3`, and the checkout step's `token:` input + the orchestrator step's `GH_TOKEN` env should both reference `${{ steps.app-token.outputs.token }}`. See the dogfood workflow at `.github/workflows/docs-agent-nightly.yml` for a working example. The canonical example uses `client-id: ${{ vars.DOCS_AGENT_APP_CLIENT_ID }}` (Variable, not Secret) — the Client ID is non-sensitive and lives in repo Variables.

### Symptom: workflow_dispatch returns HTTP 422 "Unrecognized named-value"

Root cause: a `${{ steps.* }}` reference at job-env scope. GitHub's runtime validator rejects `steps.*` at job-env because job-env is resolved before any step runs.

**Fix:** move the reference to step-env (CCE-45 PR #66 has the canonical pattern). Pre-merge `python3 -c "yaml.safe_load(...)"` does NOT catch this — actionlint does (CCE-52). Adding actionlint as a pre-merge gate prevents this class of bug from landing.

### Symptom: every PR opens with `partial_reasons: [jira_auth_missing]`

Root cause: `JIRA_API_TOKEN` + `JIRA_EMAIL` not configured in the runner env.

**Fix:** set the secrets (Part 2.4) and verify the workflow's job-env block surfaces them via `${{ secrets.JIRA_API_TOKEN }}` etc. (CCE-53).

### Symptom: a PR opens with `partial_reasons: [prose_contamination_rescued: …]`

Root cause (post-CCE-55): the subagent emitted prose around its JSON in a shape that the whole-string code-fence stripper at `scripts/orchestrator_runner.py:_strip_code_fence` does not normalize away. Pure ` ```json … ``` ` markdown wraps now strip silently at parse time and do NOT trigger this banner. If the banner now appears, the contamination is genuinely anomalous — prose preamble, trailing prose, or some shape not covered by the whole-string fence match.

**Fix:** download the per-dispatch forensics artifact from the workflow run (CCE-41 uploads it as `docs-agent-subagent-forensics-<run-id>`). The `<ts>-<name>.stdout.txt` for the rescued dispatch shows the exact contamination. From there: either tighten the agent contract prompt for that subagent OR add a new normalization layer alongside `_strip_code_fence` for the newly-observed shape.

### Symptom: `release.yml` live tests fail with "OAuth token not configured"

Root cause: token may be missing, wrong type (e.g. `sk-ant-api…` console key pasted into the OAuth slot), or truncated.

**Fix:** the CCE-49 multi-stage assert distinguishes between these modes with distinct `::error::` messages. Re-paste from `claude setup-token`.

### Symptom: branch protection blocks merge with "head not up-to-date"

Expected behavior when `strict=true`. Resolve by merging `origin/main` into the PR branch and pushing.

## Part 7 — Setup checklist (copy-paste)

For a fresh host repo:

**One-time (Part 1):**

- [ ] Run `claude setup-token`, copy the OAuth token.
- [ ] Register the GitHub App (Part 1.2).
- [ ] Download the App's private key (`.pem` file).
- [ ] Note the App ID.
- [ ] (Optional) Generate an Atlassian API token.

**Per host (Part 2 + Part 5):**

- [ ] `claude plugin marketplace add …`
- [ ] `claude plugin install engineering-docs-agent@…`
- [ ] `claude /engineering-docs-agent-setup`
- [ ] Commit `.engineering-docs-agent/` + `.github/workflows/docs-agent-nightly.yml`.
- [ ] Install the GitHub App on this repo (Part 2.3).
- [ ] Set secrets: `CLAUDE_CODE_OAUTH_TOKEN`, `DOCS_AGENT_APP_PRIVATE_KEY`. Set variables: `DOCS_AGENT_APP_CLIENT_ID`.
- [ ] (Optional) Set secret `JIRA_API_TOKEN` and variable `JIRA_EMAIL` for Jira enrichment.
- [ ] (Optional) Set `SLACK_WEBHOOK_URL` / SMTP for notifications.
- [ ] Configure branch protection: pytest checks + actionlint (Part 2.5).
- [ ] (Recommended) Add `.github/workflows/actionlint.yml` (Part 5).
- [ ] `gh workflow run docs-agent-nightly.yml -f reason="first-run smoke test"`.
- [ ] Verify the resulting PR opens with App identity AND CI checks fire on it.

## Reference

Key tickets that shaped this guide:

- **CCE-39**: Initial nightly cron workflow.
- **CCE-40**: Durable state persistence (`state.json` in git, not gitignored).
- **CCE-41**: Subagent forensics upload (`actions/upload-artifact`).
- **CCE-42**: Branch collision handling for same-day reruns.
- **CCE-43**: Working-tree handling for same-hour reruns.
- **CCE-45**: GitHub App token replaces default `GITHUB_TOKEN` (enables PR-trigger CI).
- **CCE-48**: `partial_reasons` surfaced in `$GITHUB_STEP_SUMMARY`.
- **CCE-49**: Multi-stage OAuth token assert.
- **CCE-50, CCE-51**: Auth-token doc references corrected (OAuth vs API key).
- **CCE-52**: `actionlint` pre-merge gate.
- **CCE-53**: Jira credentials wired into the runner env.
- **CCE-54**: Node-20 → Node-24 actions bump.
- **CCE-55**: Strip benign markdown code-fence wraps before strict JSON parse (silences the most common partial-banner class).
- **CCE-56**: This guide.
- **CCE-57, CCE-58**: Onboarding the next two hosts (exercises this guide; surfaces gaps).
- **CCE-59**: Remove `pull_request paths:` filter on the actionlint workflow so it runs on every PR (unblocks the required-check + path-filter footgun).
