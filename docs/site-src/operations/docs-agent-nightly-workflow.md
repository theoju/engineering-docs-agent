---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/96
synthesized_into: []
---

# Nightly Workflow Operations

The nightly authoring pipeline runs via `.github/workflows/docs-agent-nightly.yml`. It fires daily at 07:07 UTC on a cron schedule and accepts manual `workflow_dispatch` triggers.

## Triggering a manual run

Use `gh workflow run` to fire the workflow without waiting for the schedule:

```bash
gh workflow run docs-agent-nightly.yml -f reason="your reason here" -f claude_model="claude-opus-4-5"
gh run watch
```

The `reason` input is free-text; it appears in the run summary alongside the post-run `state.json` snapshot.

The `claude_model` input is optional. Leave it empty to use the runner's default model. Supply a model string (e.g. `claude-opus-4-5`) to override it for that dispatch without touching the YAML.

## Model override

The `claude_model` workflow_dispatch input lets you pin a specific model at dispatch time. The workflow writes the value into the `CLAUDE_MODEL` environment variable before invoking `orchestrator_runner.py`. The runner reads `CLAUDE_MODEL` and appends `--model <value>` to every Claude CLI invocation when it is non-empty.

The default (empty string) leaves the CLI to choose the model from its own defaults. You do not need to set `claude_model` for routine runs.

## Authentication: OAuth token, not API key

The runner authenticates to the Claude CLI exclusively via `CLAUDE_CODE_OAUTH_TOKEN`. The workflow does **not** pass `ANTHROPIC_API_KEY` explicitly — the Claude CLI reads native OAuth credentials from the runner environment without an explicit env block.

Passing `ANTHROPIC_API_KEY` separately was dead weight left over from before the OAuth plumbing landed. Removing it (PR #96, Phase 4 of CCE-66) reduces the key's blast radius: the console API key slot is no longer reachable from the workflow context at all.

If the OAuth token is missing, wrong type, or truncated, the `Assert OAuth token is configured and well-formed` step prints an actionable error before the runner dispatches a single subagent. The three checks are:

1. Non-empty — catches a missing or mis-named repo secret.
2. `sk-ant-oat` prefix — catches a console API key (`sk-ant-api`) pasted into the wrong slot.
3. Length floor (≥ 32 chars) — catches truncation from copy-paste.

## Concurrency

The `docs-agent-nightly` concurrency group serializes all runs — manual and scheduled alike. When a second trigger fires while a run is in progress, it queues rather than cancels. This prevents two runs from racing on the same `docs-agent/YYYY-MM-DD` branch.

## Diagnostics and forensics

Set `DOCS_AGENT_DEBUG_DIR` before invoking the runner locally to capture per-dispatch prompt, stdout, stderr, and stream artifacts:

```bash
DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug python3 scripts/orchestrator_runner.py --repo-root .
```

In CI, the workflow captures these artifacts automatically under `runner.temp/docs-agent-debug/` and uploads them as `docs-agent-subagent-forensics-<run_id>-<attempt>` (14-day retention). The upload step runs on `always()` so forensics persist even when the authoring step fails.

## Partial runs

A partial run opens the docs-agent PR anyway with `partial: true` in the PR body. The workflow step itself exits 0 so the nightly schedule is not suppressed by a failure status. Check the PR body's `partial_reasons` list to identify which capability degraded and why.

## State advancement

`state.json.last_successful_run` advances only when an operator merges the docs-agent PR to `main`. The workflow never auto-merges. If you let a PR sit unmerged past the next 07:07 UTC fire, the next nightly opens a fresh `docs-agent/YYYY-MM-DDTHH` branch from the same stale baseline — it does not append to the existing PR. The D2 auto-close-stale policy (CCE-89) closes the older open docs-agent PR so only the freshest snapshot stays open.
