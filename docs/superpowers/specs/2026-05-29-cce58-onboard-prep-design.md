# CCE-58 — Onboard `theoju/advanced-data-import-system` (hybrid CI prep)

## Background

CCE-58 asks us to onboard `theoju/advanced-data-import-system` as a new engineering-docs-agent host. Three properties of the host are novel relative to prior dogfood:

1. **Hybrid CI.** Primary checks live in CircleCI (`ci/circleci: backend-lint`, `backend-test`, `frontend-test`, `gcp-id-guard`). One GitHub Actions workflow already exists (`docs-deploy.yml`). The two providers coexist; nothing forces a migration.
2. **Python + TypeScript mix.** Python 4.1MB, TypeScript 1.5MB. Python is the larger half, but the host is not pure-Python.
3. **Strict branch protection.** `strict=true` on `main`; the four CircleCI contexts are required for merge.

CCE-58 lands AFTER CCE-56 (comprehensive `docs/setup-guide.md`) and is a sibling of CCE-57 (claude-code-self-assessment onboarding). The setup guide already calls out "Hybrid CI (CircleCI, Jenkins, Buildkite, …)" in Part 4 and explicitly names `advanced-data-import-system` and CCE-58 as the host validating that path. So most of the user-facing doc is already shipped — CCE-58 prep is mostly fixtures + runbook + a small forward-looking schema concession.

## Problem

The actual install is blocked on user actions on the target repo (App install, secret paste, branch-protection edit). The plugin-side work is preparation: anything we can ship now to make the eventual install boring, plus a concrete answer to the "does publish-verifier need CircleCI support?" question that the ticket asks.

## Goal

Ship the plugin-side prep for CCE-58 such that, once the user completes the gated steps, the first nightly run on `advanced-data-import-system` succeeds without code edits to the plugin. Concretely:

1. A copy-pasteable host config template tuned for a Python + TypeScript hybrid-CI repo.
2. A host fixture exercising the hybrid-CI shape end-to-end through the config loader.
3. A host-onboarding runbook (single markdown file at `docs/host-onboarding/advanced-data-import-system.md`) that captures every per-host decision, App install steps, and post-install smoke-test checklist for THIS host (the generic setup guide stays generic).
4. A definitive answer in writing on whether the publish-verifier needs CircleCI support, and (if yes) a sub-ticket filed with concrete scope.

## Non-goals

- Editing scripts/, agents/, or shared helpers in a way that touches existing semantics. Any new code must be additive — new fixture, new doc, plus a strictly additive schema field.
- Installing the plugin on the target repo. That's user-gated.
- Implementing CircleCI polling in publish-verifier. If we decide it's needed, that's a follow-up ticket — CCE-58 is prep, not the novel-CI feature.
- Validating the rendered nightly PR by running the orchestrator against the live target repo. That happens after install.

## Design

### Critical question — does publish-verifier need CircleCI support?

**No, not for this host.** Reasoning:

1. The publish-verifier's job is to wait for the **publish workflow** (the one that builds the docs site) to finish, then `curl` the resulting URLs. That workflow is `docs-deploy.yml`, which is GitHub Actions on this host. `gh run list --workflow docs-deploy.yml` works as written.
2. CircleCI on this host gates **user PRs into main** — `backend-test`, `frontend-test`, etc. The publish-verifier never polls those. It polls the workflow that runs on `push` to `main` after a docs-agent PR merges. None of the four required CircleCI contexts run on `push` to main as a docs-publish step.
3. So the CircleCI surface area is a **branch-protection concern**, not a publish-verifier concern. Docs-agent PRs will be subject to the CircleCI required checks — either they must pass them (the four contexts run on every PR including docs-agent branches) or the user must scope required contexts to non-`docs-agent/*` branches via branch protection. We document this trade-off in the runbook.

**However**, the publish-verifier prompt does hard-code "Poll `gh run list --workflow <build_workflow>`". A future host might want CircleCI to be the docs-publish CI (not just the gating CI). That is a real generalization gap. We file a follow-up sub-ticket capturing it, with the expected shape:

- Add `publishing.ci_provider: "github" | "circleci"` (default `"github"`).
- When `circleci`, the verifier polls `https://circleci.com/api/v2/project/gh/<owner>/<repo>/pipeline` filtered by `branch=main` and `vcs.revision=<post-merge SHA>`, then walks workflows → jobs to find the named build job.
- Auth via `CIRCLECI_TOKEN` secret, surfaced as a new entry in the setup-guide secret table.

