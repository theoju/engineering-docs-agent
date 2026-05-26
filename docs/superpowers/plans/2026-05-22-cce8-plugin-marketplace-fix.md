# CCE-8: Plugin marketplace registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `claude plugin marketplace add /Users/theo/Projects/engineering-docs-agent` succeed without `--plugin-dir` workarounds.

**Architecture:** Move `marketplace.json` from repo root to `.claude-plugin/marketplace.json` (the CLI-expected location) and add the missing required `owner` object. Delete the old root file (no legacy copy — single source of truth). Document the install path in README.

**Tech Stack:** JSON config; `claude` CLI for validation; markdown for README.

**Spec reference:** `docs/superpowers/specs/2026-05-22-cce6-7-8-batch-design.md` — CCE-8 section.

---

## File Structure

- **Create:** `.claude-plugin/marketplace.json` — moved + augmented copy of root `marketplace.json`.
- **Delete:** `marketplace.json` (repo root) — superseded by the move; not kept as legacy copy.
- **Modify:** `README.md` — add "Install from local clone" subsection under Self-hosting.

---

## Task 1: Capture current schema error and confirm required `owner` shape

**Files:**

- (no edits — diagnostic only)

- [ ] **Step 1: Confirm root marketplace.json contents**

Run: `cat marketplace.json`

Expected:

```json
{
  "name": "engineering-docs-agent-marketplace",
  "description": "Self-hosted marketplace for engineering-docs-agent.",
  "plugins": [
    {
      "name": "engineering-docs-agent",
      "source": ".",
      "version": "0.1.1"
    }
  ]
}
```

- [ ] **Step 2: Try the failing `marketplace add` command to capture the current error**

Run: `claude plugin marketplace add /Users/theo/Projects/engineering-docs-agent 2>&1`

Expected stderr: an error message about either the path (`Marketplace file not found at .../.claude-plugin/marketplace.json`) or — if you first `cp` to `.claude-plugin/` — about the `owner` field.

- [ ] **Step 3: If the path error is the only one, copy the file and try again**

Run:

```bash
mkdir -p .claude-plugin
cp marketplace.json .claude-plugin/marketplace.json
claude plugin marketplace add . 2>&1
```

Expected: schema error mentioning `owner` (per the ticket: `Invalid input: expected object, received undefined`). Capture the **exact error message** — this drives Task 2's `owner` block shape.

- [ ] **Step 4: If the error mentions other required fields, capture them too**

Different CLI versions may require additional fields. Run `claude plugin validate .` and record every required-field complaint. The full set drives Task 2.

- [ ] **Step 5: Clean up the temporary copy**

Run: `rm .claude-plugin/marketplace.json`

