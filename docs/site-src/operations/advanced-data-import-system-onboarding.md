---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/82
synthesized_into: []
---

# Onboarding: advanced-data-import-system (Hybrid CI)

This page documents the plugin-side scaffolding delivered for onboarding `theoju/advanced-data-import-system` as the first **hybrid-CI host**: CircleCI runs user-facing PR checks; GitHub Actions runs the docs-publish workflow. The canonical step-by-step runbook lives at `docs/host-onboarding/advanced-data-import-system.md` (created in PR #82). This page captures what changed on the plugin side and what you still need to do manually on the target repo.

## What PR #82 delivered

PR #82 is purely additive — no changes to `scripts/`, `agents/`, or shared helpers.

**`publishing.ci_provider` config field.** A new enum field on the `publishing` block accepts `'github'` (default) or `'circleci'`. Set it in your host's `.engineering-docs-agent/config.yml`:

```yaml
publishing:
  ci_provider: github   # or circleci
```

The field is declarative only today. The existing `verify_runner.py` publish-verifier targets GitHub Actions unconditionally, so `advanced-data-import-system` works as-is — the CircleCI pipeline never touches the docs-publish path. CCE-63 will make `ci_provider` load-bearing by adding a CircleCI branch to `verify_runner.py`.

**Host config template.** A copy-pasteable config block for `advanced-data-import-system` is included in the runbook. It validates against the production `load_config_validated` contract (covered by the parametrized fixture added in this PR).

**Parametrized fixture.** `tests/fixtures/host_advanced_data_import_system/` holds a minimal host tree that exercises the new config field against `load_config_validated`. Run it with:

```bash
python3 -m pytest tests/ -k advanced_data_import
```

## Manual steps on the target repo

CCE-58 requires the plugin-side scaffolding above to land before you complete the host-side steps. With PR #82 merged, proceed in order:

1. **Install the GitHub App** on `theoju/advanced-data-import-system`. Use the App ID and private key registered during setup.
2. **Add repo secrets**: `CLAUDE_CODE_OAUTH_TOKEN`, `DOCS_DEPLOY_KEY` (or equivalent), plus any Jira vars if Jira enrichment is enabled.
3. **Commit the config.** Copy the template from `docs/host-onboarding/advanced-data-import-system.md` into `.engineering-docs-agent/config.yml` on the target repo's default branch.
4. **Scaffold the docs-publish workflow.** Add a GitHub Actions workflow (not CircleCI) for the publish step. The plugin's `engineering-docs-agent-setup` skill generates a starter workflow you can commit directly.
5. **Set branch protection.** The runbook recommends H1 (require status checks before merging). CircleCI checks apply to user PRs; the docs-publish workflow runs on merge to `main` — these do not conflict, but your branch protection rules need to reference the correct CI provider per check type.

> **Note:** The setup-guide Part 4 hybrid-CI subsection was expected to gain a one-line link to this runbook as part of PR #82, but `docs/setup-guide.md` does not appear in the PR's files-changed list. Verify whether the link landed in a prior commit or add it manually before completing the onboarding.

## Hybrid-CI branch-protection trade-off

The runbook documents the key trade-off: CircleCI status checks cannot be listed in GitHub branch protection by name the same way GitHub Actions checks can. If you enforce required status checks, you must either:

- Use the CircleCI GitHub App integration so the check name appears in the GitHub UI (recommended — H1).
- Or set branch protection to "require at least N approvals" without a named check requirement, accepting that a failed CircleCI build does not block merge.

H1 (named-check enforcement via the CircleCI App) is the recommended path.

## What's pending

| Item | Tracker | Status |
|------|---------|--------|
| `ci_provider` wired into `verify_runner.py` CircleCI branch | CCE-63 | Not started |
| `docs/setup-guide.md` Part 4 hybrid-CI link | — | Verify / add manually |
| Host-side config commit and workflow scaffold | Manual steps above | Blocked on PR #82 merge |

Once CCE-63 lands, the `publishing.ci_provider: circleci` value will control which API the runner queries during publish verification. No config change will be needed on the host — the field you set now will take effect automatically.
