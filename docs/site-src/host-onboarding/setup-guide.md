---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/188
synthesized_into: []
doc_kind: architecture
---

# Setup Guide

End-to-end walkthrough: from zero to a working `engineering-docs-agent` nightly docs-PR pipeline on a new host repo.

The structure splits global (per-user, one-time) setup from per-host (per-repo) setup, and the troubleshooting section covers every partial-mode failure the pipeline is known to hit.

## Quick map

| Section       | What you do                              | Where                                 |
| ------------- | ----------------------------------------- | -------------------------------------- |
| Prerequisites | Sanity-check your environment             | Local                                  |
| Part 1        | One-time setup, reused across every host  | Claude CLI + GitHub UI + Atlassian UI  |
| Part 2        | Per-host onboarding                       | Host repo + GitHub UI                  |
| Part 3        | Validate the first run                    | GitHub Actions                         |
| Part 4        | Per-language / per-CI host notes          | Reference                              |
| Part 5        | Optional add-ons                          | Host repo                              |
| Part 6        | Troubleshooting                           | Reference                              |
| Part 7        | Setup checklist                           | Copy-paste                             |

## Prerequisites

- **Claude Code CLI** installed and authenticated. Run `claude --version` to confirm.
- A **GitHub host repo** where you want auto-generated docs.
- **Admin access** to the host repo (you'll set repo secrets, install a GitHub App, and configure branch protection).
- The host repo has (or will have) a **docs site** — `mkdocs`, `Docusaurus`, or another supported framework. The setup skill auto-detects.

## Part 1 — One-time setup (per Claude Code user)

You do these steps once. They apply across every host repo you onboard.

### 1.1 Get a Claude OAuth token

The Claude CLI reads an OAuth token (a slot distinct from console API keys). Generate one:

```bash
claude setup-token
```

The output starts with `sk-ant-oat`. Copy it — you'll paste it into each host repo's secrets in Part 2.

### 1.2 Register the GitHub App (once)

This GitHub App mints installation tokens so the nightly workflow can push docs-agent branches AND have host-repo CI fire on them. The default `GITHUB_TOKEN` suppresses both `pull_request` and `push` event triggers on commits it makes; App installation tokens are exempt.

You register the App once, then install it on each host repo individually (Part 2.3).

1. Open https://github.com/settings/apps and click **New GitHub App**.
2. Pick a globally-unique name, e.g. `<your-username>-docs-agent-bot`.
3. **Homepage URL**: any URL you control.
4. **Webhook**: uncheck **Active** (no webhooks needed; the workflow polls via cron).
5. **Repository permissions**: Contents (read/write), Pull requests (read/write), Issues (read-only).
6. **Organization / Account permissions**: none.
7. **Where can this App be installed?**: Only on this account.
8. Click **Create GitHub App**, then generate and download a private key (`.pem`).
9. Note the **Client ID** on the App's General page — you'll need it as the `DOCS_AGENT_APP_CLIENT_ID` repo Variable in each host.

### 1.3 (Optional) Atlassian API token

Skip if you don't use Jira. If you do, the source-collector subagent enriches PRs with linked Jira issue summaries. Generate a token at https://id.atlassian.com/manage-profile/security/api-tokens and keep it for the `JIRA_API_TOKEN` secret in Part 2.

## Part 2 — Per-host setup

Do these steps once per host repo you want auto-doc generation on.

### 2.1 Install the plugin

```bash
claude plugin marketplace add /path/to/engineering-docs-agent
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace
```

### 2.2 Run the setup skill

```
claude /engineering-docs-agent-setup
```

The skill auto-detects docs framework, docs source directory, lens information architecture, and Jira opt-in, then commits `.engineering-docs-agent/config.yml`, `.engineering-docs-agent/state.json`, and the nightly cron workflow.

### 2.3 Install the GitHub App on this repo

Install the App from Part 1.2 onto the host repo (**Install App** → select the repo). Verify at `https://github.com/<owner>/<repo>/settings/installations`.

### 2.4 Configure repo secrets and variables

Sensitive values go in **Secrets**; non-sensitive identifiers go in **Variables** so they're visible in workflow logs.

| Secret / Variable              | What it is                                    | Required?                                                        |
| ------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------ |
| `CLAUDE_CODE_OAUTH_TOKEN`      | Claude CLI OAuth token                        | **Yes**                                                           |
| `DOCS_AGENT_APP_PRIVATE_KEY`   | The App's `.pem` private key                  | **Yes**                                                           |
| `DOCS_AGENT_APP_CLIENT_ID`     | The App's OAuth Client ID (Variable)          | **Yes**                                                           |
| `JIRA_API_TOKEN` / `JIRA_EMAIL` | Atlassian API auth                           | Only if Jira enrichment                                           |
| `SLACK_WEBHOOK_URL`            | Slack incoming-webhook URL                    | Only if Slack notifications                                       |
| `SMTP_SERVER`/`SMTP_USER`/`SMTP_PASSWORD` | SMTP creds                          | Only if email notifications                                       |
| `CIRCLECI_TOKEN`               | CircleCI API token, read-only pipeline/workflow/job scope | Only if `publishing.ci_provider: circleci` — see [Part 4](#circleci-and-other-non-github-publish-providers) before you set this |

Without `JIRA_API_TOKEN` + `JIRA_EMAIL`, the source-collector skips Jira enrichment cleanly and the run is marked partial. The PR still opens.

### 2.5 Branch protection (recommended)

Require your test workflow's status check(s) and `actionlint` (if installed, see Part 5) before merging to `main`.

## Part 3 — Validate

### 3.1 First nightly fire (manual dispatch)

```bash
gh workflow run docs-agent-nightly.yml -f reason="first-run smoke test"
gh run watch
```

### 3.2 What success looks like

A new branch and PR appear, authored by your App identity, with CI checks firing on the PR itself. If `partial_reasons` is non-empty, the PR body opens with a `WARNING — Partial run` block explaining why.

### 3.3 First production nightly

The cron fires per `.github/workflows/docs-agent-nightly.yml`. If a PR for the same date already exists, the runner append-commits to it.

## Part 4 — Per-language / per-CI host notes

### Python hosts

The dogfood host (`theoju/engineering-docs-agent`) is Python; most invariants are validated there. The orchestrator prefers stdlib where feasible.

### JavaScript / TypeScript hosts

The plugin is generic-first: behavior is driven by detection + config, not hardcoded paths. Docs-framework detection covers `mkdocs` and `Docusaurus`.

### Hybrid CI (CircleCI, Jenkins, Buildkite, …)

The docs-agent nightly workflow lives in GitHub Actions for cron-trigger simplicity; the host's primary CI can stay on whatever provider you use. For branch-protection purposes, keep the host's primary checks required on user PRs, and add `actionlint` as a universal gate if you use it — the docs-agent's own workflows don't need to be gated on user PRs.

#### CircleCI and other non-GitHub publish providers

The publish-verify step that runs after a docs-agent PR merges normally goes through the `publish-verifier` subagent, which polls `gh run list` against your GitHub Actions `build_workflow`. That path is unchanged and is what runs when `publishing.ci_provider` is `github` (the default, per `verify_runner.run`).

Set `publishing.ci_provider: circleci` if your docs site publishes via a CircleCI pipeline instead. `verify_runner` (`scripts/verify_runner.py`) branches on that field: only `github` reaches the `publish-verifier` agent at all — `circleci` and any other non-`github` value route to `resolve_build_verdict` in `scripts/build_poller.py`, a Python seam that never dispatches an LLM subagent for the poll.

**Today that seam does not poll CircleCI.** There is no live CircleCI-publishing host yet to validate the v2 API shape against, so `resolve_build_verdict` degrades honestly instead of guessing: while its `UNVALIDATED_AGAINST_LIVE_HOST` flag is `True` (the current, committed state), it returns a fixed non-promoting verdict — `build_status: "circleci_unvalidated"`, empty `verified`/`failed` lists, and a single fixed reason string, `circleci_provider_modeled_but_unvalidated`. No network call is made, so there's nothing that can hang or mis-verify. The real poller (`poll_circleci`) and its status-vocabulary mapper (`map_circleci_status`) exist as explicit `NotImplementedError` stubs in the same file — they're reached only once someone flips the flag after validating against a real CircleCI-publishing host.

Practically, this means: setting `ci_provider: circleci` today gets you an honest "we didn't check" signal on every publish-verify run, not a false green and not a crash. The reason string flows into `state.json`'s partial-reasons list and, because it's non-empty, into the `notifier` digest's "Partial-run reasons" section (`agents/notifier.md`) — the GitHub-provider digest stays byte-for-byte unchanged since that field is only populated on the non-github path. The notifier renders a `build_status` outside `{success, failure, timeout}` (such as `circleci_unvalidated`) as informational, never with failure wording, as long as there are no failed URLs.

Do not set `CIRCLECI_TOKEN` expecting it to be used yet — nothing reads it on this path today. `CircleCiClient` (also in `scripts/build_poller.py`) reads `CIRCLECI_TOKEN` from the environment and sends it only as a `Circle-Token` request header, never a URL userinfo segment or query param, precisely so it can't leak via a logged URL — but the client's pipeline-lookup methods raise `NotImplementedError` and are unreached while the honest-degrade flag is set. As part of adding this seam, the credential-redaction helper (`scripts/stderr_emit.py:_redact_credentials`) was also extended: it previously only masked `user:pass@host` URL credentials, and now additionally masks header-form secrets — a `Circle-Token` or `Authorization` value, including the quoted dict-repr shape (`{'Circle-Token': 'value'}`) that `str()`-ing a headers dict produces, which is the leak vector `CircleCiClient.auth_headers` would hit once wired up.

`theoju/advanced-data-import-system` is the current hybrid-CI host in this fleet; it publishes its docs via GitHub Actions and stays on `ci_provider: github`. Note also that the *trigger* side of publishing (dispatching the build workflow after an auto-merge, via `orchestrator_runner`'s `gh.workflow_run` call) is still GitHub-only regardless of `ci_provider` — provider-awareness there is tracked separately and is out of scope for this seam.

## Part 5 — Optional add-ons

### actionlint pre-merge gate

Recommended. Catches GitHub Actions context-scoping bugs that YAML schema validation misses. Run it on every `pull_request` (no `paths:` filter) so it stays a valid required status check even on PRs that don't touch workflow files.

### Slack notifications

Set `SLACK_WEBHOOK_URL` (Part 2.4) and enable `notifications.slack.enabled: true` in config.

### Email notifications

Set `SMTP_SERVER` + `SMTP_USER` + `SMTP_PASSWORD` (Part 2.4) and enable `notifications.email.enabled: true` in config.

### Jira enrichment opt-in

Set `JIRA_API_TOKEN` + `JIRA_EMAIL` (Part 2.4) and enable `sources.jira.enabled: true` + `sources.jira.project_keys: [...]` in config.

## Part 6 — Troubleshooting

### Symptom: no docs-agent PR appears after a workflow run

Check the workflow run log — the runner's pre-flight asserts catch most missing-secret problems with distinct messages.

### Symptom: PR opens but no CI fires on it

Root cause: the workflow used the default `GITHUB_TOKEN`, which suppresses `pull_request`/`push` triggers on its own commits. Fix: wire the GitHub App token through `actions/create-github-app-token@v3` for both the checkout `token:` input and the orchestrator step's `GH_TOKEN` env.

### Symptom: every PR opens with `partial_reasons: [jira_auth_missing]`

`JIRA_API_TOKEN` + `JIRA_EMAIL` aren't set in the runner env. Set the secrets (Part 2.4).

### Symptom: a publish-verify digest shows a `circleci_unvalidated` build status with a `circleci_provider_modeled_but_unvalidated` partial reason

Expected behavior, not a bug — see [CircleCI and other non-GitHub publish providers](#circleci-and-other-non-github-publish-providers). It means `publishing.ci_provider: circleci` is set and the honest-degrade path ran; nothing was actually polled. It is informational, not a failure signal, and it will surface on every verify run until the real CircleCI poller is implemented and validated.

### Symptom: branch protection blocks merge with "head not up-to-date"

Expected behavior when `strict=true`. Resolve by merging `origin/main` into the PR branch and pushing.

## Part 7 — Setup checklist (copy-paste)

**One-time (Part 1):**

- [ ] Run `claude setup-token`, copy the OAuth token.
- [ ] Register the GitHub App (Part 1.2), download its private key, note the Client ID.
- [ ] (Optional) Generate an Atlassian API token.

**Per host (Part 2 + Part 5):**

- [ ] `claude plugin marketplace add …` / `claude plugin install …`
- [ ] `claude /engineering-docs-agent-setup`
- [ ] Commit `.engineering-docs-agent/` + the nightly workflow.
- [ ] Install the GitHub App on this repo (Part 2.3).
- [ ] Set secrets/variables from the Part 2.4 table. Leave `CIRCLECI_TOKEN` unset unless you've read the CircleCI section above.
- [ ] Configure branch protection.
- [ ] `gh workflow run docs-agent-nightly.yml -f reason="first-run smoke test"`.
- [ ] Verify the resulting PR opens with App identity AND CI checks fire on it.

## Reference

- **CCE-63**: CircleCI (non-GitHub) publish-verify provider seam — `scripts/build_poller.py` — honest-degrade until a live CircleCI-publishing host validates the real poller; closed a header-form credential-redaction gap in `scripts/stderr_emit.py` along the way.
