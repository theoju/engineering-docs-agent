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

## Architecture

See the [design spec](docs/superpowers/specs/2026-05-19-engineering-docs-agent-design.md).

## Lint rules

Standalone scripts in `scripts/lint/`. Hosts can run them in their own CI on human-authored PRs:

```
python scripts/lint/lint_runner.py --config .engineering-docs-agent/config.yml --paths docs/**/*.md --json
```

## License

MIT.
