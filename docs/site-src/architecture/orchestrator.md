---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/50
synthesized_into: []
---

# Orchestrator

The orchestrator (`scripts/orchestrator_runner.py`) is the top-level coordinator for every nightly docs-update run. It sequences the seven subagents — source-collector, PR-summarizer, gap-detector, page-author, notifier, publish-verifier, and linter — and writes run state to `.engineering-docs-agent/` so each stage can be replayed independently.

## Bootstrap stage (C2)

The bootstrap stage (Capability C2) seeds the docs site on first run by calling `page-author` for every page stub identified by the gap-detector. Starting with PR #50, the bootstrap loop fails fast on three previously silent failure modes rather than accepting corrupt output.

### dispatch_verified

`dispatch_verified` (`scripts/orchestrator_runner.py`) wraps `dispatch_validated` with a post-write artifact check. After `page-author` returns `ok: true`, `dispatch_verified` reads the written file, parses its frontmatter, and verifies the artifact actually landed on disk with valid YAML and non-empty frontmatter fields. If the check fails, the bootstrap loop raises immediately rather than advancing the progress cursor.

Before this change, a `page-author` agent that wrote malformed YAML and still returned `ok: true` would pass the bootstrap loop silently. `dispatch_verified` closes that gap.

### _BootstrapProgress

`_BootstrapProgress` (`scripts/contracts.py`) is a dataclass that records per-page bootstrap state atomically. After each page completes (pass or fail), the orchestrator serializes the full progress record to `.engineering-docs-agent/bootstrap.progress.json` via a temp-file-plus-`os.replace` pattern. This guarantees the progress file is never left in a partially-written state, even if the process is interrupted mid-loop.

The progress file is the authoritative source for resuming a partial bootstrap run. If the orchestrator restarts, it reads the file and skips pages already marked `done`.

### parse_frontmatter_strict

`parse_frontmatter_strict` (`scripts/archive_indexes.py`) raises `yaml.YAMLError` for a YAML parse failure and `ValueError` for absent frontmatter. The two exception types are now distinct so callers can handle corrupt YAML separately from pages that simply have no frontmatter block. The bootstrap loop catches `yaml.YAMLError` as a hard failure; `ValueError` (no frontmatter) is treated as a fixable gap.

## Lint integration at bootstrap

The orchestrator runs the Tier-1 lint suite against each page immediately after `dispatch_verified` confirms the artifact is on disk. A page that fails any Tier-1 rule causes the bootstrap loop to record a failure for that page and continue — the run is marked `partial: true` with the offending pages listed in `partial_reasons`.

The `description_quality` rule is the eighth Tier-1 default (registered alongside the original seven). It rejects pages whose frontmatter `description` field is absent or below the minimum character threshold. See `docs/site-src/operations/lint-rules.md` for the threshold value and per-page suppression mechanism.

## State files

| File | Purpose |
|------|---------|
| `.engineering-docs-agent/state.json` | Committed run state; `last_successful_run.head_sha` drives the next nightly window. |
| `.engineering-docs-agent/current_run.json` | Gitignored ephemeral run state; written every state-update for diagnostics. |
| `.engineering-docs-agent/bootstrap.progress.json` | Per-page bootstrap progress; written atomically after each page; used for resume. |

The `bootstrap.progress.json` file is gitignored. It is local to the runner and not included in the docs-agent PR.

## Error handling summary

The bootstrap loop distinguishes four outcomes per page:

1. **Pass** — `dispatch_verified` succeeds and all Tier-1 lint rules pass. Page is marked `done`.
2. **Artifact failure** — `dispatch_verified` raises (bad YAML, missing frontmatter, file not written). Page is marked `failed`; run continues.
3. **Lint failure** — Tier-1 rule fires. Page is marked `lint_failed`; run continues.
4. **Agent error** — `page-author` returns `ok: false`. Page is marked `failed`; run continues.

A run that exits with any `failed` or `lint_failed` pages sets `partial: true` in `state.json` and surfaces the list in Slack/email notifications.