That ticket is scoped at ~1 day of work. It is **not** part of CCE-58 because no concrete host needs it yet — CCE-58's host uses GitHub Actions for publish.

### Plugin-side prep deliverables

**A1. Host config template at `templates/hosts/advanced-data-import-system.config.yml`.**

A complete, copy-pasteable `.engineering-docs-agent/config.yml` tuned for this specific host. Concrete values:

```yaml
docs:
  framework: mkdocs
  source_dir: docs/site-src
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths:
    - "docs/site-src/**"
  lens_paths:
    core: docs/site-src/

sources:
  git:
    host: github
  jira:
    enabled: false # adjust per host preference

voice:
  sample_paths:
    - README.md
    - CLAUDE.md

lint:
  tier1: default

publishing:
  base_url: https://theoju.github.io/advanced-data-import-system/
  build_workflow: docs-deploy.yml
  url_map_rule: standard
  verify_timeout_seconds: 90 # extra slack for hybrid-CI scheduling

notifications:
  slack:
    enabled: false
  email:
    enabled: false
```

The file is a starting template. The runbook (deliverable C below) documents which fields the user must double-check before commit.

**A2. Schema concession (additive only): optional `publishing.ci_provider` field.**

`templates/config.schema.json`: extend the `publishing` properties block with:

```json
"ci_provider": {
  "type": "string",
  "enum": ["github", "circleci"],
  "default": "github",
  "description": "Which CI provider runs the publish workflow. Default `github`. Forward-looking; only `github` is implemented in the publish-verifier today (see CCE-NN)."
}
```

This is purely declarative — no behavioral consumer wires it yet. The benefit: when the CircleCI sub-ticket lands, config files in the wild can already declare intent without a schema break. Tests assert the field is accepted and rejected outside the enum.

**B. Fixture at `tests/fixtures/host_onboarding/advanced-data-import-system/`.**

A directory matching the on-disk shape the user would commit. Layout:

```
tests/fixtures/host_onboarding/advanced-data-import-system/
  .engineering-docs-agent/
    config.yml                      # copy of A1 above
    state.example.json              # standard seed
  README.md                         # one-line note about what the fixture represents
```

A new test `tests/setup/test_host_onboarding_fixtures.py` parametrizes over every directory under `tests/fixtures/host_onboarding/` and asserts:

- The config validates via `load_config_validated`.
- The lens-path / editable-glob invariant holds.
- The `publishing.build_workflow` is a non-empty string (smoke).
- If `publishing.ci_provider` is set, it validates against the schema enum.

This is the generic-first contract: any host config we ship in the runbook passes the same validation the production loader runs.

**C. Host-onboarding runbook at `docs/host-onboarding/advanced-data-import-system.md`.**

This file is specific to this host (NOT generic). It is the artifact a user paste-walks once. Structure:

