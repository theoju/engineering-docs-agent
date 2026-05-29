---
title: What's New
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/39
synthesized_into: []
---

# What's New

## 2026-05-28T23:15:56.279744+00:00
- PR #55: Enables the orchestrator's existing subagent forensic capture mode (DOCS_AGENT_DEBUG_DIR, built in CCE-9 + CCE-12) in the nightly CI workflow and adds an actions/upload-artifact@v4 step with 14-day retention and if: always() so per-subagent forensic files — prompt.txt, stdout.txt, stderr.txt, stream.jsonl, meta.json — survive runner teardown even on failure. No Python source changes; the only modified source file is the nightly workflow YAML. Two new internal spec and plan documents were also added under docs/superpowers/.

## 2026-05-27

### Publish the docs site to GitHub Pages

The docs site can now be published to GitHub Pages through a generic, Node-24-safe GitHub Actions deploy. The setup skill scaffolds a workflow that builds the site, writes `.nojekyll` so the artifact is served verbatim, and publishes it with `upload-pages-artifact` and `deploy-pages` — replacing the legacy Jekyll build that crashed on `{{` and `{%` sequences in source markdown. Non-MkDocs hosts can point it at a custom `build_command` and `site_dir`. See the Operations guide "Publishing to GitHub Pages" for the full flow.

Source: [PR #39](https://github.com/theoju/engineering-docs-agent/pull/39).
