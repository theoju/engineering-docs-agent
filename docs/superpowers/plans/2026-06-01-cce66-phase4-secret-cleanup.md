# CCE-66 Phase 4 — Obsolete Secret Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` (inline execution chosen per spec; the user wants to drive each gate explicitly). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the two obsolete secrets (`DOCS_AGENT_APP_ID`, `JIRA_EMAIL`) from all 3 live host repos, with gated verification at each step.

**Architecture:** 6 sequential phases. Phases 1-2 verify pre-state. Phase 3 deletes on dogfood (canary). Phase 4 re-verifies the canary. Phase 5 deletes the remaining 4 (CCSA + ADIS in parallel). Phase 6 closes out CCE-66 in Jira. Every phase has an explicit HALT gate; the executor confirms each gate before moving on.

**Tech Stack:** Bash, `gh` CLI, Atlassian MCP (for Jira), `jq`.

**Reference spec:** `docs/superpowers/specs/2026-06-01-cce66-phase4-secret-cleanup.md`

**Branch:** `chore/CCE-66-phase4-secret-cleanup` (currently 1 commit ahead of main — the spec).

---

## Task 1: Phase 1 — Parallel verification dispatch

**Files:**

- No file changes. Output captured in shell variables and a scratchpad: `/tmp/cce66-phase4/`.

- [ ] **Step 1.1: Create scratchpad directory**

```bash
mkdir -p /tmp/cce66-phase4 && cd /tmp/cce66-phase4
```

Expected: directory exists; no output.

- [ ] **Step 1.2: Fire workflow_dispatch on all 3 repos**

```bash
gh workflow run docs-agent-nightly.yml --repo theoju/engineering-docs-agent -f reason="CCE-66 Phase 4 pre-delete verification"
gh workflow run docs-agent-nightly.yml --repo theoju/claude-code-self-assessment -f reason="CCE-66 Phase 4 pre-delete verification"
gh workflow run docs-agent-nightly.yml --repo theoju/advanced-data-import-system -f reason="CCE-66 Phase 4 pre-delete verification"
```

Expected: 3 URL lines, one per dispatch (e.g., `https://github.com/theoju/.../actions/runs/...`).

- [ ] **Step 1.3: Capture the 3 run IDs after dispatch registers**

```bash
sleep 8
DOGFOOD_RUN=$(gh run list --workflow=docs-agent-nightly.yml --repo theoju/engineering-docs-agent --limit 1 --json databaseId,event --jq 'map(select(.event=="workflow_dispatch"))[0].databaseId')
CCSA_RUN=$(gh run list --workflow=docs-agent-nightly.yml --repo theoju/claude-code-self-assessment --limit 1 --json databaseId,event --jq 'map(select(.event=="workflow_dispatch"))[0].databaseId')
ADIS_RUN=$(gh run list --workflow=docs-agent-nightly.yml --repo theoju/advanced-data-import-system --limit 1 --json databaseId,event --jq 'map(select(.event=="workflow_dispatch"))[0].databaseId')
echo "DOGFOOD_RUN=$DOGFOOD_RUN"
echo "CCSA_RUN=$CCSA_RUN"
echo "ADIS_RUN=$ADIS_RUN"
echo "$DOGFOOD_RUN $CCSA_RUN $ADIS_RUN" > /tmp/cce66-phase4/phase1-runs.txt
```

Expected: 3 numeric run IDs printed; file written.

- [ ] **Step 1.4: Watch all 3 runs to completion (parallel)**

```bash
gh run watch "$DOGFOOD_RUN" --repo theoju/engineering-docs-agent --exit-status > /tmp/cce66-phase4/dogfood.log 2>&1 &
gh run watch "$CCSA_RUN" --repo theoju/claude-code-self-assessment --exit-status > /tmp/cce66-phase4/ccsa.log 2>&1 &
gh run watch "$ADIS_RUN" --repo theoju/advanced-data-import-system --exit-status > /tmp/cce66-phase4/adis.log 2>&1 &
wait
echo "all 3 runs reached terminal status"
```

Expected: blocks until all 3 are `completed`. The wait returns when the last watcher exits. Exit statuses don't matter here — we'll verify the auth-tier slice in 1.5.