1. **Pre-flight assumptions.** "You have completed Part 1 of `docs/setup-guide.md` (OAuth token, GitHub App registration). You have admin on `theoju/advanced-data-import-system`."
2. **Per-host decisions made here.** Tabulates the choices we baked into A1 — `framework: mkdocs`, `lens: core`, `publishing.build_workflow: docs-deploy.yml`, `verify_timeout_seconds: 90`. Each row links to where in the generic guide that field is explained.
3. **Hybrid-CI branch-protection trade-off.** Documents the choice between:
   - **Option H1 (recommended):** Leave the four CircleCI contexts globally required; docs-agent PRs must wait for them. CircleCI runs on the docs-agent branch, the contexts pass (docs-only changes don't break backend tests), PR merges. Net cost: extra CircleCI minutes on every docs-agent PR.
   - **Option H2:** Use a branch-protection rule that scopes the CircleCI contexts to non-`docs-agent/*` heads. Requires a custom protection rule and operational discipline. Lower CI spend, more config surface.

   We recommend H1 because the four contexts are short-running and unblock docs-agent PRs without operational fragility.

4. **Step-by-step install.** Maps each generic step from `docs/setup-guide.md` Part 2 onto a concrete command for this host. Includes `gh` snippets to install the GitHub App, set the secrets, and verify branch protection.
5. **Smoke test.** `gh workflow run docs-agent-nightly.yml -f reason="cce-58 smoke"` + checklist of what success looks like (matches Part 3 of generic guide).
6. **Known follow-up.** Links to the CircleCI publish-verifier sub-ticket so the next person knows the gap is filed.

**D. Update `docs/setup-guide.md` Part 4 (hybrid-CI section) only.**

The existing section already names this host and CCE-58. Add one paragraph at the end pointing at `docs/host-onboarding/advanced-data-import-system.md` as a worked example. This is the only edit to a doc that lives on main outside the new host-onboarding subdirectory.

### Sub-ticket: CircleCI publish-verifier support

Filed as a separate CCE ticket with scope:

- New `publishing.ci_provider` field becomes load-bearing in `scripts/verify_runner.py` (dispatch a CircleCI-aware variant of the polling logic).
- `agents/publish-verifier.md` Procedure §1 grows a conditional branch: GitHub → `gh run list`; CircleCI → `curl https://circleci.com/api/v2/...`.
- New secret `CIRCLECI_TOKEN` in the setup guide's secret table.
- Test plan: dry-run fixture with `ci_provider: circleci` exercises the new procedure end-to-end via monkeypatched HTTP.

Linked to CCE-58 via "relates" (not "blocks" — CCE-58 ships without this).

## Test plan

- `python3 -m pytest -q` — full suite. Expected: existing tests unchanged; ~3 new tests pass.
- `python3 -m pytest tests/setup/test_host_onboarding_fixtures.py -v` — host-fixture validation.
- `python3 -m pytest tests/schemas/test_config_schema.py -v` — schema accepts `ci_provider: github`, accepts `ci_provider: circleci`, rejects `ci_provider: gitlab`, accepts config without the field (default behavior).
- Render check: `mkdocs build --strict` on the dogfood docs site succeeds with the new runbook added to the nav (best-effort — runbook lives in `docs/host-onboarding/` which is outside `docs/site-src/`, so mkdocs nav is unaffected; the check verifies no incidental damage).

## Files changed

- `templates/config.schema.json` — additive `publishing.ci_provider` enum.
- `templates/hosts/advanced-data-import-system.config.yml` — new host template.
- `tests/fixtures/host_onboarding/advanced-data-import-system/.engineering-docs-agent/config.yml` — new fixture (mirrors the template).
- `tests/fixtures/host_onboarding/advanced-data-import-system/.engineering-docs-agent/state.example.json` — new fixture (standard seed).
- `tests/fixtures/host_onboarding/advanced-data-import-system/README.md` — new fixture (one-line note).
- `tests/setup/test_host_onboarding_fixtures.py` — new test.
- `tests/schemas/test_config_schema.py` — new assertions covering `ci_provider`.
- `docs/host-onboarding/advanced-data-import-system.md` — new runbook.
- `docs/setup-guide.md` — one paragraph addition pointing at the runbook.
- `docs/superpowers/specs/2026-05-29-cce58-onboard-prep-design.md` — this spec.
- `docs/superpowers/plans/2026-05-29-cce58-onboard-prep.md` — plan (follow-up doc).

## Risk

- **`ci_provider` schema addition is forward-looking with no consumer.** Mitigated: documented inline in the schema description as "only `github` implemented". The follow-up sub-ticket reference keeps the gap traceable.
- **Host config template might drift from this host's actual repo layout.** Mitigated: the runbook explicitly tells the user to verify `framework`, `source_dir`, and `whats_new_file` against the host's `docs/` tree before commit. The runbook is host-specific, not normative.
- **CircleCI branch-protection trade-off is opinionated.** Mitigated: both H1 and H2 are documented with trade-offs; H1 is the recommendation, not the only option.

## Out of scope

- `actionlint` workflow setup for this host. Already covered in `docs/setup-guide.md` Part 5; user follows the generic guide for that step.
- Per-PR cost analysis of running CircleCI contexts on docs-agent branches. The runbook calls out the cost qualitatively; quantitative analysis is operational, not setup.
- Detecting hybrid-CI hosts automatically in `setup_discover.py`. The setup skill currently does not enumerate non-GitHub CI providers; adding that is a separate generalization and would be tracked in its own ticket if needed.
- Onboarding the host's TypeScript sub-tree as a separate docs source. Single-lens `core` is sufficient for v1; the spec docs/extractors path is a future enhancement.
