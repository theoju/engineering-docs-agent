# GitHub Pages publish target Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the plugin a generic, Node-24-safe GitHub Actions–source Pages deploy — the missing build half of the publish→verify contract — and dogfood it by publishing this repo's own site.

**Architecture:** A scaffolded deploy workflow (`templates/workflow-pages.yml`) builds the docs site (MkDocs-first, `build_command`/`site_dir` fallback), writes `.nojekyll`, and publishes via `upload-pages-artifact`/`deploy-pages` with `configure-pages(enablement:true)`. The setup skill wires `publishing.build_workflow`/`base_url` and only scaffolds when detection says the host can publish. A guard test floors every workflow (repo + templates) at Node-24 action majors.

**Tech Stack:** GitHub Actions (checkout@v5, setup-python@v6, configure-pages@v6, upload-pages-artifact@v5, deploy-pages@v5 — all verified node24/composite), MkDocs Material, Python stdlib + `jsonschema` + `pyyaml`, pytest.

**Spec:** `docs/superpowers/specs/2026-05-26-cce32-github-pages-publish-target-design.md` (commit `c19043e`). **Branch:** `feat/CCE-32-github-pages-publish-target`.

---

## File structure

| File                                                                   | Responsibility                                                                                                           | Tasks   |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------- |
| `tests/ci/test_workflow_node_runtime.py` (modify)                      | Node-24 floor across repo workflows **and** `templates/workflow-*.yml`; Pages-action floors; `.nojekyll`/no-Jekyll guard | 1, 4, 8 |
| `templates/workflow-run.yml`, `templates/workflow-verify.yml` (modify) | Stop scaffolding Node-20 actions to hosts                                                                                | 1       |
| `templates/config.schema.json` (modify)                                | Optional `publishing.build_command` + `site_dir`                                                                         | 2       |
| `templates/workflow-pages.yml` (create)                                | The deploy workflow scaffolded to hosts                                                                                  | 3       |
| `tests/ci/test_workflow_pages_template.py` (create)                    | Template-validity assertions                                                                                             | 3       |
| `scripts/setup_discover.py` (modify)                                   | `derive_pages_base_url()`, `detect_pages_publishable()`, discover output                                                 | 5       |
| `tests/setup/test_setup_discover.py` (modify)                          | Detection + base_url derivation tests                                                                                    | 5, 6    |
| `skills/engineering-docs-agent-setup/SKILL.md` (modify)                | Document writing the pages workflow + `publishing.*`                                                                     | 6       |
| `mkdocs.yml`, `docs/site-src/**` (create)                              | Minimal dogfood site                                                                                                     | 7       |
| `.github/workflows/docs-pages.yml` (create)                            | This repo's deploy workflow                                                                                              | 8       |
| Pages source switch (operational)                                      | Stop legacy Jekyll on this repo                                                                                          | 9       |
| Live validation                                                        | Deploy + C3 site-gate activation                                                                                         | 10      |

**Sub-plan 1 (generic capability): Tasks 1–6. Sub-plan 2 (dogfood): Tasks 7–10.**

Note on test runner: use `python3 -m pytest` (local Python 3.9). The guard/template/discover tests are pure stdlib + `pyyaml`/`jsonschema`.

---

# Sub-plan 1 — Generic capability

### Task 1: Bump scaffolded templates to Node-24 + extend guard to templates

**Files:**

- Modify: `tests/ci/test_workflow_node_runtime.py`
- Modify: `templates/workflow-run.yml:25,28`
- Modify: `templates/workflow-verify.yml` (checkout/setup-python lines)

- [ ] **Step 1: Extend the guard to scan workflow templates**

In `tests/ci/test_workflow_node_runtime.py`, replace the `WORKFLOWS` definition:

