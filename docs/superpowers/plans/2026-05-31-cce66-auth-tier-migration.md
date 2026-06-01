# CCE-66 — Auth-tier migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate three docs-agent workflows off the deprecated `app-id` input onto `client-id` AND re-classify `JIRA_EMAIL` from Secret to Variable. Update the onboarding helper (`preflight_host.py`) so new hosts get the right checklist, sweep all user-facing docs, and add a guard test so the pattern cannot creep back.

**Architecture:** Plugin PR carries the guard test + workflow edit + preflight helper update + comment correction + documentation sweep. Two thin host PRs (CCSA, ADIS) each carry only the 2-line workflow edit. Per-repo Variables are added manually before any PR merges (Phase 1) and verified before each merge (Phase 1.5). Obsolete secrets are deleted last (Phase 4) after each repo's workflow_dispatch confirms both token-mint AND Jira-enrichment succeed.

**Tech Stack:** Python stdlib (`re`, `pathlib`). pytest. GitHub Actions YAML. `gh` CLI for manual variable/secret operations.

**Test runner:** `python3 -m pytest`

**Commit trailer (required on every commit):** `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

**Branch:** `chore/CCE-66-auth-tier-migration` (already checked out, 2 commits ahead of main with spec + spec revision).

**Never use:** `-f`, `--force`, `--no-verify`, `--amend`.

**Spec:** `docs/superpowers/specs/2026-05-31-cce66-auth-tier-migration.md`

---

## Task 1: Failing guard tests for workflow auth tier (TDD red)

**Files:**

- Create: `tests/ci/test_workflow_auth_tier.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/ci/test_workflow_auth_tier.py`:

```python
"""Guard: workflows must use correct auth tiers.

Repo Variables (vars.*) for non-secret identifiers (Client ID, email).
Repo Secrets (secrets.*) for credentials (private keys, tokens, webhooks).

This test fails the moment any workflow drifts back to the deprecated
`app-id` input or treats JIRA_EMAIL as a secret. Covers both the dogfood
workflow and scaffolded host templates (which propagate to onboarded
hosts via the setup skill).

CCE-66 root cause: `actions/create-github-app-token@v3` deprecated
`app-id` in favor of `client-id` (a semantically different App field).
CCE-66 also re-classifies `JIRA_EMAIL` from Secret to Variable because
it is a basic-auth username, not a credential.
"""

from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted(
    [
        *(ROOT / ".github" / "workflows").glob("*.yml"),
        *(ROOT / "templates").glob("workflow-*.yml"),
    ]
)


def test_workflows_discovered():
    """Sanity: glob-based discovery would vacuously pass with empty list."""
    assert WORKFLOWS, "no workflow files discovered"


def test_no_workflow_uses_deprecated_app_id_input():
    """CCE-66: actions/create-github-app-token@v3 deprecated `app-id`
    in favor of `client-id`. Catches stale workflows and templates that
    haven't been migrated, and forward-protects PR #383 (template
    refresh) — when the template gains App-token wiring, it must use
    `client-id` from the start."""
    offenders = [wf.name for wf in WORKFLOWS if "app-id:" in wf.read_text()]
    assert not offenders, (
        "workflows still use deprecated `app-id:`: " + ", ".join(offenders)
    )


def test_no_workflow_reads_jira_email_as_secret():
    """CCE-66: JIRA_EMAIL is a basic-auth username, not a credential.
    Belongs in repo Variables (vars.JIRA_EMAIL), not Secrets."""
    offenders = [
        wf.name for wf in WORKFLOWS if "secrets.JIRA_EMAIL" in wf.read_text()
    ]
    assert not offenders, (
        "workflows still read JIRA_EMAIL as secret: " + ", ".join(offenders)
    )
