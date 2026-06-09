---
title: Operations
status: draft
---

# Operations

_Operations: deployment workflows, configuration guides, and runbooks._

<!-- docs-agent:overview:start -->
**In this section**

- **Subagent Forensic Capture in CI** — When a nightly run fails and the runner tears down, there is nothing left to examine. PR #55 fixes that by enabling `DOCS_AGENT_DEBUG_DIR` in `.github/workflows/docs-agent-nightly.yml` and uploading the resulting per-subagent files as a GitHub Actions artifact.
- **actionlint Required-Check Fix** — **PR #76 · CCE-52 / CCE-55 · 2026-05-29**
- **actionlint CI gate** — The `.github/workflows/actionlint.yml` workflow runs `actionlint` as a required pre-merge check on every pull request targeting `main`. It catches a class of GitHub Actions bugs that YAML schema validation cannot: context-scoping violations, illegal expression references, and expression syntax errors that only surface at dispatch time.
- **CI OAuth Token Pre-flight** — Both `release.yml` and `docs-agent-nightly.yml` run a multi-layer validation of `CLAUDE_CODE_OAUTH_TOKEN` before dispatching any Claude CLI work. This page documents the expected token shape, each validation layer, and what the failure output means so you can diagnose CI problems without reading the workflow YAML.
- **Description Quality Lint Rule** — The `description_quality` rule is a Tier-1 lint check that blocks pages with missing or thin `description` frontmatter from reaching the published site. It ships enabled by default — any host with `lint.tier1: default` in its config gets this rule without additional opt-in.
- **Nightly docs-agent CI** — The nightly authoring pipeline runs automatically at 07:07 UTC via `.github/workflows/docs-agent-nightly.yml`. It computes the change window against `state.json`, dispatches the subagent pipeline, and opens or appends a commit to a `docs-agent/YYYY-MM-DD` branch. A partial run still opens the PR with `partial: true` in the body — no run goes silent.
- **Nightly Workflow: GitHub App Token** — The `docs-agent-nightly` workflow authenticates as the `docs-agent-bot` GitHub App rather than using the default `GITHUB_TOKEN`. This page explains why that matters and what you need to configure.
- **Nightly workflow: Jira authentication** — The nightly docs-agent workflow authenticates to Jira using two repo credentials — one Secret, one Variable — forwarded as job-level environment variables in `.github/workflows/docs-agent-nightly.yml`. Without them, every run operates in partial mode.
- **Nightly Workflow Run Summary** — The nightly workflow writes a run summary to `$GITHUB_STEP_SUMMARY` after every execution. This gives you a fast read on what the last nightly did — state snapshot, partial status, any errors — without downloading the forensics artifact.
- **Publishing to GitHub Pages** — The engineering-docs-agent plugin can scaffold and verify a complete GitHub Pages deployment for any host repo that uses MkDocs or a custom build command. This guide covers how the scaffolded workflow operates, why each step exists, and how detection decides whether to scaffold it at all.
- **Setting up the auth token** — The engineering-docs-agent authenticates to the Claude CLI via a single GitHub secret: `CLAUDE_CODE_OAUTH_TOKEN`. This replaced `ANTHROPIC_API_KEY` when the OAuth-based dispatch path became the only supported path (CCE-35). Using `ANTHROPIC_API_KEY` silently fails — the CLI ignores that slot and no error surfaces in the run log.
- **Step summary observability** — When a nightly run encounters a partial or hard-failed subagent, the runner writes a formatted digest to GitHub Actions' built-in step summary. You can read this digest directly in the workflow run UI without downloading any forensics artifact.

_12 pages · regenerated nightly_
<!-- docs-agent:overview:end -->
