# CCE-80 Host Migration Runbook

Run this for each host repo currently onboarded to engineering-docs-agent
(ADIS, CCSA, data-importer) after CCE-80 merges and the `v0.5.0` tag is cut.

## Pre-merge checklist

- [ ] CCE-80 PR is open, all checks green.
- [ ] Operator has the plugin tree checked out at the CCE-80 feature branch and has run:
  ```bash
  claude plugin add --local <path-to-plugin-checkout>  # e.g. /Users/you/Projects/engineering-docs-agent
  ```
  This makes the setup skill resolve to the feature branch's SKILL.md + scripts.
  After merge, run `claude plugin update engineering-docs-agent` to switch back
  to the main-tracking install.
- [ ] Operator has `gh auth status` confirming authentication to GitHub (V3-I4).

## Post-merge gate

The plugin checkout in `templates/workflow-run.yml` pins `ref: v0.5.0`.
Hosts re-scaffolded BEFORE the tag exists will fail at the plugin-vendoring
checkout step.

First, update the CHANGELOG — it is a release-day artifact, not an afterthought.
Add the entry to `CHANGELOG.md` and commit it on `main` via the release PR so the
tag captures it:

```
## [0.5.0] — 2026-06-04
### Changed
- CCE-80: template/workflow-run.yml parity refresh (OAuth assert, forensics
  upload, run-summary, partial-reasons steps).
```

Then the PR author cuts the tag within 5 minutes of merge:

```bash
gh release create v0.5.0 \
    --target main \
    --title "v0.5.0 — CCE-80 template refresh" \
    --notes "Template sync: OAuth assert, forensics upload, run-summary, partial-reasons steps added. Pin: v0.5.0. See CCE-80 spec for full changelog."
gh release view v0.5.0  # verify
```

Do not begin per-host migration until `gh release view v0.5.0` succeeds.

> **If this release goes bad** — rolling back the tag, the two release clocks
> (validation vs ~24h host pickup), and tag-cut-misfire recovery — see
> [`release-and-rollback.md`](release-and-rollback.md).

## Per-host: ADIS, CCSA, data-importer (in this order)

For each `<host>` in `{adis, ccsa, data-importer}`:

### 1. Provision new secrets/variables

```bash
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo theoju/<host> --body "$OAUTH_TOKEN"
```

Optional (recommended) — register a GitHub App `engineering-docs-agent`:

```bash
gh variable set DOCS_AGENT_APP_CLIENT_ID --repo theoju/<host> --body "$CLIENT_ID"
gh secret set DOCS_AGENT_APP_PRIVATE_KEY --repo theoju/<host> --body-file path/to/private-key.pem
```

Optional (enterprise hosts):

```bash
gh variable set DOCS_AGENT_SKIP_OAUTH_ASSERT --repo theoju/<host> --body "true"
```

**Verify:**

```bash
gh secret list --repo theoju/<host>    # CLAUDE_CODE_OAUTH_TOKEN visible
gh variable list --repo theoju/<host>  # vars set
```

### 2. Re-run setup skill on the host

```bash
cd /path/to/host && claude
> /engineering-docs-agent-setup
```

**Verify:**

- `.github/workflows/docs-agent-nightly.yml` exists. If `docs-agent-run.yml`
  still exists (pre-CCE-80 naming), delete it: `git rm .github/workflows/docs-agent-run.yml && git commit -m "chore: drop legacy docs-agent-run.yml"`.
  The legacy `docs-agent-verify.yml` is unrelated; leave it alone.
- File contains `client-id:`, OAuth-assert step, forensics step, run-summary
  step, Print-partial-reasons step.
- Cron line: `grep -E '^\s+- cron: "[0-9]+ 7 \* \* \*"' .github/workflows/docs-agent-nightly.yml`
  returns a single line with a minute in `[5, 55]`.

### 3. (ADIS only) Re-apply mkdocs install carve-out

ADIS uses mkdocs (CCE-69 deferred). After re-scaffolding, insert this step
IMMEDIATELY AFTER the "Install runtime dependencies" step:

```yaml
- name: Install mkdocs (ADIS-specific; CCE-69 follow-up will absorb)
  run: python -m pip install mkdocs mkdocs-material
```

Commit on the ADIS repo:

```bash
git commit -m "chore(ADIS-DOCS): CCE-80 carve-out — restore mkdocs install pending CCE-69"
```

**Verify:** `actionlint .github/workflows/docs-agent-nightly.yml` clean.

### 4. Verify with manual dispatch

```bash
gh workflow run docs-agent-nightly.yml --repo theoju/<host> -f reason="post-CCE-80 migration verify"
gh run watch --repo theoju/<host>
```

**Verify:**

- OAuth pre-flight passes (no `sk-ant-api*` complaint).
- App-token step runs (or cleanly skips for hosts without the App).
- Forensics artifact uploads (visible in `gh run view --log`).
- Run-summary renders.
- Print-partial-reasons step runs (empty stdout is fine).

**Rollback on failure:**

1. If you already ran Step 5 partially (legacy secret deleted), re-create it:
   `gh secret set ANTHROPIC_API_KEY --repo theoju/<host> --body "$ANTHROPIC_API_KEY"`
   then verify with `gh secret list --repo theoju/<host>`. On a Step 4 failure
   path with Step 5 not yet started, ANTHROPIC_API_KEY is still present — skip
   this item.
2. Revert the workflow file:
   ```bash
   git revert <re-scaffold-commit-sha>
   git push
   ```
3. File a follow-up CCE ticket with the failure mode; halt remaining-host migrations.

### 5. Remove legacy secret (after verification)

```bash
gh secret delete ANTHROPIC_API_KEY --repo theoju/<host>
gh secret list --repo theoju/<host>   # verify removal
```

Wait 24 hours so one unattended scheduled nightly run completes without
the legacy secret. A manual dispatch at this point would not exercise the
same code path, so skipping the wait suppresses the signal. Confirm via
`gh run list --repo theoju/<host> --workflow docs-agent-nightly.yml --limit 1`;
the most recent run must be `success`. Document completion in CCE-80 Jira
comments.

## Post-runbook cleanup

After ALL hosts complete step 5 and confirm nightly success:

- [ ] Operator runs `claude plugin update engineering-docs-agent` to switch
      back to main-tracking install.
- [ ] CCE-80 Jira ticket transitioned to Done.