```

- [ ] **Step 2: Run the tests — confirm BOTH new assertions FAIL**

Run: `python3 -m pytest tests/ci/test_workflow_auth_tier.py -v 2>&1 | tail -15`

Expected:

- `test_workflows_discovered` PASSES (discovery is non-empty).
- `test_no_workflow_uses_deprecated_app_id_input` FAILS with `docs-agent-nightly.yml` in offenders list (`app-id:` is at line 57).
- `test_no_workflow_reads_jira_email_as_secret` FAILS with `docs-agent-nightly.yml` in offenders list (`secrets.JIRA_EMAIL` is at line 41).

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/ci/test_workflow_auth_tier.py
git commit -m "$(cat <<'EOF'
test(CCE-66): failing guard tests for workflow auth tier

Two new assertions in tests/ci/test_workflow_auth_tier.py iterate the
same WORKFLOWS list as test_workflow_node_runtime.py (repo workflows
plus templates/workflow-*.yml):

1. test_no_workflow_uses_deprecated_app_id_input — fails if any workflow
   text contains the substring `app-id:`.
2. test_no_workflow_reads_jira_email_as_secret — fails if any workflow
   text contains `secrets.JIRA_EMAIL`.

Both currently fail on the dogfood docs-agent-nightly.yml (line 57 has
`app-id:`, line 41 has `secrets.JIRA_EMAIL`). Task 2 migrates the
workflow to make both pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Workflow edit — plugin's docs-agent-nightly.yml (TDD green)

**Files:**

- Modify: `.github/workflows/docs-agent-nightly.yml` (3 textual changes)

- [ ] **Step 1: Replace the misleading CCE-54 comment (lines 50-54)**

Locate the existing block:

```yaml
# CCE-54: bumped v1 -> v3 for Node-24 runtime. v1 and v2 both ship on
# Node 20, which GitHub deprecates June 2026; v3 is the first major on
# Node 24. v3 emits a cosmetic `app-id` deprecation warning (the input
# was renamed to `app_id`); the old name still works — follow-up if/when
# we want to silence it.
uses: actions/create-github-app-token@v3
```

Replace with:

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

- [ ] **Step 2: Swap the input (line 57 of the original file)**

Locate:

```yaml
with:
  app-id: ${{ secrets.DOCS_AGENT_APP_ID }}
  private-key: ${{ secrets.DOCS_AGENT_APP_PRIVATE_KEY }}
```

Replace `app-id:` line:

```yaml
with:
  client-id: ${{ vars.DOCS_AGENT_APP_CLIENT_ID }}
  private-key: ${{ secrets.DOCS_AGENT_APP_PRIVATE_KEY }}
```

- [ ] **Step 3: Move JIRA_EMAIL to vars (line 41 of the original file)**

Locate:

```yaml
JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
```

Replace `JIRA_EMAIL` line:

```yaml
JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
JIRA_EMAIL: ${{ vars.JIRA_EMAIL }}
```

- [ ] **Step 4: Run Task 1's tests — confirm BOTH now PASS**

Run: `python3 -m pytest tests/ci/test_workflow_auth_tier.py -v 2>&1 | tail -15`

Expected: all 3 tests PASS.

- [ ] **Step 5: Optional local actionlint check**

If `actionlint` is on PATH locally:

`actionlint .github/workflows/docs-agent-nightly.yml`

Expected: no errors.

- [ ] **Step 6: Commit the workflow migration**

```bash
git add .github/workflows/docs-agent-nightly.yml
git commit -m "$(cat <<'EOF'
fix(CCE-66): migrate plugin workflow to client-id + vars.JIRA_EMAIL

Three textual changes to docs-agent-nightly.yml:

1. Replace the misleading CCE-54 comment (lines 50-54) that claimed the
   v3 deprecation was a cosmetic `app-id` -> `app_id` hyphen rename.
   Actual upstream deprecation is `app-id` -> `client-id` — a
   semantically different App field (the OAuth Client ID, format
   Iv1.xxx, not the numeric App ID).

2. Swap `app-id: secrets.DOCS_AGENT_APP_ID` for
   `client-id: vars.DOCS_AGENT_APP_CLIENT_ID` on the app-token step.

3. Move JIRA_EMAIL from secrets.JIRA_EMAIL to vars.JIRA_EMAIL. The
   email is a basic-auth username, not a credential — it is already
   visible in every Jira comment and git commit author.

Both guard tests in tests/ci/test_workflow_auth_tier.py turn green.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: preflight_host.py — surface required variables alongside secrets

**Files:**

- Modify: `scripts/preflight_host.py:72-91` — `secrets_from_workflow` function
- Modify: `scripts/preflight_host.py:176-200` — `build_report` (adds `variables_checklist` field)
- Modify: `scripts/preflight_host.py:143-174` — `render_text` (renders the new variables section)
- Modify: `tests/setup/test_preflight_host.py:36-40` — assertion set

- [ ] **Step 1: Read current `secrets_from_workflow` and `build_report`**

Read `scripts/preflight_host.py` lines 70-95 to anchor the edit on `secrets_from_workflow`, and lines 175-205 to anchor on `build_report`. The function currently:

- `secrets_from_workflow(workflow_text)` (line 72): scans via `re.findall(r"secrets\.([A-Z_]+)", workflow_text)`, force-injects `{CLAUDE_CODE_OAUTH_TOKEN, DOCS_AGENT_APP_ID, DOCS_AGENT_APP_PRIVATE_KEY}` as required, filters `GITHUB_TOKEN`, returns `[{name, required}]`.
- `build_report(repo_root)` (line 176): composes the JSON report dict — currently stores secrets via `"secrets_checklist": secrets_from_workflow(workflow_text)`.
- `render_text(report)` (line 143): renders the human-readable text version, reading `report["secrets_checklist"]` (line 162).

