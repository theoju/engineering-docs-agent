# CCE-80 Host Migration Runbook

Run this for each host repo currently onboarded to engineering-docs-agent
(ADIS, CCSA, data-importer) after CCE-80 merges and the `v0.5.0` tag is cut.

## Pre-merge checklist

- [ ] CCE-80 PR is open, all checks green.
- [ ] Operator has the plugin tree checked out at the CCE-80 feature branch and has run:
  ```bash
  claude plugin add --local /Users/theo/Projects/engineering-docs-agent
  ```
  This makes the setup skill resolve to the feature branch's SKILL.md + scripts.
  After merge, run `claude plugin update engineering-docs-agent` to switch back
  to the main-tracking install.
- [ ] Operator has `gh auth status` confirming authentication to GitHub (V3-I4).

## Post-merge gate

The plugin checkout in `templates/workflow-run.yml` pins `ref: v0.5.0`.
Hosts re-scaffolded BEFORE the tag exists will fail at the plugin-vendoring
checkout step. PR author cuts the tag within 5 minutes of merge:

```bash
gh release create v0.5.0 \
    --target main \
    --title "v0.5.0 — CCE-80 template refresh" \
    --notes "Template absorbs 16 STALE divergences from dogfood nightly. See CCE-80 spec."
gh release view v0.5.0  # verify
```

Do not begin per-host migration until `gh release view v0.5.0` succeeds.

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

- `.github/workflows/docs-agent-nightly.yml` exists. If the pre-CCE-80
  `docs-agent-run.yml` is also present, delete it (`git rm` + commit). The
  legacy `docs-agent-verify.yml` is unrelated and stays.
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

1. Restore `ANTHROPIC_API_KEY` secret if it was already deleted.
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

Wait 24 hours; confirm the next scheduled nightly succeeds. Document
completion in CCE-80 Jira comments.

## Post-runbook cleanup

After ALL hosts complete step 5 and confirm nightly success:

- [ ] Operator runs `claude plugin update engineering-docs-agent` to switch
      back to main-tracking install.
- [ ] CCE-80 Jira ticket transitioned to Done.
