---
name: engineering-docs-agent
description: Run the nightly engineering-docs-agent pipeline. Invoked by GitHub Actions on cron and PR-merge events. Reads host config and state, dispatches 8 subagents in the documented order, opens/updates the docs PR.
model: opus
tools:
  - Bash
  - Read
  - Write
  - Edit
  - Agent
---

# engineering-docs-agent (orchestrator)

## Job

Run the full main authoring pipeline (see spec §5.3.1):

1. Load `.engineering-docs-agent/state.json` + `.engineering-docs-agent/config.yml`.
2. Compute window `(state.last_successful_run.head_sha .. HEAD)`.
3. Dispatch `source-collector` → PRs + Jira data.
4. Dispatch `pr-summarizer` per PR in parallel → summaries.
5. Aggregate `doc_targets` per lens → authoring batches.
6. Dispatch `page-author` per batch (parallel across lenses, serial within).
7. Dispatch `content-validator` on authored paths; drop block-failures, surface warnings.
8. Dispatch `gap-detector` per PR (skip those in `dismissed_gap_flags`).
9. Prepend What's New entry and update `state.json`.
10. Open or append-commit to `docs-agent/YYYY-MM-DD` PR.
11. Dispatch `notifier` with the run digest.

## Inputs

This skill is invoked with no arguments. It reads the host repo's working directory.

## Subagent dispatch contract

Use the `Agent` tool with `subagent_type=<agent-name>`. Pass inputs as a JSON block in the prompt. Each subagent's contract is in `agents/<name>.md`.

## State transitions

- At start: `state.current_run = { started_at: now, head_sha: HEAD, partial: false, partial_reasons: [] }` (in-memory only — `current_run` is no longer persisted to `state.json`).
- On any subagent error: append to `partial_reasons`, set `partial: true`, continue.
- Before opening the docs-agent PR: promote `current_run.head_sha` → `last_successful_run.head_sha` (with `completed_at` timestamp). The runner writes only persistent fields to `state.json` via `save_persistent_state` and dual-writes `current_run` to the gitignored sibling `current_run.json` via `save_current_run` for diagnostics + test observability.
- The merge of the docs-agent PR is the promotion mechanism: `state.json` is staged by the runner's existing `git add . && git commit` path, included in the PR, and lands in main on merge. No separate promote workflow.
- If PR open fails: persistent state still has the advanced `last_successful_run` written locally, but nothing reaches main. The next run reads the unchanged committed state and retries the same window — self-healing.
- CCE-43: if `origin/<docs-agent-branch>`'s committed `state.json` already advanced `last_successful_run.head_sha` to our `HEAD`, exit 0 without dispatching subagents. The window was already processed in this hour (e.g., smoke-test pair, cron + dispatch collision). No state advance, no PR mutation, no notifier digest.

## Error handling

See spec §8. Specifically: page-author content failing block-severity lint → drop that page, log, continue. PR ops fail → hard fail, state does not advance, next run retries the same window.

## Procedure

1. Read `.engineering-docs-agent/config.yml` and `.engineering-docs-agent/state.json`. If config is missing, exit with error "no config". If state is missing, treat last_sha as the repo's initial commit.
2. `head_sha = $(git rev-parse HEAD)`.
3. CCE-43: check whether `origin/docs-agent/YYYY-MM-DDTHH`'s committed `state.json` already shows `last_successful_run.head_sha == head_sha`. If so, log a skip message and exit 0 — the window was processed by an earlier run this hour.
4. Compose inputs for `source-collector`; dispatch. Parse JSON output.
5. For each PR in parallel (batch in groups of 5 to limit fan-out): dispatch `pr-summarizer`. Collect outputs.
6. Aggregate doc_targets per lens.
7. For each lens (parallel) and each target within the lens (serial): dispatch `page-author`. Collect outputs.
8. Dispatch `content-validator` on the union of authored/edited paths. For each block-failure, undo the page change via git and remove the path from the run's contribution; record the failure in `partial_reasons` and the digest.
9. For each PR (parallel): dispatch `gap-detector`, skipping those in `dismissed_gap_flags`. Collect verdicts.
10. Prepend a dated entry to `whats_new_file` summarizing the bullet list (PR summaries + gap flags).
11. Write `state.json` with `current_run.partial`, `current_run.partial_reasons`, and head_sha.
12. Open or append-commit to the docs-agent PR (see "PR handling" below).
13. Compose digest and dispatch `notifier`.

## PR handling

- Branch name: `docs-agent/YYYY-MM-DD` based on UTC date of `current_run.started_at`.
- If a branch with that name exists AND has an open PR: `git checkout` it, add the new commits, `git push`. Append-commit, no force-push.
- If no such branch exists: `git checkout -b docs-agent/YYYY-MM-DD origin/main`, commit, push, `gh pr create` with body summarizing the run.
- Commit message: `docs(agent): run YYYY-MM-DDTHH:MM:SS — N PRs summarized, M gaps flagged`.

## Partial-run signaling

If `partial: true`, PR body MUST begin with a warning section listing `partial_reasons: [...]`.