- [ ] **Step 2: Write a failing test for new behavior**

Read `tests/setup/test_preflight_host.py` first to anchor the assertion site. Then extend the existing assertion (currently at lines 36-40) to:

Replace:

```python
    names = {s["name"] for s in out["secrets_checklist"]}
    assert {
        "CLAUDE_CODE_OAUTH_TOKEN",
        "DOCS_AGENT_APP_ID",
        "DOCS_AGENT_APP_PRIVATE_KEY",
    } <= names
```

with:

```python
    names = {s["name"] for s in out["secrets_checklist"]}
    # CCE-66: DOCS_AGENT_APP_ID is migrated out; CLAUDE_CODE_OAUTH_TOKEN
    # and DOCS_AGENT_APP_PRIVATE_KEY remain secrets.
    assert {
        "CLAUDE_CODE_OAUTH_TOKEN",
        "DOCS_AGENT_APP_PRIVATE_KEY",
    } <= names
    assert "DOCS_AGENT_APP_ID" not in names, (
        "CCE-66: DOCS_AGENT_APP_ID should no longer appear in secrets_checklist"
    )

    # CCE-66: new variables_checklist surfaces the required vars
    # (client-id, JIRA_EMAIL) so onboarding operators get correct guidance.
    var_names = {v["name"] for v in out["variables_checklist"]}
    assert {
        "DOCS_AGENT_APP_CLIENT_ID",
        "JIRA_EMAIL",
    } <= var_names
```

Run: `python3 -m pytest tests/setup/test_preflight_host.py -v 2>&1 | tail -15`

Expected: failures on (a) `DOCS_AGENT_APP_ID` still present, and/or (b) `variables_checklist` key missing from `out`. Confirms the test is red.

- [ ] **Step 3: Update `secrets_from_workflow` — remove DOCS_AGENT_APP_ID**

In `scripts/preflight_host.py:78-83` (the `required` set inside `secrets_from_workflow`), remove `"DOCS_AGENT_APP_ID",` so only genuine credentials remain (`CLAUDE_CODE_OAUTH_TOKEN`, `DOCS_AGENT_APP_PRIVATE_KEY`).

- [ ] **Step 4: Add `variables_from_workflow`**

In the same file, add a new function `variables_from_workflow(workflow_text)` next to `secrets_from_workflow`. It mirrors the secrets pattern but scans `vars\.` references:

```python
def variables_from_workflow(workflow_text: str) -> list[dict]:
    """Return required + discovered repo Variables for the host.

    Variables are independent of Secrets (no shared namespace). CCE-66
    introduced two required variables: DOCS_AGENT_APP_CLIENT_ID (the
    OAuth Client ID for the GitHub App, format Iv1.xxx) and JIRA_EMAIL
    (the basic-auth username for Atlassian — a public identifier, not
    a credential).
    """
    found = sorted(set(re.findall(r"vars\.([A-Z_]+)", workflow_text)))
    required = {
        "DOCS_AGENT_APP_CLIENT_ID",
        "JIRA_EMAIL",
    }
    for n in sorted(required):
        if n not in found:
            found.append(n)
    return [{"name": n, "required": n in required} for n in sorted(set(found))]
```

- [ ] **Step 5: Surface `variables_checklist` in the output payload**

