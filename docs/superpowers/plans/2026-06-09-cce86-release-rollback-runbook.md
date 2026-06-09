# CCE-86 Release-Ops Runbook Polish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture reusable release-day operational knowledge (rollback, two-clock SLA, tag-cut-misfire recovery) in a durable `docs/runbooks/release-and-rollback.md`, add the migration-specific CHANGELOG step + a cross-link to the CCE-80 runbook, add a discoverability pointer to `CLAUDE.md`, and guard the cross-links with a link-resolution test.

**Architecture:** Pure documentation change plus one pytest guard. Three Markdown touch points (one new file, two edits) and one new test module. No runtime code, no site pages — everything lives in `docs/runbooks/` (outside `docs_dir`, so `mkdocs --strict` is unaffected). The single durable automated guard is a link-resolution test; per-task validation greps confirm each content change matches expectations.

**Tech Stack:** Markdown, Python 3 stdlib (`re`, `pathlib`), pytest. `mkdocs` is on PATH at `~/.local/bin/mkdocs`.

**Spec:** `docs/superpowers/specs/2026-06-09-cce86-release-rollback-runbook-design.md`

**Branch:** `docs/CCE-86-release-rollback-runbook` (already created off `main`; the spec is already committed there as `cf7c3a9`).

---

## File Structure

| File                                    | Responsibility                                                                                                                                                               | Task |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| `docs/runbooks/release-and-rollback.md` | **New.** Durable, version-agnostic release-ops runbook: two-clock SLA, rollback playbook, tag-cut-misfire recovery. Backlinks to the CCE-80 runbook.                         | 1    |
| `docs/runbooks/cce80-host-migration.md` | **Edit.** Add a CHANGELOG-update step in the post-merge gate + a cross-link callout to the new runbook. Existing per-host migration steps untouched.                         | 2    |
| `CLAUDE.md`                             | **Edit.** One-line release-ops pointer bullet (discoverability hook).                                                                                                        | 3    |
| `tests/docs/__init__.py`                | **New.** Empty package marker (matches `tests/site/`, `tests/archive/` convention).                                                                                          | 4    |
| `tests/docs/test_runbook_links.py`      | **New.** Link-resolution guard: every relative Markdown link in `docs/runbooks/*.md` resolves; the CCE-80 runbook cross-links the release runbook; `CLAUDE.md` points at it. | 4    |

**Execution order rationale:** content first (Tasks 1–3), durable test last (Task 4). This is a docs change, so each content task is validated at commit time by exact greps (content correctness) rather than a pre-written failing unit test. The link-resolution test is added last and **proven discriminating** by temporarily breaking a link — the same "prove the test would catch the bug" technique used in CCE-107, giving the test-first guarantee without committing a red test.

---

## Task 1: Create the durable release-ops runbook

**Files:**

- Create: `docs/runbooks/release-and-rollback.md`

- [ ] **Step 1: Write the new runbook**

Use the Write tool with file path `docs/runbooks/release-and-rollback.md` and **exactly** this content:

````markdown
# Release & Rollback Runbook

Version-agnostic operational guide for cutting, validating, rolling back, and
recovering a release of the engineering-docs-agent plugin. Reusable for every
version tag; examples use `v0.5.0` (cut 2026-06-04) as the worked case.

For the one-time CCE-80 host-migration steps, see
[`cce80-host-migration.md`](cce80-host-migration.md).

## The two release clocks

Cutting a release starts two independent clocks. Operators repeatedly conflate
them — do not. "The release passed" (Clock 1) does not mean "the hosts have it"
(Clock 2).

| Clock                      | What you are waiting on                                                | Typical duration                 | How to check                                                                   |
| -------------------------- | ---------------------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------------------------ |
| **1 — release validation** | `release.yml` live-tests run after the tag is pushed                   | ~5–10 min                        | `gh run watch --workflow release.yml`                                          |
| **2 — host pickup**        | Tag-pinned host repos pull the new ref on their next nightly cron tick | up to ~24h (next 07:07 UTC tick) | `gh run list --repo theoju/<host> --workflow docs-agent-nightly.yml --limit 1` |

Notes:

- **Clock 2 is daily, not hourly.** The nightly cron is `7 7 * * *` (07:07 UTC) in
  `templates/workflow-run.yml`. A host pinned to a tag (the default `ref:` in
  `templates/workflow-run.yml`) does not pick up a new release until the next 07:07
  UTC tick — worst case ~24h after the tag is cut.
- **Main-tracking hosts skip Clock 2's tag dependency.** A host installed via
  `claude plugin update` (main-tracking, not tag-pinned) picks up `main` on its next
  nightly with no tag wait.

**Worked example — v0.5.0:**

- Tag pushed `2026-06-04T15:33Z`; `release.yml` went green ~30s later — Clock 1
  closed in under a minute that cut (the ~5–10 min figure is the upper bound when the
  live-tests exercise the full matrix).
- Tag-pinned hosts became eligible at the next 07:07 UTC tick — Clock 2.

## Rollback playbook

Use when a cut release is bad enough that hosts must not pick it up.

### Decide first: roll back vs. cut a forward patch

| Situation                                                                 | Action                                                                                          |
| ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Tag is broken and **no host has picked it up yet** (still within Clock 2) | **Roll back** — delete the tag before the next 07:07 UTC tick.                                  |
| Hosts have **already** picked it up, or the fix is small                  | **Cut a forward patch** (e.g. `v0.5.1`). Rolling back a consumed tag strands hosts mid-version. |

### Roll back a tag

```bash
gh release delete <tag> --cleanup-tag --yes   # e.g. gh release delete v0.5.0 --cleanup-tag --yes
gh release view <tag>                          # expect: "release not found"
```

`--cleanup-tag` deletes the underlying git tag as well as the GitHub release; `--yes`
skips the confirmation prompt.

### Post-rollback hygiene

- **Main-tracking hosts** self-heal: their next nightly pulls `main`, which no longer
  references the deleted tag. No action needed.
- **Tag-pinned hosts** need a **downgrade PR** re-pinning `ref:` in their
  `.github/workflows/docs-agent-nightly.yml` to the prior good tag. Until that lands,
  their plugin-vendoring checkout step fails (the tag is gone).
- Post a comment on the closing Jira ticket recording the rollback and the reason.

## Tag-cut-misfire recovery

The misfire: `gh release create` **succeeds**, but `release.yml` then **fails** (for
example, live-tests red). The tag exists; the release is unvalidated.

