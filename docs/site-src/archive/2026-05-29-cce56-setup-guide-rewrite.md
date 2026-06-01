---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/77
synthesized_into: []
---

# CCE-56: Setup Guide Rewrite (2026-05-29)

**PR #77** replaced the 46-line stub at `docs/setup-guide.md` with a 370-line, 7-part host setup guide. This archive entry records what changed and why.

## What changed

The previous setup guide was a minimal placeholder that listed the three install commands and nothing else. It gave new host operators no path through GitHub App registration, repo secret wiring, or the branch-protection rules that the nightly workflow requires.

PR #77 rewrites the guide end-to-end. The new document covers:

1. **Prerequisites** — required CLI tools, permissions, and accounts before you start.
2. **Claude OAuth setup** — generating and storing `CLAUDE_CODE_OAUTH_TOKEN`.
3. **GitHub App registration** — creating the App, setting the required permissions, and wiring the installation token into the host repo's secrets.
4. **Per-host configuration** — populating `.engineering-docs-agent/config.yml`, seeding `state.json` from the example template, and configuring `docs.lens_paths` / `docs.agent_editable_paths`.
5. **Validation steps** — running the dry-run locally (`--no-pr`) and reading the resulting `current_run.json` to confirm the orchestrator resolved sources correctly.
6. **Per-language host notes** — conventions that differ for non-Python hosts (no package detection, no `pyproject.toml` extractor).
7. **Optional add-ons** — Slack webhook, email SMTP, and Jira enrichment (`JIRA_EMAIL` + `JIRA_API_TOKEN`).

A **troubleshooting** section covers every partial-mode failure mode that shipped through CCE-45, CCE-49, CCE-52, CCE-53, CCE-55, and CCE-59. Each entry names the `partial_reasons` value you will see in `state.json`, explains the root cause, and gives the fix.

A **copy-paste checklist** at the end of the guide lets you verify every required secret and config key is in place before your first nightly run.

A **reference section** cross-links the design spec, agent contracts, and Jira tickets.

## Why it was needed

CCE-56 was opened after multiple host onboarding attempts stalled at different points — GitHub App permissions, missing secrets, misconfigured `agent_editable_paths` — all of which were undocumented. The incidents that produced CCE-45 through CCE-59 each revealed a gap. The rewrite consolidates those lessons into one authoritative document so you do not need to dig through closed tickets to onboard.

## Companion documents

The PR also adds a spec and plan under `docs/superpowers/`:

- `docs/superpowers/specs/2026-05-29-cce56-setup-guide-rewrite.md` — the CCE-56 design spec.
- `docs/superpowers/plans/2026-05-29-cce56-setup-guide-rewrite.md` — the implementation plan.

The `superpowers` lens is not present in `lens_names` for this host's config, so these files are captured here in the core archive rather than a separate superpowers archive entry.

## Drift fixes in the same PR

- **CCE-55 status** updated to `done` in the drift log.
- **CCE-59** added: `actionlint` required-check and path-filter footgun fix (the nightly workflow's `on.push.paths` filter was excluding its own trigger branch).

## Out of scope

End-to-end validation against non-Python hosts is tracked in CCE-57 and CCE-58 and is explicitly not part of this PR. The setup guide's per-language notes section covers known differences, but CI-level proof on a real non-Python host comes later.