Note: ADIS will likely show `conclusion=failure` due to known CCE-75. That's OK.

- [ ] **Step 1.5: Verify auth-tier slice per repo**

```bash
for spec in "engineering-docs-agent:$DOGFOOD_RUN" "claude-code-self-assessment:$CCSA_RUN" "advanced-data-import-system:$ADIS_RUN"; do
  repo="${spec%%:*}"; run="${spec##*:}"
  echo "=== $repo (run $run) ==="
  app_token=$(gh run view "$run" --repo "theoju/$repo" --json jobs --jq '.jobs[0].steps[] | select(.name=="Generate GitHub App installation token") | .conclusion')
  jira_email_present=$(gh run view "$run" --repo "theoju/$repo" --log 2>&1 | grep -c "JIRA_EMAIL: theo@designitright.net" || true)
  echo "  app-token: $app_token"
  echo "  JIRA_EMAIL in env block: $jira_email_present occurrences (expect >=1)"
  if [ "$app_token" = "success" ] && [ "$jira_email_present" -ge 1 ]; then
    echo "  ✅ auth-tier slice VERIFIED"
  else
    echo "  ❌ auth-tier slice FAILED"
  fi
done
```

Expected: 3 blocks, each ending `✅ auth-tier slice VERIFIED`.

- [ ] **Step 1.6: GATE — HALT if any auth-tier slice failed**

If any repo shows `❌ auth-tier slice FAILED`: **STOP**. Do not proceed to Task 2. Diagnose. Either the new vars are misconfigured on that repo, OR the workflow file regressed. Re-verify after fixing.

If all 3 verified: write a phase-1 success marker and continue.

```bash
date -u +%Y-%m-%dT%H:%M:%SZ > /tmp/cce66-phase4/phase1-complete.txt
echo "Phase 1 complete: $(cat /tmp/cce66-phase4/phase1-complete.txt)"
```

Expected: timestamp written and printed.

---

## Task 2: Phase 2 — Static reference grep

**Files:**

- No file changes. Output written to: `/tmp/cce66-phase4/phase2-refs.txt`.

- [ ] **Step 2.1: Search each repo for stale `secrets.DOCS_AGENT_APP_ID` references via gh code search**

```bash
> /tmp/cce66-phase4/phase2-refs.txt
for repo in engineering-docs-agent claude-code-self-assessment advanced-data-import-system; do
  for secret in DOCS_AGENT_APP_ID JIRA_EMAIL; do
    count=$(gh api "search/code?q=secrets.$secret+repo:theoju/$repo" --jq '.total_count' 2>/dev/null)
    echo "$repo / secrets.$secret: $count matches" | tee -a /tmp/cce66-phase4/phase2-refs.txt
    if [ "${count:-0}" -gt 0 ]; then
      gh api "search/code?q=secrets.$secret+repo:theoju/$repo" --jq '.items[].path' | tee -a /tmp/cce66-phase4/phase2-refs.txt
    fi
  done
done
```

Expected: 6 lines, each ending in `0 matches`. Any line ending in a non-zero count is followed by the offending path.

Note: GitHub code-search API can be eventually consistent; if you just merged a workflow change, give it ~30s before running this step.

- [ ] **Step 2.2: GATE — HALT if any non-zero match found**

```bash
if grep -E ": [1-9][0-9]* matches" /tmp/cce66-phase4/phase2-refs.txt; then
  echo "❌ Phase 2 HALT — stale references found above. Fix them before Task 3."
  exit 1
fi
echo "✅ Phase 2 complete — zero stale references in live host workflows"
```

Expected: prints `✅ Phase 2 complete`.

If HALT: open the offending file in each repo, replace `secrets.DOCS_AGENT_APP_ID` with `vars.DOCS_AGENT_APP_CLIENT_ID` (or remove if unused), replace `secrets.JIRA_EMAIL` with `vars.JIRA_EMAIL`. PR + merge that fix, then re-run Tasks 1 and 2.

---

## Task 3: Phase 3 — Canary delete on dogfood

**Files:**

- No file changes. Output captured: `/tmp/cce66-phase4/phase3-canary.txt`.

