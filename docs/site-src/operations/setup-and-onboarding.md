---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/79
synthesized_into: []
---

# Setup and Onboarding

This is the single canonical setup guide for the engineering-docs-agent plugin. A duplicate root-level draft (`docs/setup-guide.md`) was removed in PR #79 (CCE-60); this page is authoritative.

## Prerequisites

- Claude Code installed and authenticated (OAuth or `ANTHROPIC_API_KEY`).
- `gh` CLI authenticated with write access to the target host repo.
- Python 3.11+ on `PATH` (`python3 --version` to confirm).
- Admin GitHub auth for the one-time Pages bootstrap step (Step 6 below). Your standard `gh auth login` token works if the account has admin on the repo.

## Install the plugin

```bash
# From the marketplace (published release):
claude plugin marketplace add engineering-docs-agent
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace

# From a local clone (for testing unreleased changes):
claude plugin marketplace add /path/to/engineering-docs-agent
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace
```

The marketplace registration reads `.claude-plugin/marketplace.json`; the plugin manifest is `.claude-plugin/plugin.json`. Both files must be present in the source tree.

## Run the setup skill

From your **host repo's root** (not the plugin source tree):

```bash
claude /engineering-docs-agent-setup
```

The setup skill (`skills/engineering-docs-agent-setup`) runs interactively and walks you through:

1. Detecting your repo layout (language, framework, existing docs structure).
2. Writing `.engineering-docs-agent/config.yml` with your lens paths, editable paths, Jira project key, and publishing target.
3. Seeding `.engineering-docs-agent/state.json` from `state.example.json`.
4. Creating the `docs/site-src/` tree if it does not exist.
5. Registering the nightly workflow at `.github/workflows/docs-agent-nightly.yml`.
6. Bootstrapping GitHub Pages via `scripts/enable_pages.py` (wraps `gh api -X POST repos/.../pages -f build_type=workflow`). This requires admin scope — `actions/configure-pages@v6 enablement: true` does NOT do this automatically; see CLAUDE.md for the full explanation.

## Configure secrets

The nightly workflow needs two repo secrets:

| Secret | Value |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Your Claude OAuth token (same as `release.yml`). |
| `JIRA_API_TOKEN` | Atlassian Cloud API token (optional; omit to skip Jira enrichment). |

Set them via `gh secret set CLAUDE_CODE_OAUTH_TOKEN` or the repo's **Settings → Secrets → Actions** UI.

If `JIRA_API_TOKEN` is absent, the agent continues to run. `jira_issues` in the source-collector output will be `[]`, and the run is marked `partial: true` with `error: "jira_auth_missing"` in `.engineering-docs-agent/state.json`.

## Validate the installation

Run the agent locally against your host repo in dry-run mode:

```bash
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

`--no-pr` skips the GitHub PR creation; everything else runs — source collection, summarization, page authoring, linting. Check `.engineering-docs-agent/current_run.json` for the full run state. For per-subagent diagnostics, set `DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug` before invoking.

After a clean dry run, verify the docs build:

```bash
mkdocs build --strict
```

A strict-mode build is required before you call a plan step complete. A path that resolves on disk can still fail mkdocs strict if a link target lives outside `docs_dir`. `test -f` is not sufficient.

## Trigger the nightly run manually

```bash
gh workflow run docs-agent-nightly.yml -f reason="initial test run"
gh run watch
```

The `reason` field is a free-text label surfaced in the run summary alongside the post-run `state.json` snapshot. The nightly cron fires at 07:00 UTC once it is enabled; use `workflow_dispatch` for ad-hoc runs.

## Understand the state file

`.engineering-docs-agent/state.json` (committed) holds `last_successful_run.head_sha` — the baseline for the next nightly's window. It advances only when a docs-agent PR merges to main. If you leave docs-agent PRs unmerged, the next nightly opens a competing snapshot from the same stale baseline, not an incremental delta. Merge promptly.

`.engineering-docs-agent/current_run.json` is gitignored ephemeral state written at each checkpoint. It is for diagnostics only and never part of the docs-agent PR.

## Lens paths and editable paths

`docs.lens_paths` defines where docs live per lens (e.g., `core: docs/site-src/`). The voice-load, gap-detection, and summarization stages read from these paths.

`docs.agent_editable_paths` defines where the agent may write. The orchestrator rejects any proposed page outside these globs at runtime.

Every `lens_paths` entry must be covered by at least one `agent_editable_paths` glob. The config loader enforces this at boot via `_validate_lens_paths_are_editable` in `scripts/state_io.py`. A lens with no matching editable glob means the agent reads docs it can never update — this is always a misconfiguration.

The editable glob may be narrower than the lens path. A lens `core: docs/` paired with editable `docs/generated/**` is valid: the agent reads everything under `docs/` but writes only to the `generated/` sub-path.

## Prevent duplicate guides

A regression test (`test_no_duplicate_setup_guide`) asserts that only one setup guide exists at the canonical location. If you add a new setup-related doc, add it as a section here rather than a separate file at the repo root.
