# Spec: CCE-77 / CCE-80 Cycle Hygiene — Multi-Venue Followups

**Date:** 2026-06-04
**Status:** Draft → Approved (consolidating spec; per-ticket detail in Jira)
**Author:** Claude (orchestrator)
**Tickets covered:** CCE-84, CCE-85, CCE-87, CCE-88

## Context

The CCE-77 (`/ship -f` guardrail) and CCE-80 (mkdocs-autorefs docstring) cycles each shipped with explicit out-of-scope followups. This spec consolidates the four highest-priority followups so they land as a coherent post-sprint hygiene batch rather than 4 trickle PRs.

The followups span **three venues** because the underlying work lives in three places:

| Ticket                                                  | Where the work lands                                                      | Mechanism                                                   |
| ------------------------------------------------------- | ------------------------------------------------------------------------- | ----------------------------------------------------------- |
| **CCE-84** Promote `diagram-gate` to required check     | GitHub branch protection on `theoju/engineering-docs-agent`               | `gh api -X PUT .../branches/main/protection` — no PR commit |
| **CCE-85** Narrow `docs.yml` paths trigger              | `theoju/engineering-docs-agent/.github/workflows/docs.yml`                | PR commit                                                   |
| **CCE-87** Defensive docstring `--FLAG VALUE` lint test | `theoju/engineering-docs-agent/tests/ci/` (new test file)                 | PR commit                                                   |
| **CCE-88** `/ship -f` regex upgrade                     | `~/.claude/skills/ship/lib/validate-git-cmd.sh` — **not in any git repo** | Direct edit + run existing test suite                       |

CCE-85 + CCE-87 ship together as a single engineering-docs-agent PR (both touch CI definitions for the same repo, both are CCE-80 cycle followups). CCE-84 and CCE-88 ship as one-shot operations (admin call and local-edit respectively) with Jira-comment close-out.

## Goals

