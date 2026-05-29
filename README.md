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

1. `claude plugin marketplace add <this-repo>` — register the marketplace from the local path or remote URL.
2. `claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace` — install the plugin.
3. `claude /engineering-docs-agent-setup` — run the setup skill from your host repo's root.

For the comprehensive walkthrough (GitHub App registration, all repo secrets, branch protection, validation, per-language host notes, troubleshooting for every partial-mode failure), see [docs/setup-guide.md](docs/setup-guide.md).

## Self-hosting (dogfood)

This repo is configured to run the agent against itself — a reference layout for new host repos:

1. `.engineering-docs-agent/config.yml` — host config (framework, paths, Jira project keys, voice samples, publishing target).
2. `.engineering-docs-agent/state.json` — committed state. `last_successful_run.head_sha` is the source of truth for the next nightly's window. Each merged `docs-agent/YYYY-MM-DD` PR advances it via normal git merge — no separate promote workflow.
3. `.engineering-docs-agent/state.example.json` — seed template for fresh host repos. This dogfood host already has a real `state.json`; the example file is preserved for plugin users installing into a new repo.
4. `.engineering-docs-agent/current_run.json` — gitignored ephemeral run state, written every state-update for diagnostics + test observability. Not part of the docs-agent PR.
5. `docs/site-src/` — agent-editable area and MkDocs source dir; the `agent_editable_paths` glob (`docs/site-src/**`) restricts writes here, and the same tree publishes to GitHub Pages.

Run the agent locally against this host:

```bash
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

For per-subagent raw-stdout diagnostics, set `DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug` before invoking.

> Publish-verification is configured against a `deploy.yml` GitHub Actions workflow that is not yet committed; the `--no-pr` flag above keeps the bootstrap dry-run only. Wiring up the workflow + end-to-end publish path is tracked separately.

### Nightly authoring run

The main authoring pipeline (`scripts/orchestrator_runner.py` with no subcommand) runs automatically once daily at 07:00 UTC via `.github/workflows/docs-agent-nightly.yml`. The workflow opens or append-commits to a `docs-agent/YYYY-MM-DD` PR; per spec §8, a partial run still opens the PR with `partial: true` in the body so an operational gap is visible, not silent.

To fire it manually:

```bash
gh workflow run docs-agent-nightly.yml -f reason="<your reason>"
gh run watch
```

The `reason` input is a free-text label surfaced in the run summary alongside the post-run `state.json` snapshot. Auth is via the `CLAUDE_CODE_OAUTH_TOKEN` repo secret (same secret as `release.yml`). One run at a time per repo — concurrent invocations queue rather than race on the same docs-agent branch.

### Install from local clone

If you're working from a checkout of this repo (e.g., to test changes before publishing), register the local marketplace and install the plugin:

```bash
claude plugin marketplace add /path/to/engineering-docs-agent
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace
```

That makes the seven agents resolvable without `--plugin-dir` workarounds. The marketplace registration reads `.claude-plugin/marketplace.json`; the plugin manifest is at `.claude-plugin/plugin.json`.

### Lens paths and editable paths

The agent reads from **lens paths** and writes to **editable paths**. They overlap, but they are different:

- `docs.lens_paths` defines _where docs live for each lens_ (e.g., `core: docs/site-src/`). The voice-load, gap-detection, and PR-summarization stages read from these paths.
- `docs.agent_editable_paths` defines _where the agent may write_. The orchestrator's runtime filter rejects any proposed page outside these globs.

**Invariant:** every `lens_paths` entry must be covered by at least one `agent_editable_paths` glob. The config loader enforces this at boot via `_validate_lens_paths_are_editable` in `scripts/state_io.py`. A lens with no matching editable glob means the agent reads docs it can never update — usually a mistake.

The editable glob may be **narrower** than the lens path — e.g., a lens `core: docs/` paired with editable `docs/generated/**` is valid: the agent reads everything under `docs/` but only writes to the `generated/` sub-path. The validator accepts this because the editable glob's anchor (`docs/generated/`) starts with the lens path (`docs/`). The compatibility rule is bidirectional: glob anchor and lens path must share a path branch. This repo's dogfood config keeps the two co-located: lens `docs/site-src/` with editable `docs/site-src/**`.

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
