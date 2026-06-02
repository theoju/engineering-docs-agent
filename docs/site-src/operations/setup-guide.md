---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/77
synthesized_into: []
---

# Host Onboarding Guide

This guide walks you through installing the engineering-docs-agent plugin on a new host repo from scratch. It covers GitHub App registration, required repo secrets, branch protection rules, the setup skill, and validation. A troubleshooting section at the end covers every known partial-mode failure mode.

---

## Part 1: Prerequisites

Before you start, confirm you have:

- **Claude Code** installed and authenticated (`claude --version` succeeds).
- **GitHub CLI** (`gh`) authenticated to the host org (`gh auth status` is clean).
- **Python 3.10+** on the machine running the orchestrator (`python3 --version`).
- Write access to the host repo (you'll push a branch and configure secrets).

The agent runs against arbitrary host repos regardless of language. The host repo does not need to be a Python project. Non-Python hosts have been validated end-to-end (see Part 6).

---

## Part 2: Install the plugin

Register the marketplace and install the plugin:

```bash
# Option A: from the published marketplace URL
claude plugin marketplace add <marketplace-url>
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace

# Option B: from a local clone (useful when testing unreleased changes)
claude plugin marketplace add /path/to/engineering-docs-agent
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace
```

Both paths produce the same result. The marketplace manifest is at `.claude-plugin/marketplace.json`; the plugin manifest is at `.claude-plugin/plugin.json`.

---

## Part 3: Run the setup skill

From your **host repo root**, run:

```bash
claude /engineering-docs-agent-setup
```

The setup skill (`/engineering-docs-agent:engineering-docs-agent-setup`) detects your repo layout and scaffolds:

- `.engineering-docs-agent/config.yml` — host config skeleton, pre-filled from detection.
- `.engineering-docs-agent/state.json` — initial state seeded from `state.example.json`.
- `docs/site-src/` (or your detected `docs_dir`) — MkDocs source tree with a starter `mkdocs.yml` and `whats-new.md`.
- `.github/workflows/docs-agent-nightly.yml` — the nightly authoring workflow.

Review and adjust `config.yml` before continuing. The most important fields are `docs.source_dir`, `docs.agent_editable_paths`, `sources.jira`, and `voice.sample_paths`.

### Config invariant

Every `docs.lens_paths` entry must be covered by at least one `docs.agent_editable_paths` glob. The config loader enforces this at boot via `_validate_lens_paths_are_editable` in `scripts/state_io.py`. If the invariant fails, the orchestrator exits early with a clear error.

---

## Part 4: Configure the host

Open `.engineering-docs-agent/config.yml` and verify:

```yaml
docs:
  framework: mkdocs          # mkdocs | sphinx | plain
  source_dir: docs/site-src  # MkDocs docs_dir value
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths:
    - "docs/site-src/**"
  lens_paths:
    core: docs/site-src/

sources:
  git:
    host: github             # github | gitlab
  jira:
    enabled: true            # set false if no Jira
    base_url: https://your-org.atlassian.net
    project_keys:
      - YOUR-PREFIX

voice:
  sample_paths:
    - CLAUDE.md              # any files that establish your repo's writing voice
    - README.md

lint:
  tier1: default

publishing:
  base_url: https://your-org.github.io/repo-name/
  build_workflow: docs-pages.yml
  url_map_rule: standard
  verify_timeout_seconds: 60

notifications:
  slack:
    enabled: false
  email:
    enabled: false
```

Jira enrichment is optional. If `sources.jira.enabled: false`, the orchestrator skips the Jira fetch stage and marks the run `partial: true` with `reason: jira_disabled` — not an error.

---

## Part 5: GitHub App registration and secrets

The nightly workflow authenticates to the GitHub API and (optionally) Jira. Set the following repo secrets in **Settings → Secrets and variables → Actions**:

| Secret | Required | Purpose |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Yes | Claude Code OAuth token for the `claude` CLI |
| `GH_TOKEN` | Yes | Fine-grained GitHub token with `contents: write` and `pull-requests: write` on the host repo |
| `JIRA_EMAIL` | If Jira enabled | Atlassian account email |
| `JIRA_API_TOKEN` | If Jira enabled | Atlassian Cloud API token (from `id.atlassian.com`, NOT your password) |

The `JIRA_API_TOKEN` is sent via HTTP basic-auth over TLS to the Jira REST API. `dispatch_subagent` passes the full parent environment into subprocesses, so any inherited `JIRA_*` vars reach the source-collector agent without extra plumbing.

### GitHub App vs. PAT

A GitHub App installation token gives more granular permission control than a classic PAT. If your org requires GitHub Apps:

1. Create an App in **Organization settings → Developer settings → GitHub Apps**.
2. Grant it `Contents: Read & Write` and `Pull requests: Read & Write` on the host repo.
3. Install the App on the repo.
4. Store the App ID + private key as separate secrets and exchange them for an installation token at workflow start (use the `tibdex/github-app-token` action or equivalent).

If your org allows fine-grained PATs, set `GH_TOKEN` to one scoped to just the host repo — no org-wide access needed.

---

## Part 6: Branch protection and workflow wiring

### Branch protection

Enable branch protection on `main` with at minimum:

- Require pull request reviews before merging.
- Require status checks to pass (add `test` or your CI job name).
- Do **not** check "Restrict pushes that create matching branches" unless you explicitly allow the bot actor.

The nightly workflow pushes to `docs-agent/YYYY-MM-DD` branches, not `main`. Branch protection on `main` does not block the bot's branch creation.

### Workflow wiring

The setup skill writes `.github/workflows/docs-agent-nightly.yml`. Commit and push it:

```bash
git add .engineering-docs-agent/ docs/ .github/workflows/docs-agent-nightly.yml
git commit -m "feat: add engineering-docs-agent host config (CCE-<number>)"
git push -u origin feat/CCE-<number>-add-docs-agent
gh pr create --title "feat: add engineering-docs-agent" --body "Adds docs agent config and nightly workflow"
```

After the PR merges to `main`, the nightly will run automatically at 07:00 UTC. You can also trigger it manually:

```bash
gh workflow run docs-agent-nightly.yml -f reason="initial smoke test"
gh run watch
```

---

## Part 7: Validation

After the first successful nightly run, verify:

1. A `docs-agent/YYYY-MM-DD` PR exists and is not marked `partial: true` in its body.
2. `.engineering-docs-agent/state.json` has a new `last_successful_run.head_sha`.
3. The docs site build workflow (`docs-pages.yml`) succeeded and pages are live at `publishing.base_url`.
4. `whats-new.md` contains an entry for the run date.

To run a local dry-run without opening a PR:

```bash
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

Set `DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug` before invoking for per-subagent raw-stdout diagnostics.

### Non-Python host notes

The agent is language-agnostic. Two non-Python host repos were onboarded end-to-end (CCE-57, CCE-58) with the following notes:

- `setup_discover.py` detects the language from the repo root. For non-Python hosts, the `python_package` detection path returns `None` — this is expected; the capability skips Python-specific extraction and proceeds.
- The `docs.framework` field drives the build step, not the host language. Set it to `mkdocs`, `sphinx`, or `plain` regardless of what language the app is written in.
- If your host has no `CLAUDE.md` or `README.md`, point `voice.sample_paths` at any Markdown files that represent your team's writing style. The voice-load stage reads these files as few-shot samples; at least one is strongly recommended.

---

## Troubleshooting

### CCE-45: `state.json` missing or malformed on first run

**Symptom:** Orchestrator exits with `KeyError: 'last_successful_run'` or `FileNotFoundError`.

**Fix:** Seed `state.json` from the example:

```bash
cp .engineering-docs-agent/state.example.json .engineering-docs-agent/state.json
```

Then set `last_successful_run.head_sha` to the SHA you want as the start of the first window:

```bash
git log --oneline -1   # copy the SHA
# edit state.json: set "head_sha" to that value
```

Commit and push. The orchestrator reads `state.json` from the working tree, not from a secret or env var.

### CCE-49: Jira fetch fails with 401 even though `JIRA_API_TOKEN` is set

**Symptom:** Run marked `partial: true`, `partial_reasons` includes `jira_auth_missing` or `jira_401`.

**Fix:** Confirm the token is an **Atlassian Cloud API token**, not your account password. Generate one at `https://id.atlassian.com/manage-profile/security/api-tokens`. Also confirm `JIRA_EMAIL` matches the Atlassian account that owns the token — basic-auth requires the email+token pair to match.

If you want to disable Jira entirely, set `sources.jira.enabled: false` in `config.yml`. The run will complete without Jira data.

### CCE-52: `agent_editable_paths` invariant failure at boot

**Symptom:** Orchestrator exits immediately with a message like `lens_path 'docs/site-src/' has no matching agent_editable_paths glob`.

**Fix:** Add a glob to `docs.agent_editable_paths` that covers the lens path:

```yaml
docs:
  agent_editable_paths:
    - "docs/site-src/**"
  lens_paths:
    core: docs/site-src/
```

The editable glob can be narrower than the lens path (e.g., `docs/site-src/generated/**`) but its anchor must share a path branch with the lens path. The validator is in `scripts/state_io.py:_validate_lens_paths_are_editable`.

### CCE-53: Nightly workflow fails with `gh: command not found`

**Symptom:** The `docs-agent-nightly.yml` run exits on the PR-creation step with `gh: command not found`.

**Fix:** The workflow runner image may not include the GitHub CLI. Add an install step before the `gh pr create` call:

```yaml
- name: Install gh
  run: |
    type -p curl >/dev/null || (sudo apt update && sudo apt install curl -y)
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] \
      https://cli.github.com/packages stable main" \
      | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
    sudo apt update && sudo apt install gh -y
```

Alternatively, use `actions/gh-release` or the `octokit/request-action` to create the PR via the REST API without the CLI.

### CCE-55: `whats-new.md` not updated after merge

**Symptom:** The PR merges but `whats-new.md` on `main` still shows the old content.

**Fix:** This usually means `state.json` was not advanced after the merge. After a `docs-agent/YYYY-MM-DD` branch merges, `last_successful_run.head_sha` must point to the new `main` HEAD — the merge commit SHA, not the branch tip. The orchestrator advances state automatically when `--no-pr` is not set. If you ran with `--no-pr` for testing, advance state manually:

```bash
git log origin/main --oneline -1   # get the new HEAD SHA
# edit .engineering-docs-agent/state.json: set head_sha to that value
git add .engineering-docs-agent/state.json
git commit -m "chore: advance docs-agent state to post-merge HEAD"
git push
```

### CCE-57 / CCE-58: Non-Python host partial runs

**Symptom:** Run marked `partial: true` with `partial_reasons: ["python_package_not_found"]`.

**Fix:** This is expected for non-Python hosts. The source-collector's Python-package extraction step returns an empty result when no `setup.py`, `pyproject.toml`, or `setup.cfg` is present. This is a graceful skip, not a failure. The run proceeds with the PR/commit/Jira data it did collect.

If you see this on a Python host, confirm your package root is at the repo root or set `sources.python.package_root` in `config.yml` to the correct relative path.

### CCE-59: Duplicate `docs-agent/YYYY-MM-DD` PR on manual re-run

**Symptom:** A second PR is opened for the same date after a manual trigger.

**Fix:** The nightly workflow checks for an existing open `docs-agent/YYYY-MM-DD` PR before creating a new one (via `gh pr list --head docs-agent/YYYY-MM-DD`). If your workflow version predates this check, update to the latest `docs-agent-nightly.yml` from the plugin. If a duplicate was already created, close the older one manually — it will not interfere with state, but leaving two open PRs for the same window creates confusion.
