---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/62
synthesized_into: []
---

# Setting up the auth token

The engineering-docs-agent authenticates to the Claude CLI via a single GitHub secret: `CLAUDE_CODE_OAUTH_TOKEN`. This replaced `ANTHROPIC_API_KEY` when the OAuth-based dispatch path became the only supported path (CCE-35). Using `ANTHROPIC_API_KEY` silently fails — the CLI ignores that slot and no error surfaces in the run log.

## Get the token

Run `claude setup-token` in any terminal where the Claude CLI is authenticated. The command prints an OAuth token that starts with `sk-ant-oat…`. Copy the full value.

## Add the secret to your repo

1. Go to **Settings → Secrets and variables → Actions** in your GitHub repository.
2. Create a new secret named exactly `CLAUDE_CODE_OAUTH_TOKEN`.
3. Paste the token value from the step above.

The nightly workflow (`.github/workflows/docs-agent-nightly.yml`) reads this secret as `${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}` and injects it into the `claude` CLI subprocess environment.

## Verify it works

After adding the secret, trigger a manual run:

```bash
gh workflow run docs-agent-nightly.yml -f reason="auth smoke test"
gh run watch
```

A successful run prints a step summary. If authentication is broken, the orchestrator logs `dispatch failed` and the run exits non-zero — check the step summary and the `stream.jsonl` artifact attached by the forensics stage (CCE-41).

## Common mistakes

**Using `ANTHROPIC_API_KEY` instead of `CLAUDE_CODE_OAUTH_TOKEN`.** The CLI reads the OAuth slot. Setting `ANTHROPIC_API_KEY` has no effect and produces no warning, so the failure is silent until you examine the dispatch output.

**Token rotation.** If you rotate the token via `claude setup-token`, update the GitHub secret immediately. The runner holds no fallback; a stale token causes every dispatch call to fail.

**Scope mismatch.** The token must belong to the account that has Claude Code access. Tokens issued for a team seat without the required model entitlement will authenticate but fail when the CLI tries to invoke the model.