- [ ] **Step 3.1: Delete `DOCS_AGENT_APP_ID` on dogfood**

```bash
gh secret delete DOCS_AGENT_APP_ID --repo theoju/engineering-docs-agent
```

Expected: silent success (or `Secret deleted from theoju/engineering-docs-agent` depending on `gh` version).

If error: HALT. Most likely a permission issue or already-deleted state. Investigate.

- [ ] **Step 3.2: Delete `JIRA_EMAIL` on dogfood**

```bash
gh secret delete JIRA_EMAIL --repo theoju/engineering-docs-agent
```

Expected: silent success.

- [ ] **Step 3.3: Verify both are gone**

```bash
gh secret list --repo theoju/engineering-docs-agent | tee /tmp/cce66-phase4/phase3-canary.txt | grep -E "DOCS_AGENT_APP_ID|JIRA_EMAIL"
rc=$?
if [ $rc -eq 0 ]; then
  echo "❌ Phase 3 HALT — one or both still listed above"
else
  echo "✅ Phase 3 complete — dogfood secrets deleted"
fi
```

Expected: empty grep match → `✅ Phase 3 complete`.

- [ ] **Step 3.4: GATE — HALT if either secret still listed**

If `❌ Phase 3 HALT`: stop. Re-issue the `gh secret delete` for whichever name remains. Do not proceed.

---

## Task 4: Phase 4 — Canary re-verification

**Files:**

- No file changes. Run ID captured: `/tmp/cce66-phase4/phase4-canary-run.txt`.

- [ ] **Step 4.1: Re-dispatch dogfood workflow**

```bash
gh workflow run docs-agent-nightly.yml --repo theoju/engineering-docs-agent -f reason="CCE-66 Phase 4 canary post-delete re-verification"
sleep 8
CANARY_RUN=$(gh run list --workflow=docs-agent-nightly.yml --repo theoju/engineering-docs-agent --limit 1 --json databaseId,event --jq 'map(select(.event=="workflow_dispatch"))[0].databaseId')
echo "$CANARY_RUN" > /tmp/cce66-phase4/phase4-canary-run.txt
echo "CANARY_RUN=$CANARY_RUN"
```

Expected: numeric run ID printed and saved.

- [ ] **Step 4.2: Watch canary to completion**

```bash
gh run watch "$CANARY_RUN" --repo theoju/engineering-docs-agent --exit-status 2>&1 | tail -10
```

