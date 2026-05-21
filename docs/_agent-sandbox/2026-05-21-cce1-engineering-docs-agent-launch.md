---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/1
synthesized_into: []
---

# engineering-docs-agent Launch: v0.1.0 + v0.1.1

**Date:** 2026-05-21  
**Jira:** CCE-1  
**Releases:** v0.1.0 (initial) + v0.1.1 (hardening), merged together

## What shipped

v0.1.0 introduces the complete engineering-docs-agent Claude Code plugin. Seven coordinated subagents — source-collector, pr-summarizer, page-author, content-validator, gap-detector, publish-verifier, and notifier — convert merged PRs, commits, and Jira issues into a nightly docs-update PR with voice-matched authoring, tiered linting, gap detection, and publish verification.

v0.1.1 followed immediately with a structured hardening pass before the first merge to `main`. A code-reviewer sweep surfaced 40 findings across five phases; all are resolved in this PR.

## v0.1.1 hardening highlights

The 40 findings split across these categories:

- **Typed contracts and JSON-schema validation** — `scripts/contracts.py` now exposes dataclasses for every subagent boundary; `agents/schemas/` codifies the shapes the orchestrator enforces at runtime.
- **Jira forwarding** — Jira auth env vars propagate from the orchestrator process into each subagent subprocess without additional plumbing.
- **Path filtering** — the orchestrator pre-filters write targets against `agent_editable_paths` before dispatching page-author, blocking writes outside the sandbox.
- **Archive index support** — the publish-verifier checks archive index pages, not just leaf pages.
- **`pr_id` alignment** — field naming is consistent across all subagent outputs and the orchestrator state file.
- **GhClient and orchestrator error handling** — every GitHub API call and orchestrator stage now surfaces a structured error rather than a bare exception.
- **Regression test backfill** — 160+ tests pass; all production Claude CLI dispatch is monkeypatched in unit tests via the fixture-driven dry-run path.
- **Exit-code normalization** — the orchestrator exits non-zero on any stage failure, making CI integration unambiguous.
- **Multi-summary batching** — page-author accepts a list of pr-summarizer outputs for a single page, not just one.
- **CHANGELOG** — `CHANGELOG.md` records both releases.

## Why this matters

Before this plugin, documentation updates required manual effort after every PR merge. The agent system removes that toil: engineers merge PRs and the orchestrator propagates changes into the doc site nightly without human intervention.

The v0.1.1 hardening ensures the initial production cut is reliable — contract mismatches, schema omissions, and error-handling gaps were all caught and closed before the first real run.

## What remains pending

Two items are not yet wired:

1. **Smoke test against a real host repo** — the bootstrap dry-run (`--no-pr`) works; an end-to-end run producing an actual GitHub PR is tracked separately.
2. **GitHub Actions publish workflow** — `deploy.yml` is not yet committed to the host repo. The `--no-pr` flag keeps the publish-verifier from failing in the interim. Full wiring is a follow-on task.

## Running the agent now

Bootstrap against this repo as the host:

```bash
cp .engineering-docs-agent/state.example.json .engineering-docs-agent/state.json
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

The seed `last_successful_run.head_sha` points to the v0.1.0 tag commit, giving source-collector a real diff window over CCE-1 through CCE-9. Set `DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug` to capture per-subagent raw stdout.
