---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/88
synthesized_into: []
---

# Orchestrator Git Staging

The orchestrator ends each nightly run by staging changed files and opening (or appending to) a docs-agent PR. How it stages those files matters: stage too little and docs changes are lost; stage too much and unrelated artifacts contaminate the PR.

## The staging helper

`scripts/orchestrator_runner.py` uses a dedicated `_stage_docs_run_changes(repo_root)` helper rather than a bare `git add .`. The helper calls:

```
git add . -- ':!.docs-agent-plugin' ':!.docs-agent-plugin/**'
```

The exclude pathspecs (`':!'` prefix) tell git to add every modified file under the working tree **except** anything inside `.docs-agent-plugin/`. All other paths — new pages, updated pages, frontmatter changes — are staged normally.

## Why `.docs-agent-plugin/` must be excluded

When the nightly workflow runs, `actions/checkout@v5` checks the plugin out into `.docs-agent-plugin/`. That directory contains its own `.git/` directory. Git sees a nested repository and records it as a **submodule gitlink** (mode `160000`) rather than ordinary file content.

A bare `git add .` stages the gitlink automatically. The gitlink encodes the plugin's HEAD SHA at the time of the run, so it drifts on every nightly and appears as a changed entry in every docs-agent PR — even when no docs actually changed. This was confirmed in ADIS#394 (commit `8c00014`) and tracked as a plugin-wide host-contamination bug under CCE-70.

The `_stage_docs_run_changes` helper eliminates the gitlink by excluding `.docs-agent-plugin/` from the `git add` scope entirely.

## Belt-and-suspenders: `.gitignore`

The setup skill (`skills/engineering-docs-agent-setup/SKILL.md`) instructs new host onboardings to add `.docs-agent-plugin/` to the host repo's `.gitignore`. This prevents the directory from appearing as an untracked path at all, so even a naive `git add .` invocation elsewhere in a CI pipeline won't re-introduce the gitlink.

The exclude pathspec in the staging helper and the `.gitignore` entry are independent guards. Either one alone is sufficient; both together make the invariant robust to future changes in the staging call.

## Regression tests

`tests/orchestrator/test_gitlink_exclusion.py` contains two real-git tests that run against a temporary repository:

1. **Docs files are staged.** The helper stages a new markdown file under the docs directory correctly.
2. **Plugin directory is excluded.** A `.docs-agent-plugin/` directory with a nested `.git/` directory is present in the working tree; after the helper runs, `git status` shows no staged entry for `.docs-agent-plugin`.

The tests use a real git repository (not a mock) because the gitlink behavior is git internals — a mock would not reproduce the mode-`160000` promotion.

## Cleaning up existing contamination

If a host repo already has a staged or committed `.docs-agent-plugin` gitlink, remove it with:

```bash
git rm --cached .docs-agent-plugin
git commit -m "Remove .docs-agent-plugin gitlink (docs-agent cleanup)"
```

Run this as a one-off cleanup PR on any host where the nightly had been running before PR #88 landed. After cleanup, re-trigger the nightly and confirm `.docs-agent-plugin` does not appear in the resulting docs PR diff.