In `build_report(repo_root)` at `scripts/preflight_host.py:176`, add a `"variables_checklist": variables_from_workflow(workflow_text)` field alongside the existing `"secrets_checklist": secrets_from_workflow(workflow_text)` field (the one at the function's return dict around line 185).

- [ ] **Step 5b: Render `variables_checklist` in human-readable output**

In `render_text(report)` at `scripts/preflight_host.py:143`, after the block that loops over `report["secrets_checklist"]` (around line 162), add a parallel block that loops over `report["variables_checklist"]` and prints each line under a `Required Variables:` heading. Use the same `[x] required` / `[ ] optional` glyph convention. Without this addition `preflight_host` would emit variables in JSON output but hide them from the text helper, defeating the onboarding-clarity goal.

- [ ] **Step 6: Run Task 3's tests — confirm both PASS**

`python3 -m pytest tests/setup/test_preflight_host.py -v 2>&1 | tail -15`

Expected: existing tests + new variables_checklist assertions all PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/preflight_host.py tests/setup/test_preflight_host.py
git commit -m "$(cat <<'EOF'
fix(CCE-66): preflight surfaces required variables (client-id, JIRA_EMAIL)

Two functional changes to scripts/preflight_host.py:

1. build_secrets_checklist: drop DOCS_AGENT_APP_ID from the required
   set. The workflow no longer references this secret after CCE-66's
   workflow edit lands.

2. New build_variables_checklist function: scan `vars.X` patterns in
   the workflow text and force-inject the two required Variables
   (DOCS_AGENT_APP_CLIENT_ID, JIRA_EMAIL). Surface as
   `variables_checklist` in the --format json output.

Test extends to assert: DOCS_AGENT_APP_ID is NOT in secrets_checklist,
and both required variables ARE in variables_checklist. Onboarding
operators following the helper now get the correct mixed-tier guidance.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Documentation sweep

**Files:**

- Modify: `docs/site-src/setup-guide.md` (8 verified edit anchors: 62, 70, 124, 133, 136, 293, 342, 343)
- Modify: `docs/site-src/operations/docs-agent-nightly-ci.md:22`
- Modify: `docs/site-src/operations/docs-agent-nightly-jira-auth.md` (4 lines: 16, 19, 26, 33)
- Modify: `docs/host-onboarding/advanced-data-import-system.md:105,113`

- [ ] **Step 1: Update setup-guide.md**

For each of the 8 verified anchors, replace per the spec's "Documentation updates" subsection (4.). Use Read + Edit per anchor; do not bulk-rewrite the file. Anchors (verified against current file state):

- Line 62: replace the App ID note with a Client ID note (format `Iv1.xxxxxxxxxxxxxxxx`).
- Line 70: clarify `JIRA_EMAIL` is stored as a repo Variable.
- Line 124: rewrite the App-ID derivation prose to reference Client ID. The current sentence is `"You don't need to copy the installation ID — actions/create-github-app-token@v3 derives it at runtime from the App ID, private key, and repo name."` — flip `App ID` to `App Client ID (Iv1.xxx)`.
- Line 133: table row for `DOCS_AGENT_APP_ID` → row for `DOCS_AGENT_APP_CLIENT_ID` (Required Variable, not Secret).
- Line 136: table row for `JIRA_EMAIL` — mark as Variable.
- Line 293: in the "Fix" prose paragraph for the CCE-45 wiring, append a one-sentence note that the canonical example uses `client-id: ${{ vars.DOCS_AGENT_APP_CLIENT_ID }}` (Variable, not Secret).
- Line 342: checklist updated — "Set secrets: `CLAUDE_CODE_OAUTH_TOKEN`, `DOCS_AGENT_APP_PRIVATE_KEY`. Set variables: `DOCS_AGENT_APP_CLIENT_ID`."
- Line 343: checklist clarified — "Set secret `JIRA_API_TOKEN` and variable `JIRA_EMAIL` for Jira enrichment."

**Imperative re-Read rule (avoid stale-offset edits):** After EACH Edit, re-Read the surrounding ±3 lines before the next Edit. The format-on-edit hook may renumber rows of nearby content as it reformats. Do not chain multiple Edits without an intervening Read of the affected line range — silent off-by-one edits compound and produce a syntactically valid but semantically wrong file.

- [ ] **Step 2: Update operations/docs-agent-nightly-ci.md:22**

Replace the secrets-table row for `DOCS_AGENT_APP_ID` with a Variables-table row for `DOCS_AGENT_APP_CLIENT_ID`. If the surrounding table header reads "Secret only", split into two tables (Secrets + Variables) or add a "Tier" column.

- [ ] **Step 3: Update operations/docs-agent-nightly-jira-auth.md**

Four edits:

- Line 16: table header — split or add a Tier column to accommodate Variable vs Secret.
- Line 19: `JIRA_EMAIL` row — mark as Variable.
- Line 26: YAML snippet — `JIRA_EMAIL: ${{ vars.JIRA_EMAIL }}` instead of `secrets.JIRA_EMAIL`.
- Line 33: "until the secrets are configured" → "until the credentials are configured" (mixed tier now).

- [ ] **Step 4: Update host-onboarding/advanced-data-import-system.md**

Two edits:

- Line 105: `gh secret set DOCS_AGENT_APP_ID --repo theoju/advanced-data-import-system   # paste the numeric App ID` → `gh variable set DOCS_AGENT_APP_CLIENT_ID --repo theoju/advanced-data-import-system   # paste the OAuth Client ID (Iv1.xxx format)`
- Line 113: `gh secret set JIRA_EMAIL` → `gh variable set JIRA_EMAIL`

- [ ] **Step 5: Commit**

```bash
git add docs/site-src/setup-guide.md \
        docs/site-src/operations/docs-agent-nightly-ci.md \
        docs/site-src/operations/docs-agent-nightly-jira-auth.md \
        docs/host-onboarding/advanced-data-import-system.md
git commit -m "$(cat <<'EOF'
docs(CCE-66): update onboarding + operations docs for auth tier migration

Update four user-facing docs to reference the new Variable-based
storage for the Client ID and JIRA_EMAIL, and to remove references to
the obsolete DOCS_AGENT_APP_ID secret:

- setup-guide.md: 8 lines covering App-Client-ID introduction, Variable
  vs Secret tier callouts, table rows, "Fix" snippet, and checklists.
- operations/docs-agent-nightly-ci.md: secrets table row replaced with
  Variables table row.
- operations/docs-agent-nightly-jira-auth.md: header tier column,
  JIRA_EMAIL row, YAML snippet, "until configured" prose.
- host-onboarding/advanced-data-import-system.md: two `gh ... set`
  command examples flipped from `secret` to `variable`.

Historical entries in whats-new.md, CHANGELOG.md, and superpowers
specs/plans are intentionally preserved.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Full pytest + actionlint verification

**Files:** (none — verification only)

- [ ] **Step 1: Full pytest suite**

Run: `python3 -m pytest 2>&1 | tail -5`

Expected: `669 + 3 (Task 1 new) + 1 (Task 3 new vars assertion) = 673 passed, 3 skipped, 0 failed` — or close to it. The exact +new count may vary by how many sub-assertions the new tests contain. Acceptable bound: ≥672 passed, 3 skipped, 0 failed.

- [ ] **Step 2: Confirm clean working tree**

```bash
git status --short
git log --oneline main..HEAD
```

Expected: clean working tree; **7 commits** ahead of main. Composition: spec original (5588830) + spec revised (6da0d1f) + plan (d4aa5f0) + plan revised (this commit's HEAD~3) + Task 1 failing tests + Task 2 workflow edit + Task 3 preflight + Task 4 docs sweep = 7 commits. Adjust the lower bound by ±1 if /ship's commit spoke amends or no-ops the plan-revision commit; the floor for a healthy state is **≥6 commits** ahead with a clean working tree.

- [ ] **Step 3: No commit — hand off to /ship**

---

## Task 6: Phase 1 + 1.5 — variables set + verified across 3 repos

**Files:** (none — manual GitHub operations)

This task is operator-driven (or assistant with explicit user authorization), not a subagent task. Performed before the plugin PR merges, and is a hard gate for Phase 3 (merging the host PRs).

- [ ] **Step 1: Phase 1 — set variables in all 3 repos**

Look up the Client ID at `https://github.com/settings/apps/<docs-agent-bot-slug>` — same value across all 3 hosts of the same App.

```bash
gh variable set DOCS_AGENT_APP_CLIENT_ID --repo theoju/engineering-docs-agent      --body "Iv1.xxxxxxxxxxxxxxxx"
gh variable set DOCS_AGENT_APP_CLIENT_ID --repo theoju/claude-code-self-assessment --body "Iv1.xxxxxxxxxxxxxxxx"
gh variable set DOCS_AGENT_APP_CLIENT_ID --repo theoju/advanced-data-import-system --body "Iv1.xxxxxxxxxxxxxxxx"

gh variable set JIRA_EMAIL --repo theoju/engineering-docs-agent      --body "<atlassian-email>"
gh variable set JIRA_EMAIL --repo theoju/claude-code-self-assessment --body "<atlassian-email>"
gh variable set JIRA_EMAIL --repo theoju/advanced-data-import-system --body "<atlassian-email>"
```

- [ ] **Step 2: Phase 1.5 — verify all 6 variables exist**

```bash
for repo in theoju/engineering-docs-agent theoju/claude-code-self-assessment theoju/advanced-data-import-system; do
  echo "=== $repo ==="
  gh variable list --repo "$repo" | grep -E "DOCS_AGENT_APP_CLIENT_ID|JIRA_EMAIL"
done
```

Expected: 2 lines per repo (6 total). Anything else = STOP, do not merge.

- [ ] **Step 3: Record completion**

Add a note to the plugin PR's body confirming Phase 1.5 verification: `Variables set + verified across all 3 repos.`

---

## Task 7: /ship plugin PR

**Files:** (none — `/ship` orchestrates)

- [ ] **Step 0: HARD GATE — Re-verify Phase 1.5 across all 3 repos**

Before `/ship` may proceed, the operator MUST re-run the variables-verification gate from Task 6 Step 2. The plugin PR's merge will trigger every host's next nightly to use the new `vars.DOCS_AGENT_APP_CLIENT_ID` / `vars.JIRA_EMAIL` references; if any repo is missing either variable, that nightly hard-fails at the app-token step or surfaces a `jira_auth_missing` partial reason.

Run (machine-checkable):

```bash
set -e
FAIL=0
for repo in theoju/engineering-docs-agent theoju/claude-code-self-assessment theoju/advanced-data-import-system; do
  COUNT=$(gh variable list --repo "$repo" --json name --jq '[.[] | select(.name == "DOCS_AGENT_APP_CLIENT_ID" or .name == "JIRA_EMAIL")] | length')
  if [ "$COUNT" != "2" ]; then
    echo "::error::$repo is missing one or both required variables (have $COUNT, need 2)"
    FAIL=1
  else
    echo "OK: $repo has both DOCS_AGENT_APP_CLIENT_ID and JIRA_EMAIL"
  fi
done
[ "$FAIL" = "0" ] || { echo "Phase 1.5 gate FAILED — do not /ship"; exit 1; }
echo "Phase 1.5 gate PASSED — proceed to /ship"
```

Expected: 3 `OK:` lines and a final `Phase 1.5 gate PASSED`. Anything else → STOP. Re-run Task 6 Step 1 to fill the gaps, then re-verify before proceeding.

- [ ] **Step 1: Confirm working tree clean + on feature branch**

```bash
git branch --show-current  # expect: chore/CCE-66-auth-tier-migration
git status --short          # expect: empty
git log --oneline main..HEAD  # expect: 7 commits (spec + spec revision + plan + plan revision + Tasks 1-4)
```

- [ ] **Step 2: Invoke /ship**

```
/ship
```

The chain handles: test → verify-agent → simplify → code-review → commit (idempotent skip; HEAD already matches) → push + PR → Jira CCE-66 transition.

`--no-simplify` is optional; CCE-66 is mechanical, so simplify is unlikely to find anything.

- [ ] **Step 3: Watch CI; merge when green**

Plugin PR will appear at `https://github.com/theoju/engineering-docs-agent/pull/<n>`. Once CI is green (actionlint + pytest 3.11 + 3.12 + diagram-gate), admin-squash-merge.

---

## Task 8: Host PR — CCSA workflow edit

> **Repo-name convention:** Tasks 8 and 9 hardcode concrete `theoju/<repo>` slugs (`theoju/claude-code-self-assessment`, `theoju/advanced-data-import-system`) intentionally — this plan is rolling out CCE-66 to a known fleet of onboarded hosts. If a future operator runs the same task on a different fleet, swap the slugs. Do NOT parameterize; the literal slugs are the audit trail.

**Files:**

- Modify (in CCSA clone): `.github/workflows/docs-agent-nightly.yml` (2 lines)

- [ ] **Step 1: Clone CCSA into /tmp**

```bash
cd /tmp && mkdir -p cce66-ccsa && cd cce66-ccsa && \
  git clone --depth 1 https://github.com/theoju/claude-code-self-assessment.git .
```

- [ ] **Step 2: Create feature branch + apply 2-line edit**

```bash
git checkout -b chore/CCE-66-client-id-migration
```

In `.github/workflows/docs-agent-nightly.yml`:

```diff
-          app-id: ${{ secrets.DOCS_AGENT_APP_ID }}
+          client-id: ${{ vars.DOCS_AGENT_APP_CLIENT_ID }}
...
-      JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
+      JIRA_EMAIL: ${{ vars.JIRA_EMAIL }}
```

- [ ] **Step 3: Commit + push + open PR**

```bash
git add .github/workflows/docs-agent-nightly.yml
git commit -m "$(cat <<'EOF'
chore(CCE-66): migrate workflow to client-id + vars.JIRA_EMAIL

Two-line workflow edit on docs-agent-nightly.yml:

1. Swap `app-id: secrets.DOCS_AGENT_APP_ID` for
   `client-id: vars.DOCS_AGENT_APP_CLIENT_ID` (upstream-deprecated
   input).
2. Move JIRA_EMAIL env from `secrets.` to `vars.` (basic-auth username,
   not a credential).

Companion plugin work is CCE-66 in the Claude-Code-Extensions Jira
project. Phase 1 of the rollout (set both repo Variables) MUST be
complete on this repo before this PR merges — otherwise the next
nightly hard-fails at the app-token step.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push -u origin chore/CCE-66-client-id-migration
```

Then open the PR (run from `/tmp/cce66-ccsa` since `gh pr create` needs the repo's working tree). Use the heredoc form to keep the PR body verbatim — no placeholder text:

```bash
gh pr create \
  --base main \
  --head chore/CCE-66-client-id-migration \
  --title "chore(CCE-66): migrate workflow to client-id + vars.JIRA_EMAIL" \
  --body "$(cat <<'EOF'
## Summary

Two-line edit to `.github/workflows/docs-agent-nightly.yml`:

1. `app-id: ${{ secrets.DOCS_AGENT_APP_ID }}` → `client-id: ${{ vars.DOCS_AGENT_APP_CLIENT_ID }}`
   — `app-id` is deprecated upstream in `actions/create-github-app-token@v3`.
2. `JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}` → `JIRA_EMAIL: ${{ vars.JIRA_EMAIL }}`
   — basic-auth username, not a credential. Already visible in commit author + Jira comments.

## Phase 1.5 verification

Before this PR merges, BOTH repo variables MUST exist on this repository:

- `DOCS_AGENT_APP_CLIENT_ID` (Iv1.xxx format from the App settings page)
- `JIRA_EMAIL` (Atlassian account email)

The reviewer should run:

```

gh variable list --repo theoju/claude-code-self-assessment | grep -E "DOCS_AGENT_APP_CLIENT_ID|JIRA_EMAIL"

```

and confirm both rows are present before merging. If either is missing, the next nightly hard-fails at the app-token step.

## References

- Companion plugin PR: theoju/engineering-docs-agent#<plugin-pr> (CCE-66)
- Jira: CCE-66 in the Claude-Code-Extensions project
- Upstream deprecation: https://github.com/actions/create-github-app-token

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Watch CI; admin-merge when green**

```bash
gh pr view <pr#> --repo theoju/claude-code-self-assessment --json statusCheckRollup
# When green:
gh pr merge <pr#> --repo theoju/claude-code-self-assessment --admin --squash --delete-branch
```

- [ ] **Step 5: Workflow_dispatch verification (Phase 3) — machine-checkable**

```bash
gh workflow run docs-agent-nightly.yml --repo theoju/claude-code-self-assessment -f reason="CCE-66 verify"
sleep 30  # let the run register
RUN_ID=$(gh run list --repo theoju/claude-code-self-assessment --workflow docs-agent-nightly.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN_ID" --repo theoju/claude-code-self-assessment --exit-status
LOG=$(gh run view "$RUN_ID" --repo theoju/claude-code-self-assessment --log)

# Assertion A: app-token step succeeded (Bash exit propagated above; double-check the marker line):
echo "$LOG" | grep -qE "Generate GitHub App installation token.*completed.*success" \
  || { echo "::error::app-token step did not show a success marker"; exit 1; }

# Assertion B: no `app-id` deprecation warning emitted:
if echo "$LOG" | grep -qE "Warning:.*app-id"; then
  echo "::error::workflow still surfaces an app-id deprecation warning"; exit 1
fi

# Assertion C: source-collector Jira enrichment ran without missing-auth flag:
if echo "$LOG" | grep -qE "jira_auth_missing"; then
  echo "::error::source-collector reports jira_auth_missing — JIRA_EMAIL var likely empty"; exit 1
fi

echo "Task 8 Step 5 verification PASSED"
```

Each assertion is a non-zero-exit check, so failure halts the script and surfaces the specific failed condition to the operator.

---

## Task 9: Host PR — ADIS workflow edit

**Files:**

- Modify (in ADIS clone): `.github/workflows/docs-agent-nightly.yml` (2 lines)

- [ ] **Step 1: Repeat Task 8 steps for ADIS**

Same 2-line edit. Branch: `chore/CCE-66-client-id-migration`. Clone path: `/tmp/cce66-adis`. Open PR against `theoju/advanced-data-import-system`. Workflow_dispatch verification after merge.

The body of the commit and PR is identical to Task 8 except for the host repo name.

---

## Task 10: Phase 4 — secret cleanup

**Files:** (none — manual GitHub operations)

Only after Tasks 7, 8, 9 are merged AND each repo has a green workflow_dispatch verification confirming token-mint + Jira enrichment.

- [ ] **Step 1: Delete the obsolete secrets**

```bash
for repo in theoju/engineering-docs-agent theoju/claude-code-self-assessment theoju/advanced-data-import-system; do
  gh secret delete DOCS_AGENT_APP_ID --repo "$repo" || echo "(already gone on $repo)"
  gh secret delete JIRA_EMAIL        --repo "$repo" || echo "(already gone on $repo)"
done
```

- [ ] **Step 2: Final verification — trigger one more workflow_dispatch**

For each repo, fire workflow_dispatch and confirm it still passes (nothing reads the deleted secrets anymore).

- [ ] **Step 3: Close out Jira**

Transition CCE-66 → Done with a comment summarizing: plugin PR + 2 host PRs + Phase 4 cleanup all complete.

---

## Recovery procedures

The migration is staged so any single phase can fail and roll back without losing the others. Refer to this section if any of Tasks 7/8/9 produces an unexpected red CI run or hard-fails in production.

### Scenario A — Plugin PR merged, host PR not yet merged, host nightly red

Most likely cause: variable not set on the host. The plugin PR's docs sweep and preflight changes alone are inert on a host until that host's workflow file references `vars.` paths. If the host's `docs-agent-nightly.yml` still references `secrets.DOCS_AGENT_APP_ID` AND the secret hasn't been deleted yet (Phase 4 not yet run), the host should be unaffected. If you are seeing red runs, re-check Phase 1.5 with the bash from Task 7 Step 0.

### Scenario B — Host PR merged, variable missing on that host

The next nightly will hard-fail at the `Generate GitHub App installation token` step (the action will refuse to mint a token with an empty `client-id`). Fix:

```bash
gh variable set DOCS_AGENT_APP_CLIENT_ID --repo theoju/<host> --body "Iv1.xxxxxxxxxxxxxxxx"
gh workflow run docs-agent-nightly.yml --repo theoju/<host> -f reason="post-fix verify"
```

No code change needed. Set the variable, re-fire dispatch.

### Scenario C — Need to revert ONE host while leaving the others migrated

The host PRs are mutually independent (Tasks 8 and 9 each open a separate PR on a separate repo). Revert is per-host:

```bash
# In the host repo's clone:
git checkout main && git pull
git revert <merge-commit-of-CCE-66-host-PR> -m 1
git push
# Then restore the host's old secrets if you also already ran Phase 4 on it:
gh secret set DOCS_AGENT_APP_ID --repo theoju/<host> --body "<numeric-app-id>"
gh secret set JIRA_EMAIL        --repo theoju/<host> --body "<atlassian-email>"
```

The OTHER hosts stay on the new wiring. The plugin PR does not need to revert — preflight surfacing both `secrets_checklist` and `variables_checklist` is forward-compatible with both auth tiers on different hosts.

### Scenario D — Plugin PR introduces a pytest regression discovered after merge

Re-open a fix PR off `main`. Do NOT revert the plugin PR — the host PRs may already reference the new variable wiring and rolling back the plugin would leave them with no preflight guidance. Fix forward.

## Out of scope

- `templates/workflow-run.yml` / `workflow-verify.yml` refresh — separate brainstorm (task #383).
- Auditing other `secrets.*` references for category errors — Phase 1 audit already exhaustive.
- Removing `app-id` upstream support — GitHub-side concern.
- Changing the App itself — same App, same permissions, same installations.
- `docs/site-src/whats-new.md` and `CHANGELOG.md` entries — written by the docs-agent nightly itself from the merged PR's commit history, not by this plan. Do not pre-author them.

## Review notes (Phase C revision)

This plan was revised after a 3-reviewer parallel pass (workflow `wf_091ebf57-ab3`) found 4 Critical + 8 Important + 10 Nice-to-have issues. Phase C addressed all Critical + 7 Important findings inline:

- **C1 (function names)** — Task 3 now references the real `secrets_from_workflow` (line 72), `build_report` (line 176), and `render_text` (line 143). Earlier draft hallucinated `build_secrets_checklist` and `compose_output`.
- **C2 (spec/plan contract)** — Plan keeps the YAGNI separate-function design (`variables_from_workflow` + `variables_checklist` field) rather than the spec's tagged-list-with-`kind`. The companion spec edit aligns spec §2 to this choice.
- **C3 (setup-guide.md lines)** — Verified anchors via grep + targeted Read: 62, 70, 124, 133, 136, 293, 342, 343. Earlier draft cited 124, 280, 293 with 280 being a fictitious anchor for env-var resolution prose that does not contain a `DOCS_AGENT_APP_ID` reference.
- **C4 (Phase 1.5 enforcement)** — Task 7 now opens with Step 0, a machine-checkable bash gate that exits non-zero unless all three repos report both required variables.
- **I1 (commit count)** — Task 5 + Task 7 normalized to **7 commits ahead of main** with a ≥6 floor.
- **I2 (Task 4 Files header)** — Reconciled with Step 1's verified anchor list.
- **I3 (format-on-edit warning)** — Promoted to imperative: re-Read ±3 lines after each Edit before issuing the next.
- **I4 (Task 8 Step 5 verifiability)** — Verification block now exits non-zero on any failed assertion.
- **I5 (no partial-revert procedure)** — New "Recovery procedures" section above covers four real failure modes.
- **I6 (Task 8 PR body placeholder)** — Replaced with a verbatim heredoc body.
- **I7 (hardcoded repo names)** — Documented at Task 8's intro as intentional audit-trail concrete-name rollout, not a generalization defect.

Nice-to-have items (h-level alignment, deeper docstrings, etc.) were considered and skipped to keep the diff focused.

## After Task 10 — handoff

CCE-66 fully closed. Three repos on new auth wiring. Tomorrow's 07:07 UTC nightly is the production-truth gate.