Expected: blocks until terminal status. Note: dogfood SHOULD pass end-to-end (it has no CCE-75 trigger because its `.gitignore` doesn't include `.docs-agent-plugin/`). If you see `failure`, that's NEW and concerning — proceed to 4.3 to find out why.

- [ ] **Step 4.3: Verify auth-tier slice on canary**

```bash
app_token=$(gh run view "$CANARY_RUN" --repo theoju/engineering-docs-agent --json jobs --jq '.jobs[0].steps[] | select(.name=="Generate GitHub App installation token") | .conclusion')
jira_email_present=$(gh run view "$CANARY_RUN" --repo theoju/engineering-docs-agent --log 2>&1 | grep -c "JIRA_EMAIL: theo@designitright.net" || true)
overall=$(gh run view "$CANARY_RUN" --repo theoju/engineering-docs-agent --json conclusion --jq '.conclusion')
echo "Canary: app-token=$app_token jira-email-visible=$jira_email_present overall=$overall"
if [ "$app_token" = "success" ] && [ "$jira_email_present" -ge 1 ]; then
  echo "✅ Canary auth-tier slice VERIFIED — secrets deletion is safe"
else
  echo "❌ Canary auth-tier slice FAILED — ROLLBACK REQUIRED"
fi
```

Expected: `✅ Canary auth-tier slice VERIFIED`.

- [ ] **Step 4.4: GATE — CRITICAL halt + rollback if canary slice failed**

If `❌ Canary auth-tier slice FAILED`: **CRITICAL ROLLBACK**. Re-create the deleted secrets on dogfood:

```bash
# Recover DOCS_AGENT_APP_ID from GitHub App settings page:
#   https://github.com/settings/apps/docs-agent-bot → App ID field (numeric)
gh secret set DOCS_AGENT_APP_ID --repo theoju/engineering-docs-agent --body "<app-id-from-settings-page>"

# JIRA_EMAIL is just the operator's email:
gh secret set JIRA_EMAIL --repo theoju/engineering-docs-agent --body "theo@designitright.net"
```

Then STOP. Do not proceed to Task 5 until the root cause is identified and fixed.

If canary VERIFIED: continue to Task 5.

---

## Task 5: Phase 5 — Parallel delete on CCSA + ADIS

**Files:**

- No file changes. Output captured: `/tmp/cce66-phase4/phase5-deletions.txt`.

- [ ] **Step 5.1: Delete `DOCS_AGENT_APP_ID` and `JIRA_EMAIL` on CCSA + ADIS in parallel**

```bash
gh secret delete DOCS_AGENT_APP_ID --repo theoju/claude-code-self-assessment &
PID1=$!
gh secret delete JIRA_EMAIL --repo theoju/claude-code-self-assessment &
PID2=$!
gh secret delete DOCS_AGENT_APP_ID --repo theoju/advanced-data-import-system &
PID3=$!
gh secret delete JIRA_EMAIL --repo theoju/advanced-data-import-system &
PID4=$!
wait $PID1 $PID2 $PID3 $PID4
echo "all 4 deletions returned"
```

Expected: 4 silent successes (or `Secret deleted from ...` lines). The `wait` blocks until all 4 finish.

- [ ] **Step 5.2: Verify all 4 are gone**

```bash
> /tmp/cce66-phase4/phase5-deletions.txt
for repo in claude-code-self-assessment advanced-data-import-system; do
  echo "=== $repo ===" | tee -a /tmp/cce66-phase4/phase5-deletions.txt
  remaining=$(gh secret list --repo "theoju/$repo" | grep -E "DOCS_AGENT_APP_ID|JIRA_EMAIL" || true)
  if [ -z "$remaining" ]; then
    echo "  ✅ both secrets gone" | tee -a /tmp/cce66-phase4/phase5-deletions.txt
  else
    echo "  ❌ still listed:" | tee -a /tmp/cce66-phase4/phase5-deletions.txt
    echo "$remaining" | tee -a /tmp/cce66-phase4/phase5-deletions.txt
  fi
done
```

Expected: both repos show `✅ both secrets gone`.

- [ ] **Step 5.3: GATE — investigate any host with residual secrets**

If either repo shows `❌ still listed`: re-issue the `gh secret delete` for that specific name+repo. If it errors, investigate (permission, App-installation revocation, etc.) and resolve before Phase 6. Phase 5's failures don't block Phase 6 closeout IF the residual repo is documented in the closeout comment — but ideally you re-attempt until clean.

---

## Task 6: Phase 6 — Closeout

**Files:**

- Jira ticket CCE-66 (comment via Atlassian MCP).
- This branch `chore/CCE-66-phase4-secret-cleanup` (merge to main as docs PR).

- [ ] **Step 6.1: Compose closeout summary**

```bash
cat > /tmp/cce66-phase4/closeout.md <<EOF
CCE-66 Phase 4 (obsolete secret cleanup) — complete.

Pre-delete verification run IDs (auth-tier slice green per spec contract):
- dogfood: $(cat /tmp/cce66-phase4/phase1-runs.txt | awk '{print $1}')
- CCSA: $(cat /tmp/cce66-phase4/phase1-runs.txt | awk '{print $2}')
- ADIS: $(cat /tmp/cce66-phase4/phase1-runs.txt | awk '{print $3}') (failed at known CCE-75 \`git_add_failed\` — auth-tier slice still verified per spec contract)

Canary delete + re-verify on dogfood (run $(cat /tmp/cce66-phase4/phase4-canary-run.txt)) confirmed the new vars sustain the workflow with the obsolete secrets gone.

Parallel delete on CCSA + ADIS completed. \`gh secret list\` on all 3 repos confirms neither \`DOCS_AGENT_APP_ID\` nor \`JIRA_EMAIL\` remain.

Auth-tier migration epic fully complete. Plugin (PR #91), host workflows (CCSA #111, ADIS #397), observability follow-up (CCE-73 PR #93) all merged.

Follow-ups outside CCE-66 scope:
- CCE-71 (template refresh — \`templates/workflow-run.yml\` still references old secret names)
- CCE-74 (extend stderr emission to all \`add_partial\` sites)
- CCE-75 (ADIS \`_stage_docs_run_changes\` pathspec interaction)
EOF
cat /tmp/cce66-phase4/closeout.md
```

Expected: closeout text printed; saved to file.

- [ ] **Step 6.2: Post closeout comment to CCE-66 via Atlassian MCP**

Invoke `mcp__plugin_atlassian_atlassian__addCommentToJiraIssue` with:

- `cloudId`: `designitright.atlassian.net`
- `issueIdOrKey`: `CCE-66`
- `commentBody`: the content of `/tmp/cce66-phase4/closeout.md`

Expected: response with comment ID (e.g., `"id": "1234X"`).

If CCE-66 is currently in any non-Done state, also transition to Done via `mcp__plugin_atlassian_atlassian__transitionJiraIssue` with transition `41` (Done). Skip if already Done.

- [ ] **Step 6.3: Commit the implementation plan**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add docs/superpowers/plans/2026-06-01-cce66-phase4-secret-cleanup.md
git commit -m "$(cat <<'COMMITMSG'
docs(CCE-66): SP-4 plan — obsolete secret cleanup

6-task implementation plan derived from the SP-4 design. Inline-
execution flow with gated HALTs per phase. Pure ops (no code, no
tests); commands run against gh CLI + Atlassian MCP.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
COMMITMSG
)"
```

Expected: commit succeeds.

- [ ] **Step 6.4: Mark task #420 completed via TodoWrite + final summary**

Update TodoWrite: mark #420 as completed.

Print final summary table:

```bash
echo ""
echo "=== CCE-66 Phase 4 final summary ==="
echo "All 6 phases passed. Secrets cleaned across 3 repos. CCE-66 closed."
echo ""
echo "Artifacts:"
echo "  Spec: docs/superpowers/specs/2026-06-01-cce66-phase4-secret-cleanup.md"
echo "  Plan: docs/superpowers/plans/2026-06-01-cce66-phase4-secret-cleanup.md"
echo "  Scratchpad: /tmp/cce66-phase4/"
```

---

## Post-execution: optional PR to land spec + plan on main

After all 6 tasks pass and you've confirmed CCE-66 is Done, open a PR for this branch to merge the spec + plan onto main:

```bash
git push -u origin chore/CCE-66-phase4-secret-cleanup
gh pr create --title "docs(CCE-66): Phase 4 spec + plan + closeout" --body "Spec + plan for the obsolete-secret cleanup. Execution evidence lives in the linked Jira comment on CCE-66. Pure docs PR — no code changes."
```

Then admin-squash-merge after your review.

---

## Self-Review (writing-plans skill checklist)

**1. Spec coverage:** ✅

- Spec § Architecture (6 phases) → Tasks 1-6 (one task per phase)
- Spec § Verification contract → Steps 1.5, 4.3 (auth-tier slice check)
- Spec § Error handling → HALT gates in Steps 1.6, 2.2, 3.4, 4.4, 5.3
- Spec § Out of scope → reaffirmed in closeout (CCE-71/74/75 are linked but not touched)
- Spec § Acceptance criteria → all 5 checkboxes match Steps 5.2 + 6.2

**2. Placeholder scan:** ✅

- No "TBD", "TODO", "later", or vague descriptors.
- All commands are concrete with expected output.
- The only `<placeholder>` is `<app-id-from-settings-page>` in Step 4.4's rollback — which is a genuine human-supplied value not knowable in advance.

**3. Type/identifier consistency:** ✅

- Shell variables `$DOGFOOD_RUN`, `$CCSA_RUN`, `$ADIS_RUN`, `$CANARY_RUN` used consistently from definition (Step 1.3/4.1) through consumption (Steps 1.4/1.5/4.2/4.3/6.1).
- Repo names use full `theoju/<name>` form consistently with `gh --repo`.
- Secret names `DOCS_AGENT_APP_ID` and `JIRA_EMAIL` consistent throughout (matching spec).

Plan ready for execution.
