# CCE-57 onboarding runbook — `theoju/claude-code-self-assessment`

This runbook executes the user-gated steps that the plugin-side prep (CCE-57 PR) cannot do for you. Follow it top-to-bottom. Each step lists what to run, what to expect, and what to do if it fails.

You will need: admin access to the target repo, the OAuth + App credentials from `docs/setup-guide.md` Part 1, and ~30 minutes uninterrupted.

## Prerequisites

- `claude --version` succeeds.
- The engineering-docs-agent plugin PR for CCE-57 is merged to `main` (so `templates/workflow-run.yml` and `scripts/preflight_host.py` exist).
- You have a local clone of `theoju/engineering-docs-agent` at `~/Projects/engineering-docs-agent` (paths below assume this).

## Step 1 — Clone the target

```bash
cd ~/Projects
git clone https://github.com/theoju/claude-code-self-assessment
cd claude-code-self-assessment
git checkout -b feat/CCE-57-bootstrap-docs-agent
```

**Expected:** clean clone, new branch checked out.

**If it fails:** check repo access and SSH config; this runbook assumes you can clone.

## Step 2 — Run preflight

```bash
python3 ~/Projects/engineering-docs-agent/scripts/preflight_host.py \
  --repo-root . \
  --format text
```

**Expected:** a Discovery block, a Proposed config block, a Secrets checklist with 5+ entries, and warnings. For this target the warnings will include `no_docs_framework` (no Docusaurus site yet) or `pages_not_auto_scaffolded` (if you've already scaffolded one). The `node_only_host` warning will fire because the target is JS/TS.

**What to copy out:** the `Secrets checklist` rows. You will paste each into the GitHub UI in Step 7.

**If it fails:** confirm Python 3.11+ is on PATH; the script is stdlib-only — no pip install required.

## Step 3 — Install the plugin in the target

```bash
claude plugin marketplace add ~/Projects/engineering-docs-agent
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace
```

**Expected:** install succeeds; `~/.claude/plugins/` contains the plugin.

**If it fails:** see `docs/setup-guide.md` Part 2.1.

## Step 4 — Run the setup skill

```bash
claude /engineering-docs-agent-setup
```

The skill prints discovered values (same as Step 2) and asks a small number of questions. For this target answer:

- **Notifications:** all `n` (Slack/email off; opt in later if needed).
- **Voice samples:** accept default (`CLAUDE.md`, `README.md`).
- **Gap allowlist:** empty.
- **Tier-2 lint:** none (keep just Tier-1 default).
- **Glossary:** no.

**Expected outputs:**

- `.engineering-docs-agent/config.yml`
- `.engineering-docs-agent/state.json`
- `.github/workflows/docs-agent-nightly.yml` (or `docs-agent-run.yml`, depending on the skill's current naming)

The workflow file MUST contain a step named `Check out engineering-docs-agent plugin` (CCE-57 fix). If it does not, the skill is running from an old plugin version — re-run Step 3.

**If it fails:** see `docs/setup-guide.md` Part 2.2.

## Step 5 — Register / reuse the GitHub App

Follow `docs/setup-guide.md` Part 1.2 to register the App if you don't already have one for this account. If you onboarded `theoju/engineering-docs-agent` previously, reuse the same App — no need to register a second one.

**Expected:** you have an App ID, a `.pem` private key file, and the App showing in `https://github.com/settings/apps`.

## Step 6 — Install the App on `claude-code-self-assessment`

Follow `docs/setup-guide.md` Part 2.3 — install the App, scope to this single repo.

**Verify:** `https://github.com/theoju/claude-code-self-assessment/settings/installations` shows your App.

## Step 7 — Set repo secrets

Use the checklist from Step 2's preflight output. For each row, in the GitHub UI:

1. Open `https://github.com/theoju/claude-code-self-assessment/settings/secrets/actions`.
2. Click **New repository secret**.
3. Paste name and value.

The three blocking secrets are:

- `CLAUDE_CODE_OAUTH_TOKEN` — from `claude setup-token` (starts with `sk-ant-oat`).
- `DOCS_AGENT_APP_ID` — App ID from Step 5.
- `DOCS_AGENT_APP_PRIVATE_KEY` — full contents of the `.pem` file (including BEGIN/END lines).

Optional but recommended for Jira enrichment:

- `JIRA_API_TOKEN` — see `docs/setup-guide.md` Part 1.3.
- `JIRA_EMAIL` — the Atlassian account email associated with the Jira token.

**Expected:** the Secrets list shows all of the entries you set.

## Step 8 — Commit, push, open PR, smoke test

```bash
git add .engineering-docs-agent .github/workflows
git commit -m "feat: bootstrap engineering-docs-agent (CCE-57)"
git push -u origin feat/CCE-57-bootstrap-docs-agent
gh pr create --title "feat: bootstrap engineering-docs-agent (CCE-57)" \
  --body "Adds the docs-agent config + workflow per CCE-57."
```

Merge the PR via the GitHub UI (CCE-57 is a bootstrap, no required-check coverage yet). Then smoke the workflow:

```bash
gh workflow run docs-agent-nightly.yml \
  -R theoju/claude-code-self-assessment \
  -f reason="CCE-57 first-run smoke test"
gh run watch -R theoju/claude-code-self-assessment
```

**Expected (per `docs/setup-guide.md` Part 3.2):**

- A `docs-agent/<YYYY-MM-DD>T<HH>` branch appears.
- A docs-agent PR is open against `main`, authored by the App identity.
- `partial_reasons` block in the PR body lists `no_docs_framework` (expected — Docusaurus site not scaffolded yet) but does not list `jira_auth_missing` (proves Jira secrets wired correctly).

**If it fails:** check the workflow run log; cross-reference against `docs/setup-guide.md` Part 6 (Troubleshooting). The most common first-run failure is a typo in `DOCS_AGENT_APP_PRIVATE_KEY` (forgot to include the BEGIN/END lines).

## Optional next steps (after smoke test passes)

- **Scaffold Docusaurus** in the target (`npx create-docusaurus@latest`). After committing, re-run preflight — `no_docs_framework` warning should disappear and the next nightly will produce real content.
- **Branch protection** (`docs/setup-guide.md` Part 2.5). The host's test-check name will be Node-shaped (e.g. `test (node 20)`), not `pytest (3.11)`. Adjust accordingly.
- **actionlint workflow** (`docs/setup-guide.md` Part 5) — recommended for every host.

## Done

The host is onboarded when Step 8's smoke test produces a docs-agent PR with App identity. Move CCE-57 to "In Review" once the bootstrap PR is open on the target.
