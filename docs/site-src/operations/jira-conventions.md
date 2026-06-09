---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/77
synthesized_into: []
---

# Jira Conventions

All Jira work for this project lives in the **Claude-Code-Extensions** project at `https://designitright.atlassian.net`. The key prefix is `CCE`.

## Branch naming

Format every branch as `<type>/CCE-<number>-<short-slug>`.

```
feat/CCE-12-jira-input-wiring
fix/CCE-7-empty-path-guard
```

The type segment follows conventional-commit vocabulary (`feat`, `fix`, `chore`, `refactor`, `docs`, etc.). The slug is lowercase, hyphen-separated, and short enough to scan in `git branch` output.

## Commit messages

Include `CCE-<number>` in the subject line or a trailer when the commit implements a specific ticket:

```
feat(CCE-42): wire Jira input to orchestrator
```

Hardening or refactor commits that close multiple tickets may list them in the body instead of the subject. The subject should still describe the change; the ticket references are navigational aids, not substitutes for a clear message.

## PR titles

Prefix or include `CCE-<number>` in the PR title so the Atlassian GitHub integration auto-links the issue:

```
CCE-42 Wire Jira input to orchestrator runner
```

The PR **title** is the single source of truth for automated Jira transitions. `extract_keys` in `scripts/jira_transition_on_merge.py` pulls `CCE-\d+` keys from the title only — body, branch, and commit mentions are deliberately ignored, so a PR body that cross-references other tickets does not accidentally close them.

## Automatic issue transition on merge

When a PR that includes a CCE key in its title merges to `main`, `.github/workflows/jira-transition.yml` calls `scripts/jira_transition_on_merge.py` to transition the matching issue(s) to **Done**.

The workflow:

1. Posts a "Closed by PR #N" comment on the issue using Jira REST v2 (accepts a plain string body; v3 requires ADF).
2. Transitions the issue to Done via Jira REST v3.
3. If the transition fails, the comment remains as a visible triage signal on the still-open ticket.
4. The workflow exits non-zero on failure — the PR is already merged, so a noisy failure cannot block delivery, but it does produce a red check and an email.

The helper is stdlib-only (`urllib`). Test the read path without any writes via `workflow_dispatch` with `dry_run` set to `true` (the default).

This workflow is **repo-local only** and is not scaffolded onto host repos. Plugin promotion to host repos is deferred; `JIRA_BASE_URL` would move to config at that point.

## `/ship` skill integration

The `/ship` skill's Jira stage runs `extract-jira-key.sh`, which pulls the CCE key from the branch name or the first commit subject. Keep the branch and commit formats above so the key lands automatically — a misformatted branch name produces a silent failure in that stage, not an error.
