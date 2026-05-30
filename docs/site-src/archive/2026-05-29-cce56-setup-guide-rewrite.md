---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/77
synthesized_into: []
---

# Archive: CCE-56 Setup Guide Rewrite (PR #77)

**Date:** 2026-05-29
**PR:** [#77](https://github.com/theoju/engineering-docs-agent/pull/77)
**Ticket:** CCE-56

## What changed

PR #77 replaced the 46-line placeholder at `docs/setup-guide.md` with a comprehensive 370-line, 7-part guide.

The old file was a stub. It named the steps but gave no actionable detail — no GitHub App registration instructions, no secrets table, no troubleshooting, no per-language notes. Anyone onboarding a new host repo had to reconstruct the process from tickets, commit history, and the workflow files themselves.

The new guide covers the full operator journey:

- **Prerequisites** — environment sanity-check before you start.
- **Part 1 (one-time)** — Claude OAuth token, GitHub App registration, optional Atlassian API token.
- **Part 2 (per-host)** — plugin install, setup skill invocation, GitHub App installation on the repo, secrets configuration table, branch protection setup.
- **Part 3** — first manual dispatch, what success looks like, what the cron fires.
- **Part 4** — per-language host notes: Python (the dogfood path), JS/TS (CCE-57 open considerations), hybrid CI (CCE-58 path).
- **Part 5** — optional add-ons: actionlint workflow (full YAML copy-paste), Slack, email, Jira enrichment.
- **Part 6** — troubleshooting for every known partial-mode failure: missing App token, `workflow_dispatch` 422, `jira_auth_missing`, `prose_contamination_rescued`, OAuth token type confusion, strict branch protection.
- **Part 7** — copy-paste checklist for fresh host repos.

The README install section was trimmed from a 4-step walkthrough (which duplicated the guide) to a 3-step quickstart with a cross-link.

## Drift fixes (D1–D9 + bonus)

Nine stale-documentation fixes landed in the same PR, bringing the guide into sync with post-CCE-55/CCE-59 `main`:

| Fix | What was corrected |
|-----|--------------------|
| D1  | Removed stale reference to `docs-agent-verify.yml` (that workflow was never committed; post-merge publish verification is tracked separately). |
| D2  | Corrected `prose_contamination_rescued` behavior: it is now a silent fence-strip on pure ` ```json … ``` ` wraps (CCE-55), not an error. The banner only fires for genuinely anomalous contamination. |
| D3  | Updated actionlint coverage: the workflow now runs on every PR with no `paths:` filter (CCE-59 footgun removed), so it blocks merge reliably as a required status check. |
| D4  | Added CCE-59 to the Reference table. |
| D5–D9 + bonus | Terminology, link, and accuracy fixes discovered during the end-to-end authoring review. |

## What this closes

- **CCE-56** — authoritative setup guide for engineering-docs-agent.
- Partial closure of **CCE-45** docs gap (GITHUB_TOKEN CI trigger behavior now explained in troubleshooting).
- Partial closure of **CCE-55** docs gap (`prose_contamination_rescued` signal correctly described).

## What remains open

The troubleshooting section covers failures observed on Python hosts. End-to-end validation against JS/TS hosts (CCE-57) and hybrid-CI hosts (CCE-58) is still in progress. The guide may need amendments to Part 4 and Part 6 once those hosts are onboarded.

## Design notes

The guide is structured as two concentric loops: **global once, per-host every time**. Part 1 steps (OAuth token, GitHub App registration) are expensive to redo and must not be repeated. Part 2 steps are cheap and repo-specific. This split was the main structural decision — the old stub blurred the two, which created confusion about why GitHub App registration was needed at all.

The actionlint YAML in Part 5 includes the CCE-59 comment inline. The comment explains the absence of a `pull_request paths:` filter, which otherwise looks like an oversight to anyone reading the workflow cold.
