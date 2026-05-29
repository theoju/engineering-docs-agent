# CCE-58 Onboarding Prep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship plugin-side prep for onboarding `theoju/advanced-data-import-system` — additive schema field, host config template, host fixture + validation test, host-specific runbook, single setup-guide paragraph addition.

**Architecture:** Pure prep work, no behavior change. Schema gets one strictly-additive optional field. Fixtures land in a new `tests/fixtures/host_onboarding/<host>/` subtree. Runbook lives in a new `docs/host-onboarding/` subdirectory (outside the mkdocs `site-src/` tree so it doesn't bleed into the rendered docs site). Tests use the existing `load_config_validated` contract — no new helpers.

**Tech Stack:** Python (stdlib + pyyaml + jsonschema, already deps); pytest; markdown.

---

### Task 1: Add `publishing.ci_provider` optional enum to config schema

**Files:**

- Modify: `templates/config.schema.json`
- Test: `tests/schemas/test_config_schema.py`

- [ ] **Step 1: Read current schema to find the publishing block**

Run: `python3 -c "import json; s=json.load(open('templates/config.schema.json')); print(json.dumps(s['properties']['publishing'], indent=2))"`
Expected: shows existing properties (`base_url`, `build_workflow`, `url_map_rule`, `verify_timeout_seconds`, `build_command`, `site_dir`).

- [ ] **Step 2: Write failing tests for the new field**

Append to `tests/schemas/test_config_schema.py`:

```python
def test_publishing_ci_provider_accepts_github():
    cfg = yaml.safe_load(
        """
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/ }
sources: { git: { host: github } }
lint: {}
publishing:
  base_url: https://x
  build_workflow: deploy.yml
  url_map_rule: standard
  ci_provider: github
notifications: {}
"""
    )
    jsonschema.validate(cfg, SCHEMA)


def test_publishing_ci_provider_accepts_circleci():
    cfg = yaml.safe_load(
        """
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/ }
sources: { git: { host: github } }
lint: {}
publishing:
  base_url: https://x
  build_workflow: deploy.yml
  url_map_rule: standard
  ci_provider: circleci
notifications: {}
"""
    )
    jsonschema.validate(cfg, SCHEMA)


def test_publishing_ci_provider_rejects_unknown():
    cfg = yaml.safe_load(
        """
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/ }
sources: { git: { host: github } }
lint: {}
publishing:
  base_url: https://x
  build_workflow: deploy.yml
  url_map_rule: standard
  ci_provider: gitlab
notifications: {}
"""
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(cfg, SCHEMA)
```

- [ ] **Step 3: Run tests to confirm they fail**

Run: `python3 -m pytest tests/schemas/test_config_schema.py -v -k ci_provider`
Expected: `test_publishing_ci_provider_accepts_github` and `_circleci` may pass (extra properties are accepted by default in jsonschema); `_rejects_unknown` will FAIL (gitlab will be accepted because the field isn't declared yet). The key signal is the rejection test failing.

- [ ] **Step 4: Add the field to the schema**

In `templates/config.schema.json`, inside `properties.publishing.properties`, after `site_dir`, add:

```json
"ci_provider": {
  "type": "string",
  "enum": ["github", "circleci"],
  "description": "Which CI provider runs the docs publish workflow. Default `github` (no field present). `circleci` is reserved for a future publish-verifier extension; the field is accepted in config today but only `github` is wired through scripts/verify_runner.py."
}
```

- [ ] **Step 5: Run tests to confirm they pass**

Run: `python3 -m pytest tests/schemas/test_config_schema.py -v -k ci_provider`
Expected: all three new tests PASS.

- [ ] **Step 6: Run the full schema-test module**

Run: `python3 -m pytest tests/schemas/test_config_schema.py -v`
Expected: all existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add templates/config.schema.json tests/schemas/test_config_schema.py
git commit -m "$(cat <<'EOF'
feat(CCE-58): additive publishing.ci_provider schema field

Adds an optional `publishing.ci_provider` enum (`github`|`circleci`,
default `github` when absent) so host configs can declare publish-CI
intent forward-looking. Only `github` is wired in verify_runner.py
today — a follow-up sub-ticket will land the CircleCI variant.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Create host config template for advanced-data-import-system

**Files:**

- Create: `templates/hosts/advanced-data-import-system.config.yml`
- Create: `templates/hosts/README.md`

- [ ] **Step 1: Create the templates/hosts/ directory and README**

Create `templates/hosts/README.md`:

```markdown
# Host config templates

Per-host starting configurations for `engineering-docs-agent`. Each file is a copy-pasteable `.engineering-docs-agent/config.yml` tuned to a specific known host. The corresponding runbook at `docs/host-onboarding/<host>.md` documents which fields the user must review before committing.

Templates here are validated by `tests/setup/test_host_onboarding_fixtures.py` via the production `load_config_validated` contract — anything that lands here passes the same checks the orchestrator runs at startup.
```

- [ ] **Step 2: Create the host template**

Create `templates/hosts/advanced-data-import-system.config.yml`:

```yaml
# Host config template for theoju/advanced-data-import-system (CCE-58).
# Copy this file to .engineering-docs-agent/config.yml in the host repo,
# review every field flagged TODO in docs/host-onboarding/advanced-data-import-system.md,
# then commit.

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
    enabled: false # flip to true and set project_keys if linking to Jira

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
  ci_provider: github # CircleCI gates user PRs but does not publish docs

notifications:
  slack:
    enabled: false
  email:
    enabled: false
```

- [ ] **Step 3: Verify the template parses as valid YAML and validates against schema**

Run:

```bash
python3 -c "
import sys, yaml, json, jsonschema
cfg = yaml.safe_load(open('templates/hosts/advanced-data-import-system.config.yml'))
schema = json.load(open('templates/config.schema.json'))
jsonschema.validate(cfg, schema)
print('OK')
"
```

Expected: prints `OK`.

- [ ] **Step 4: Commit**

```bash
git add templates/hosts/
git commit -m "$(cat <<'EOF'
feat(CCE-58): host config template for advanced-data-import-system

Adds templates/hosts/ with a starting config.yml for the
theoju/advanced-data-import-system host. Hybrid-CI host:
publish workflow is GitHub Actions (docs-deploy.yml) so
ci_provider stays github; CircleCI gates user PRs separately
and is a branch-protection concern, not a verifier concern.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Create host-onboarding fixture

**Files:**

- Create: `tests/fixtures/host_onboarding/advanced-data-import-system/.engineering-docs-agent/config.yml`
- Create: `tests/fixtures/host_onboarding/advanced-data-import-system/.engineering-docs-agent/state.example.json`
- Create: `tests/fixtures/host_onboarding/advanced-data-import-system/README.md`

- [ ] **Step 1: Copy the template into the fixture path**

Run:

```bash
mkdir -p tests/fixtures/host_onboarding/advanced-data-import-system/.engineering-docs-agent
cp templates/hosts/advanced-data-import-system.config.yml \
   tests/fixtures/host_onboarding/advanced-data-import-system/.engineering-docs-agent/config.yml
```

- [ ] **Step 2: Create the state.example.json seed**

Create `tests/fixtures/host_onboarding/advanced-data-import-system/.engineering-docs-agent/state.example.json`:

```json
{
  "version": "1"
}
```

- [ ] **Step 3: Create the fixture README**

Create `tests/fixtures/host_onboarding/advanced-data-import-system/README.md`:

```markdown
# Fixture: advanced-data-import-system

Mirrors the on-disk shape a user committing this host's `.engineering-docs-agent/` directory would land on `main`. Used by `tests/setup/test_host_onboarding_fixtures.py` to validate the config through the production loader. The `config.yml` is a verbatim copy of `templates/hosts/advanced-data-import-system.config.yml`.
```

- [ ] **Step 4: Verify fixture loads under the production loader**

Run:

```bash
python3 -c "
import sys
sys.path.insert(0, 'scripts')
from pathlib import Path
from state_io import load_config_validated
cfg = load_config_validated(Path('tests/fixtures/host_onboarding/advanced-data-import-system/.engineering-docs-agent/config.yml'))
print('lens:', list(cfg['docs']['lens_paths'].keys()))
print('publish:', cfg['publishing']['build_workflow'])
"
```

Expected: prints `lens: ['core']` and `publish: docs-deploy.yml`.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/host_onboarding/
git commit -m "$(cat <<'EOF'
test(CCE-58): host-onboarding fixture for advanced-data-import-system

Mirrors the .engineering-docs-agent/ shape a user would land on main.
Fixture exists so the next task can validate it through the production
load_config_validated contract.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Add validation test for host-onboarding fixtures

**Files:**

- Create: `tests/setup/test_host_onboarding_fixtures.py`

- [ ] **Step 1: Write the test**

Create `tests/setup/test_host_onboarding_fixtures.py`:

```python
"""Validate every directory under tests/fixtures/host_onboarding/ as a host
that could be committed to main. Each fixture's `.engineering-docs-agent/config.yml`
is run through the production loader so any host we ship in a runbook passes the
same checks the orchestrator runs at startup. CCE-58.
"""

from __future__ import annotations
import sys
from pathlib import Path

import pytest

# Make the production scripts package importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from state_io import load_config_validated  # noqa: E402


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "host_onboarding"


def _host_dirs() -> list[Path]:
    if not FIXTURE_ROOT.exists():
        return []
    return sorted(p for p in FIXTURE_ROOT.iterdir() if p.is_dir())


@pytest.mark.parametrize("host_dir", _host_dirs(), ids=lambda p: p.name)
def test_host_config_validates(host_dir: Path) -> None:
    cfg_path = host_dir / ".engineering-docs-agent" / "config.yml"
    assert cfg_path.exists(), f"missing config.yml at {cfg_path}"
    cfg = load_config_validated(cfg_path)

    # Smoke checks: every host fixture must declare the bare minimum the
    # publish-verifier needs.
    assert isinstance(cfg.get("publishing", {}).get("build_workflow"), str)
    assert cfg["publishing"]["build_workflow"].strip()

    # If ci_provider is set, it must be one of the schema-allowed values.
    ci = cfg["publishing"].get("ci_provider")
    if ci is not None:
        assert ci in ("github", "circleci"), f"unexpected ci_provider {ci!r}"


def test_at_least_one_host_fixture_exists() -> None:
    """Guards against an empty fixture tree silently passing the parametrized
    test with zero parameter cases."""
    assert _host_dirs(), "expected at least one host fixture directory"
```

- [ ] **Step 2: Run the test**

Run: `python3 -m pytest tests/setup/test_host_onboarding_fixtures.py -v`
Expected: 2 tests collected, both PASS (`test_at_least_one_host_fixture_exists` + `test_host_config_validates[advanced-data-import-system]`).

- [ ] **Step 3: Commit**

```bash
git add tests/setup/test_host_onboarding_fixtures.py
git commit -m "$(cat <<'EOF'
test(CCE-58): parametrized validation of host_onboarding fixtures

Walks every directory under tests/fixtures/host_onboarding/, loads
each host's .engineering-docs-agent/config.yml through the production
load_config_validated contract, and asserts the publish-verifier
smoke fields are present.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Create host-onboarding runbook

**Files:**

- Create: `docs/host-onboarding/advanced-data-import-system.md`

- [ ] **Step 1: Create the docs/host-onboarding/ directory and runbook**

Create `docs/host-onboarding/advanced-data-import-system.md`:

````markdown
# Host onboarding: theoju/advanced-data-import-system

CCE-58 worked example. Walks the per-host steps from `docs/setup-guide.md` for this specific host. The generic guide owns the explanations; this runbook owns the concrete commands and the per-host decisions baked into `templates/hosts/advanced-data-import-system.config.yml`.

## Pre-flight assumptions

You have completed Part 1 of `docs/setup-guide.md`:

- `claude setup-token` produced an OAuth token starting with `sk-ant-oat`.
- You registered a GitHub App (`docs-agent-bot` or similar), downloaded its private key, and noted the App ID.
- You have admin on `theoju/advanced-data-import-system`.

If any of these are not done, complete `docs/setup-guide.md` Part 1 first.

## Per-host decisions baked into the template

`templates/hosts/advanced-data-import-system.config.yml` ships these choices. Verify each before commit.

| Field                               | Value                                                   | Why                                                                                                 |
| ----------------------------------- | ------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `docs.framework`                    | `mkdocs`                                                | The host's existing `.github/workflows/docs-deploy.yml` is a mkdocs deploy.                         |
| `docs.source_dir`                   | `docs/site-src`                                         | Matches the dogfood pattern; the agent authors into the tree mkdocs publishes.                      |
| `docs.lens_paths.core`              | `docs/site-src/`                                        | Single-lens setup is sufficient for v1.                                                             |
| `publishing.build_workflow`         | `docs-deploy.yml`                                       | The existing GitHub Actions workflow that builds and publishes the site.                            |
| `publishing.base_url`               | `https://theoju.github.io/advanced-data-import-system/` | Default GitHub Pages URL for this repo. Verify against actual Pages settings.                       |
| `publishing.verify_timeout_seconds` | `90`                                                    | Extra slack vs the dogfood `60` because hybrid-CI scheduling adds a few seconds.                    |
| `publishing.ci_provider`            | `github`                                                | Publish CI is GitHub Actions on this host. CircleCI does NOT publish docs — it only gates user PRs. |
| `sources.jira.enabled`              | `false`                                                 | Flip to `true` and set `project_keys` if you want Jira enrichment.                                  |
| `notifications.*.enabled`           | `false`                                                 | Opt in per `docs/setup-guide.md` Part 5.                                                            |

If `mkdocs.yml` lives at a different path than what `docs.source_dir` implies, or the host's GitHub Pages URL is different from the default, adjust the template before commit.

## Hybrid-CI branch-protection trade-off

This host's `main` branch protection currently requires four CircleCI contexts:

- `ci/circleci: backend-lint`
- `ci/circleci: backend-test`
- `ci/circleci: frontend-test`
- `ci/circleci: gcp-id-guard`

Docs-agent PRs will be subject to these required checks like any other PR. You have two options:

### Option H1 (recommended) — leave CircleCI required, accept the CI minutes cost

Keep the four contexts globally required. Docs-only changes don't break backend tests, so the contexts will pass on every docs-agent PR. The merge succeeds; you pay a few CircleCI minutes per nightly run.

This is the recommended path because the contexts run quickly, and the operational surface is zero extra configuration.

### Option H2 — scope the CircleCI contexts to non-`docs-agent/*` heads

Use a branch-protection rule that exempts heads matching `docs-agent/*` from the four CircleCI required checks. Saves the CI minutes but adds a custom protection rule the team must maintain.

Pick H1 unless CircleCI usage cost is a documented constraint.

## Step-by-step install

These map onto `docs/setup-guide.md` Part 2.

### Install the plugin (Part 2.1)

In the host repo's working directory:

```bash
cd ~/Projects/advanced-data-import-system
claude plugin marketplace add /path/to/engineering-docs-agent
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace
```

### Scaffold (Part 2.2)

```bash
claude /engineering-docs-agent-setup
```

When the skill prompts for config, **decline to write a fresh config** if it offers — instead, copy the prepared template:

```bash
cp /path/to/engineering-docs-agent/templates/hosts/advanced-data-import-system.config.yml \
   .engineering-docs-agent/config.yml
```

The skill still writes `.engineering-docs-agent/state.json`, `state.example.json`, and `.github/workflows/docs-agent-nightly.yml`. Verify each lands.

### Install the GitHub App on this repo (Part 2.3)

```bash
# Open the App's install URL in your browser
open https://github.com/settings/apps
# Click your App → Install App → Only select repositories → advanced-data-import-system → Install
```

Verify with:

```bash
gh api repos/theoju/advanced-data-import-system/installation
```

Expected: returns the App installation JSON (not 404).

### Set repo secrets (Part 2.4)

```bash
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo theoju/advanced-data-import-system   # paste the sk-ant-oat token
gh secret set DOCS_AGENT_APP_ID       --repo theoju/advanced-data-import-system   # paste the numeric App ID
gh secret set DOCS_AGENT_APP_PRIVATE_KEY --repo theoju/advanced-data-import-system < /path/to/app-key.pem
```

If you flipped `sources.jira.enabled: true`:

```bash
gh secret set JIRA_API_TOKEN --repo theoju/advanced-data-import-system
gh secret set JIRA_EMAIL     --repo theoju/advanced-data-import-system
```

### Branch protection (Part 2.5)

Per Option H1 above, the existing CircleCI contexts stay required. If you also added the `actionlint` workflow (Part 5 of the generic guide), add it as a required check:

```bash
gh api -X PATCH \
  repos/theoju/advanced-data-import-system/branches/main/protection/required_status_checks \
  --field strict=true \
  --field 'contexts[]=ci/circleci: backend-lint' \
  --field 'contexts[]=ci/circleci: backend-test' \
  --field 'contexts[]=ci/circleci: frontend-test' \
  --field 'contexts[]=ci/circleci: gcp-id-guard' \
  --field 'contexts[]=actionlint'
```

The `PATCH` endpoint REPLACES the contexts list — include every existing context or you lose it. The CircleCI contexts above are copied from the current state observed 2026-05-29; re-check before running.

### Commit and push

```bash
git add .engineering-docs-agent/ .github/workflows/docs-agent-nightly.yml
git commit -m "feat: add engineering-docs-agent nightly pipeline (CCE-58)"
git push
```

## Smoke test (Part 3 of the generic guide)

```bash
gh workflow run docs-agent-nightly.yml -f reason="cce-58 smoke test" --repo theoju/advanced-data-import-system
gh run watch --repo theoju/advanced-data-import-system
```

Success criteria:

1. The run completes (status `success`).
2. A branch `docs-agent/<YYYY-MM-DD>T<HH>` exists on the remote.
3. A PR opens against `main`, authored by your App identity.
4. CI fires on the PR (CircleCI contexts run, actionlint runs if installed).
5. `partial_reasons` is empty in the PR body (or, if non-empty, lists only expected reasons like `jira_auth_missing` if you opted out of Jira).

If the run fails, follow `docs/setup-guide.md` Part 6 (Troubleshooting).

## Known follow-up

The publish-verifier currently polls GitHub Actions via `gh run list`. A future host might want CircleCI to be the docs-publish CI rather than GitHub Actions. That generalization is filed as a follow-up CCE ticket (linked from CCE-58 in Jira). This host does not need it — `docs-deploy.yml` is GitHub Actions and the verifier works as-is.
````

- [ ] **Step 2: Verify the runbook renders as valid markdown**

Run: `python3 -c "
import re, sys
text = open('docs/host-onboarding/advanced-data-import-system.md').read()

# count code fences — should be even

fences = re.findall(r'^\\s\*\\\`\\\`\\\`', text, flags=re.MULTILINE)
print(f'fences: {len(fences)} ({\"OK\" if len(fences) % 2 == 0 else \"UNPAIRED\"})')
"`
Expected: prints an even fence count.

- [ ] **Step 3: Commit**

```bash
git add docs/host-onboarding/
git commit -m "$(cat <<'EOF'
docs(CCE-58): host-onboarding runbook for advanced-data-import-system

Worked-example walkthrough of docs/setup-guide.md Part 2 for the
hybrid-CI host. Documents the per-host decisions baked into the
config template, the CircleCI branch-protection trade-off, and the
post-install smoke test. Generic guide stays generic; per-host
decisions live here.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Update setup-guide hybrid-CI section to link the worked example

**Files:**

- Modify: `docs/setup-guide.md`

- [ ] **Step 1: Read the current hybrid-CI block**

Run: `grep -n "Hybrid CI\|advanced-data-import-system" docs/setup-guide.md`
Expected: identifies the line range of Part 4's Hybrid-CI subsection.

- [ ] **Step 2: Add the worked-example paragraph**

Use Edit on `docs/setup-guide.md`. Replace:

```
This is the path used by `theoju/advanced-data-import-system` (tracked in CCE-58).
```

with:

```
This is the path used by `theoju/advanced-data-import-system` (tracked in CCE-58). For a fully worked example with the concrete commands, see [`docs/host-onboarding/advanced-data-import-system.md`](host-onboarding/advanced-data-import-system.md).
```

- [ ] **Step 3: Verify no other sections changed**

Run: `git diff docs/setup-guide.md | head -30`
Expected: shows only the one-line change above.

- [ ] **Step 4: Commit**

```bash
git add docs/setup-guide.md
git commit -m "$(cat <<'EOF'
docs(CCE-58): link host-onboarding runbook from hybrid-CI section

The generic Part 4 already names this host and CCE-58; add a single
link pointing at the worked example so readers walking the hybrid-CI
path land on the concrete runbook.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Full test sweep + lint

**Files:**

- (verification only)

- [ ] **Step 1: Run full pytest suite**

Run: `python3 -m pytest -q`
Expected: existing pass count + 4 new tests (3 schema + 1 fixture validation, plus 1 sentinel). Zero failures, zero new skips.

- [ ] **Step 2: Confirm no untracked files left over**

Run: `git status`
Expected: clean working tree.

- [ ] **Step 3: Confirm commit history is well-shaped**

Run: `git log --oneline main..HEAD`
Expected: 6 commits, each `feat(CCE-58)` / `test(CCE-58)` / `docs(CCE-58)`.

---

## Self-review

Spec coverage:

- A1 (host template) → Task 2.
- A2 (schema concession) → Task 1.
- B (fixture + test) → Tasks 3, 4.
- C (runbook) → Task 5.
- D (setup-guide edit) → Task 6.
- Sub-ticket for CircleCI verifier → filed via mcp tool outside the plan (handled by orchestration step, not a code task).

Placeholder scan: no TBD/TODO in plan steps. Every code block is fully specified.

Type consistency: schema field name `ci_provider` is consistent across schema, template, fixture, runbook, and tests.
