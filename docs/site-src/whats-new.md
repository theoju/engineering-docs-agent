---
title: What's New
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/39
synthesized_into: []
---

# What's New

## 2026-05-27

### Publish the docs site to GitHub Pages

The docs site can now be published to GitHub Pages through a generic, Node-24-safe GitHub Actions deploy. The setup skill scaffolds a workflow that builds the site, writes `.nojekyll` so the artifact is served verbatim, and publishes it with `upload-pages-artifact` and `deploy-pages` — replacing the legacy Jekyll build that crashed on `{{` and `{%` sequences in source markdown. Non-MkDocs hosts can point it at a custom `build_command` and `site_dir`. See the Operations guide "Publishing to GitHub Pages" for the full flow.

Source: [PR #39](https://github.com/theoju/engineering-docs-agent/pull/39).
