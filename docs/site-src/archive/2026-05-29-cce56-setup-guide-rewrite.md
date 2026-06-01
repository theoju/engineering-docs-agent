---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/77
synthesized_into: []
---

# CCE-56: Setup Guide Rewrite — Design Rationale

**Date:** 2026-05-29  
**PR:** [#77](https://github.com/theoju/engineering-docs-agent/pull/77)  
**Ticket:** CCE-56

## Context

The previous `docs/setup-guide.md` was a 46-line stub that covered only the happy path: install the plugin, run the setup skill, set one secret, fire the workflow. It left operators without guidance on GitHub App registration, per-repo installation, the full secrets table, branch protection, and every partial-mode failure surfaced across CCE-45/49/52/53/55/59.

CCE-56 mandated a full rewrite to serve as the definitive operator reference. The result is a 370-line guide split across seven named parts, supported by companion spec and plan documents under `docs/superpowers/specs/` and `docs/superpowers/plans/`.

## Design decisions

### Split global from per-host setup

The original stub conflated one-time per-user steps (generating a Claude OAuth token, registering the GitHub App) with per-host steps (installing the App on a specific repo, setting secrets). An operator onboarding their tenth host would repeat work they'd already done.

The rewrite introduces a clear split: Part 1 is one-time per Claude Code user, Parts 2–3 are per host. This matches how the GitHub App model actually works — register once, install on each target repo.

### GitHub App registration coverage (CCE-45)

The default `GITHUB_TOKEN` suppresses both `pull_request` and `push` event triggers on commits it makes. The nightly workflow must use a GitHub App installation token so that docs-agent PRs trigger downstream CI.

The stub never mentioned this. The rewrite covers App registration step-by-step (Part 1.2) and wires the resulting App ID and private key into the secrets table (Part 2.4). It also provides a concrete troubleshooting entry for the symptom ("PR opens but no CI fires on it") that cross-references CCE-45.

### Secrets table, not a prose list

The previous stub mentioned `CLAUDE_CODE_OAUTH_TOKEN` once, in passing. The rewrite presents all seven secrets in a structured table with columns: secret name, what it is, where to get it, whether it's required. This format makes it scan-able and diff-able as new secrets land.

### Troubleshooting covers every known partial-mode trigger

Each partial-mode failure mode that shipped through CCE-45/49/52/53/55/59 gets its own named troubleshooting entry with a "Symptom:" header, root cause, and a concrete fix. The entries are:

- **No docs-agent PR** — pre-flight assert failures.
- **PR opens, no CI fires** — default `GITHUB_TOKEN` loop-prevention (CCE-45). Fix: wire the App token.
- **HTTP 422 "Unrecognized named-value"** — `steps.*` at job-env scope (CCE-45 / CCE-52). Fix: move to step-env; add actionlint gate.
- **`partial_reasons: [jira_auth_missing]`** — missing `JIRA_API_TOKEN` / `JIRA_EMAIL` (CCE-53).
- **`partial_reasons: [prose_contamination_rescued: …]`** — post-CCE-55 contamination shape not covered by the whole-string fence stripper. Fix: pull the forensics artifact and tighten the agent prompt.
- **OAuth token assert fails** — wrong token type or truncated paste (CCE-49). Fix: repaste from `claude setup-token`.
- **Branch protection blocks merge** — expected when `strict=true`.

### actionlint YAML reflects CCE-59

The recommended actionlint workflow in Part 5 uses the post-CCE-59 shape: no `paths:` filter on the `pull_request` trigger. The earlier pre-CCE-59 shape only ran actionlint when workflow files changed, which meant a required actionlint check blocked every non-workflow PR. The rewrite documents the footgun explicitly in the `actionlint.yml` snippet with an inline comment citing CCE-59.

### README trimmed to a 3-step quickstart

The old README install section duplicated four steps from the guide. The rewrite reduces it to a 3-step quickstart that links to the full guide. Keeping the two files from drifting independently is an ongoing maintenance concern — the archive reference section and the README quickstart link are the coupling points.

## Companion artifacts

The plan and spec documents shipped alongside PR #77 are under:

- `docs/superpowers/plans/` — implementation plan for CCE-56.
- `docs/superpowers/specs/` — design spec capturing the section decomposition, secrets table schema, and troubleshooting entry format.

These artifacts are inputs for any future rewrite of the setup guide via the docs-agent's own pipeline.

## Open work at merge time

- **CCE-57** (JS/TS host onboarding) and **CCE-58** (hybrid-CI host onboarding) were open when PR #77 merged. The per-language notes in Part 4 are placeholders. Once those tickets close, a follow-up edit should expand the JS/TS and hybrid-CI sections with any gaps the real onboarding revealed.
- The prose contamination troubleshooting entry (CCE-55 path) will need revision once a broader sample of anomalous contamination shapes accumulates — the current entry describes the post-CCE-55 state where only genuinely anomalous contamination triggers the partial banner.