```python
ROOT = Path(__file__).resolve().parents[2]
_WF_DIR = ROOT / ".github" / "workflows"
_TPL_DIR = ROOT / "templates"
# Repo workflows + scaffolded workflow templates (templates/workflow-*.yml).
# Templates are copied verbatim to host repos, so they must meet the same floor.
WORKFLOWS = sorted(
    [*_WF_DIR.glob("*.yml"), *_WF_DIR.glob("*.yaml"), *_TPL_DIR.glob("workflow-*.yml")]
)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/ci/test_workflow_node_runtime.py -q`
Expected: FAIL — `workflow-run.yml: actions/checkout@v4 (needs >= v5)` and `actions/setup-python@v5 (needs >= v6)`, same for `workflow-verify.yml`.

- [ ] **Step 3: Bump the two templates**

In `templates/workflow-run.yml`: `actions/checkout@v4` → `@v5`, `actions/setup-python@v5` → `@v6`.
In `templates/workflow-verify.yml`: same two substitutions.

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/ci/test_workflow_node_runtime.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add tests/ci/test_workflow_node_runtime.py templates/workflow-run.yml templates/workflow-verify.yml
git commit -m "fix(CCE-32): scaffolded workflow templates to Node-24 majors + guard them"
```

---

### Task 2: Optional `build_command` + `site_dir` in the config schema

**Files:**

- Modify: `templates/config.schema.json:85-90` (publishing.properties)
- Test: `tests/schemas/test_config_publishing_fallback.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/schemas/test_config_publishing_fallback.py
import json
from pathlib import Path
import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "templates" / "config.schema.json").read_text())

def _publishing(extra):
    base = {"base_url": "https://x.github.io/r/", "build_workflow": "docs-agent-pages.yml", "url_map_rule": "directory"}
    base.update(extra)
    return base

def test_build_command_and_site_dir_are_accepted():
    pub = _publishing({"build_command": "npm run build", "site_dir": "build"})
    jsonschema.validate(pub, SCHEMA["properties"]["publishing"])

