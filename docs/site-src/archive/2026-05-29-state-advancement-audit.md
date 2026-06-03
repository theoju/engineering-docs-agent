---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/81
synthesized_into: []
---

# State-Advancement Invariant Audit (CCE-62)

**Date:** 2026-05-29  
**Verdict:** Invariant holds. No regressions from CCE-40 or CCE-41.

## Background

CCE-40 introduced durable state-in-git: `last_successful_run.head_sha` is committed on the docs-agent branch and advanced by the normal git merge when the docs PR lands. CCE-41 added per-subagent forensics in CI, writing raw stdout to `DOCS_AGENT_DEBUG_DIR` for post-run inspection.

CCE-62 re-audits the §8 state-advancement contract against both changes to confirm that neither introduced a regression in how the orchestrator advances — or withholds advancing — the head SHA.

## The Invariant

§8 of the design spec defines two branches:

1. **Partial run that produces a PR:** even if some subagents fail, the orchestrator opens (or appends to) the `docs-agent/YYYY-MM-DD` PR. State advances — `last_successful_run.head_sha` is updated to the tip of the source window.
2. **PR-create/update failure:** if the GitHub API call that opens or updates the PR itself fails, state does not advance. The next run will re-attempt the same source window.

Only the second branch leaves `last_successful_run.head_sha` un-advanced. Every other partial-failure mode — subagent error, Jira auth missing, gap-detection skip — still advances state once a PR exists.

## Audit Findings

The audit confirmed the invariant holds end-to-end across the CCE-40/41 changes. Specific findings:

**State write path.** `scripts/orchestrator_runner.py` writes `last_successful_run.head_sha` only after `open_or_update_pr` returns successfully. A PR-create failure raises before the write; the file is untouched.

**Partial-run path.** When subagents fail but the PR call succeeds, the orchestrator sets `partial: true` in the PR body and then writes state. The partial flag is visible in `.engineering-docs-agent/state.json` under `partial_reasons`, and in Slack/email notifications, so the gap is never silent.

**CCE-40 interaction.** The promote workflow (post-merge SHA advancement) was audited for double-advance risk. It is not a risk: the promote workflow runs on merge of the docs PR, at which point the `head_sha` already reflects the authoring run's window tip. The promote step writes the merged-docs-branch SHA, which moves forward monotonically.

**CCE-41 interaction.** The forensics debug dump (`DOCS_AGENT_DEBUG_DIR`) is written before the PR call, not after. It does not affect the state-write path.

## Test Coverage

PR #81 ships three regression tests in `tests/orchestrator/test_state_advancement_invariant.py`:

- **`test_partial_run_advances_state`** — simulates a subagent failure followed by a successful PR call; asserts `head_sha` advances.
- **`test_pr_create_failure_does_not_advance_state`** — simulates a GitHub API error on PR create; asserts `head_sha` is unchanged.
- **`test_pr_update_failure_does_not_advance_state`** — simulates a GitHub API error on PR update (append-commit path); asserts `head_sha` is unchanged.

All three run in the fixture-driven dry-run path with the Claude CLI dispatch monkeypatched. They are part of the default `pytest` suite with no special marks.

## Artifacts

The audit produced two internal documents (host-internal paths, not agent-editable):

- `docs/superpowers/plans/2026-05-29-state-advancement-audit-plan.md` — audit plan and checklist.
- `docs/superpowers/specs/2026-05-29-state-advancement-invariant.md` — invariant definition and design spec.

The design spec is also published to the core lens at `architecture/state-advancement-invariant.md`.
