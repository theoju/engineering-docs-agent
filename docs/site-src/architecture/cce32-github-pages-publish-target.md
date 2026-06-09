---
description: "Architecture of the GitHub Pages publish target introduced in CCE-32\
  \ \u2014 workflow structure, Node 24 action pins, Jekyll bypass, and publish-verifier\
  \ integration."
source_files:
- docs/superpowers/plans/*.md
- templates/*.yml
- tests/ci/test_workflow_node_runtime.py
last_reviewed: '2026-05-28'
status: draft
doc_kind: architecture
---

# GitHub Pages Publish Target (CCE-32)

The engineering-docs-agent publishes docs sites to GitHub Pages using the Actions-source deploy mode. This page covers the workflow architecture, the Node 24 constraint, the `.nojekyll` invariant, and how the publish-verifier integrates with the deployed URL.

## Deploy mode choice

GitHub Pages supports two deploy sources: a legacy mode that runs Jekyll on a branch, and the Actions-source mode where a workflow owns the full build-and-upload cycle. The plugin uses Actions-source mode exclusively.

Legacy Jekyll mode is off the table. It runs a Liquid template pass over every uploaded file, which corrupts any markdown containing `{{` or `{%` — code examples, Jinja snippets, config samples. Actions-source mode lets the build job produce the artifact and upload it verbatim.

## Workflow structure

The dogfood workflow is at `.github/workflows/docs-pages.yml`. The setup skill scaffolds a copy at `templates/workflow-pages.yml` into host repos. Both follow the same two-job structure.

**`build` job:**

```yaml
steps:
  - uses: actions/checkout@v5
  - uses: actions/configure-pages@v6
    with:
      enablement: true
  - uses: actions/setup-python@v6
    with:
      python-version: "3.12"
  - name: Build site
    run: |
      pip install -r requirements-docs.txt
      mkdocs build --strict
  - name: Write .nojekyll so Pages serves the artifact as-is
    run: touch site/.nojekyll
  - uses: actions/upload-pages-artifact@v5
    with:
      path: site
```

**`deploy` job:**

```yaml
needs: build
environment:
  name: github-pages
  url: ${{ steps.deployment.outputs.page_url }}
steps:
  - id: deployment
    uses: actions/deploy-pages@v5
```

The two jobs are split so the `deploy` job can run under the `github-pages` environment, which enforces branch protection and exposes `page_url` as the deployment URL the publish-verifier reads.

The `concurrency` group is set to `pages` with `cancel-in-progress: false`. Cancelling a Pages deploy mid-flight leaves the CDN in an inconsistent state; this setting ensures deploys complete or queue rather than abort.

## Node 24 action pins

GitHub Actions switched its hosted runner Node runtime from Node 20 to Node 24 on 2026-06-02. Action majors that bundle Node 20 hard-fail after that date.

The required minimum majors for Pages workflows:

| Action                          | Minimum major | `runs.using` |
| ------------------------------- | ------------- | ------------ |
| `actions/checkout`              | `@v5`         | `node24`     |
| `actions/configure-pages`       | `@v6`         | `node24`     |
| `actions/setup-python`          | `@v6`         | `node24`     |
| `actions/upload-pages-artifact` | `@v5`         | `node24`     |
| `actions/deploy-pages`          | `@v5`         | `node24`     |

`tests/ci/test_workflow_node_runtime.py` enforces these floors on every workflow file under `.github/workflows/` and on every `templates/workflow-*.yml` file. The test runs on every PR, so a downgrade cannot creep back in via a merge.

The test also asserts that any workflow referencing `actions/deploy-pages` writes `.nojekyll` and does not invoke a Jekyll build step (`test_pages_deploy_workflows_disable_jekyll`).

## `.nojekyll` invariant

Even in Actions-source mode, GitHub's CDN layer runs a Jekyll post-processing pass on uploaded artifacts unless a `.nojekyll` file is present at the artifact root. The `.nojekyll` touch happens after `mkdocs build` so it lands inside `site/` before `upload-pages-artifact` packages the directory.

The file has no content. Its presence is the signal.

## Permissions and token scope

The workflow declares the minimum required permissions:

```yaml
permissions:
  contents: read
  pages: write
  id-token: write
```

`id-token: write` is required by the OIDC-based `deploy-pages` action. `pages: write` scopes the token to Pages operations only. Without `contents: write`, the workflow cannot commit back to the repo — a deliberate constraint.

## Trigger paths

The dogfood workflow triggers on pushes to `main` that touch `docs/site-src/**`, `mkdocs.yml`, `requirements-docs.txt`, or the workflow file itself. `workflow_dispatch` is also enabled for manual runs. This path filter prevents docs deploys from running on code-only merges.

The template (`templates/workflow-pages.yml`) uses a broader `docs/**` glob. When the setup skill scaffolds the template into a host repo, it rewrites the path filter to match the host's `docs.source_dir` from config.

## Config integration

The `publishing` block in `.engineering-docs-agent/config.yml` connects the workflow to the rest of the pipeline:

```yaml
publishing:
  base_url: https://theoju.github.io/engineering-docs-agent/
  build_workflow: docs-pages.yml
  url_map_rule: standard
  verify_timeout_seconds: 60
```

`build_workflow` is the workflow filename the publish-verifier polls after a docs-agent PR merges. `base_url` is used to construct expected page URLs from changed file paths. `url_map_rule: standard` applies MkDocs's default path-to-URL mapping (strip `.md`, add trailing slash). `verify_timeout_seconds` caps how long the verifier waits for the build workflow to complete before declaring a timeout.

## Non-MkDocs hosts

The scaffolded template is MkDocs-first. For hosts that use a different static site generator, the setup skill rewrites the build step using `publishing.build_command` and `publishing.site_dir` from config:

```yaml
publishing:
  build_command: "npm run docs:build"
  site_dir: "docs-dist/"
```

Everything else — action pins, `.nojekyll`, deploy job structure — stays identical. The Node 24 floor applies regardless of framework.