def test_publishing_still_requires_core_fields():
    with_missing = {"build_command": "x"}  # no base_url/build_workflow/url_map_rule
    try:
        jsonschema.validate(with_missing, SCHEMA["properties"]["publishing"])
        assert False, "expected ValidationError for missing required fields"
    except jsonschema.ValidationError:
        pass
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/schemas/test_config_publishing_fallback.py -q`
Expected: `test_build_command_and_site_dir_are_accepted` PASSES already (draft-07 allows unknown props by default), `test_publishing_still_requires_core_fields` PASSES. If both already pass, the schema does not yet _document_ the fields — proceed to Step 3 to make them explicit (the test's intent is to lock the documented shape).

- [ ] **Step 3: Add the two optional properties**

In `templates/config.schema.json`, the `publishing.properties` object becomes:

```json
"properties": {
  "base_url": { "type": "string" },
  "build_workflow": { "type": "string" },
  "url_map_rule": { "type": "string" },
  "verify_timeout_seconds": { "type": "integer" },
  "build_command": {
    "type": "string",
    "description": "Generic fallback build command for non-MkDocs hosts. Omit for MkDocs (the deploy workflow runs `mkdocs build --strict`)."
  },
  "site_dir": {
    "type": "string",
    "description": "Built-site directory to publish. Default `site` (MkDocs)."
  }
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/schemas/test_config_publishing_fallback.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add templates/config.schema.json tests/schemas/test_config_publishing_fallback.py
git commit -m "feat(CCE-32): publishing.build_command + site_dir (generic build fallback)"
```

---

### Task 3: The deploy workflow template + validity test

**Files:**

- Create: `templates/workflow-pages.yml`
- Test: `tests/ci/test_workflow_pages_template.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/ci/test_workflow_pages_template.py
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
TPL = ROOT / "templates" / "workflow-pages.yml"

def test_template_exists():
    assert TPL.exists(), "templates/workflow-pages.yml must exist"

def test_required_permissions_and_actions():
    text = TPL.read_text()
    data = yaml.safe_load(text)
    perms = data["permissions"]
    assert perms.get("pages") == "write"
    assert perms.get("id-token") == "write"
    for pin in ("actions/checkout@v5", "actions/configure-pages@v6",
                "actions/setup-python@v6", "actions/upload-pages-artifact@v5",
                "actions/deploy-pages@v5"):
        assert pin in text, f"missing pinned action {pin}"

def test_enablement_and_nojekyll_and_no_jekyll_build():
    text = TPL.read_text()
    assert "enablement: true" in text
    assert ".nojekyll" in text
    # Must not rely on the legacy Jekyll build path.
    assert "jekyll" not in text.lower()

def test_default_build_workflow_filename_is_the_scaffold_target():
    # The setup skill writes this file as docs-agent-pages.yml and sets
    # publishing.build_workflow to that name; keep the contract visible.
    assert "docs-agent-pages.yml" in TPL.read_text()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/ci/test_workflow_pages_template.py -q`
Expected: FAIL — file does not exist.

- [ ] **Step 3: Create the template**

```yaml
# templates/workflow-pages.yml — GitHub Pages deploy (GitHub Actions source)
# Drop into the host repo at .github/workflows/docs-agent-pages.yml
# MkDocs-first. For a non-MkDocs host the setup skill rewrites the "Build site"
# step to run publishing.build_command and the artifact path to publishing.site_dir.
name: docs-agent pages

on:
  push:
    branches: [main]
    paths:
      - "docs/**"
      - "mkdocs.yml"
      - ".github/workflows/docs-agent-pages.yml"
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
        with:
          enablement: true
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
      - name: Build site
        run: |
          pip install mkdocs-material
          mkdocs build --strict
      - name: Disable Jekyll on the built artifact
        run: touch site/.nojekyll
      - uses: actions/upload-pages-artifact@v5
        with:
          path: site
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

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/ci/test_workflow_pages_template.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add templates/workflow-pages.yml tests/ci/test_workflow_pages_template.py
git commit -m "feat(CCE-32): workflow-pages.yml deploy template + validity test"
```

---

### Task 4: Pages-action floors + `.nojekyll`/no-Jekyll guard

**Files:**

- Modify: `tests/ci/test_workflow_node_runtime.py`

- [ ] **Step 1: Add Pages floors and a Jekyll-disabled assertion**

Extend `NODE24_FLOOR` and add a new test:

```python
NODE24_FLOOR = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/configure-pages": 6,
    "actions/deploy-pages": 5,
}

def test_pages_deploy_workflows_disable_jekyll():
    """Any workflow that deploys Pages must publish the artifact verbatim
    (.nojekyll) and never invoke the legacy Jekyll build."""
    offenders = []
    for wf in WORKFLOWS:
        text = wf.read_text()
        if "actions/deploy-pages" not in text:
            continue
        if ".nojekyll" not in text:
            offenders.append(f"{wf.name}: deploys Pages but never writes .nojekyll")
        if "jekyll" in text.lower().replace(".nojekyll", ""):
            offenders.append(f"{wf.name}: references legacy Jekyll")
    assert not offenders, "\n".join(offenders)
```

- [ ] **Step 2: Run to verify it passes against the correct template**

Run: `python3 -m pytest tests/ci/test_workflow_node_runtime.py -q`
Expected: PASS — `templates/workflow-pages.yml` (from Task 3) satisfies both the floor and the `.nojekyll`/no-Jekyll checks.

- [ ] **Step 3: Prove the guard bites (temporary negative check)**

Temporarily edit `templates/workflow-pages.yml` to `actions/deploy-pages@v4`, run the test, confirm FAIL with `deploy-pages@v4 (needs >= v5)`, then revert. (Do not commit the temporary edit.)

Run: `python3 -m pytest tests/ci/test_workflow_node_runtime.py -q` (after revert) → PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/ci/test_workflow_node_runtime.py
git commit -m "test(CCE-32): guard Pages action floors + .nojekyll/no-Jekyll"
```

---

### Task 5: Detection helpers in `setup_discover.py`

**Files:**

- Modify: `scripts/setup_discover.py`
- Test: `tests/setup/test_setup_discover.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/setup/test_setup_discover.py`:

```python
from setup_discover import derive_pages_base_url, detect_pages_publishable

def test_base_url_project_site():
    assert derive_pages_base_url("theoju", "engineering-docs-agent") == "https://theoju.github.io/engineering-docs-agent/"

def test_base_url_user_site():
    assert derive_pages_base_url("theoju", "theoju.github.io") == "https://theoju.github.io/"

def test_base_url_custom_domain():
    assert derive_pages_base_url("theoju", "r", "docs.example.com") == "https://docs.example.com/"

def test_pages_publishable_only_mkdocs_on_actions():
    assert detect_pages_publishable("mkdocs", "github_actions") is True
    assert detect_pages_publishable("docusaurus", "github_actions") is False
    assert detect_pages_publishable("mkdocs", "gitlab_ci") is False
    assert detect_pages_publishable(None, "github_actions") is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/setup/test_setup_discover.py -q`
Expected: FAIL — `ImportError: cannot import name 'derive_pages_base_url'`.

- [ ] **Step 3: Implement the helpers**

Add to `scripts/setup_discover.py` (before `discover`):

```python
def derive_pages_base_url(owner: str, repo: str, cname: str | None = None) -> str:
    """Project site -> https://<owner>.github.io/<repo>/; user/org site
    (repo named <owner>.github.io) -> https://<owner>.github.io/; custom
    domain (CNAME) -> https://<cname>/."""
    if cname:
        return f"https://{cname.strip().rstrip('/')}/"
    if repo.lower() == f"{owner.lower()}.github.io":
        return f"https://{owner}.github.io/"
    return f"https://{owner}.github.io/{repo}/"


def detect_pages_publishable(framework: str | None, ci: str | None) -> bool:
    """True when the host can be auto-scaffolded for Pages deploy: MkDocs on
    GitHub Actions. Other frameworks need a config build_command (handled by
    the setup skill), so they are not auto-publishable here."""
    return ci == "github_actions" and framework == "mkdocs"
```

In `discover()`, add to the `out` dict (after `ci` is computed):

```python
        "pages_publishable": detect_pages_publishable(framework, ci),
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/setup/test_setup_discover.py -q`
Expected: PASS (existing tests + 4 new).

- [ ] **Step 5: Commit**

```bash
git add scripts/setup_discover.py tests/setup/test_setup_discover.py
git commit -m "feat(CCE-32): setup_discover pages_publishable + base_url derivation"
```

---

### Task 6: Setup-skill wiring (prose) + discover-output fixture test

**Files:**

- Modify: `skills/engineering-docs-agent-setup/SKILL.md:33`
- Test: `tests/setup/test_setup_discover.py`

- [ ] **Step 1: Write the failing fixture test**

Append to `tests/setup/test_setup_discover.py`:

```python
def test_discover_reports_pages_publishable_for_mkdocs_actions(tmp_path):
    (tmp_path / "mkdocs.yml").write_text("site_name: x\n")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    from setup_discover import discover
    out = discover(tmp_path)
    assert out["pages_publishable"] is True

def test_discover_not_publishable_without_framework(tmp_path):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    from setup_discover import discover
    out = discover(tmp_path)
    assert out["pages_publishable"] is False
```

- [ ] **Step 2: Run to verify it fails (or passes if Task 5 wired discover)**

Run: `python3 -m pytest tests/setup/test_setup_discover.py -q`
Expected: PASS if Task 5's `discover()` change landed; if `pages_publishable` is missing from `discover()`, FAIL with `KeyError` — fix by ensuring the Task 5 Step 3 `discover()` edit is present.

- [ ] **Step 3: Document the wiring in SKILL.md**

In `skills/engineering-docs-agent-setup/SKILL.md`, extend step 6 (and add a step 6a). Replace the step-6 line with:

```markdown
6. Write `.engineering-docs-agent/config.yml`, `.engineering-docs-agent/state.json` (initial), `.github/workflows/docs-agent-run.yml`, `.github/workflows/docs-agent-verify.yml`, optionally `docs-agent-glossary.yml`.
   6a. If discovery's `pages_publishable` is true (MkDocs + GitHub Actions) OR the user supplied a `publishing.build_command`, also write `.github/workflows/docs-agent-pages.yml` from `templates/workflow-pages.yml`. For a non-MkDocs host, substitute the "Build site" run step with the `build_command` and the `upload-pages-artifact` `path:` with `publishing.site_dir`. Set `publishing.build_workflow: docs-agent-pages.yml` and `publishing.base_url` via `derive_pages_base_url(owner, repo, cname)`. If neither condition holds, skip the pages workflow and print: "Pages deploy not scaffolded (no MkDocs site and no publishing.build_command) — add one to enable publishing." `configure-pages(enablement:true)` sets the repo's Pages source to GitHub Actions on first run.
```

- [ ] **Step 4: Run the full sub-plan-1 surface**

Run: `python3 -m pytest tests/ci tests/setup tests/schemas -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/engineering-docs-agent-setup/SKILL.md tests/setup/test_setup_discover.py
git commit -m "feat(CCE-32): setup skill scaffolds pages workflow + wires publishing.*"
```

---

# Sub-plan 2 — Dogfood this repo

### Task 7: Bootstrap a minimal MkDocs site

**Files:**

- Create: `mkdocs.yml`, `docs/site-src/index.md` (+ minimal section pages via scaffolder)

- [ ] **Step 1: Run the scaffolder**

Run: `python3 scripts/setup_scaffold.py --repo-root . --site-name "engineering-docs-agent"`
Expected: writes `mkdocs.yml` and `docs/site-src/` (sections + grid-card home + `.pages`).

- [ ] **Step 2: Install docs deps and build strict**

Run: `pip install -r requirements-docs.txt && mkdocs build --strict`
Expected: builds to `site/` with **zero** warnings (––strict fails on any). If a scaffolded section has an empty/broken nav entry, trim `mkdocs.yml`/`docs/site-src/` to a minimal home + one section until `--strict` is clean. Keep no `mermaid` on these pages (so the C3 diagram gate passes trivially).

- [ ] **Step 3: Confirm the C3 site-gate now activates locally**

Run: `python3 scripts/verify_diagrams.py --site-dir site --source-dir docs/site-src --json`
Expected: ledger with `self_test.ok true`, `failures: []` (no diagrams → trivially passes). If Playwright is absent locally it skips — that is fine; CI runs it.

- [ ] **Step 4: Commit**

```bash
git add mkdocs.yml docs/site-src
git commit -m "feat(CCE-32): bootstrap minimal MkDocs site (dogfood)"
```

---

### Task 8: This repo's deploy workflow

**Files:**

- Create: `.github/workflows/docs-pages.yml`

- [ ] **Step 1: Create the workflow (reuses requirements-docs.txt)**

```yaml
name: docs-pages
on:
  push:
    branches: [main]
    paths:
      - "docs/site-src/**"
      - "mkdocs.yml"
      - "requirements-docs.txt"
      - ".github/workflows/docs-pages.yml"
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
        with:
          enablement: true
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - name: Build site
        run: |
          pip install -r requirements-docs.txt
          mkdocs build --strict
      - name: Disable Jekyll on the built artifact
        run: touch site/.nojekyll
      - uses: actions/upload-pages-artifact@v5
        with:
          path: site
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

- [ ] **Step 2: Confirm guards cover it**

Run: `python3 -m pytest tests/ci -q`
Expected: PASS — `docs-pages.yml` meets the Node-24 floor, writes `.nojekyll`, no Jekyll. (`test_pages_deploy_workflows_disable_jekyll` now also exercises this real workflow.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/docs-pages.yml
git commit -m "feat(CCE-32): docs-pages.yml — deploy this repo's site to Pages"
```

---

### Task 9: Switch this repo's Pages source to GitHub Actions