1. **Land CCE-85 + CCE-87 as a single PR** in `theoju/engineering-docs-agent` with comprehensive tests (TDD-first for CCE-87's lint test; verification-only for CCE-85's YAML change since GitHub Actions path matching can't be unit-tested locally).
2. **Apply CCE-84 branch protection** via a single `gh api -X PUT` call, verify with `gh api ... | jq .required_status_checks.contexts`.
3. **Apply CCE-88's regex upgrade** to `~/.claude/skills/ship/lib/validate-git-cmd.sh` with the variable-assigned bash 3.2.57-compatible regex pattern; verify with the existing test suite (`~/.claude/skills/ship/tests/validate-git-cmd.test.sh`) plus new test cases for `git {checkout,clean,branch,tag} -f` blocks.
4. **Close all four Jira tickets** with comments documenting the landing artifact (PR URL, admin-call output, or commit-equivalent local change record).

## Non-goals

- **No spec for CCE-88's design.** The ticket's "Reference plan" describes the design (variable-assigned regex with enumerated subcommand list) and three lenses already validated it during meta-orchestration. We execute, not re-design. If the test suite reveals a flaw, we revise — but starting from the prescribed design.
- **No expansion of the `/ship` blocked-flag set** beyond the existing `--no-verify`, `--amend`, `--force`, `--force-with-lease`, `-f`. CCE-88 explicitly scoped this out.
- **No refactor of `validate-git-cmd.sh`'s long-form glob checks** (lines 35–38, pre-existing). CCE-88 explicitly scoped this out.
- **No re-write of CCE-85's `docs.yml`** beyond adding the negation patterns and verifying the existing positive patterns still match site sources. No paths-ignore inversion experiments.

## Components

### Component A — CCE-85 + CCE-87 PR (engineering-docs-agent)

**Branch:** `chore/cce-77-80-hygiene-cce-85-87`

**Files modified:**

- `.github/workflows/docs.yml` — add negation patterns for `docs/runbooks/**` and `docs/superpowers/**` under the `paths:` trigger
- `tests/ci/test_docstring_flag_value_lint.py` (NEW) — pytest that walks `scripts/*.py`, applies the two regex patterns from the CCE-87 ticket, fails on matches outside fenced code blocks
- `tests/ci/conftest.py` (modify if needed) — register the new test file appropriately

**Test approach for CCE-87:**

1. RED: write the test, run it expecting PASS against current codebase (CCE-80 fix already landed)
2. RED: write a synthetic regression fixture (`tests/ci/fixtures/regression_docstring.py` with a `--BAR BAZ` shape outside any code block); assert the lint detects it
3. GREEN: implementation is the test itself — the regex catches the synthetic, ignores the legitimate

**Test approach for CCE-85:**
The negation patterns in GitHub Actions `paths:` can't be unit-tested locally. Verification is:

- Manual: confirm the YAML parses (`actionlint .github/workflows/docs.yml`)
- Doc: include in the PR body a 4-row test plan matching CCE-85's acceptance criteria (1: runbooks-only doesn't trigger; 2: superpowers-only doesn't trigger; 3: site-src DOES trigger; 4: mkdocs.yml DOES trigger). Pre-merge: spot-check by viewing the workflow's "files changed" preview on the PR.

### Component B — CCE-84 admin call

**Operation:** `gh api -X PUT repos/theoju/engineering-docs-agent/branches/main/protection -F required_status_checks.contexts[]=...`

**Pre-flight:**

1. Read current protection: `gh api repos/theoju/engineering-docs-agent/branches/main/protection > /tmp/branch-protection-snapshot.json`
2. Extract current contexts: `jq .required_status_checks.contexts /tmp/branch-protection-snapshot.json`
3. Build new contexts array: existing + `"diagram-gate"`
4. PUT the updated protection

**Verification:**

- `gh api repos/theoju/engineering-docs-agent/branches/main/protection | jq -r .required_status_checks.contexts[]` includes `diagram-gate`
- Spot-check: open a draft PR with diagram-gate failing, confirm the merge button is disabled

**Rollback:**

- `gh api -X PUT ... -F required_status_checks.contexts[]=<original-contexts-without-diagram-gate>` using `/tmp/branch-protection-snapshot.json`

### Component C — CCE-88 user-home edit

**File:** `/Users/theo/.claude/skills/ship/lib/validate-git-cmd.sh` (NOT under git)
**Tests:** `/Users/theo/.claude/skills/ship/tests/validate-git-cmd.test.sh` (existing harness)

**Design (per CCE-88 ticket, prescribed):**

- Replace the glob fallback at lines 39–48 with a variable-assigned regex
- Regex anchors on segment boundaries (`^`, `;`, `&`, `|`, `(`, backtick, whitespace) BEFORE the `git` token, then matches a git subcommand from the enumerated set `{push, commit, checkout, clean, branch, tag}`, then `\s+(.+\s+)?-f(\s|$)` to catch `-f` as a flag
- Bash 3.2.57 compatibility: variable-assigned regex (`PATTERN="..."` then `[[ "$CMD" =~ $PATTERN ]]`), NOT inline bracket-class regex
- Stderr format: keep the existing `-f (on git <subcommand>)` pattern

**Test additions:**

- 6 new positive cases: `git checkout -f`, `git clean -f`, `git clean -fd`, `git branch -f X`, `git tag -f X`, plus an extended-pipeline form like `cd repo && git checkout -f master`
- 4 new negative cases: `tar -f`, `grep -f`, `find -f`, `rm -f` (must remain unblocked)
- 1 set -u safety case: `set -u; bash -c '. validate-git-cmd.sh; validate "git checkout -f"'` returns 1, no unbound-variable

**Close-out:**

- Local commit-equivalent record: store a copy of the diff at `~/.claude/skills/ship/.changelog/2026-06-04-cce-88.diff` (creates `.changelog/` if absent)
- Jira comment: paste the diff path + test pass count

## Data flow

```
        ┌─────────────────────────────────────┐
        │      ONE consolidated spec          │
        │  (this document, in eng-docs-agent) │
        └─────────────────────────────────────┘
                       │
                       ▼
        ┌─────────────────────────────────────┐
        │      ONE consolidated plan          │
        │  (per-component task breakdown)     │
        └─────────────────────────────────────┘
                       │
                       ▼
        ┌─────────────────────────────────────┐
        │  Pre-exec 3-agent gate (this spec)  │
        └─────────────────────────────────────┘
              │              │            │
              ▼              ▼            ▼
        ┌──────────┐    ┌──────────┐  ┌──────────┐
        │ Comp A   │    │ Comp B   │  │ Comp C   │
        │ (PR)     │    │ (admin)  │  │ (skill)  │
        └──────────┘    └──────────┘  └──────────┘
              │              │            │
              ▼              ▼            ▼
        ┌─────────────────────────────────────┐
        │  Per-component 3-agent post-impl    │
        │  gates (one set per component)      │
        └─────────────────────────────────────┘
              │              │            │
              ▼              ▼            ▼
        ┌──────────┐    ┌──────────┐  ┌──────────┐
        │ /ship    │    │ verify   │  │ commit-  │
        │ PR       │    │ via gh   │  │ equiv +  │
        │          │    │ api      │  │ Jira ack │
        └──────────┘    └──────────┘  └──────────┘
                       │
                       ▼
        ┌─────────────────────────────────────┐
        │  Jira close-out (4 transitions +    │
        │  4 comments — per-action auth req.) │
        └─────────────────────────────────────┘
```

## Error handling

- **Component A:** standard PR pipeline; if CI red on the new test, fix the test, recommit. If `actionlint` flags the YAML, address syntax. If the negation pattern doesn't work as expected on GitHub Actions, fall back to `paths-ignore:` syntax (note this requires a different YAML shape — would need a follow-up spec correction).
- **Component B:** if `gh api` returns 4xx (e.g., insufficient permissions), abort and surface the error; do not retry. If the existing contexts include `null` or unexpected types, snapshot and abort for human review.
- **Component C:** if the new regex test cases reveal a flaw, isolate (which exact case fails), tweak the regex, re-test. If bash 3.2.57 still mis-parses the variable-assigned regex on macOS, escape iteratively. Keep a snapshot of the pre-edit `validate-git-cmd.sh` at `/tmp/validate-git-cmd.sh.pre-cce88` so rollback is one `cp` away.

## Testing strategy

- **Per the user direction (pragmatic TDD):** real tests for executable behavior; lint/grep verify for config/admin work.
- **CCE-87:** TDD-first (write the test, run it, build the synthetic regression, run it, assert behavior).
- **CCE-88:** existing test harness extended with the new cases; TDD where possible (write new test cases, run them expecting RED, then apply the regex, run them expecting GREEN).
- **CCE-85:** verification by reading the PR's "files changed" trigger preview after the PR opens.
- **CCE-84:** verification by `gh api ... | jq .required_status_checks.contexts`.

## Acceptance criteria

1. **CCE-85** — PR-EDA-HYGIENE merged; the AC1–AC4 in the CCE-85 ticket verified via PR-time inspection of the `docs.yml` paths trigger.
2. **CCE-87** — Same PR; new pytest in `tests/ci/` passes against current main; synthetic regression fixture (committed as part of the PR for future re-validation) fails the lint as expected.
3. **CCE-84** — `gh api repos/theoju/engineering-docs-agent/branches/main/protection | jq -r .required_status_checks.contexts[]` includes `diagram-gate`. A test PR with diagram-gate failing cannot be merged.
4. **CCE-88** — All existing 18 ship lib tests pass; new positive cases (6) and negative cases (4) all pass; `bash -n` parse-check passes on macOS bash 3.2.57; `set -u` safety verified; diff snapshot at `~/.claude/skills/ship/.changelog/2026-06-04-cce-88.diff`.
5. **All four Jira tickets transitioned to Done** with close-out comments (per-action auth needed for each transition).

## Risk surface

- **CCE-84:** the admin call could lock out merges if mis-configured. Snapshot + rollback path covers this; the snapshot is read first, modified locally, and written back — never destructively constructed from scratch.
- **CCE-88:** regex changes in user-home are NOT git-tracked. A regression here breaks `/ship` for ALL future operations. The pre-edit snapshot at `/tmp/validate-git-cmd.sh.pre-cce88` is the rollback. Recommend also copying the post-edit version to `~/.claude/skills/ship/.changelog/` for permanence.
- **CCE-85:** GitHub Actions `paths:` negation syntax is documented but not perfectly intuitive. If the negation order or pattern shape doesn't work, the gate over-fires (annoying but safe) or under-fires (could miss real failures — riskier). Spot-check carefully on the first PR after landing.
- **CCE-87:** the test could be too strict (false positives) on legitimate docstring uses of `--FLAG VALUE` inside backticks the regex doesn't recognize. The implementation has to handle backticks AND `::`-fenced blocks AND triple-backtick fences. Mitigation: TDD against representative fixtures, including the post-CCE-80 `scaffold_workflow.py` which must remain green.

## Followups (out of scope for this batch)

- **CCE-84 + 85 + 87 + 88 close-out:** the Jira-transition step needs explicit per-action auth from the user (one per `transitionJiraIssue` call). Batched here as 4 transitions at the end; orchestrator pauses for go before each.
- **Track-back to CCE-77 plan:** the CCE-77 plan referenced in CCE-88's description (`docs/superpowers/plans/2026-06-04-cce77-ship-guardrails-fix.md`) does not exist in any local checkout. Likely either (a) was never written despite the meta-orchestrator B11 step claiming to, or (b) lives in a worktree or branch not currently on disk. Not blocking — the CCE-88 ticket itself enumerates the design clearly. Worth tracing as a CCE-83 meta-orchestrator fidelity audit (already on the followup queue).
