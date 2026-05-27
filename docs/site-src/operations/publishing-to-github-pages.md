---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/39
synthesized_into: []
---

# Publishing to GitHub Pages

The engineering-docs-agent plugin can scaffold and verify a complete GitHub Pages deployment for any host repo that uses MkDocs or a custom build command. This guide covers how the scaffolded workflow operates, why each step exists, and how detection decides whether to scaffold it at all.

## What the publish target is

GitHub Pages can serve content from two sources: a legacy "deploy from branch" mode that runs the Jekyll processor, and the newer "GitHub Actions" source mode that gives you full control over what gets built and uploaded. The plugin uses Actions-source mode exclusively.

Actions-source mode lets the build run inside a workflow step — MkDocs, a custom command, or anything else — and upload the result as an artifact. GitHub then deploys that artifact directly, bypassing Jekyll.

## How the scaffolded workflow operates

The setup skill writes `templates/workflow-pages.yml` into the host repo when detection confirms the conditions are met (see the section below on detection). The workflow runs five sequential steps:

```yaml
steps:
  - uses: actions/configure-pages@v6
  - uses: actions/checkout@v5
  - run: pip install mkdocs && mkdocs build # or your build_command
  - run: touch site/.nojekyll
  - uses: actions/upload-pages-artifact@v5
    with:
      path: site/
  - uses: actions/deploy-pages@v5
```

`configure-pages` sets the `GITHUB_PAGES_URL` output and validates that the repo has Pages enabled. The build step runs MkDocs (or your `publishing.build_command` from config). The `.nojekyll` touch happens after the build so it lands inside the artifact directory before upload. `upload-pages-artifact` packages the directory. `deploy-pages` pushes it live.

## Why `.nojekyll` matters

Without `.nojekyll`, GitHub's CDN layer runs a Jekyll post-processing pass on the uploaded artifact even in Actions-source mode. Jekyll treats `{{` and `{%` as Liquid template syntax. Any markdown source that contains those character sequences — code examples, Jinja snippets, configuration samples — gets mangled or stripped.

Placing `.nojekyll` at the root of the uploaded artifact directory tells the CDN to skip that pass entirely. The file has no content; its presence is the signal.

## Action version pins

All five actions are pinned to major versions that are safe for the Node 24 runtime GitHub Actions uses as of 2026:

| Action                          | Pin   |
| ------------------------------- | ----- |
| `actions/configure-pages`       | `@v6` |
| `actions/checkout`              | `@v5` |
| `actions/setup-python`          | `@v6` |
| `actions/upload-pages-artifact` | `@v5` |
| `actions/deploy-pages`          | `@v5` |

A CI guard in the plugin's own workflow validates these pins on every PR so they do not drift as the repo evolves.

## How detection decides whether to scaffold

The setup skill runs `detect_pages_publishable` during its step 6a. The function returns true when both of the following hold:

1. The host has MkDocs configured (detected by a `mkdocs.yml` in the repo root) **or** the host config specifies a `publishing.build_command`.
2. The host config's `publishing.target` is `github-pages` or the value is absent and GitHub Actions is the detected CI provider.

When detection returns false — for example, a repo with no docs build tooling — the setup skill skips step 6a entirely and emits a log line explaining why. No partial workflow file is written.

The derived base URL comes from `derive_pages_base_url`, which reads the `GITHUB_PAGES_URL` output from the `configure-pages` action. The publish-verifier agent uses this URL after a docs PR merges to confirm pages are actually live.

## Non-MkDocs hosts

If your repo uses a custom static site generator, set `publishing.build_command` and `publishing.site_dir` in `.engineering-docs-agent/config.yml`:

```yaml
publishing:
  target: github-pages
  build_command: "npm run docs:build"
  site_dir: "docs-dist/"
```

The scaffolded workflow substitutes your `build_command` in place of the MkDocs invocation and uploads from `site_dir` instead of `site/`. Everything else — the `.nojekyll` touch, the action pins, the deploy step — stays the same.

## Source

This page reflects changes introduced in [PR #39](https://github.com/theoju/engineering-docs-agent/pull/39), which added the deploy workflow template, detection helpers, and the `.nojekyll` fix, and switched this repo's own Pages source from legacy Jekyll to GitHub Actions.
