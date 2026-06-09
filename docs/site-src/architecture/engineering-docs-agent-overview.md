---
description: "The engineering-docs-agent is a Claude Code plugin that watches a host repo's merged PRs, commits, and Jira issues and opens a nightly docs-update PR."
source_files:
  - scripts/orchestrator_runner.py
  - agents/source-collector.md
  - agents/pr-summarizer.md
  - agents/gap-detector.md
  - agents/page-author.md
  - scripts/lint/lint_runner.py
last_reviewed: '2026-06-09'
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/121
synthesized_into: []
---

# Engineering Docs Agent — System Overview

The engineering-docs-agent is a Claude Code plugin that watches a host repo's merged PRs, commits, and Jira issues and opens a nightly docs-update PR. Seven specialized subagents divide the work: source collection, PR summarization, gap detection, page authoring, linting, notification, and publish verification. Each subagent has a canonical input/output contract defined in `agents/` and a JSON schema in `agents/schemas/`.

The agent runs against **any** host repo. Behavior is driven by config detection (`setup_discover.py`) and the `site:` block in `.engineering-docs-agent/config.yml`, not by hardcoded paths. When a host lacks a convention — no OpenAPI schema, no Jira project, no specs directory — the affected capability skips or degrades cleanly rather than erroring.

## Pipeline stages

The nightly run is orchestrated by `scripts/orchestrator_runner.py`. Stages execute in order; a failure in any stage records a `partial_reason` and continues where possible so the PR always opens.

| Stage | Subagent / script | Key output |
|---|---|---|
| Source collection | `agents/source-collector.md` | `SourceCollectorOutput` (PRs, Jira issues, commits) |
| PR summarization | `agents/pr-summarizer.md` | Per-PR `PrSummary` with `what_changed`, `why`, `doc_targets` |
| Gap detection | `agents/gap-detector.md` | Gap flags for PRs with no spec/plan coverage |
| Page authoring | `agents/page-author.md` | Written/updated Markdown files |
| Linting | `scripts/lint/lint_runner.py` | Tier-1 block results + optional Tier-2/3 |
| Notification | `agents/notifier.md` | Slack + email digest |
| Publish verification | `agents/publish-verifier.md` | Post-merge live URL check |

A partial run still opens a PR. The body starts with a `WARNING — Partial run` block listing every `partial_reason` so the gap is visible, not silent.

## Doc routing and `doc_kind`

The pr-summarizer emits an optional `doc_kind` field on each `doc_target`: `architecture` for evergreen reference pages, `decision` for ADRs and design docs. The orchestrator passes this through to the page-author's frontmatter.

For **create** targets, the orchestrator calls `scripts/doc_routing.py:route_create_hint` to redirect decision-kind pages to the host's archive section. The archive section is discovered via a generator marker (`<!-- docs-agent:archive-index -->`) embedded in the section's index page — never a hardcoded directory name. If the marker is absent (bare host), the target path is used as-is, degrading gracefully.

Edit targets are never relocated. The routing logic applies only to new pages.

This separation keeps decision documents (historical context, rationale) out of the architecture reference section (current-state facts). Users find the freshest reference content in `architecture/` and historical decisions in `archive/`.

## Section overview ordering

Directory-level landing pages (e.g., `architecture/index.md`) list child pages sorted by freshness. The sort is a two-pass stable sort implemented in `section_overview._scan_children`:

1. Pages with a `last_reviewed` frontmatter date sort newest-first.
2. Pages with no date fall to the end, sorted by title.

This replaced the prior filename/title ordering that buried recently-reviewed content behind older pages with alphabetically earlier filenames.

## State and resumption

The orchestrator reads `.engineering-docs-agent/state.json` to determine the window of PRs to process (everything merged since `last_successful_run.head_sha`). State advances only when a docs-agent PR merges to `main` — a partial run or an unmerged PR does not advance the pointer. The next nightly re-processes the same window until a PR merges.

The ephemeral run state lives in `.engineering-docs-agent/current_run.json` (gitignored). It is written on every state update for diagnostics and test observability.

## Agent-editable paths

The orchestrator enforces a write fence. Only paths covered by `docs.agent_editable_paths` globs in config may be written. The page-author subagent receives this list and refuses writes outside it. Every `docs.lens_paths` entry must be covered by at least one editable glob — validated at load by `_validate_lens_paths_are_editable` in `scripts/state_io.py`.

## Frontmatter contract

Agent-authored pages carry a machine-verifiable frontmatter block. The required keys depend on the authoring path:

- **Default path**: `status`, `sources`, `synthesized_into`
- **Agent-authored core pages (Capability C2)**: `description`, `source_files`, `last_reviewed`, `status`

The lint runner checks these at Tier 1 (block) — a page with missing required frontmatter cannot reach the published site.

## Subagent dispatch

The orchestrator dispatches each subagent via `scripts/dispatch_subagent.py`. Responses are strict-JSON parsed against the subagent's schema before the orchestrator acts on them. A schema-invalid response records a `partial_reason` and skips that subagent's contribution for the run; it never crashes the pipeline.

For diagnostics, set `DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug` before invoking the orchestrator. Each dispatch writes a `<ts>-<name>.stdout.txt` file showing the raw subagent output.

## Related pages

- `architecture/doc-routing.md` — `route_create_hint` interface, marker-discovery mechanism, and bare-host degradation contract
- `setup-guide.md` — end-to-end host onboarding
