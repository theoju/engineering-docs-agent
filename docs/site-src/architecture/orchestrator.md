---
description: "The orchestrator is the central coordinator of the nightly docs-agent run."
source_files:
  - scripts/orchestrator_runner.py
last_reviewed: '2026-06-09'
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/96
  - https://github.com/theoju/engineering-docs-agent/pull/112
  - https://github.com/theoju/engineering-docs-agent/pull/113
  - https://github.com/theoju/engineering-docs-agent/pull/118
synthesized_into: []
---

# Orchestrator

The orchestrator is the central coordinator of the nightly docs-agent run. It lives in `scripts/orchestrator_runner.py` and drives every stage: collecting PR summaries, invoking subagents, committing changes, opening the docs-agent PR, and regenerating the published site.

## Nightly run lifecycle

The nightly workflow (`docs-agent-nightly.yml`) triggers the orchestrator once daily at 07:07 UTC, or on `workflow_dispatch`. The orchestrator reads `.engineering-docs-agent/config.yml` and `.engineering-docs-agent/state.json` to determine the baseline SHA and the set of merged PRs since the last successful run.

Each stage writes into `.engineering-docs-agent/current_run.json` (gitignored) as it completes. If a stage fails, the orchestrator records a partial reason rather than aborting — the nightly PR still opens with `partial: true` in the body so the gap is visible, never silent.

## Model selection

The orchestrator reads the `CLAUDE_MODEL` environment variable and, when non-empty, appends `--model <value>` to every Claude CLI invocation (PR #96). The `docs-agent-nightly.yml` workflow exposes a `claude_model` `workflow_dispatch` input that populates this variable, so you can override the model at dispatch time without editing the YAML.

The explicit `ANTHROPIC_API_KEY` env block was removed from the workflow in the same PR. The Claude CLI reads the secret natively from the runner environment since PR #91; the explicit block was dead weight that slightly widened the key's blast radius.

## PR body enrichment

Each nightly PR body is assembled by `_compose_pr_body` (PR #112), a pure function that renders four conditional sections:

- **Review window** — baseline → current SHA, so you can open the diff directly.
- **Per-lens file count** — how many files changed under each lens path.
- **Top-N changed pages** — the highest-churn pages in the run, ranked by diff size.
- **Partial-reasons digest** — inline list of any `info_only` or `partial` failures recorded during the run.

`_compose_pr_body` is wired into `open_or_append_pr` via three optional kwargs (`lens_paths`, `baseline_sha`, `current_sha`) with safe back-compat defaults. A `_changed_files_in_head_commit` helper diffs `HEAD~1..HEAD` after the run commits to populate the top-N list.

The enriched body makes each nightly PR reviewable in under 60 seconds without opening the diff — addressing the six-PR pile-up incident between 2026-05-30 and 2026-06-01 where bare `partial` bodies gave operators no signal about scope.

## Auto-close superseded PRs

After each new nightly PR is opened, `_auto_close_superseded_docs_agent_prs` walks all open `docs-agent/*` PRs and closes any whose commits are exclusively bot-authored (PR #113). The closer posts a standardised comment referencing the superseding PR number before closing.

Human-edited PRs are intentionally spared. If any commit in the PR's history has a non-bot author, the PR is skipped.

Three `GhClient` methods back this feature:

| Method | Purpose |
|---|---|
| `pr_list_docs_agent_open` | Lists all open PRs whose branch matches `docs-agent/*`. |
| `pr_view_commits` | Fetches the commit author list for a given PR number. |
| `pr_close` | Closes the PR and posts the superseded comment. |

Failures at every stage — list, per-PR lookup, per-PR close — are captured as `info_only` partial reasons. A hygiene failure does not flip the nightly run to `partial`.

## Site generators

The orchestrator calls `run_site_generators()` after the authoring and commit stages (PR #118). This method invokes the CCE-23 generators — `generate_archive` and `generate_contracts` — in sequence with best-effort error handling: if a generator raises, the orchestrator records an `info_only` partial reason and continues. A failing generator does not block the nightly PR.

For hosts without a `site:` block in their config, the orchestrator falls back to the legacy `archive_indexes.regenerate()` path. Detection drives the path taken; the fallback never errors.

The `site:` block is now persisted into every host config by `preflight_host._proposed_site()` at setup time (PR #118), so fresh host repos get the generators wired automatically rather than requiring a manual config edit.

### Why generators were silently no-op-ing

Two independent disconnections caused the docs site at `theoju.github.io/engineering-docs-agent` to render empty despite generators passing unit tests:

1. The live `.engineering-docs-agent/config.yml` had no `site:` block. Every generator hit `if not config.get('site'): return` and exited immediately.
2. The orchestrator only invoked the orphaned legacy `archive_indexes.regenerate()` path, gated on an unset lens flag. `generate_archive` and `generate_contracts` were never called.

PR #118 fixes both. The Decision Archive (specs/plans/measurements — 48/52/7 entries) now populates on every nightly run.

A latent `_strip_inline_links` bug in `archive_indexes.py` was also fixed in the same PR: relative markdown links were leaking into archive table cells under `mkdocs build --strict`.

## PR lifecycle and branch naming

Every docs-agent PR branches off `main` as `docs-agent/YYYY-MM-DDTHH`. The orchestrator never append-commits to a prior branch — each run opens a fresh branch and PR. `state.json.last_successful_run` advances only when the PR merges to `main`; an unmerged PR means the next nightly opens a competing snapshot of the same stale baseline.

The nightly cron is paused to `workflow_dispatch`-only until CCE-89's D3 (merge-gate decision) lands. D1 (PR-body enrichment, PR #112) and D2 (auto-close-stale, PR #113) are shipped. Follow-on phases are tracked in CCE-105, CCE-106, and CCE-107.
