---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/117
synthesized_into: []
doc_kind: architecture
---

# Jira Auto-Transition on Merge

When a CCE pull request merges to `main`, the repo automatically transitions its linked Jira issue(s) to **Done**. No manual triage step is needed.

## How it works

The GitHub Actions workflow `.github/workflows/jira-transition.yml` fires on every push to `main`. It invokes `scripts/jira_transition_on_merge.py` with the merged PR's number, title, and base branch.

The helper does three things in order:

1. **Extracts CCE keys** from the PR title using `extract_keys` — a regex match for `CCE-\d+`. Keys in the PR body, branch name, or commit messages are deliberately ignored.
2. **Posts a comment** on each matched Jira issue ("Closed by PR #N").
3. **Transitions the issue to Done** via the Jira REST API.

Comment-before-transition ordering is intentional: if the transition call fails, the comment is already visible on the ticket. The next triage pass sees "Closed by PR #N" on a still-open issue and can complete the transition manually.

## Why PR title only

Extracting keys from body, branch, or commits would silently close tickets that are merely *referenced* — not implemented — by a PR. A PR body that mentions CCE-45 as background context would close that ticket even though the work is unfinished.

The PR title is the narrowest, most intentional signal. Enforce it: put exactly the CCE keys you want closed in the title, nothing else.

## Retry and backoff

The helper retries transient HTTP failures with exponential backoff. `urllib` is the only HTTP dependency — no third-party packages. Timeout errors (`socket.timeout`, `urllib.error.URLError` wrapping `TimeoutError`) are caught alongside `HTTPError` so a slow Jira API does not produce an uncaught exception.

## REST API split

The implementation uses two Jira REST API versions:

- **Reads** (issue lookup, transition ID fetch): Jira REST **v3** (`/rest/api/3/...`).
- **Comment POST**: Jira REST **v2** (`/rest/api/2/issue/{key}/comment`). The v2 comment endpoint accepts a plain string body; v3 requires Atlassian Document Format (ADF), which adds serialization complexity for no functional gain here.

If you extend this helper, keep the version split in mind — a v3 comment POST will reject a plain string payload.

## Failure mode

The workflow exits non-zero on any unrecovered error. GitHub surfaces this as a red check on the merge commit and sends an email notification.

The PR is already merged when the workflow runs, so a loud failure cannot block delivery. It surfaces the problem without hiding it.

## Dry-run procedure

The workflow supports a `workflow_dispatch` trigger with a `dry_run` input (default: `true`). A dry-run exercises the full read path — it fetches the PR title, extracts keys, and resolves Jira issue metadata — but writes nothing: no comment is posted and no transition is called.

To run a dry-run manually:

```bash
gh workflow run jira-transition.yml \
  -f pr_number=<PR number> \
  -f dry_run=true
gh run watch
```

To trigger a live run against a specific PR (for testing the write path after secrets are set):

```bash
gh workflow run jira-transition.yml \
  -f pr_number=<PR number> \
  -f dry_run=false
```

## Required secrets and variables

The workflow requires two repo-level configuration values:

| Name | Type | Value |
|---|---|---|
| `JIRA_API_TOKEN` | Secret | An Atlassian API token scoped to the Jira project |
| `JIRA_EMAIL` | Variable | The email address associated with the API token |

The Jira base URL is hardcoded to `https://designitright.atlassian.net` in the current implementation. If you promote this to a host-repo scaffold, move the URL to `.engineering-docs-agent/config.yml`.

The live Jira API was not exercised before the first production merge after PR #117 landed. The first real run will validate the secret/variable wiring end-to-end.

## Scope

This automation is **repo-local** — it runs only in `engineering-docs-agent` and is not scaffolded onto host repos by the setup skill. Plugin promotion is deferred until there is explicit demand. If you add it to a host repo manually, `JIRA_BASE_URL` and the project key pattern (`CCE-\d+`) would need to move to config.