Real precedent: the `2026-05-27` `release.yml` run (the PR #43 release attempt) failed
this way. (v0.5.0 itself did not — its run was green ~30s after the tag.)

Recovery:

1. **Leave the tag in place.** Do not reflexively delete it — deleting mid-validation
   destroys the audit trail and confuses any host that already polled.
2. **Post the partial state on the closing Jira ticket:** "Tag `<tag>` cut at
   `<time>`; `release.yml` run `<id>` failed at `<step>`. Validation incomplete." This
   leaves the next triager a visible breadcrumb on a still-open concern.
3. **Decide by severity:**
   - Live-tests red for an **environmental/flaky** reason → re-run `release.yml`
     (`gh run rerun <id>`); no new tag needed.
   - Live-tests red for a **real defect** → cut a forward patch with the fix
     (`v0.5.1`), or roll back per the playbook above if no host has picked up yet.
````

- [ ] **Step 2: Validate the content matches expectations**

Run each command; every one must print the expected line(s):

```bash
cd /Users/theo/Projects/engineering-docs-agent
# All three required section headings present
grep -n "^## The two release clocks$"     docs/runbooks/release-and-rollback.md
grep -n "^## Rollback playbook$"           docs/runbooks/release-and-rollback.md
grep -n "^## Tag-cut-misfire recovery$"    docs/runbooks/release-and-rollback.md
# Exact rollback command (with the --cleanup-tag --yes flags from the ticket)
grep -n "gh release delete <tag> --cleanup-tag --yes" docs/runbooks/release-and-rollback.md
# Corrected Clock-2 figure (~24h / 07:07 UTC), NOT the ticket's wrong "~60 min"
grep -n "up to ~24h"   docs/runbooks/release-and-rollback.md
grep -n "07:07 UTC"    docs/runbooks/release-and-rollback.md
test "$(grep -c "~60 min" docs/runbooks/release-and-rollback.md)" = "0" && echo "OK: no stale ~60 min figure"
# Worked-example v0.5.0 facts + misfire precedent
grep -n "2026-06-04T15:33Z" docs/runbooks/release-and-rollback.md
grep -n "2026-05-27"        docs/runbooks/release-and-rollback.md
# Backlink to the CCE-80 runbook
grep -n "(cce80-host-migration.md)" docs/runbooks/release-and-rollback.md
```

Expected: each `grep` prints a matching line; the `~60 min` check prints `OK: no stale ~60 min figure`.

- [ ] **Step 3: Confirm the docs site is unaffected**

Run: `export PATH="$HOME/.local/bin:$PATH" && mkdocs build --strict >/tmp/cce86_t1.log 2>&1; echo "exit=$?"`
Expected: `exit=0` (the file is outside `docs_dir`, so the build is unchanged). If non-zero, inspect `/tmp/cce86_t1.log` for any `WARNING`/`ERROR` other than the benign MkDocs deprecation banner.

- [ ] **Step 4: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add docs/runbooks/release-and-rollback.md
git commit -m "docs(CCE-86): add durable release-and-rollback runbook

Two-clock SLA (release.yml validation vs ~24h tag-pinned host pickup),
rollback playbook (gh release delete --cleanup-tag --yes), and tag-cut-misfire
recovery. Worked example grounded in the actual v0.5.0 cut + the 2026-05-27
misfire precedent.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Add the CHANGELOG step + cross-link to the CCE-80 runbook

**Files:**

- Modify: `docs/runbooks/cce80-host-migration.md` (Post-merge gate section, lines ~18–32)

- [ ] **Step 1: Read the anchor region**

Run: `sed -n '18,33p' docs/runbooks/cce80-host-migration.md`
Confirm line 22 reads `checkout step. PR author cuts the tag within 5 minutes of merge:` and line 32 reads ``Do not begin per-host migration until `gh release view v0.5.0` succeeds.`` (If line numbers drift, match on the text — these are the two Edit anchors.)

- [ ] **Step 2: Add the CHANGELOG-update step (Edit A)**

Use the Edit tool on `docs/runbooks/cce80-host-migration.md`.

old_string:

```
checkout step. PR author cuts the tag within 5 minutes of merge:
```

new_string:

````
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
````

- [ ] **Step 3: Add the cross-link callout (Edit B)**

Use the Edit tool on `docs/runbooks/cce80-host-migration.md`.

old_string:

```
Do not begin per-host migration until `gh release view v0.5.0` succeeds.
```

new_string:

```
Do not begin per-host migration until `gh release view v0.5.0` succeeds.

> **If this release goes bad** — rolling back the tag, the two release clocks
> (validation vs ~24h host pickup), and tag-cut-misfire recovery — see
> [`release-and-rollback.md`](release-and-rollback.md).
```

- [ ] **Step 4: Validate the edits matched expectations**

```bash
cd /Users/theo/Projects/engineering-docs-agent
# CHANGELOG step landed
grep -n "update the CHANGELOG" docs/runbooks/cce80-host-migration.md
grep -n "## \[0.5.0\] — 2026-06-04" docs/runbooks/cce80-host-migration.md
# Cross-link landed and points at the new runbook
grep -n "(release-and-rollback.md)" docs/runbooks/cce80-host-migration.md
# Existing per-host migration steps are UNTOUCHED (all five still present)
for h in "Provision new secrets" "Re-run setup skill" "Re-apply mkdocs install" "Verify with manual dispatch" "Remove legacy secret"; do
  grep -q "$h" docs/runbooks/cce80-host-migration.md && echo "OK kept: $h" || echo "MISSING: $h"
done
```

Expected: the two `grep` lines print matches, the cross-link `grep` prints a match, and all five `OK kept:` lines print (no `MISSING:`).

- [ ] **Step 5: Confirm additive-only**

Run: `git diff --stat docs/runbooks/cce80-host-migration.md`
Expected: insertions only, `0` deletions (e.g. `1 file changed, N insertions(+)`). If any deletions appear, an Edit clobbered existing content — revert and redo.

- [ ] **Step 6: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add docs/runbooks/cce80-host-migration.md
git commit -m "docs(CCE-86): CHANGELOG step + release-runbook cross-link in cce80 runbook

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Add the discoverability pointer to CLAUDE.md

**Files:**

- Modify: `CLAUDE.md` (Plugin conventions list — after the CCE-103 jira-transition bullet)

- [ ] **Step 1: Read the anchor region**

Run: `grep -n "Reference: CCE-103." CLAUDE.md`
Confirm exactly one match (the end of the jira-transition bullet). Then `sed -n` a few lines around it to capture the exact trailing text for the Edit.

- [ ] **Step 2: Insert the release-ops pointer bullet**

Use the Edit tool on `CLAUDE.md`. The `old_string` is the tail of the CCE-103 bullet; the `new_string` re-states it and appends the new bullet.

old_string:

```
 `JIRA_BASE_URL` would move to config then). Reference: CCE-103.
```

new_string:

```
 `JIRA_BASE_URL` would move to config then). Reference: CCE-103.
- **Release & rollback ops live in `docs/runbooks/release-and-rollback.md`.** Cutting a version tag, the two release clocks (`release.yml` validation ~5–10 min vs tag-pinned host pickup up to ~24h at the next 07:07 UTC nightly), rolling back a bad tag (`gh release delete <tag> --cleanup-tag --yes`), and tag-cut-misfire recovery are documented there. The one-time CCE-80 host migration is in `docs/runbooks/cce80-host-migration.md`. Reference: CCE-86 (2026-06-09).
```

(If the `old_string` does not match verbatim because of surrounding whitespace, use the exact text captured in Step 1 — the goal is a new top-level `- **Release & rollback ops...**` bullet immediately after the CCE-103 bullet.)

- [ ] **Step 3: Validate**

```bash
cd /Users/theo/Projects/engineering-docs-agent
grep -n "docs/runbooks/release-and-rollback.md" CLAUDE.md
grep -n "Reference: CCE-86 (2026-06-09)" CLAUDE.md
git diff --stat CLAUDE.md   # expect insertions only, 0 deletions
```

Expected: both `grep`s print a match; the diffstat shows insertions only.

- [ ] **Step 4: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add CLAUDE.md
git commit -m "docs(CCE-86): point CLAUDE.md conventions at the release-and-rollback runbook

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Link-resolution guard test + final validation

**Files:**

- Create: `tests/docs/__init__.py`
- Create: `tests/docs/test_runbook_links.py`

- [ ] **Step 1: Create the package marker**

Use the Write tool to create `tests/docs/__init__.py` with empty content (`""`). This matches the existing `tests/site/__init__.py` / `tests/archive/__init__.py` convention.

- [ ] **Step 2: Write the link-resolution test**

Use the Write tool with file path `tests/docs/test_runbook_links.py` and **exactly** this content:

```python
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNBOOKS = _REPO_ROOT / "docs" / "runbooks"

# Markdown inline links: [text](target). Captures the target. Link text may
# contain backticks (e.g. [`file.md`](file.md)), so [^\]]+ is correct.
_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _relative_link_targets(md_path: Path) -> list[str]:
    """Relative Markdown link targets in a file (skips http(s)/mailto and anchors)."""
    text = md_path.read_text(encoding="utf-8")
    targets: list[str] = []
    for raw in _LINK_RE.findall(text):
        target = raw.split("#", 1)[0].strip()  # drop any #anchor fragment
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        targets.append(target)
    return targets


def test_release_runbook_exists():
    assert (_RUNBOOKS / "release-and-rollback.md").is_file()


def test_runbook_relative_links_resolve():
    # Every relative Markdown link inside docs/runbooks/*.md must resolve to a real
    # file. Guards the cross-links between cce80-host-migration.md and
    # release-and-rollback.md against rot (e.g. a rename).
    broken: list[str] = []
    for md in sorted(_RUNBOOKS.glob("*.md")):
        for target in _relative_link_targets(md):
            if not (md.parent / target).resolve().is_file():
                broken.append(f"{md.name} -> {target}")
    assert not broken, f"broken runbook links: {broken}"


def test_cce80_runbook_links_to_release_runbook():
    cce80 = (_RUNBOOKS / "cce80-host-migration.md").read_text(encoding="utf-8")
    assert "release-and-rollback.md" in cce80, (
        "cce80-host-migration.md must cross-link to the release runbook"
    )


def test_claude_md_points_to_release_runbook():
    claude = (_REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    rel = "docs/runbooks/release-and-rollback.md"
    assert rel in claude, "CLAUDE.md is missing the release-runbook pointer"
    assert (_REPO_ROOT / rel).is_file()
```

- [ ] **Step 3: Run the test — expect PASS (content from Tasks 1–3 is in place)**

Run: `python3 -m pytest tests/docs/test_runbook_links.py -v`
Expected: `4 passed`.

- [ ] **Step 4: Prove the test is discriminating (break a link, watch it fail, restore)**

The test was written after the content, so prove it would actually catch a regression:

```bash
cd /Users/theo/Projects/engineering-docs-agent
# Temporarily rot the cross-link target in the CCE-80 runbook
cp docs/runbooks/cce80-host-migration.md /tmp/cce80.bak
python3 - <<'PY'
from pathlib import Path
p = Path("docs/runbooks/cce80-host-migration.md")
p.write_text(p.read_text().replace("(release-and-rollback.md)", "(release-and-rollback-MOVED.md)"))
PY
python3 -m pytest tests/docs/test_runbook_links.py -q 2>&1 | tail -5   # expect FAILURES
# Restore
cp /tmp/cce80.bak docs/runbooks/cce80-host-migration.md && rm /tmp/cce80.bak
python3 -m pytest tests/docs/test_runbook_links.py -q 2>&1 | tail -3   # expect 4 passed
```

Expected: the middle run reports failures in `test_runbook_relative_links_resolve` (and `test_cce80_runbook_links_to_release_runbook` still passes — the literal string is present even when the target is wrong, which is why the _resolution_ test is the real guard); the final run reports `4 passed`. Confirm `git status --porcelain` shows the runbook unchanged after restore.

- [ ] **Step 5: Full-suite + consumer-tool validation**

```bash
cd /Users/theo/Projects/engineering-docs-agent
# New test is collected by the full suite (testpaths = ["tests"])
python3 -m pytest -q 2>&1 | tail -3
# Real consumer gate (AC3)
export PATH="$HOME/.local/bin:$PATH" && mkdocs build --strict >/tmp/cce86_final.log 2>&1; echo "mkdocs exit=$?"
```

Expected: the suite reports all passed (prior count `963 passed, 3 skipped` + the 4 new = `967 passed, 3 skipped`); `mkdocs exit=0`.

- [ ] **Step 6: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add tests/docs/__init__.py tests/docs/test_runbook_links.py
git commit -m "test(CCE-86): link-resolution guard for runbook cross-links + CLAUDE.md pointer

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification (after all tasks)

- [ ] Full suite green: `python3 -m pytest -q` → `967 passed, 3 skipped`.
- [ ] Real consumer green: `mkdocs build --strict` exit 0.
- [ ] Branch contains 4 implementation commits (+ the spec commit `cf7c3a9`): `git log --oneline main..HEAD`.
- [ ] Tree clean: `git status --porcelain` empty.
- [ ] Dispatch a final whole-branch code reviewer over `git diff main...HEAD`.

**Acceptance-criteria cross-check (from the spec):**

- **AC1** (four operator-actionable sections) → Task 2 (CHANGELOG step in the CCE-80 runbook) + Task 1 (rollback, two-clock SLA, misfire recovery in the new runbook).
- **AC2** (references the actual v0.5.0 release as a worked example) → Task 1 Step 2 validates the `2026-06-04T15:33Z` tag facts, the green v0.5.0 run framing, the `2026-05-27` misfire precedent, and the corrected `~24h` Clock 2.
- **AC3** (`mkdocs build --strict` still passes) → Task 1 Step 3 + Task 4 Step 5.

---

## Notes for the executor

- **Why content-first, test-last:** this is a docs change; there is no production function to TDD. The durable guard (Task 4) is proven to discriminate by Step 4's break-and-restore — that supplies the "watch it fail" guarantee without committing a red test.
- **`~24h` not `~60 min`:** the spec deliberately corrects the ticket's host-pickup figure (the cron is `7 7 * * *`, daily). Do not "fix" it back to ~60 min.
- **Outside `docs_dir`:** `docs/runbooks/` is not part of the published site, so no frontmatter contract and no Tier-1 lint apply. `mkdocs --strict` is a regression guard only (it must stay green; it is not exercising the runbook).
- **Additive edits:** Tasks 2 and 3 must show `0` deletions in `git diff --stat`. Any deletion means an Edit clobbered content.
