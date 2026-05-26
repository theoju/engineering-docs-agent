# engineering-docs-agent

A Claude Code plugin: nightly docs-PR generator with publish verification and tiered content linting.

## What it does

- Watches a host repo's Git/PRs/Jira for changes since the last successful run.
- Opens a PR against the host's docs site with:
  - **What's New** entry summarizing changes.
  - **Updated/new pages** authored by a `page-author` subagent with voice few-shot.
  - **Gap flags** for non-trivial PRs that have no spec/plan.
- Sends a Slack + email digest.
- After the PR merges, verifies the host's build pipeline succeeded and pages are live.

## Install

1. Add this repo as a Claude Code marketplace:
   ```
   claude marketplace add engineering-docs-agent <repo-url>
   ```
2. Install the plugin:
   ```
   claude plugin install engineering-docs-agent
   ```
3. In your host repo, run the setup skill:
   ```
   claude /engineering-docs-agent-setup
   ```
4. Configure GitHub secrets: `ANTHROPIC_API_KEY`, `SLACK_WEBHOOK_URL`, `JIRA_API_TOKEN`, `SMTP_*` as needed.

## Self-hosting (dogfood)

This repo is configured to run the agent against itself — a reference layout for new host repos:

1. `.engineering-docs-agent/config.yml` — host config (framework, paths, Jira project keys, voice samples, publishing target).
2. `.engineering-docs-agent/state.example.json` — seed template. Copy to `state.json` on first setup; the runtime file is gitignored so per-run mutations stay local.
3. `docs/_agent-sandbox/` — agent-editable area (`agent_editable_paths` glob restricts writes here).

Bootstrap a fresh checkout:

```bash
cp .engineering-docs-agent/state.example.json .engineering-docs-agent/state.json
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

The seed `last_successful_run.head_sha` points to the v0.1.0 tag commit, giving source-collector a real diff window over the project's PR history (CCE-1 through CCE-9). For per-subagent raw-stdout diagnostics, set `DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug` before invoking.

> Publish-verification is configured against a `deploy.yml` GitHub Actions workflow that is not yet committed; the `--no-pr` flag above keeps the bootstrap dry-run only. Wiring up the workflow + end-to-end publish path is tracked separately.

### Install from local clone

If you're working from a checkout of this repo (e.g., to test changes before publishing), register the local marketplace and install the plugin:

```bash
claude plugin marketplace add /path/to/engineering-docs-agent
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace
```

That makes the seven agents resolvable without `--plugin-dir` workarounds. The marketplace registration reads `.claude-plugin/marketplace.json`; the plugin manifest is at `.claude-plugin/plugin.json`.

### Lens paths and editable paths

The agent reads from **lens paths** and writes to **editable paths**. They overlap, but they are different:

- `docs.lens_paths` defines _where docs live for each lens_ (e.g., `core: docs/`, `superpowers: docs/superpowers/`). The voice-load, gap-detection, and PR-summarization stages read from these paths.
- `docs.agent_editable_paths` defines _where the agent may write_. The orchestrator's runtime filter rejects any proposed page outside these globs.

**Invariant:** every `lens_paths` entry must be covered by at least one `agent_editable_paths` glob. The config loader enforces this at boot via `_validate_lens_paths_are_editable` in `scripts/state_io.py`. A lens with no matching editable glob means the agent reads docs it can never update — usually a mistake.

The editable globs may be **narrower** than the lens path — e.g., `core: docs/` paired with editable `docs/_agent-sandbox/**` is valid: the agent reads everything under `docs/` but only writes to the sandbox. The validator accepts this because the editable glob's anchor (`docs/_agent-sandbox/`) starts with the lens path (`docs/`). The compatibility rule is bidirectional: glob anchor and lens path must share a path branch.

### Jira enrichment (optional)

If your host config sets `sources.jira.enabled: true` and you want the
source-collector subagent to fetch linked issue summaries, set two env
vars in the shell that invokes the orchestrator:

```bash
export JIRA_EMAIL="your.email@example.com"
export JIRA_API_TOKEN="…"  # token from https://id.atlassian.com/manage-profile/security/api-tokens
```

`JIRA_API_TOKEN` is an Atlassian Cloud API token (NOT your password). The
token is sent over TLS via HTTP basic-auth to the Jira REST API.
`dispatch_subagent` already passes the full parent environment into the
subprocess, so any inherited `JIRA_*` vars reach the agent without
additional plumbing.

Without these env vars, the orchestrator continues to run; `jira_issues`
in the source-collector output will be `[]` and the run is marked
`partial: true` with `error: "jira_auth_missing"` so the operational gap
is visible in `.engineering-docs-agent/state.json` partial_reasons and in
Slack/email notifications. See `agents/source-collector.md` Step 5 +
Forbidden outputs §6 for the agent-side contract.

## Live integration tests

The default `pytest` run is fully mocked — no network, no LLM, no cost. A separate `@pytest.mark.live` gate covers the real-LLM dispatch path:

```bash
pytest -m live -v
```

These tests invoke the real `claude` CLI and cost roughly **$1-3 per full pass** (each test ~$0.10-$0.50). They require the `claude` CLI installed and authenticated (OAuth or `ANTHROPIC_API_KEY`), network access, and API quota. Live tests are skipped by default (a `conftest.py` hook); opt in with `-m live`. CI runs them only on tag pushes (`.github/workflows/release.yml`), never per-PR.

What's covered: one `dispatch_subagent` call per payload shape (notifier with a digest, pr-summarizer with PR metadata). The dispatch path is the system-under-test — the kinds of wiring bugs CCE-2 and CCE-3 fixed are exactly what these catch.

## Architecture

See the [design spec](docs/superpowers/specs/2026-05-19-engineering-docs-agent-design.md).

## Lint rules

Standalone scripts in `scripts/lint/`. Hosts can run them in their own CI on human-authored PRs:

```
python scripts/lint/lint_runner.py --config .engineering-docs-agent/config.yml --paths docs/**/*.md --json
```

## License

MIT.
