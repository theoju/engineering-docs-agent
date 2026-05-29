---
title: What's New
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/39
synthesized_into: []
---

# What's New

## 2026-05-29T04:34:35.184775+00:00
- PR #58: Adds a `_remote_already_processed_window(repo_root, branch, our_head_sha) -> bool` helper to `scripts/orchestrator_runner.py` that detects same-hour duplicate runs before any subagent is dispatched. The helper fetches `origin/<docs-agent-branch>` and reads its committed `state.json` via `git show`; it returns `True` only when the remote branch's `last_successful_run.head_sha` strictly equals the current run's HEAD SHA. A new call site in `_main()` exits 0 with a skip log line when the helper returns `True`, eliminating the working-tree collision (on `whats-new.md` and `state.json`) that caused the post-CCE-42 smoke-test 2/2 to exit 1. Every failure path — network error, absent branch, missing or corrupted `state.json`, schema drift — returns `False` so the runner proceeds normally. Five unit tests cover all documented failure modes. `skills/engineering-docs-agent/SKILL.md` is updated with a new state-transitions bullet and a renumbered procedure step.

## 2026-05-28T23:15:56.279744+00:00
- PR #55: Enables the orchestrator's existing subagent forensic capture mode (DOCS_AGENT_DEBUG_DIR, built in CCE-9 + CCE-12) in the nightly CI workflow and adds an actions/upload-artifact@v4 step with 14-day retention and if: always() so per-subagent forensic files — prompt.txt, stdout.txt, stderr.txt, stream.jsonl, meta.json — survive runner teardown even on failure. No Python source changes; the only modified source file is the nightly workflow YAML. Two new internal spec and plan documents were also added under docs/superpowers/.

## 2026-05-27

### Publish the docs site to GitHub Pages

The docs site can now be published to GitHub Pages through a generic, Node-24-safe GitHub Actions deploy. The setup skill scaffolds a workflow that builds the site, writes `.nojekyll` so the artifact is served verbatim, and publishes it with `upload-pages-artifact` and `deploy-pages` — replacing the legacy Jekyll build that crashed on `{{` and `{%` sequences in source markdown. Non-MkDocs hosts can point it at a custom `build_command` and `site_dir`. See the Operations guide "Publishing to GitHub Pages" for the full flow.

Source: [PR #39](https://github.com/theoju/engineering-docs-agent/pull/39).
