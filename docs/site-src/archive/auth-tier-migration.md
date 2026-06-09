---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/91
synthesized_into: []
doc_kind: decision
---

# Auth-tier migration: drop explicit API key threading

**PR #91 · merged 2026-06-09 · non-breaking**

## Decision

The nightly workflow no longer injects `ANTHROPIC_API_KEY` explicitly into the Claude CLI subprocess. The key is picked up automatically by the CLI's native secret-store auth tier from the runner environment.

## What changed

Three touch points were removed:

- `.github/workflows/docs-agent-nightly.yml` — the `env: ANTHROPIC_API_KEY` line under the nightly job step.
- `scripts/orchestrator_runner.py` — the `env=` kwarg passed to `subprocess.run` when dispatching the Claude CLI.
- The corresponding test — updated to assert the `env` kwarg is **absent**, not present.

No user-visible behavior changes. The CLI invocation, output contract, and state transitions are identical.

## Why

Threading the key through workflow env vars and into `subprocess.run` was only necessary before the CLI gained a secret-store auth tier. Once the CLI reads the key from the runner environment directly, the explicit forwarding is redundant and adds two unnecessary places where credential handling can diverge or break.

Removing it shrinks the credential-handling surface area and makes the auth path easier to audit: the key exists in one place (the repo secret / runner env) and the CLI consumes it there.

## Operator impact

If you run `scripts/orchestrator_runner.py` locally, ensure `ANTHROPIC_API_KEY` is set in your shell environment. The subprocess no longer inherits a manually constructed env dict — it inherits the full parent environment, so the key must be present there.

In CI, the `ANTHROPIC_API_KEY` repo secret must still be mapped to the workflow environment (e.g., `env: ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}`). The change removes the forwarding from the workflow step into the subprocess, not the secret-to-env mapping at the workflow level.

## Rollback

Revert PR #91. Re-add the `env=` kwarg to the `subprocess.run` call in `scripts/orchestrator_runner.py` and restore the `env: ANTHROPIC_API_KEY` line in `.github/workflows/docs-agent-nightly.yml`.
