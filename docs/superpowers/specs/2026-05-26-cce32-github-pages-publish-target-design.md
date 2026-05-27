# GitHub Pages publish target — generic Actions-source deploy

**Status:** approved 2026-05-26 (brainstorm + 3 locked decisions); implementation plan next.
**Jira:** CCE-32 (Story; engineering-docs-agent plugin). The missing deploy half of the publish→verify contract.
**Reference:** existing `agents/publish-verifier.md` (already polls `publishing.build_workflow` and checks `publishing.base_url`); C1/C2/C3 capabilities; CCE-31 (`tests/ci/test_workflow_node_runtime.py`) Node-24 guard.

---

## Why this exists

The plugin already verifies published pages — `publish-verifier` polls a host's `publishing.build_workflow` and fetches `publishing.base_url` URLs after a docs PR merges — but **nothing ever scaffolds that build workflow.** The publish→verify contract has a verifier and no deployer. Because the deploy half was missing, GitHub Pages got wired up by hand as legacy "Deploy from a branch" (Jekyll), which ran Jekyll's Liquid pass over the raw repo root and crashed on `{{`/`{%` in source markdown (e.g. code samples in `docs/superpowers/plans/*.md`). That failure mode was never modeled or tested by the plugin's CI.

This capability supplies the deployer: a generic, Node-24-safe, **GitHub Actions–source** Pages deploy that publishes the _built_ site artifact verbatim. It is the standing answer to "publish generated docs to GitHub Pages for any host, stably."

## Decided approach (Approach A)

GitHub Actions–source Pages deploy, self-enabling, MkDocs-first with a generic fallback, `.nojekyll` in the artifact. Action majors are pinned to verified Node-24 runtimes:

| Action                          | Pin   | `runs.using` |
| ------------------------------- | ----- | ------------ |
| `actions/checkout`              | `@v5` | node24       |
| `actions/setup-python`          | `@v6` | node24       |
| `actions/configure-pages`       | `@v6` | node24       |
| `actions/upload-pages-artifact` | `@v5` | composite    |
| `actions/deploy-pages`          | `@v5` | node24       |

The common tutorial pins (`configure-pages@v5`, `deploy-pages@v4`) are still **node20** and are explicitly rejected — using them would re-introduce the deprecation this work removes.

Three locked decisions from brainstorming:

1. **Enablement = self-enable (auto).** The deploy workflow runs `configure-pages@v6` with `enablement: true`; its first run turns Pages on and sets the source to "GitHub Actions". No manual step. If an org policy blocks it, the run fails loudly with an actionable message (no silent manual fallback).
2. **Build target = MkDocs-first + generic fallback.** Default builds MkDocs (`mkdocs build --strict`, deploy `site/`). If the host is not MkDocs, fall back to config `publishing.build_command` + `publishing.site_dir`. Convention-optimized, degrades generically.
3. **Dogfood scope = bootstrap a site here.** This repo gets a minimal MkDocs site + the deploy workflow, so the plugin repo publishes end-to-end.

## Architecture

Two layers:

- **Generic capability** — a workflow template the setup skill scaffolds onto hosts, plus config wiring so `publish-verifier`'s target exists.
- **Dogfood** — a minimal MkDocs site in this repo built and deployed by the same workflow shape.

| Component                                                            | Responsibility                                                                                                                                            |
| -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `templates/workflow-pages.yml` (new)                                 | Scaffolded to hosts as `.github/workflows/docs-agent-pages.yml`. The deployer.                                                                            |
| `.github/workflows/docs-pages.yml` (this repo, new)                  | Same shape; builds + deploys this repo's site.                                                                                                            |
| `mkdocs.yml` + `docs/site-src/` (this repo, new)                     | Minimal Material site to publish. Generated via the plugin's own `setup_scaffold.py` (dogfooding the scaffolder).                                         |
| Setup skill (`SKILL.md` step 6) + `setup_discover.py`                | Emit the pages workflow; set `publishing.build_workflow` + `base_url`; detection-driven (only when `ci == github_actions` and a buildable target exists). |
| `templates/config.schema.json`                                       | Add optional `publishing.build_command` + `publishing.site_dir`.                                                                                          |
| `tests/ci/test_workflow_node_runtime.py` (extend, from CCE-31)       | Node-24 floor now covers the Pages actions; asserts `.nojekyll`; forbids legacy Jekyll; **covers `templates/*.yml` too**.                                 |
| `templates/workflow-run.yml`, `templates/workflow-verify.yml` (bump) | Pre-existing scaffolded templates still pin `checkout@v4`/`setup-python@v5`; bump to Node-24 majors so hosts stop inheriting the deprecation.             |

## The deploy workflow (`templates/workflow-pages.yml`)

```yaml
name: docs-agent pages
on:
  push:
    branches: [main]
    paths:
      ["<docs_dir>/**", "mkdocs.yml", ".github/workflows/docs-agent-pages.yml"]
  workflow_dispatch:
permissions:
  contents: read
  pages: write
  id-token: write
concurrency:
  group: pages
  cancel-in-progress: false
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/configure-pages@v6
        with: { enablement: true }
      - uses: actions/setup-python@v6
        with: { python-version: "3.11" }
      - name: Build site
        run: |
          pip install -r <plugin-or-host docs-requirements>
          mkdocs build --strict        # or: ${{ publishing.build_command }}
      - run: touch <site_dir>/.nojekyll
      - uses: actions/upload-pages-artifact@v5
        with: { path: <site_dir> } # default site/
  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v5
```

`paths`, the build command, and `site_dir` are filled from config at scaffold time. The `.nojekyll` line is the root-cause fix: the artifact is served verbatim, so Liquid never runs over source markdown.

## Setup-skill wiring