**Files:** none (operational settings change — **requires explicit user authorization at execution time**; it is a settings change).

- [ ] **Step 1: Confirm current (broken) state**

Run: `gh api repos/theoju/engineering-docs-agent/pages --jq '.build_type, .source'`
Expected: `legacy` / `{branch: main, path: /}` (the failing config).

- [ ] **Step 2: Switch source to GitHub Actions**

Run: `gh api -X PUT repos/theoju/engineering-docs-agent/pages -f build_type=workflow`
Expected: 204/200. This stops the legacy `pages-build-deployment` (Jekyll) from triggering. (`configure-pages(enablement:true)` in `docs-pages.yml` keeps it set on each deploy.)

- [ ] **Step 3: Verify the legacy build no longer fires**

Run: `gh api repos/theoju/engineering-docs-agent/pages --jq '.build_type'`
Expected: `workflow`.

No commit (settings change, not a file).

---

### Task 10: Live-deploy validation

**Files:** none (post-merge validation).

- [ ] **Step 1: After the branch merges to main, watch the deploy**

Run: `gh run list --workflow=docs-pages.yml --limit 3`
Expected: a `docs-pages` run, conclusion `success` (build + deploy jobs green on Node 24).

- [ ] **Step 2: Confirm the site is live**

Run: `gh api repos/theoju/engineering-docs-agent/pages/builds/latest --jq '.status'` and fetch `https://theoju.github.io/engineering-docs-agent/`
Expected: status not `errored`; the home page returns 200.

- [ ] **Step 3: Confirm C3 site-gate now runs (no longer skipped)**

Run: `gh run list --workflow=docs.yml --limit 1` then inspect the run
Expected: the "Build the docs site" + "Diagram render gate" steps execute (mkdocs.yml now present), not the `present == 'false'` skip path.

- [ ] **Step 4: No Node-20 annotations anywhere**

Run: `gh run view <docs-pages run id>` and confirm no Node.js 20 deprecation annotation.

---

## Self-review

**1. Spec coverage.**

- Approach A workflow (configure-pages@v6/deploy-pages@v5/.nojekyll/self-enable) → Task 3 (template), Task 8 (dogfood). ✓
- MkDocs-first + `build_command`/`site_dir` fallback → Task 2 (schema) + Task 6 (SKILL.md substitution prose). ✓
- Self-enable (decision 1) → `enablement: true` in Tasks 3, 8; guard for it in Task 3. ✓
- Setup wiring `publishing.build_workflow`/`base_url` + detection gating → Tasks 5, 6. ✓
- Guard extension (Pages floors, templates glob, `.nojekyll`/no-Jekyll) → Tasks 1, 4. ✓
- Bump existing scaffolded templates → Task 1. ✓
- Dogfood site + workflow + source switch + live validation + C3 activation → Tasks 7–10. ✓
- `base_url` derivation edge cases (risk) → Task 5 tests. ✓

**2. Placeholder scan.** No "TBD"/"add error handling"/"similar to". `<docs run id>` in Task 10 Step 4 is a runtime value the executor reads from Step 1, not a plan gap.

**3. Type/name consistency.** `derive_pages_base_url(owner, repo, cname=None)` and `detect_pages_publishable(framework, ci)` are referenced identically in Tasks 5 and 6. `pages_publishable` discover key consistent across Tasks 5/6. `site_dir`/`build_command` consistent across Tasks 2/6. Workflow filename `docs-agent-pages.yml` (scaffolded) vs `docs-pages.yml` (this repo) are intentionally distinct and used consistently.

---

## Execution coda

Subagent-driven-development, model selection: Tasks 1, 7, 8 mechanical (cheap); Tasks 2, 3, 4, 5, 6 standard; Task 9/10 operational (controller runs directly — settings change + live checks). Final whole-branch review (opus). Then `/ship` base `main` **per sub-plan** (land sub-plan 1, re-test, then sub-plan 2). **Pause before merge unless told otherwise.** Task 9's settings change needs explicit user authorization at execution time.
