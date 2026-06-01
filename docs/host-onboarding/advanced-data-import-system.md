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

When the skill prompts for config, decline to write a fresh config if it offers — instead, copy the prepared template:

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
gh variable set DOCS_AGENT_APP_CLIENT_ID --repo theoju/advanced-data-import-system   # paste the OAuth Client ID (Iv1.xxx or Iv23li... format)
gh secret set DOCS_AGENT_APP_PRIVATE_KEY --repo theoju/advanced-data-import-system < /path/to/app-key.pem
```

If you flipped `sources.jira.enabled: true`:

```bash
gh secret set JIRA_API_TOKEN --repo theoju/advanced-data-import-system
gh variable set JIRA_EMAIL   --repo theoju/advanced-data-import-system
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