At setup-skill step 6 (workflow writing), additionally:

- Write `templates/workflow-pages.yml` → `.github/workflows/docs-agent-pages.yml`, substituting `docs_dir`, build command, and `site_dir` from discovery/config.
- Set `publishing.build_workflow` to `docs-agent-pages.yml` (the contract seam `publish-verifier` polls).
- Set `publishing.base_url` via derivation: project site → `https://<owner>.github.io/<repo>/`; user/org site (`<owner>.github.io` repo) → `https://<owner>.github.io/`; honor an existing `CNAME` custom domain if present.
- **Detection-driven:** scaffold the pages workflow only when `setup_discover.detect_ci(...) == "github_actions"` AND (`detect_framework(...) == "mkdocs"` OR a `publishing.build_command` is configured). Otherwise skip cleanly and print how to enable it. Never error, never emit a half-wired config.

`templates/config.schema.json` gains optional `publishing.build_command` (string) and `publishing.site_dir` (string, default `site`). `base_url`/`build_workflow`/`url_map_rule` stay required.

## Guard & tests

- **Guard extension** (`tests/ci/test_workflow_node_runtime.py`): extend `NODE24_FLOOR` to `{checkout:5, setup-python:6, configure-pages:6, deploy-pages:5}`; extend the workflow glob set to include `templates/*.yml`; add assertions that any workflow named like a pages deploy (`deploy-pages` present) also `touch`es `.nojekyll` and contains no Jekyll markers (`jekyll`, `_config.yml` build). Stdlib only; runs in `test.yml`.
- **Template-validity test** (new, fixture-free): parse `templates/workflow-pages.yml` as YAML; assert required permissions (`pages: write`, `id-token: write`), the five pinned actions at their Node-24 majors, the `.nojekyll` step, and an `upload-pages-artifact`/`deploy-pages` pair. Assert the scaffold default `publishing.build_workflow` equals the workflow's target filename.
- **`setup_discover` / wiring test** (fixture-driven, arbitrary host): a fixture host with `mkdocs.yml` + GitHub Actions → setup scaffolds the pages workflow and sets `publishing.build_workflow` + `base_url`; a fixture host with neither framework nor `build_command` → no pages workflow scaffolded, config still valid (graceful degrade).
- **Dogfood live validation:** this repo's `docs-pages.yml` deploys on merge to main; once `mkdocs.yml` exists here, the C3 `docs.yml` site-gate (currently skipped) builds and gates the real site.

## Dogfood (this repo)

1. Run `python scripts/setup_scaffold.py --repo-root . --site-name "engineering-docs-agent"` to generate `mkdocs.yml` + a minimal `docs/site-src/` (home + a section), dogfooding the scaffolder. Hand-trim to a minimal, buildable site.
2. Add `.github/workflows/docs-pages.yml` (the deploy workflow, this repo's paths/site_dir).
3. **Interim/first step:** switch this repo's Pages source from legacy Jekyll to "GitHub Actions" (a settings change, `gh api -X PUT .../pages -f build_type=workflow`, done with explicit authorization). This stops the failing legacy build immediately; `configure-pages@v6` then keeps the source set on each run.
4. Validate: merge → `docs-pages.yml` builds + deploys; site live at `https://theoju.github.io/engineering-docs-agent/`; C3 site-gate now exercises the built site.

## Generic-first & graceful degradation

- No `mkdocs.yml` and no `build_command` → setup does not scaffold the deployer; documents how to add one.
- `ci != github_actions` → skip Pages-deploy scaffolding entirely.
- `mkdocs build --strict` fails → workflow fails (never publish a broken site).
- `configure-pages` self-enable blocked by org policy → run fails with an actionable "set Settings → Pages → Source = GitHub Actions" message.
- `.nojekyll` guarantees verbatim serving regardless of host markdown content.

## Relationship to existing code

- **`agents/publish-verifier.md`** — unchanged contract; its `publishing.build_workflow` target now exists. The deployer and verifier meet at the workflow filename in config.
- **`docs.yml` (C3)** — once the dogfood `mkdocs.yml` lands, its build + diagram-render gate stop skipping and exercise the real site.
- **CCE-31 guard** — extended, not duplicated; single source of truth for "CI workflows pin Node-24 action majors", now spanning repo workflows + scaffolded templates + the Pages actions.

## Sequencing & delivery

One spec, two sub-plans on `feat/CCE-32-github-pages-publish-target`:

1. **Generic capability** — `templates/workflow-pages.yml`; bump `workflow-run.yml`/`workflow-verify.yml`; `config.schema.json` `build_command`/`site_dir`; setup-skill wiring + detection; guard extension + template-validity + `setup_discover` tests.
2. **Dogfood** — scaffold this repo's MkDocs site; `docs-pages.yml`; switch Pages source to GitHub Actions; live-deploy validation; confirm C3 site-gate activates.

Executed via subagent-driven-development; final whole-branch review; `/ship` per sub-plan, base `main`.

## Risks & open questions

- **`configure-pages enablement:true` permissions.** Needs the run token to have Pages admin; `GITHUB_TOKEN` with `pages: write` suffices on most repos, but org policy can still block Actions-as-source — surfaced as a loud failure per decision 1.
- **`base_url` derivation edge cases.** Custom domains (CNAME), org/user sites, and `path != /` need correct derivation; covered by the wiring tests.
- **Existing scaffolded hosts.** Hosts set up before this lands won't have the pages workflow; re-running the (idempotent) setup skill adds it. Document in the setup skill's next-steps output.
- **`url_map_rule` consistency.** The verifier's source→URL mapping should match MkDocs `use_directory_urls`; align with C3's `source_to_built_urls` logic rather than inventing a second rule.
