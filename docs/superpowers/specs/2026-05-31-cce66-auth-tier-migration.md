---
status: draft
ticket: CCE-66
related: CCE-45, CCE-53, CCE-54, CCE-57, CCE-58
created: 2026-05-31
revised: 2026-05-31 (post-three-reviewer pass — see "Review notes")
---

# CCE-66 — Auth-tier migration: `app-id` → `client-id` + JIRA_EMAIL re-classification

## Goal

Migrate every docs-agent workflow off the deprecated `app-id` input of `actions/create-github-app-token@v3` and onto the canonical `client-id` input, AND re-classify `JIRA_EMAIL` from a Secret to a repo Variable. Both moves correct **the same category error**: non-credential identifiers (public OAuth Client ID, basic-auth username) were being stored as secrets. Apply across the three repos that run the docs-agent nightly today (plugin dogfood + CCSA + ADIS), update the onboarding helper and its tests, sweep all user-facing docs that reference the obsolete names, and add a guard test so the pattern cannot creep back.

## Background

The 2026-05-31 dual-host smoke test (workflow runs [CCSA #26726939558](https://github.com/theoju/claude-code-self-assessment/actions/runs/26726939558) and [ADIS #26727100978](https://github.com/theoju/advanced-data-import-system/actions/runs/26727100978)) surfaced this warning on every run:

```
Input 'app-id' has been deprecated with message: Use 'client-id' instead.
```

Phase 1 of systematic-debugging (root-cause investigation) revealed three things:

1. **The dogfood's own `docs-agent-nightly.yml:52-54` mis-describes the deprecation.** The comment claims `app-id` was "renamed to `app_id`" (a cosmetic hyphen→underscore swap). The actual upstream `action.yml` deprecation is `app-id`→`client-id` — a semantically different App field. `client-id` is the App's OAuth Client ID (format `Iv1.xxxxxxxxxxxxxxxx`, visible on the App's public settings page); `app-id` is the numeric App ID (also public). They are different VALUES, not different SPELLINGS. Anyone sizing the fix from the comment would expect a 1-character edit; the real fix needs new variable values rotated into three repos.

2. **Three live workflows share the same wrong pattern**, all derived from the dogfood:
   - `theoju/engineering-docs-agent` `.github/workflows/docs-agent-nightly.yml:57` (and `:41` for JIRA_EMAIL)
   - `theoju/claude-code-self-assessment` `.github/workflows/docs-agent-nightly.yml:48`
   - `theoju/advanced-data-import-system` `.github/workflows/docs-agent-nightly.yml:53`

3. **The hidden-consumer surface is larger than the workflows.** An exhaustive grep across the plugin repo for `DOCS_AGENT_APP_ID` and `JIRA_EMAIL` (excluding historical specs/plans) surfaced:
   - `scripts/preflight_host.py:80-84` — hardcodes `DOCS_AGENT_APP_ID` in the `required` secrets set returned by `build_secrets_checklist`. After CCE-66, this function would still tell new-host operators to set the obsolete secret.
   - `tests/setup/test_preflight_host.py:36-40` — asserts the same hardcoded set.
   - `docs/site-src/setup-guide.md` — 8 lines (62, 70, 124, 133, 136, 280, 293, 342, 343) reference the obsolete names or describe them as secrets.
   - `docs/site-src/operations/docs-agent-nightly-ci.md:22` — secrets table row.
   - `docs/site-src/operations/docs-agent-nightly-jira-auth.md:16,19,26,33` — table header + YAML snippet + prose all describe `JIRA_EMAIL` as a secret.
   - `docs/host-onboarding/advanced-data-import-system.md:105,113` — `gh secret set` commands for both obsolete names.

The Phase 1 audit of every `secrets.*` reference in the dogfood found exactly two category errors:

| Env / Input                  | Current tier | Reality                                                               | Should be                              |
| ---------------------------- | ------------ | --------------------------------------------------------------------- | -------------------------------------- |
| `CLAUDE_CODE_OAUTH_TOKEN`    | `secrets.`   | OAuth credential for Claude CLI                                       | `secrets.` ✅                          |
| `JIRA_API_TOKEN`             | `secrets.`   | API credential for Jira write                                         | `secrets.` ✅                          |
| `DOCS_AGENT_APP_PRIVATE_KEY` | `secrets.`   | RSA private key                                                       | `secrets.` ✅                          |
| `SLACK_WEBHOOK_URL`          | `secrets.`   | Webhook URL (anyone-with-it can post)                                 | `secrets.` ✅                          |
| `DOCS_AGENT_APP_ID`          | `secrets.`   | Public numeric App ID (visible on App settings page)                  | drop entirely; replaced by `client-id` |
| `JIRA_EMAIL`                 | `secrets.`   | Basic-auth username (visible in every Jira comment, every git commit) | `vars.`                                |

The Jira ticket originally proposed `secrets.DOCS_AGENT_APP_CLIENT_ID`, but upstream's `actions/create-github-app-token@v3` README uses `vars.APP_CLIENT_ID` throughout. Client IDs are OAuth-style identifiers — semi-public by design. Putting them in `secrets.` is a category error that propagates the same misclassification this PR is supposed to fix.

## Approach

**Storage tier per upstream convention.** `client-id` → `vars.DOCS_AGENT_APP_CLIENT_ID`. `JIRA_EMAIL` → `vars.JIRA_EMAIL`. `private-key` stays `secrets.DOCS_AGENT_APP_PRIVATE_KEY`. Both `vars` and `secrets` are independent stores (no shared namespace, no precedence rules), so the old secrets can remain in place during the transition (the workflow that references `vars.X` doesn't care whether `secrets.X` also exists with the old value).

**Vars resolve at job start, not step start.** A workflow run already in flight is not affected by a variable added or changed mid-run — there is no race condition.

**Vars are not masked in logs.** `secrets.*` references are auto-masked by the Actions runtime; `vars.*` references are visible verbatim in step output. Moving `JIRA_EMAIL` to `vars.` makes the email visible in logs, which is not a new exposure (it's already in every Jira comment and git commit author) and is a small debugging improvement (you can see whether the wiring is correct without inspecting repo Settings).

**Vars-first, parallel rollout (Approach A).**

1. **Phase 1 — add variables to all 3 repos** (manual, ~10 min). Old secrets remain.
2. **Phase 1.5 — verify variables exist** before any PR merges. Cheap pre-flight check; closes the silent-failure window.
3. **Phase 2 — open 3 workflow PRs in parallel.** Mechanically identical except the plugin PR also carries the guard test + preflight_host.py update + comment correction + doc updates.
4. **Phase 3 — merge in any order** as each CI goes green. Old + new coexist non-destructively.
5. **Phase 4 — delete obsolete secrets** after a workflow_dispatch run on each repo confirms BOTH the token-mint step succeeds AND Jira enrichment runs (source-collector emits non-empty jira fields, or partial_reasons is empty of `jira_auth_missing`). Pure janitorial.

**Why this over sequential or canary-first:** the three workflows share the same shape; the dogfood doesn't reveal anything host-specific that would justify a canary delay. Sequential serialization buys nothing when each PR is the same 4-line change.

Rejected alternatives:

- **Secret-only swap (rename `DOCS_AGENT_APP_ID` → `DOCS_AGENT_APP_CLIENT_ID` as secret).** Mechanically simplest, but propagates the same category error this PR is supposed to fix.
- **Org-level variable consolidation.** Requires org admin, locks all 3 repos into the same App identity, and makes external-host onboarding harder later. Overkill at 3 repos.
- **Single bundled PR with template refresh (#383).** The template refresh is a full rewrite, not a 4-line input swap. Bundling inflates review surface for no coordination benefit.
- **Hard-cut without secret-stay coexistence.** Delete old secrets in the same PR as the workflow change. One mistype on the new variable value = immediate hard-fail with no fallback.

## What changes

### 1. Workflow edits — three repos

**Plugin: `theoju/engineering-docs-agent/.github/workflows/docs-agent-nightly.yml`** carries three textual changes.

**a) Replace the misleading CCE-54 comment (lines 50-54):**

```yaml
# CCE-54: bumped v1 -> v3 for Node-24 runtime. v1 and v2 both ship on
# Node 20, which GitHub deprecates June 2026; v3 is the first major on
# Node 24.
# CCE-66: v3 deprecates `app-id` in favor of `client-id` — a
# semantically different App field (the OAuth Client ID, format
# Iv1.xxxxxxxxxxxxxxxx, not the numeric App ID). Both inputs work in v3
# today, but only `client-id` appears in upstream examples. Stored as a
# repo Variable (not Secret) because Client IDs are not credentials —
# they are visible on the App's public settings page.
uses: actions/create-github-app-token@v3
```

**b) Swap the input (line 57):**

```diff
        with:
-          app-id: ${{ secrets.DOCS_AGENT_APP_ID }}
+          client-id: ${{ vars.DOCS_AGENT_APP_CLIENT_ID }}
           private-key: ${{ secrets.DOCS_AGENT_APP_PRIVATE_KEY }}
```

**c) Move JIRA_EMAIL to vars (line 41):**

```diff
       JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
-      JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
+      JIRA_EMAIL: ${{ vars.JIRA_EMAIL }}
```

**CCSA host: `theoju/claude-code-self-assessment/.github/workflows/docs-agent-nightly.yml`** — same two input/env swaps as 1b and 1c (no comment to fix). Separate PR.

**ADIS host: `theoju/advanced-data-import-system/.github/workflows/docs-agent-nightly.yml`** — same two input/env swaps as 1b and 1c. Separate PR.

### 2. Onboarding helper — `scripts/preflight_host.py` + tests

`scripts/preflight_host.py:72-91` builds the secrets checklist that the setup skill surfaces during host onboarding. The current `secrets_from_workflow` function force-injects `DOCS_AGENT_APP_ID` into the required set even when the discovered workflow text doesn't reference it. After CCE-66, the workflow text contains `vars.DOCS_AGENT_APP_CLIENT_ID` instead of `secrets.DOCS_AGENT_APP_ID`, so:

- Remove `DOCS_AGENT_APP_ID` from `secrets_from_workflow`'s required set.
- Add a sibling function `variables_from_workflow(workflow_text)` that mirrors the secrets pattern but scans `vars\.([A-Z_]+)` and force-injects the required variables (`DOCS_AGENT_APP_CLIENT_ID`, `JIRA_EMAIL`). Two parallel functions keep each call site single-purpose and avoid `kind`-discriminated branching in the caller.
- Surface the result via a new `variables_checklist` key in `build_report`'s output dict, alongside the existing `secrets_checklist`. Update `render_text` to print both sections under `Required Secrets:` and `Required Variables:` headings.
- The required-variables set seeded by `variables_from_workflow`: `DOCS_AGENT_APP_CLIENT_ID`, `JIRA_EMAIL`.

Update `tests/setup/test_preflight_host.py:36-40` to assert `DOCS_AGENT_APP_ID` is NOT in `secrets_checklist` and both required variables ARE in `variables_checklist`. The test must turn red on a partial migration (e.g., the new function returns variables but the secrets test still expects the obsolete name).

### 3. Guard test — `tests/ci/test_workflow_auth_tier.py` (NEW)

Reuses the existing `WORKFLOWS = [repo .github/workflows/*.yml + templates/workflow-*.yml]` discovery pattern from `test_workflow_node_runtime.py:15-22` so the same harness covers both the dogfood and scaffolded host templates. The new test forward-protects the template refresh (task #383): when the template eventually gains App-token wiring, it must use `client-id` from the start.

Two assertions:

```python
def test_no_workflow_uses_deprecated_app_id_input():
    """CCE-66: actions/create-github-app-token@v3 deprecated `app-id`."""
    offenders = [wf.name for wf in WORKFLOWS if "app-id:" in wf.read_text()]
    assert not offenders, (
        "workflows still use deprecated `app-id:`: " + ", ".join(offenders)
    )


def test_no_workflow_reads_jira_email_as_secret():
    """CCE-66: JIRA_EMAIL is a basic-auth username, not a credential."""
    offenders = [
        wf.name for wf in WORKFLOWS if "secrets.JIRA_EMAIL" in wf.read_text()
    ]
    assert not offenders, (
        "workflows still read JIRA_EMAIL as secret: " + ", ".join(offenders)
    )
```

**TDD red state (before workflow edit):** the dogfood at `.github/workflows/docs-agent-nightly.yml:41` contains `secrets.JIRA_EMAIL` and `:57` contains `app-id:`, so both assertions FAIL red against unmodified main. After the workflow edit in change 1, both PASS.

Templates (`templates/workflow-run.yml`, `workflow-verify.yml`) currently contain neither pattern (verified by grep) — adding the assertions does not require touching the templates today.

### 4. Documentation updates

**`docs/site-src/setup-guide.md`** — eight lines:

| Line | Current                                                                                                   | Change                                                                                                                                                                     |
| ---- | --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 62   | "Note the **App ID** at the top of the General page. You'll need it as `DOCS_AGENT_APP_ID` in each host." | "Note the **App Client ID** (format `Iv1.xxxxxxxxxxxxxxxx`, also visible on the General page). You'll need it as a repo Variable `DOCS_AGENT_APP_CLIENT_ID` in each host." |
| 70   | "Your account email goes in `JIRA_EMAIL`."                                                                | "Your account email goes in `JIRA_EMAIL`, stored as a repo Variable (not Secret) because it is a basic-auth username, not a credential."                                   |
| 124  | App-ID derivation prose                                                                                   | Rewrite to reference Client ID.                                                                                                                                            |
| 133  | Table row for `DOCS_AGENT_APP_ID` (Required Secret)                                                       | Row for `DOCS_AGENT_APP_CLIENT_ID` (Required Variable).                                                                                                                    |
| 136  | Table row for `JIRA_EMAIL` (Optional Secret)                                                              | Move to a Variables section OR add a "Tier" column showing Variable.                                                                                                       |
| 293  | "Fix" example workflow snippet referencing `secrets.DOCS_AGENT_APP_ID`                                    | Rewrite snippet to use `client-id: ${{ vars.DOCS_AGENT_APP_CLIENT_ID }}`.                                                                                                  |
| 342  | Checklist: "Set secrets: ..., `DOCS_AGENT_APP_ID`, ..."                                                   | "Set secrets: `CLAUDE_CODE_OAUTH_TOKEN`, `DOCS_AGENT_APP_PRIVATE_KEY`. Set variables: `DOCS_AGENT_APP_CLIENT_ID`."                                                         |
| 343  | "Set `JIRA_API_TOKEN`, `JIRA_EMAIL` for Jira enrichment" (in Optional checklist)                          | "Set secret `JIRA_API_TOKEN` and variable `JIRA_EMAIL` for Jira enrichment."                                                                                               |

**`docs/site-src/operations/docs-agent-nightly-ci.md:22`** — secrets table row for `DOCS_AGENT_APP_ID`. Replace with a Variables row for `DOCS_AGENT_APP_CLIENT_ID`. Update the surrounding prose if the table header is "Secret only" — split into Secret / Variable columns or two tables.

**`docs/site-src/operations/docs-agent-nightly-jira-auth.md`** — four lines:

- Line 16: table header reads `| Secret | Value |`. Change to `| Auth | Tier | Value |` (or split into two tables) to accommodate the mixed tier.
- Line 19: `JIRA_EMAIL` row — mark as Variable.
- Line 26: YAML snippet `JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}` → `JIRA_EMAIL: ${{ vars.JIRA_EMAIL }}`.
- Line 33: "until the secrets are configured" → "until the credentials are configured" (since it's now mixed-tier).

**`docs/host-onboarding/advanced-data-import-system.md`** — two lines:

- Line 105: `gh secret set DOCS_AGENT_APP_ID --repo theoju/advanced-data-import-system   # paste the numeric App ID` → `gh variable set DOCS_AGENT_APP_CLIENT_ID --repo theoju/advanced-data-import-system   # paste the OAuth Client ID (Iv1.xxx format)`
- Line 113: `gh secret set JIRA_EMAIL ...` → `gh variable set JIRA_EMAIL ...`

Historical entries in `docs/site-src/whats-new.md:18,20`, all `docs/superpowers/specs/2026-05-29-cce57-*.md` and `cce58-*.md`, and `docs/superpowers/plans/2026-05-29-cce5{7,8}-*.md` are NOT updated — those describe past PRs and should preserve the historical record as authored. (The new whats-new entry for CCE-66 lands as part of the next release flow, not this PR diff.)

## What does NOT change

- `templates/workflow-run.yml` and `templates/workflow-verify.yml` — out of scope. These need a full refresh (App-token wiring, OAuth migration, Jira wiring, forensics upload, vendored-plugin path) which is much larger than this PR. Tracked as task #383, to be brainstormed as a separate sub-project. The guard test added here forward-protects whatever the refresh produces.
- The four genuine secrets — `CLAUDE_CODE_OAUTH_TOKEN`, `JIRA_API_TOKEN`, `DOCS_AGENT_APP_PRIVATE_KEY`, `SLACK_WEBHOOK_URL`. They stay in `secrets.` because they are actual credentials.
- The `actions/create-github-app-token@v3` pin — staying on v3. The deprecation is within v3 (warn-level), not "you must move to v4."
- The App itself (docs-agent-bot) — same App ID, same Client ID, same installation, same permissions. We're changing how the workflow REFERS to the App, not the App.
- The orchestrator runtime — no code changes in `scripts/orchestrator_runner.py`. The orchestrator reads `JIRA_EMAIL` from `os.environ`, which is populated identically whether sourced from `vars.` or `secrets.`. `tests/orchestrator/test_jira_env_propagation.py` continues to pass unchanged.
- Agent contract `agents/source-collector.md` — references `JIRA_EMAIL` as an env var; no reference to GitHub Actions tier.
- `README.md` local-shell `export JIRA_EMAIL=...` example — no GitHub Actions context, no update.
- Historical changelog / whats-new entries — preserve as authored.

## Data flow

```
[GitHub Settings → Variables]                    [GitHub Settings → Secrets]
DOCS_AGENT_APP_CLIENT_ID  = "Iv1.xxxxx"         DOCS_AGENT_APP_PRIVATE_KEY = "-----BEGIN..."
JIRA_EMAIL                = "<email>"           CLAUDE_CODE_OAUTH_TOKEN     = "sk-ant-oat..."
                                                JIRA_API_TOKEN              = "ATATT3..."
        │                                                  │
        ▼                                                  ▼
.github/workflows/docs-agent-nightly.yml
  │
  ├─ env.JIRA_EMAIL: vars.JIRA_EMAIL ─────────▶ runner env (visible in logs)
  ├─ env.JIRA_API_TOKEN: secrets.JIRA_API_TOKEN ▶ runner env (masked in logs)
  └─ step.app-token:
       with.client-id: vars.DOCS_AGENT_APP_CLIENT_ID
       with.private-key: secrets.DOCS_AGENT_APP_PRIVATE_KEY
                          │
                          ▼
                   actions/create-github-app-token@v3
                          │
                          ▼
                   GitHub App installation token (1h TTL, ephemeral)
                          │
                          ▼
                   steps.app-token.outputs.token
                          │
                          ▼
                   GH_TOKEN env on "Run nightly authoring" step
```

The only semantic change is the source store of `JIRA_EMAIL` and `DOCS_AGENT_APP_CLIENT_ID`. Downstream consumers (orchestrator, app-token action, git, gh CLI) see identical values.

## Error handling

| Failure                                                              | Where it surfaces                                                                                                                                                                                                       | Recovery                                                                                                                                                   |
| -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Variable missing in target repo at workflow run-time                 | "Generate GitHub App installation token" step fails with `Input required and not supplied: client-id`                                                                                                                   | `gh variable set DOCS_AGENT_APP_CLIENT_ID --repo <r> --body "Iv1.xxx"`. Re-run `gh workflow run docs-agent-nightly.yml --repo <r>`. No code revert needed. |
| `gh variable set` itself fails during Phase 1 (PAT scope, org limit) | Phase 1.5 verification (`gh variable list --repo <r>`) catches the missing variable BEFORE any PR merges.                                                                                                               | Fix the PAT scope or org variable restriction; re-run the failed `gh variable set` call.                                                                   |
| Wrong Client ID value (typo, wrong App)                              | Token mint succeeds; downstream `gh` API calls fail with 401/403 mismatch on the FIRST API call (`git push`, `gh pr create`)                                                                                            | `gh variable set DOCS_AGENT_APP_CLIENT_ID` with correct value. No code revert.                                                                             |
| `JIRA_EMAIL` variable missing                                        | Orchestrator's source-collector emits `jira_auth_missing` in partial_reasons; run completes with `partial: true`. NOT a hard fail.                                                                                      | `gh variable set JIRA_EMAIL --repo <r> --body "<email>"`. Next nightly recovers.                                                                           |
| PR merges on a Friday + no fire pending + cron is days away          | Phase 1.5 pre-merge verification gate catches it. If skipped: silent until the next scheduled fire.                                                                                                                     | Phase 1.5 is the defense; if skipped, the next nightly's failure recovers per the "Variable missing" row above.                                            |
| Old secret already deleted AND new var missing                       | Same as "Variable missing" — Phase 4 is gated on a positive workflow_dispatch verification per repo, precisely to prevent this.                                                                                         | If it happens anyway: re-add the variable; no need to restore the secret.                                                                                  |
| GitHub flips `app-id` to hard-fail mid-rollout                       | Any in-flight host PR's "before-merge" CI would fail at workflow_dispatch verification. Already-merged workflows are fine.                                                                                              | Merge the remaining PRs immediately — they ARE the fix.                                                                                                    |
| Cross-repo rollback inconsistency (plugin reverted, hosts not)       | Plugin's guard test removed by the revert; host workflows still use `vars.DOCS_AGENT_APP_CLIENT_ID`. If Phase 4 has already run, the old secrets are gone, so a host revert would also need to restore the old secrets. | Revert ALL THREE workflow PRs together. If Phase 4 already ran, re-add the old `DOCS_AGENT_APP_ID` and `JIRA_EMAIL` secrets first.                         |
| Guard test catches a future regression                               | `pytest tests/ci/test_workflow_auth_tier.py` fails red on any PR that re-introduces `app-id:` or `secrets.JIRA_EMAIL`.                                                                                                  | Author of the regressing PR rewrites to new tier.                                                                                                          |

No silent-failure mode is introduced. Every error path has a logged signal at either Phase 1.5 gate time, CI time, workflow run-time, or orchestrator partial_reasons time.

## Testing

1. **Failing-first guard tests** (TDD): commit `tests/ci/test_workflow_auth_tier.py` BEFORE the workflow edits. Both new tests FAIL red on the unmodified dogfood — `app-id:` is at `.github/workflows/docs-agent-nightly.yml:57` and `secrets.JIRA_EMAIL` is at `:41`.
2. **preflight_host.py test red-state**: extend `tests/setup/test_preflight_host.py` with two new assertions — (a) `DOCS_AGENT_APP_ID` is absent from `secrets_checklist`; (b) `DOCS_AGENT_APP_CLIENT_ID` and `JIRA_EMAIL` both appear in the new `variables_checklist` payload. Fails red on unmodified `preflight_host.py`; passes after `variables_from_workflow` is added and wired into `build_report` + `render_text`.
3. **Plugin workflow + preflight edits** make all new tests PASS.
4. **Full suite gate**: `python3 -m pytest` returns ≥669 + ~3 new = ≥672 passed, 3 skipped, 0 failed.
5. **CI integrated suite gate** (per CLAUDE.md): on each workflow PR, the actionlint job parses the modified YAML cleanly; pytest 3.11 + 3.12 + diagram-gate all green.
6. **Phase 1.5 pre-merge verification**: `gh variable list --repo <r>` on each repo confirms both `DOCS_AGENT_APP_CLIENT_ID` and `JIRA_EMAIL` exist BEFORE any workflow PR is merged.
7. **Workflow_dispatch verification per repo** (Phase 3): after each PR merges, trigger `gh workflow run docs-agent-nightly.yml --repo <r> -f reason="CCE-66 verify"`. Inspect run logs: (a) "Generate GitHub App installation token" step succeeds; (b) no `app-id` deprecation warning in that step's output; (c) source-collector's Jira enrichment runs and produces non-empty `jira_issues` (or partial_reasons does NOT contain `jira_auth_missing`).
8. **Production-truth gate**: the next 07:07 UTC nightly fires green on all 3 repos with no auth-related `lint_block` / `partial_reasons`.
9. **Phase 4 cleanup verification**: after secrets are deleted, run one more `workflow_dispatch` per repo. Workflows still pass because nothing reads the deleted secrets anymore.

## Migration

Operations are described as a generic runbook with `<owner>/<repo>` placeholders. Today's three installations are listed at the bottom — substitute as appropriate.

**Phase 1 — variables (manual, before any PR merges)**:

```bash
# For each host repo, set BOTH variables. Client ID is one lookup at
# github.com/settings/apps/<your-app-slug> (same value across all hosts
# of the same App).
gh variable set DOCS_AGENT_APP_CLIENT_ID --repo <owner>/<repo> --body "Iv1.xxxxxxxxxxxxxxxx"
gh variable set JIRA_EMAIL --repo <owner>/<repo> --body "<atlassian-email>"
```

**Phase 1.5 — verify (manual, before any PR merges)**:

```bash
# Per repo, confirm both variables are set. The grep gate makes the
# pass criterion machine-checkable.
gh variable list --repo <owner>/<repo> | grep -E "DOCS_AGENT_APP_CLIENT_ID|JIRA_EMAIL"
# Expect TWO lines per repo. Anything else = stop, do not merge.
```

**Phase 2 — workflow PRs (3 PRs, parallelizable)**:

- Plugin PR carries: guard test + preflight_host.py update + workflow edit + comment correction + all doc updates.
- CCSA PR carries: workflow edit only (2 lines).
- ADIS PR carries: workflow edit only (2 lines).

**Phase 3 — merge each PR independently** as its CI goes green. Order does not matter. After each merge, run the workflow_dispatch verification (Testing step 7).

**Phase 4 — secret cleanup** (per repo, after Phase 3 verification passes for THAT repo):

```bash
gh secret delete DOCS_AGENT_APP_ID --repo <owner>/<repo>
gh secret delete JIRA_EMAIL --repo <owner>/<repo>
```

**Today's installations (substitute into `<owner>/<repo>`):**

- `theoju/engineering-docs-agent` — plugin dogfood
- `theoju/claude-code-self-assessment` — CCSA host
- `theoju/advanced-data-import-system` — ADIS host

**Concurrent runs are safe.** Variables and secrets resolve at job start (the moment the runner accepts the job), not at step start. A workflow run already in flight is unaffected by a variable added or changed mid-run. A `workflow_dispatch` verification can fire while a nightly is mid-flight on the OLD wiring without disturbing either.

## Out of scope

- **Refreshing `templates/workflow-run.yml` and `templates/workflow-verify.yml`** — substantially larger; tracked as task #383, separate brainstorm. The guard test added in this PR forward-protects whatever shape the refresh produces.
- **Auditing other secrets across the codebase.** Phase 1 already audited the entire dogfood + host workflows + plugin repo; only `JIRA_EMAIL` and `DOCS_AGENT_APP_ID` are category errors. A broader sweep would yield nothing.
- **Removing `app-id` support from `actions/create-github-app-token@v3` upstream** — that's a GitHub-side change. v3 keeps `app-id` working with a deprecation message.
- **Changing the App itself** — `docs-agent-bot` stays the same App, with the same permissions and installations.
- **Updating CHANGELOG.md / whats-new.md** — done as part of normal release flow, not the PR diff. Historical entries in those files are preserved.
- **Historical specs/plans referencing the old secret names** (`cce57-*`, `cce58-*` in specs/ and plans/) — preserved as authored. Those documents describe past PRs and should not be retroactively edited.
- **Org-level variable consolidation** — overkill at 3 repos; revisit if/when external-host onboarding scales.

## Risks

- **Misread of Client ID at variable-set time.** Easy to typo a Client ID string. Mitigation: the GitHub App settings page lets you copy the value to clipboard; Phase 1.5 verification + Phase 3 workflow_dispatch run catches a wrong value before it affects scheduled nightlies.
- **Forgetting Phase 1.5 verification.** Without the pre-merge gate, a missed variable goes undetected until the next scheduled fire. Mitigation: Phase 1.5 is described as a hard gate (two-line grep output OR stop) — explicit step, not an optional check.
- **Drift re-creeping.** Someone copy-pastes an old workflow snippet that still references `app-id`. Mitigation: the guard test fails CI on any such PR; covers both repo workflows and scaffolded templates.
- **JIRA_EMAIL appearing in logs.** Moving to `vars.` un-masks it. The email is already public via every Jira comment and git commit author, so this is not a new exposure — but the new comment in the workflow documents the visibility expectation for future reviewers.
- **GitHub API outage during Phase 1.** `gh variable set` would fail at API call time. Phase 1.5 verification would surface the missing variable; no merge proceeds. Mitigation: Phase 1 + Phase 1.5 are independent of merge timeline.
- **Cross-repo revert asymmetry.** If only one workflow PR is reverted, the other repos still use the new wiring. Mitigation: error-handling row above documents the all-three-revert protocol; if Phase 4 has run, the old secrets must be re-added first.

## Success criteria

1. All three workflow PRs merge with CI green (actionlint + pytest 3.11/3.12 + diagram-gate).
2. The two new guard tests pass on the plugin's main after merge.
3. The updated `preflight_host.py` returns a checklist that includes `DOCS_AGENT_APP_CLIENT_ID` (variable, required) and excludes `DOCS_AGENT_APP_ID`. Updated test asserts both.
4. Next 07:07 UTC nightly fires successfully on all three repos with no `lint_block`/auth-related `partial_reasons`.
5. Inspection of any post-merge nightly's "Generate GitHub App installation token" step shows no `app-id` deprecation warning.
6. After Phase 4 cleanup, the two stale secrets are absent from all three repos AND a follow-up nightly still succeeds.
7. A new host onboarded after this PR (using `engineering-docs-agent-setup`) receives a checklist that names the correct variable, not the obsolete secret.

## Review notes

Three reviewers ran in parallel on the initial draft of this spec:

- **R1 (technical accuracy)**: caught the wrong Client ID format `Iv23.xxx` (corrected to `Iv1.xxxxxxxxxxxxxxxx` per upstream docs). Confirmed upstream truth, diff fidelity, harness location, var/secret independence.
- **R2 (operational safety)**: caught two hidden consumers (`scripts/preflight_host.py:82`, `docs/site-src/operations/docs-agent-nightly-jira-auth.md:26`); flagged the silent-failure window between PR merge and next scheduled fire; flagged the "one green nightly" Phase 4 gate as insufficient for Jira-enrichment verification.
- **R3 (convention + scope)**: caught the hardcoded `theoju/<repo>` runbook commands violating CLAUDE.md generic-first principle; called for parameterized `<owner>/<repo>` placeholders; flagged the missing Jira ticket link + smoke-test URLs in References; suggested the unifying-principle sentence in Goal.

All Critical and Important findings are addressed in this revision. The spec now:

- Parameterizes Phase 1/4 commands with `<owner>/<repo>`; lists today's installations at the bottom of Migration.
- Adds Phase 1.5 as an explicit pre-merge verification gate (closes the silent-failure window).
- Strengthens Phase 4 gate to require workflow_dispatch confirming both token-mint AND Jira-enrichment success per repo.
- Expands the change list to cover `preflight_host.py` + its test, and adds three additional doc files to the documentation update set.
- Corrects `Iv23.xxx` to `Iv1.xxxxxxxxxxxxxxxx` throughout.
- Adds References for the Jira ticket and the smoke-test runs.
- Names the unifying principle ("non-credential identifiers") in Goal.

## References

- [CCE-66 — Jira ticket](https://designitright.atlassian.net/browse/CCE-66)
- [actions/create-github-app-token — action.yml](https://github.com/actions/create-github-app-token/blob/main/action.yml) — upstream input definitions with `deprecationMessage: "Use 'client-id' instead."` on `app-id`
- [actions/create-github-app-token — README](https://github.com/actions/create-github-app-token#readme) — every example uses `client-id: ${{ vars.APP_CLIENT_ID }}`
- [CCSA smoke-test run 26726939558](https://github.com/theoju/claude-code-self-assessment/actions/runs/26726939558) — surfaced the `app-id` deprecation warning
- [ADIS smoke-test run 26727100978](https://github.com/theoju/advanced-data-import-system/actions/runs/26727100978) — same warning on a parallel host
- `.github/workflows/docs-agent-nightly.yml:41,50-58` — plugin's current dogfood (target of edit + comment correction)
- `scripts/preflight_host.py:78-91` — `build_secrets_checklist` to update
- `tests/setup/test_preflight_host.py:36-40` — assertion to update
- `tests/ci/test_workflow_node_runtime.py:15-22` — harness pattern reused for the new guard test
- `docs/site-src/setup-guide.md` (lines 62, 70, 124, 133, 136, 280, 293, 342, 343) — onboarding instructions to update
- `docs/site-src/operations/docs-agent-nightly-ci.md:22` — operations doc table row to update
- `docs/site-src/operations/docs-agent-nightly-jira-auth.md:16,19,26,33` — Jira auth doc to update
- `docs/host-onboarding/advanced-data-import-system.md:105,113` — onboarding runbook commands to update
- CCE-45 — GitHub App installation token wiring (the work this PR adjusts the storage of)
- CCE-53 — Jira basic-auth wiring (the work this PR re-tiers)
- CCE-54 — v1→v3 Node-24 bump (the PR whose comment this PR corrects)
- Task #383 — templates/workflow-run.yml refresh (separate brainstorm, separate PR)
