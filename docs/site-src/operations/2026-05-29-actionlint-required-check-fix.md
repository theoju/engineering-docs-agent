---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/76
synthesized_into: []
---

# actionlint Required-Check Fix

**PR #76 · CCE-52 / CCE-55 · 2026-05-29**

## What changed

The `paths:` filter on the `pull_request` trigger in `.github/workflows/actionlint.yml` was removed. Previously, actionlint only ran when a PR touched files under `.github/workflows/`. Now it runs on every PR, unconditionally.

The `push: paths:` filter is kept. Post-merge runs on `main` still fire only when workflow files change — there's no need to lint workflows on every push to `main` that didn't touch them.

## Why the asymmetry exists

GitHub's required-checks gate treats a *skipped* check and a *not-yet-run* check identically: both block merge. When branch protection was updated to require the `actionlint` status check (CCE-52), any PR that didn't touch workflow files would have actionlint correctly skip — but GitHub would see a missing green check and refuse to merge.

PR #75 (CCE-55) reproduced this exactly: a non-workflow change was blocked by a required check that was never scheduled to run.

## Effect on PRs

Every PR now gets a short actionlint run (~5 s). The check always completes, always produces a pass or fail status, and always satisfies the required-checks gate. PRs that don't touch workflow files pay the 5-second cost; in return, they are never blocked by a phantom missing check.

## If you see actionlint fail on a PR

A failure means a workflow file in the repo has a syntax or logic error detectable by actionlint. Fix the workflow file — the linter's output will point at the specific line. Do not re-add a `paths:` filter to the `pull_request` trigger as a workaround; that reintroduces the blocking behaviour this fix resolved.
