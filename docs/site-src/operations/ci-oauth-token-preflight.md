---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/73
synthesized_into: []
---

# CI OAuth Token Pre-flight

Both `release.yml` and `docs-agent-nightly.yml` run a multi-layer validation of `CLAUDE_CODE_OAUTH_TOKEN` before dispatching any Claude CLI work. This page documents the expected token shape, each validation layer, and what the failure output means so you can diagnose CI problems without reading the workflow YAML.

## Expected token shape

`CLAUDE_CODE_OAUTH_TOKEN` must be a Claude OAuth token — **not** a console API key. OAuth tokens are obtained via `claude setup-token` on a machine with an authenticated Claude Code session. They start with `sk-ant-oat` and are at least 32 characters long.

Console API keys — the kind you create at `console.anthropic.com` — start with `sk-ant-api`. They cannot authenticate the Claude CLI's OAuth slot and will be rejected by the pre-flight check.

## The four validation layers

The pre-flight runs four checks in order. A failure at any layer causes the workflow step to exit non-zero and print a diagnostic message; subsequent layers do not run.

### Layer 1 — empty or missing secret

The check fails if `CLAUDE_CODE_OAUTH_TOKEN` is an empty string or the secret is not set in the repository.

**What you see:** `Error: CLAUDE_CODE_OAUTH_TOKEN is not set or is empty.`

**What to do:** Add or restore the secret under **Settings → Secrets and variables → Actions** for the repository. Retrieve a fresh token with `claude setup-token` on an authenticated machine.

### Layer 2 — console API key rejection

The token value is tested against the prefix `sk-ant-api`. If it matches, the workflow rejects it immediately.

**What you see:** `Error: CLAUDE_CODE_OAUTH_TOKEN looks like a console API key (sk-ant-api*). The Claude CLI OAuth slot requires an OAuth token, not an API key.`

**What to do:** Delete the secret and replace it with the OAuth token from `claude setup-token`. The two token types are not interchangeable. `ANTHROPIC_API_KEY` is the correct home for a console API key if other tooling needs it.

### Layer 3 — unrecognised token shape diagnostic

If the token is non-empty, not an `sk-ant-api*` key, but also does not match the `sk-ant-oat` OAuth prefix, the check prints the first 10 characters for identification.

**What you see:** `Warning: CLAUDE_CODE_OAUTH_TOKEN has an unrecognised shape. First 10 chars: <prefix>. Expected an OAuth token beginning with sk-ant-oat.`

**What to do:** Verify you copied the full token from `claude setup-token` output. Partial copies, extra whitespace, or a rotated token that uses a future prefix format will land here. If the prefix is clearly wrong, replace the secret; if it looks plausibly correct, check whether the Claude CLI version in the workflow matches the version that generated the token.

### Layer 4 — minimum length floor

The token must be at least 32 characters. Shorter values indicate a truncated paste or a secret value that was set incorrectly.

**What you see:** `Error: CLAUDE_CODE_OAUTH_TOKEN is too short (N chars). Expected at least 32 characters.`

**What to do:** Re-run `claude setup-token`, copy the entire output line, and update the secret. Truncation typically happens when the secret is set via a script that trims trailing characters or hits a form field limit.

## What this validation does not cover

The pre-flight does not detect **expired** OAuth tokens. An expired token passes all four checks and fails only when the Claude CLI attempts to use it. If your workflow succeeds pre-flight but fails during a `claude` invocation with an authentication error, run `claude setup-token` to refresh the token and update the secret.

## Affected workflow files

Both workflows share the same pre-flight logic:

- `.github/workflows/release.yml` — runs on tag pushes; executes live integration tests via `pytest -m live`.
- `.github/workflows/docs-agent-nightly.yml` — runs daily at 07:00 UTC; drives the nightly docs-PR authoring pipeline.

Any change to the pre-flight validation must be applied to both files consistently.

## Source

This page reflects changes introduced in [PR #73](https://github.com/theoju/engineering-docs-agent/pull/73), which replaced the single non-empty check with the four-layer validation described above (CCE-49).