(Task 2 will recreate it with the corrected content; we don't want to leave a half-fixed file mid-task.)

- [ ] **Step 6: No commit for this task — diagnostic only**

Move to Task 2 with the captured error in hand.

---

## Task 2: Create `.claude-plugin/marketplace.json` with `owner` block

**Files:**

- Create: `.claude-plugin/marketplace.json`

- [ ] **Step 1: Write the new file**

Write `.claude-plugin/marketplace.json` with:

```json
{
  "name": "engineering-docs-agent-marketplace",
  "description": "Self-hosted marketplace for engineering-docs-agent.",
  "owner": {
    "name": "Theo Jungeblut",
    "url": "https://github.com/theoju"
  },
  "plugins": [
    {
      "name": "engineering-docs-agent",
      "source": ".",
      "version": "0.1.1"
    }
  ]
}
```

**If Task 1 Step 3 surfaced additional required fields**, add them here. Typical shapes:

- `owner.email`: string — add if the schema demands it.
- `support.url`: string — sometimes required.

Do NOT add fields the schema does not require. YAGNI.

- [ ] **Step 2: Verify with `claude plugin validate`**

Run: `claude plugin validate /Users/theo/Projects/engineering-docs-agent 2>&1`

Expected: clean exit (rc=0), no errors. If errors remain, adjust the JSON to match what the CLI reports and re-run until clean.

- [ ] **Step 3: Verify with `claude plugin marketplace add`**

Run:

```bash
# First, check if the marketplace was already added in a previous test;
# remove it if so to get a clean signal.
claude plugin marketplace list 2>&1 | grep engineering-docs-agent && \
  claude plugin marketplace remove engineering-docs-agent-marketplace || true
claude plugin marketplace add /Users/theo/Projects/engineering-docs-agent 2>&1
```

Expected: success message; no schema errors.

- [ ] **Step 4: Verify plugin installs without `--plugin-dir`**

Run:

```bash
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace 2>&1
```

Expected: success; the seven agents (content-validator, gap-detector, notifier, page-author, pr-summarizer, publish-verifier, source-collector) resolve.

If install fails for a reason other than the marketplace registration (e.g., conflict with an existing install), surface and address; don't paper over.

- [ ] **Step 5: Commit**

```bash
git add .claude-plugin/marketplace.json
git commit -m "$(cat <<'EOF'
fix(CCE-8): add .claude-plugin/marketplace.json with required owner block

The CLI expects the marketplace file at .claude-plugin/marketplace.json
(not the repo root) and requires an "owner" object. Without these,
`claude plugin marketplace add .` failed with a schema error and users
had to use --plugin-dir workarounds.

Verified with: claude plugin validate . (clean exit)
                claude plugin marketplace add . (success)
                claude plugin install engineering-docs-agent@... (success)

Refs: docs/superpowers/specs/2026-05-22-cce6-7-8-batch-design.md (CCE-8)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Delete the old root `marketplace.json`

**Files:**

- Delete: `marketplace.json` (repo root)

- [ ] **Step 1: Confirm the two files would diverge if both kept**

Run: `diff marketplace.json .claude-plugin/marketplace.json`

Expected: differences (the new file has `owner`). This confirms that keeping both would mean two sources of truth — exactly what the spec rejects.

- [ ] **Step 2: Delete the root file**

Run: `git rm marketplace.json`

- [ ] **Step 3: Verify validation still passes**

Run: `claude plugin validate /Users/theo/Projects/engineering-docs-agent 2>&1`

Expected: clean exit. The CLI reads from `.claude-plugin/marketplace.json`; the root file's absence is fine.

- [ ] **Step 4: Verify the existing 235-test suite still passes**

Run: `pytest -q 2>&1 | tail -3`

Expected: 235 passed. No test depends on the root `marketplace.json` (verified by grepping `marketplace.json` in `tests/` — should return nothing).

If any test fails because it referenced the root file path, update it to point at `.claude-plugin/marketplace.json` and surface the change as a Task 3 amendment.

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
chore(CCE-8): remove root marketplace.json — single source of truth at .claude-plugin/

The CLI reads from .claude-plugin/marketplace.json (Task 2). Keeping
a stale root copy would mean two sources of truth that drift over time.

Refs: docs/superpowers/specs/2026-05-22-cce6-7-8-batch-design.md (CCE-8)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Document install in README

**Files:**

- Modify: `README.md` — add "Install from local clone" subsection under "Self-hosting (dogfood)"

- [ ] **Step 1: Find the insertion point**

Run: `grep -n "## Self-hosting\|### Lens paths\|### Jira enrichment" README.md`

The "Install from local clone" subsection should appear AFTER "## Self-hosting (dogfood)" but BEFORE "### Lens paths and editable paths" (which CCE-22 added). Insert it as the first `###` subsection under Self-hosting.

- [ ] **Step 2: Add the subsection**

Edit `README.md` to add this block immediately before the existing `### Lens paths and editable paths` line:

````markdown
### Install from local clone

If you're working from a checkout of this repo (e.g., to test changes before publishing):

```bash
claude plugin marketplace add /path/to/engineering-docs-agent
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace
```
````

That makes the seven agents resolvable without `--plugin-dir` workarounds. The marketplace registration reads `.claude-plugin/marketplace.json`; the plugin manifest is at `.claude-plugin/plugin.json`.

````

(Note: the triple-backticks for the code block need to be escaped in this plan — the actual README block uses real triple-backticks.)

- [ ] **Step 3: Verify the rendered markdown looks right**

Run: `grep -A 12 "### Install from local clone" README.md`

Expected: the full subsection, properly formatted.

- [ ] **Step 4: Run the full test suite as a smoke**

Run: `pytest -q 2>&1 | tail -3`

Expected: 235 passed. Docs change should not affect tests.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(CCE-8): README — Install from local clone

Documents the `claude plugin marketplace add` + `claude plugin install`
path now that .claude-plugin/marketplace.json validates cleanly.

Closes CCE-8.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
````

---

## Spec coverage check

Spec acceptance criteria for CCE-8:

- [x] `claude plugin marketplace add /Users/theo/Projects/engineering-docs-agent` succeeds — Task 2 step 3.
- [x] `claude plugin install engineering-docs-agent@...` succeeds and agents resolve — Task 2 step 4.
- [x] `claude plugin validate /Users/theo/Projects/engineering-docs-agent` returns clean — Task 2 step 2 + Task 3 step 3.
- [x] README updated with "Install from local clone" section — Task 4.
- [x] Old root `marketplace.json` is deleted (decided: not kept as legacy copy) — Task 3.

No gaps.

## Risk and YAGNI

- This plan does NOT publish to an external marketplace (out of scope per ticket).
- This plan does NOT add `claude plugin tag` automation (out of scope per ticket).
- The `owner` block uses minimal viable shape (name + url). If the CLI demands more, Task 2 step 1 captures the exact list and Task 2 step 2 widens accordingly — no speculative field additions.
