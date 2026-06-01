---
status: draft
ticket: CCE-66
related: CCE-45, CCE-53, CCE-54, CCE-57, CCE-58
created: 2026-05-31
---

# CCE-66 — Auth-tier migration: `app-id` → `client-id` + JIRA_EMAIL re-classification

## Goal

Migrate every docs-agent workflow off the deprecated `app-id` input of `actions/create-github-app-token@v3` and onto the canonical `client-id` input, AND re-classify `JIRA_EMAIL` from a Secret to a repo Variable. Both moves correct the same category error: non-credential identifiers were being stored as secrets. Apply across the three repos that run the docs-agent nightly today (plugin dogfood + CCSA + ADIS) and add a guard test so the pattern cannot creep back.

## Background

The 2026-05-31 dual-host smoke test surfaced this warning on every workflow run:

```
Input 'app-id' has been deprecated with message: Use 'client-id' instead.
```

Phase 1 of systematic-debugging (root-cause investigation) revealed two things:

1. **The dogfood's own `docs-agent-nightly.yml:52-54` mis-describes the deprecation.** The comment claims `app-id` was "renamed to `app_id`" (a cosmetic hyphen→underscore swap). The actual upstream `action.yml` deprecation is `app-id`→`client-id` — a semantically different App field. `client-id` is the App's OAuth Client ID (format `Iv23.xxx`, visible on the App's public settings page); `app-id` is the numeric App ID (also public). They are different VALUES, not different SPELLINGS. Anyone sizing the fix from the comment would expect a 1-character edit; the real fix needs new variable values rotated into three repos.

2. **Three live workflows share the same wrong pattern**, all derived from the dogfood:
   - `theoju/engineering-docs-agent` `.github/workflows/docs-agent-nightly.yml:57`
   - `theoju/claude-code-self-assessment` `.github/workflows/docs-agent-nightly.yml:48`
   - `theoju/advanced-data-import-system` `.github/workflows/docs-agent-nightly.yml:53`

Each carries `app-id: ${{ secrets.DOCS_AGENT_APP_ID }}` plus a parallel `JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}` env wire (CCE-53). The Phase 1 audit of every `secrets.*` reference in the dogfood found exactly two category errors:

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

**Storage tier per upstream convention.** `client-id` → `vars.DOCS_AGENT_APP_CLIENT_ID`. `JIRA_EMAIL` → `vars.JIRA_EMAIL`. `private-key` stays `secrets.DOCS_AGENT_APP_PRIVATE_KEY`. Both `vars` and `secrets` are independent stores, so the old secrets can remain in place during the transition (the workflow that references `vars.X` doesn't care whether `secrets.X` also exists with the old value).

**Vars-first, parallel rollout (Approach A).**

1. **Phase 1 — add variables to all 3 repos** (manual, ~10 min). Old secrets remain.
2. **Phase 2 — open 3 workflow PRs in parallel.** Mechanically identical except the plugin PR also carries the guard test + comment correction + docs updates.
3. **Phase 3 — merge in any order** as each CI goes green. Old + new coexist non-destructively.
4. **Phase 4 — delete obsolete secrets** after the next nightly fires green on the new wiring across all 3 repos. Pure janitorial.

**Why this over sequential or canary-first:** the three workflows share the same shape; the dogfood doesn't reveal anything host-specific that would justify a canary delay. Sequential serialization buys nothing when each PR is the same 4-line change.

Rejected alternatives:

- **Secret-only swap (rename `DOCS_AGENT_APP_ID` → `DOCS_AGENT_APP_CLIENT_ID` as secret).** Mechanically simplest, but propagates the same category error this PR is supposed to fix. Future readers see `secrets.DOCS_AGENT_APP_CLIENT_ID` and either treat it as sensitive (unnecessary mental tax) or learn it's not (a recurring "why is this a secret?" question). Misses the broader hygiene point.
- **Org-level variable consolidation.** Define once at org level for all 3 repos. Requires org admin, locks all 3 repos into the same App identity, and makes external-host onboarding harder later. Overkill at 3 repos.
- **Single bundled PR with template refresh (#383).** The template refresh is a full rewrite, not a 4-line input swap. Bundling inflates review surface for no coordination benefit.
- **Hard-cut without secret-stay coexistence.** Delete old secrets in the same PR as the workflow change. One mistype on the new variable value = immediate hard-fail with no fallback. The free safety margin of keeping the old secret around for one nightly cycle isn't worth giving up.

## What changes

### 1. Plugin workflow — `theoju/engineering-docs-agent/.github/workflows/docs-agent-nightly.yml`

Three textual changes.

**a) Replace the misleading CCE-54 comment (lines ~50-54):**

```yaml
# CCE-54: bumped v1 -> v3 for Node-24 runtime. v1 and v2 both ship on
# Node 20, which GitHub deprecates June 2026; v3 is the first major on
# Node 24.
# CCE-66: v3 deprecates `app-id` in favor of `client-id` — a
# semantically different App field (the OAuth Client ID, format
# Iv23.xxx, not the numeric App ID). Both inputs work in v3 today, but
# only `client-id` appears in upstream examples. Stored as a repo
# Variable (not Secret) because Client IDs are not credentials — they
# are visible on the App's public settings page.
uses: actions/create-github-app-token@v3
```

**b) Swap the input (line ~57):**

```diff
        with:
-          app-id: ${{ secrets.DOCS_AGENT_APP_ID }}
+          client-id: ${{ vars.DOCS_AGENT_APP_CLIENT_ID }}
           private-key: ${{ secrets.DOCS_AGENT_APP_PRIVATE_KEY }}
```

**c) Move JIRA_EMAIL to vars (line ~41):**

