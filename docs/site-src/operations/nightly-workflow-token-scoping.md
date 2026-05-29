---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/66
synthesized_into: []
---

# Nightly workflow token scoping

The nightly docs-PR workflow (`.github/workflows/docs-agent-nightly.yml`) uses two tokens with different scoping constraints. Get this wrong and the workflow returns HTTP 422 when triggered via the API — with no error visible in the YAML parser.

## The rule

GitHub Actions resolves `job`-level `env:` blocks before any step runs. That means any expression referencing `steps.<id>.outputs.*` in a job-env block is invalid — the step hasn't executed yet, so the output doesn't exist at evaluation time. GitHub's runtime validator rejects the reference and returns HTTP 422 on `gh workflow run`.

`secrets.*` expressions are valid at job-env scope because secrets are loaded at workflow startup, not after a step completes.

## Token placement in `docs-agent-nightly.yml`

| Token | Source | Valid scope |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | `secrets.CLAUDE_CODE_OAUTH_TOKEN` | job-level `env:` |
| `GH_TOKEN` | `steps.app-token.outputs.token` | step-level `env:` only |

`GH_TOKEN` is set by the `actions/create-github-app-token` step. Because it comes from `steps.app-token.outputs.token`, it must live in the `env:` block of the step that consumes it — the **"Run nightly authoring"** step — not in the job-level `env:` block.

## What you do not need `GH_TOKEN` for

The `git push` step does not need `GH_TOKEN`. Credentials for push are supplied by `actions/checkout`'s `token:` input, which configures the local Git credential helper automatically. Passing `GH_TOKEN` to that step is redundant and not required.

## Detecting this failure

The YAML parses without errors. The failure surfaces only at runtime as an HTTP 422 from the GitHub API when the workflow is dispatched. If `gh workflow run docs-agent-nightly.yml` returns 422 and the YAML looks syntactically correct, check for `steps.*` references in job-level `env:` blocks first.

The scheduled 07:07 UTC cron fires silently in this state — it does not retry and does not report the 422 in workflow run history. An undetected regression here means the nightly docs PR stops being created with no visible alert.

## Summary

- Keep `GH_TOKEN` (app token) in the `env:` block of the step that uses it, not at job level.
- Keep `CLAUDE_CODE_OAUTH_TOKEN` at job level; `secrets.*` is valid there.
- The `git push` step gets its credentials from `actions/checkout` — no extra token needed.
