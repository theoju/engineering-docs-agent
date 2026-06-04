---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/82
synthesized_into: []
---

# Onboarding theoju/advanced-data-import-system

Concrete runbook for onboarding `theoju/advanced-data-import-system` as a docs-agent host. This host runs a **hybrid CI topology**: CircleCI gates user PRs; GitHub Actions publishes docs. The generic walkthrough lives in [setup-guide.md](../setup-guide.md); this page owns the per-host decisions and commands.

Tracks CCE-58.

## Topology overview

| CI layer | Provider | What it does |
| --- | --- | --- |
| User-PR gating | CircleCI | Runs `backend-lint`, `backend-test`, `frontend-test`, `gcp-id-guard` on every PR |
| Docs publishing | GitHub Actions | `docs-deploy.yml` builds and pushes the MkDocs site to GitHub Pages |

The plugin only needs to integrate with the docs-publish layer. Set `publishing.ci_provider: github` in the host config — the publish-verifier polls GitHub Actions for the deploy workflow result. CircleCI is invisible to the verifier.

## The `ci_provider` config field

PR #82 added `ci_provider` as an additive enum field on the `publishing` block:

```yaml
publishing:
  ci_provider: github   # "github" | "circleci" — default "github"
  build_workflow: docs-deploy.yml
  base_url: https://theoju.github.io/advanced-data-import-system/
  verify_timeout_seconds: 90
```

`ci_provider: github` is the default. Existing host configs without the field continue to work — no schema break. The field is declarative-only today; CCE-63 will make it load-bearing for CircleCI publish targets.

Set `verify_timeout_seconds: 90` instead of the dogfood default `60`. Hybrid-CI scheduling adds a few seconds to the dispatch-to-deploy window.

## Pre-flight

Complete [setup-guide.md Part 1](../setup-guide.md#part-1--one-time-setup-per-claude-code-user) before starting here. You need:

- A Claude OAuth token (`sk-ant-oat…`) stored as `CLAUDE_CODE_OAUTH_TOKEN`.
- A GitHub App with Contents + Pull requests read/write, its private key and Client ID on hand.
- Admin access to `theoju/advanced-data-import-system`.

## Config template

PR #82 ships a ready-made template at `templates/hosts/advanced-data-import-system.config.yml`. Copy it rather than running the interactive setup prompt:

```bash
cp templates/hosts/advanced-data-import-system.config.yml \
   .engineering-docs-agent/config.yml
```

Key fields and why they're set the way they are:

| Field | Value | Reason |
| --- | --- | --- |
| `docs.framework` | `mkdocs` | Host's `docs-deploy.yml` is a MkDocs deploy |
| `docs.source_dir` | `docs/site-src` | Matches the dogfood pattern; agent authors into the tree MkDocs publishes |
| `docs.lens_paths.core` | `docs/site-src/` | Single-lens is sufficient for v1 |
| `publishing.ci_provider` | `github` | GitHub Actions publishes docs; CircleCI does not |
| `publishing.build_workflow` | `docs-deploy.yml` | The existing deploy workflow |
| `publishing.base_url` | `https://theoju.github.io/advanced-data-import-system/` | Default Pages URL — verify against actual Pages settings before commit |
| `publishing.verify_timeout_seconds` | `90` | Extra slack for hybrid-CI scheduling |
| `sources.jira.enabled` | `false` | Flip to `true` and set `project_keys` if you want Jira enrichment |
| `notifications.*.enabled` | `false` | Opt in per setup-guide Part 5 |

Adjust `publishing.base_url` if the Pages URL differs from the default.

## Install steps

### 1. Install the plugin

```bash
cd ~/Projects/advanced-data-import-system
claude plugin marketplace add /path/to/engineering-docs-agent
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace
```

### 2. Scaffold the host

```bash
claude /engineering-docs-agent-setup
```

When the skill offers to write a fresh config, decline. Copy the template instead (see above). The skill still writes `.engineering-docs-agent/state.json`, `state.example.json`, and `.github/workflows/docs-agent-nightly.yml`.

### 3. Install the GitHub App on this repo

Open https://github.com/settings/apps → your App → **Install App** → **Only select repositories** → `advanced-data-import-system` → **Install**.

Verify the installation landed:

```bash
gh api repos/theoju/advanced-data-import-system/installation
```

Expected: the App installation JSON. A 404 means the install step didn't complete.

### 4. Set repo secrets and variables

```bash
gh secret set CLAUDE_CODE_OAUTH_TOKEN \
  --repo theoju/advanced-data-import-system          # paste sk-ant-oat… token

gh variable set DOCS_AGENT_APP_CLIENT_ID \
  --repo theoju/advanced-data-import-system          # paste Iv1.xxx or Iv23li… format

gh secret set DOCS_AGENT_APP_PRIVATE_KEY \
  --repo theoju/advanced-data-import-system < /path/to/app-key.pem
```

If you enabled Jira:

```bash
gh secret set JIRA_API_TOKEN --repo theoju/advanced-data-import-system
gh variable set JIRA_EMAIL   --repo theoju/advanced-data-import-system
```

### 5. Branch protection — CircleCI trade-off

The host's `main` branch requires four CircleCI contexts:

- `ci/circleci: backend-lint`
- `ci/circleci: backend-test`
- `ci/circleci: frontend-test`
- `ci/circleci: gcp-id-guard`

Docs-agent PRs are subject to these checks like any other PR. Pick one option:

**Option H1 (recommended) — leave CircleCI required, accept the CI minutes cost.** Docs-only changes don't break backend tests; the contexts pass and the merge succeeds. No extra configuration.

**Option H2 — exempt `docs-agent/*` heads from CircleCI required checks.** Saves CircleCI minutes but adds a custom protection rule the team must maintain. Choose this only if CI cost is a documented constraint.

If you stay on H1 and have also added `actionlint` (setup-guide Part 5), add it alongside the existing contexts:

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

The `PATCH` endpoint **replaces** the contexts list — include every existing context or you lose it. The CircleCI contexts above reflect the state observed 2026-05-29; re-check before running.

### 6. Commit and push

```bash
git add .engineering-docs-agent/ .github/workflows/docs-agent-nightly.yml
git commit -m "feat: add engineering-docs-agent nightly pipeline (CCE-58)"
git push
```

## Smoke test

```bash
gh workflow run docs-agent-nightly.yml \
  -f reason="cce-58 smoke test" \
  --repo theoju/advanced-data-import-system
gh run watch --repo theoju/advanced-data-import-system
```

Success criteria:

1. The workflow run completes with status `success`.
2. A branch `docs-agent/<YYYY-MM-DD>T<HH>` exists on the remote.
3. A PR opens against `main`, authored by your App identity.
4. CI fires on the PR (CircleCI contexts run; actionlint runs if installed).
5. `partial_reasons` in the PR body is empty, or lists only expected entries like `jira_auth_missing` if you opted out of Jira.

If the run fails, follow setup-guide Part 6 (Troubleshooting).

## Known follow-up

The publish-verifier currently polls GitHub Actions via `gh run list`. This host does not need anything more — `docs-deploy.yml` is GitHub Actions and the verifier works as-is.

CCE-63 will extend the verifier to support `ci_provider: circleci` for hosts where CircleCI also handles docs publishing. The `ci_provider` field added in PR #82 is the forward-looking hook for that work. Existing host configs (including this one) will not need a schema change when CCE-63 lands.