```diff
       JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
-      JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
+      JIRA_EMAIL: ${{ vars.JIRA_EMAIL }}
```

### 2. CCSA host workflow — `theoju/claude-code-self-assessment/.github/workflows/docs-agent-nightly.yml`

Same two input/env swaps as 1b and 1c (no comment to fix; comment exists only in the plugin's dogfood). Lands as a separate PR on the CCSA repo.

### 3. ADIS host workflow — `theoju/advanced-data-import-system/.github/workflows/docs-agent-nightly.yml`

Same two input/env swaps as 1b and 1c. Separate PR on ADIS.

### 4. Guard test — `tests/ci/test_workflow_auth_tier.py` (NEW)

Mirrors the `WORKFLOWS = [repo .github/workflows/*.yml + templates/workflow-*.yml]` discovery pattern from `test_workflow_node_runtime.py:15-22` so the same harness covers both the dogfood and scaffolded host templates. Two assertions:

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

Templates (`templates/workflow-run.yml`, `workflow-verify.yml`) currently do NOT contain `app-id:` or `secrets.JIRA_EMAIL` (they predate App-token + Jira wiring), so adding the assertions does not require touching the templates today. The guard forward-protects PR B (template refresh): when the template gains App-token wiring, it must use `client-id` from the start.

### 5. Documentation updates — `docs/site-src/`

- **`setup-guide.md` line 124**: change the App-ID derivation note to reference Client ID.
- **`setup-guide.md` line 293**: update the example workflow snippet (the "Fix" guidance for missing App-token wiring) to use `client-id` + `vars.DOCS_AGENT_APP_CLIENT_ID`.
- **`operations/docs-agent-nightly-ci.md` line 16**: update the explanation of the `app-token` step to reflect `client-id` usage.

Historical entries in `docs/site-src/whats-new.md:18,20` are NOT updated — those describe past PRs (CCE-54, CCE-45) and should preserve the historical record as authored.

### 6. Per-repo manual operations (not in PR diffs)

For each of plugin, CCSA, ADIS, in order:

**Before any PR merges** (Phase 1):

1. `gh variable set DOCS_AGENT_APP_CLIENT_ID --repo theoju/<repo> --body "Iv23.xxx..."` — value from `github.com/settings/apps/docs-agent-bot`, same value across all three repos.
2. `gh variable set JIRA_EMAIL --repo theoju/<repo> --body "theo@designitright.net"` — current email.

**After all PRs merge AND one nightly fires green** (Phase 4):

3. `gh secret delete DOCS_AGENT_APP_ID --repo theoju/<repo>`
4. `gh secret delete JIRA_EMAIL --repo theoju/<repo>`

Steps 1-2 must complete BEFORE any workflow PR merges. Steps 3-4 are pure cleanup; no urgency, no impact on workflow correctness.

## What does NOT change

- `templates/workflow-run.yml` and `templates/workflow-verify.yml` — out of scope. These need a full refresh (App-token wiring, OAuth migration, Jira wiring, forensics upload, vendored-plugin path) which is much larger than this PR. Tracked as task #383, to be brainstormed as a separate sub-project. The guard test added here forward-protects whatever the refresh produces.
- The four genuine secrets — `CLAUDE_CODE_OAUTH_TOKEN`, `JIRA_API_TOKEN`, `DOCS_AGENT_APP_PRIVATE_KEY`, `SLACK_WEBHOOK_URL`. They stay in `secrets.` because they are actual credentials.
- The `actions/create-github-app-token@v3` pin — staying on v3. The deprecation is within v3 (warn-level), not "you must move to v4."
- The App itself (docs-agent-bot) — same App ID, same Client ID, same installation, same permissions. We're changing how the workflow REFERS to the App, not the App.
- The orchestrator runtime — no code changes in `scripts/`. The orchestrator reads `JIRA_EMAIL` from `os.environ`, which is populated identically whether sourced from `vars.` or `secrets.`.
- Historical changelog entries — `whats-new.md` historical lines are preserved.

## Data flow

```
[GitHub Settings → Variables]                    [GitHub Settings → Secrets]
DOCS_AGENT_APP_CLIENT_ID  = "Iv23.xxx"          DOCS_AGENT_APP_PRIVATE_KEY = "-----BEGIN..."
JIRA_EMAIL                = "theo@..."          CLAUDE_CODE_OAUTH_TOKEN     = "sk-ant-oat..."
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

| Failure                                              | Where it surfaces                                                                                                                  | Recovery                                                                                                                                                   |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Variable missing in target repo at workflow run-time | "Generate GitHub App installation token" step fails with `Input required and not supplied: client-id`                              | `gh variable set DOCS_AGENT_APP_CLIENT_ID --repo <r> --body "Iv23..."`. Re-run `gh workflow run docs-agent-nightly.yml --repo <r>`. No code revert needed. |
| Wrong Client ID value (typo, wrong App)              | Token mint succeeds; downstream `gh` API calls fail with 401/403 mismatch on the FIRST API call (`git push`, `gh pr create`)       | `gh variable set DOCS_AGENT_APP_CLIENT_ID` with correct value. No code revert.                                                                             |
| `JIRA_EMAIL` variable missing                        | Orchestrator's source-collector emits `jira_auth_missing` in partial_reasons; run completes with `partial: true`. NOT a hard fail. | `gh variable set JIRA_EMAIL --repo <r> --body "theo@..."`. Next nightly recovers.                                                                          |
| Old secret already deleted AND new var missing       | Same as "Variable missing" — Phase 4 is gated on "next nightly green" precisely to prevent this.                                   | Avoidance via Phase 4 gating. If it happens anyway: re-add the variable; no need to restore the secret.                                                    |
| GitHub flips `app-id` to hard-fail mid-rollout       | Any in-flight host PR's "before-merge" CI would fail at workflow_dispatch verification. Already-merged workflows are fine.         | Merge the remaining PRs immediately — they ARE the fix.                                                                                                    |
| Guard test catches a future regression               | `pytest tests/ci/test_workflow_auth_tier.py` fails red on any PR that re-introduces `app-id:` or `secrets.JIRA_EMAIL`.             | Author of the regressing PR rewrites to new tier.                                                                                                          |

No silent-failure mode is introduced. Every error path has a logged signal at either CI time, workflow run-time, or orchestrator partial_reasons time.

## Testing

1. **Failing-first guard tests** (TDD): commit `tests/ci/test_workflow_auth_tier.py` BEFORE the workflow edits. Both new tests FAIL red on the unmodified dogfood (`app-id:` and `secrets.JIRA_EMAIL` both present).
2. **Plugin workflow edits** make both tests PASS.
3. **Full suite gate**: `python3 -m pytest` returns ≥669 + 2 new = 671 passed, 3 skipped, 0 failed.
4. **CI integrated suite gate** (per CLAUDE.md): on each workflow PR, the actionlint job parses the modified YAML cleanly; pytest 3.11 + 3.12 + diagram-gate all green.
5. **Workflow_dispatch verification per repo**: after each PR merges (and the variables already exist), trigger `gh workflow run docs-agent-nightly.yml --repo theoju/<r> -f reason="CCE-66 verify"`. Inspect run logs to confirm: (a) the "Generate GitHub App installation token" step succeeds, (b) no `app-id` deprecation warning appears in that step's output, (c) the Run summary shows state.json.
6. **Production-truth gate**: tomorrow's 07:07 UTC nightly fires green on all 3 repos with no `lint_block` or `partial: true` originating from auth wiring.
7. **Phase 4 cleanup verification**: after secrets are deleted, run one more `workflow_dispatch` per repo. Workflows still pass because nothing reads the deleted secrets anymore.

## Migration

**Phase 1 — variables (manual, before any PR merges)**:

```bash
# Same Iv23.xxx value across all 3 repos (one lookup at github.com/settings/apps/docs-agent-bot)
gh variable set DOCS_AGENT_APP_CLIENT_ID --repo theoju/engineering-docs-agent --body "Iv23.xxx..."
gh variable set DOCS_AGENT_APP_CLIENT_ID --repo theoju/claude-code-self-assessment --body "Iv23.xxx..."
gh variable set DOCS_AGENT_APP_CLIENT_ID --repo theoju/advanced-data-import-system --body "Iv23.xxx..."

gh variable set JIRA_EMAIL --repo theoju/engineering-docs-agent --body "theo@designitright.net"
gh variable set JIRA_EMAIL --repo theoju/claude-code-self-assessment --body "theo@designitright.net"
gh variable set JIRA_EMAIL --repo theoju/advanced-data-import-system --body "theo@designitright.net"
```

**Phase 2 — workflow PRs (3 PRs, parallelizable)**:

- Plugin PR carries: guard test + workflow edit + comment correction + 3 doc updates.
- CCSA PR carries: workflow edit only (2 lines).
- ADIS PR carries: workflow edit only (2 lines).

**Phase 3 — merge each PR independently** as its CI goes green. Order does not matter.

**Phase 4 — secret cleanup (after one green nightly per repo)**:

```bash
gh secret delete DOCS_AGENT_APP_ID --repo theoju/engineering-docs-agent
gh secret delete DOCS_AGENT_APP_ID --repo theoju/claude-code-self-assessment
gh secret delete DOCS_AGENT_APP_ID --repo theoju/advanced-data-import-system

gh secret delete JIRA_EMAIL --repo theoju/engineering-docs-agent
gh secret delete JIRA_EMAIL --repo theoju/claude-code-self-assessment
gh secret delete JIRA_EMAIL --repo theoju/advanced-data-import-system
```

## Out of scope

- **Refreshing `templates/workflow-run.yml` and `templates/workflow-verify.yml`** — substantially larger; tracked as task #383, separate brainstorm.
- **Auditing other secrets across the codebase.** Phase 1 already audited the entire dogfood + host workflows; only `JIRA_EMAIL` and `DOCS_AGENT_APP_ID` are category errors. A broader sweep would yield nothing.
- **Removing `app-id` support from `actions/create-github-app-token@v3` upstream** — that's a GitHub-side change. v3 keeps `app-id` working with a deprecation message.
- **Changing the App itself** — `docs-agent-bot` stays the same App, with the same permissions and installations.
- **Updating CHANGELOG.md** — done as part of normal release flow, not the PR diff.

## Risks

- **Misread of Client ID at variable-set time.** Easy to typo a 25-char `Iv23.xxx` string. Mitigation: the GitHub App settings page lets you copy the value to clipboard; verify the workflow_dispatch run succeeds before merging the next PR.
- **Forgetting to set the variable in one of the three repos.** Workflow hard-fails on first run after merge. Mitigation: Phase 1 is a single batch of six `gh variable set` calls — done atomically before any PR merges. If a repo is missed, the failure is loud (`Input required and not supplied`), not silent.
- **Drift re-creeping.** Someone copy-pastes an old workflow snippet that still references `app-id`. Mitigation: the guard test fails CI on any such PR; covers both repo workflows and scaffolded templates.
- **JIRA_EMAIL appearing in logs.** Moving to `vars.` un-masks it. The email is already public via every Jira comment and git commit author, so this is not a new exposure — but documenting the expected visibility ("if you `echo $JIRA_EMAIL` in CI, you'll see the actual email") in the comment helps future reviewers.

## Success criteria

1. All three workflow PRs merge with CI green (actionlint + pytest 3.11/3.12 + diagram-gate).
2. The two new guard tests pass on the plugin's main after merge.
3. Next 07:07 UTC nightly fires successfully on all three repos with no `lint_block`/auth-related `partial_reasons`.
4. Inspection of any post-merge nightly's "Generate GitHub App installation token" step shows no `app-id` deprecation warning.
5. After Phase 4 cleanup, the two stale secrets are absent from all three repos AND a follow-up nightly still succeeds.

## References

- `actions/create-github-app-token` `action.yml` — upstream input definitions with `deprecationMessage: "Use 'client-id' instead."` on `app-id`
- `actions/create-github-app-token` README — every example uses `client-id: ${{ vars.APP_CLIENT_ID }}`
- `.github/workflows/docs-agent-nightly.yml:50-58` — plugin's current dogfood (target of edit + comment correction)
- `tests/ci/test_workflow_node_runtime.py:15-22` — harness pattern reused for the new guard test
- `docs/site-src/setup-guide.md:124,293` — user-facing onboarding instructions to update
- `docs/site-src/operations/docs-agent-nightly-ci.md:16` — operations doc to update
- CCE-45 — GitHub App installation token wiring (the work this PR adjusts the storage of)
- CCE-53 — Jira basic-auth wiring (the work this PR re-tiers)
- CCE-54 — v1→v3 Node-24 bump (the PR whose comment this PR corrects)
- Task #383 — templates/workflow-run.yml refresh (separate brainstorm, separate PR)
