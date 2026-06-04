# CCE-66 Phase 4: Obsolete Secret Cleanup — Design

**Status:** Approved · 2026-06-01
**Jira:** [CCE-66](https://designitright.atlassian.net/browse/CCE-66) (epic, Done) · task #420 (Phase 4 closeout)
**Branch:** `chore/CCE-66-phase4-secret-cleanup`
**Scope:** Operational cleanup. No plugin code changes. No host workflow changes.

## Goal

Delete the two obsolete secrets — `DOCS_AGENT_APP_ID` and `JIRA_EMAIL` — from each of the three live host repositories. They are replaced by repo variables (`vars.DOCS_AGENT_APP_CLIENT_ID` + `vars.JIRA_EMAIL`) per the CCE-66 auth-tier migration, which has been merged on the plugin (PR #91) and on all three hosts. The CCE-73 observability fix is live, so any post-cleanup regression surfaces clearly in workflow logs.

## Scope

- **In scope:** delete `secrets.DOCS_AGENT_APP_ID` and `secrets.JIRA_EMAIL` from `theoju/engineering-docs-agent`, `theoju/claude-code-self-assessment`, `theoju/advanced-data-import-system`.
- **Out of scope:**
  - `templates/workflow-run.yml` may still reference the old secret names — handled by CCE-71 (template refresh).
  - ADIS's pending `_stage_docs_run_changes` bug — handled by CCE-75 (next in this batch).
  - Any non-secret `JIRA_EMAIL` references in the orchestrator or docs already read from `vars.JIRA_EMAIL`; no change required.

## Architecture (6 phases, gated)

```
Phase 1 — Parallel verification dispatch
  workflow_dispatch on dogfood, CCSA, ADIS in parallel
  gh run watch each; assert auth-tier slice green per repo

Phase 2 — Static reference grep
  For each repo: search workflows + repo root for "secrets.DOCS_AGENT_APP_ID"
  and "secrets.JIRA_EMAIL". Templates excluded (CCE-71 scope).

Phase 3 — Canary delete on dogfood
  gh secret delete DOCS_AGENT_APP_ID --repo theoju/engineering-docs-agent
  gh secret delete JIRA_EMAIL        --repo theoju/engineering-docs-agent
  Verify via gh secret list

Phase 4 — Canary re-verification
  workflow_dispatch on dogfood post-delete
  gh run watch; assert auth-tier slice still green

Phase 5 — Parallel delete on CCSA + ADIS
  4 deletions (2 secrets x 2 repos) in parallel
  Verify each via gh secret list

Phase 6 — Closeout
  Comment on CCE-66 with phase summary + run IDs
  Confirm CCE-66 status is Done
  Mark task #420 completed
```

## Verification contract

**Auth-tier slice = verified** for a given repo's most recent `workflow_dispatch` run when both hold:

1. `Generate GitHub App installation token` step `conclusion=success`.
2. `Run nightly authoring` step's env block shows `JIRA_EMAIL: theo@designitright.net` in plain text — proves the runner reads from `vars.JIRA_EMAIL` rather than the (about-to-be-deleted) secret slot.

Failures **after** those two signals are out of scope for Phase 4. Specifically, ADIS will fail at `git_add_failed` due to known CCE-75 — accepted, because CCE-75 fires AFTER the auth-tier slice already passed.

## Error handling and rollback

| Phase | Failure mode                                                                                        | Action                                                                                                                                                                                          |
| ----- | --------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | App-token step red OR JIRA_EMAIL empty in env block on any repo                                     | **HALT.** Do not proceed to delete. Diagnose.                                                                                                                                                   |
| 2     | Stale `secrets.DOCS_AGENT_APP_ID` or `secrets.JIRA_EMAIL` reference found in any live host workflow | **HALT.** Fix the reference, re-verify, then resume.                                                                                                                                            |
| 3     | `gh secret delete` errors                                                                           | **HALT.** Most likely a permission issue or already-deleted state. Investigate.                                                                                                                 |
| 4     | Canary re-dispatch app-token step red OR env block missing JIRA_EMAIL                               | **CRITICAL.** Re-create the deleted secrets on dogfood with original values (recoverable: APP_ID from GitHub App settings page; JIRA_EMAIL is the operator's email). Do NOT proceed to Phase 5. |
| 5     | Deletion fails on one host but succeeds on the other                                                | Continue with the successful one; investigate the failure repo separately. Repos are independent.                                                                                               |

Rollback path is always: `gh secret set <NAME> --repo <repo>` with the original value. Audit trail is lost (new UUID for the recreated secret) but functional behavior is restored.

## Testing strategy

No new unit tests — Phase 4 is operational. The verification dispatches in Phases 1 and 4 ARE the regression tests.

- Phase 1 verifies pre-state: all 3 repos green-up-to-auth-tier-slice.
- Phase 4 verifies the canary survives delete: dogfood green-up-to-auth-tier-slice after the secrets are gone.

## Out of scope (explicit non-goals)

- **No template changes.** `templates/workflow-run.yml` cleanup is CCE-71.
- **No orchestrator code changes.** This is pure infra. `_stage_docs_run_changes` ADIS bug is CCE-75.
- **No `add_partial` observability extension.** That's CCE-74.
- **No new secret introduction.** This phase only deletes; no rotation, no replacement.

## Acceptance criteria

- [ ] `gh secret list --repo theoju/engineering-docs-agent` does not list `DOCS_AGENT_APP_ID` or `JIRA_EMAIL`.
- [ ] `gh secret list --repo theoju/claude-code-self-assessment` does not list `DOCS_AGENT_APP_ID` or `JIRA_EMAIL`.
- [ ] `gh secret list --repo theoju/advanced-data-import-system` does not list `DOCS_AGENT_APP_ID` or `JIRA_EMAIL`.
- [ ] dogfood's most recent `workflow_dispatch` run shows `Generate GitHub App installation token: success` AND `JIRA_EMAIL: theo@designitright.net` in the `Run nightly authoring` env block.
- [ ] CCE-66 Jira ticket has a Phase 4 closeout comment with run IDs.

## Risks accepted

- Audit trail for deleted secrets is lost (cannot recover the original creation timestamp once deleted).
- ADIS's post-delete verification will still hit CCE-75 mid-run. Acceptable per the verification contract.

## References

- Plugin PR #91 (CCE-66 plugin-side) — merged at `91e9b6c`.
- Host PRs: CCSA #111 + ADIS #397 — both admin-squash-merged.
- CCE-73 observability fix PR #93 — merged at `3c10b49`.
- ADIS canary diagnostic run [26770782104](https://github.com/theoju/advanced-data-import-system/actions/runs/26770782104) — first post-CCE-73 dispatch that surfaced CCE-75.
