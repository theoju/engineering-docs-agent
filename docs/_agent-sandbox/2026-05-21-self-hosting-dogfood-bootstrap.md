---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/7
synthesized_into: []
---

# Self-hosting dogfood bootstrap

PR #7 wires the engineering-docs-agent against its own repository. The repo is now a live reference host — the same configuration layout any new host would follow.

## What was added

Three artifacts establish the dogfood setup:

- `.engineering-docs-agent/config.yml` — host config declaring the framework, `agent_editable_paths`, voice samples, and publishing target.
- `.engineering-docs-agent/state.example.json` — seed template. Copy to `state.json` on first setup; the runtime file is gitignored so per-run mutations stay local.
- `docs/_agent-sandbox/` — the only directory the agent may write to. The `agent_editable_paths` glob is set to `docs/_agent-sandbox/**`, giving a narrow blast radius during early validation.

## Bootstrapping a fresh checkout

```bash
cp .engineering-docs-agent/state.example.json .engineering-docs-agent/state.json
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

The seeded `last_successful_run.head_sha` points to the v0.1.0 tag commit. That gives the source-collector a real diff window — it will see PRs and commits from CCE-1 through CCE-9, enough history to exercise the full pipeline without pulling an empty range.

For per-subagent raw-stdout diagnostics, set `DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug` before invoking the runner.

## Dry-run constraint

The `--no-pr` flag is intentional. Publish-verification in the orchestrator checks a `deploy.yml` GitHub Actions workflow that is not yet committed. Running without `--no-pr` would reach the publish-verification stage and fail.

A follow-up ticket tracks adding `deploy.yml` and removing the flag. Until that workflow exists and is wired, treat every bootstrap run as a dry run — it validates subagent dispatch, state mutation, and page authoring without opening a real PR.

## Why self-hosting matters

Running the agent against its own repository catches integration gaps that unit tests cannot surface. Each subagent runs against a real Git history and a real config file, so contract mismatches, path escapes, and partial-run handling all show up before the plugin is deployed against production hosts.

The README's 'Self-hosting (dogfood)' section is the canonical human-readable record of this pattern. This page summarises the config decisions and the dry-run constraint for the docs pipeline itself.
