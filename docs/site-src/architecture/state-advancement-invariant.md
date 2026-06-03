---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/81
synthesized_into: []
---

# State-Advancement Invariant

The state-advancement invariant defines exactly when `last_successful_run.head_sha` moves forward. It is the contract that makes nightly runs safe to chain: each run knows precisely where the previous run stopped.

## The invariant

A run that produces a docs-agent PR **always** advances `last_successful_run.head_sha` to the tip of that PR's branch commit, regardless of whether the authoring stages completed fully or partially.

The only condition under which `head_sha` is **not** advanced is a failure to create or update the PR itself — that is, a failure in the GitHub API call that opens or appends to the `docs-agent/YYYY-MM-DD` branch.

Partial runs (where some subagents fail but the orchestrator still produces a PR) are not exceptions. The PR body carries `partial: true` so the operational gap is visible; the SHA still advances.

## Why this matters

Without this invariant, a partial run could leave `head_sha` pointing at the previous successful run's tip. The next nightly would re-process the same source window, duplicating entries in the docs-agent PR and producing a confusing double-write.

With it, the window is always correct: `[last_successful_run.head_sha, HEAD]` contains exactly the commits not yet reflected in docs.

## State file location

`.engineering-docs-agent/state.json` is committed on the docs-agent branch after every successful or partial-but-PR-producing run. The key path is `.last_successful_run.head_sha`.

`.engineering-docs-agent/current_run.json` is gitignored and written during the run for diagnostics. It is not the source of truth.

## Branches of the invariant

| Outcome | `head_sha` advanced? |
|---|---|
| Full run, PR created | Yes |
| Partial run (`partial: true`), PR created | Yes |
| PR-create/update fails (GitHub API error) | No |
| Run aborted before PR stage | No |

The PR-create/update path is the only failure mode that leaves the SHA un-advanced. Every other failure either produces a PR (partial path) or aborts before touching state.

## Regression coverage

Three tests in `tests/orchestrator/test_state_advancement_invariant.py` pin both branches:

1. **Full run** — asserts `head_sha` advances after a clean orchestrator pass.
2. **Partial run** — asserts `head_sha` still advances when subagents fail but the PR stage succeeds.
3. **PR-create failure** — asserts `head_sha` does **not** advance when the GitHub API call raises.

These tests were added in PR #81 (CCE-62) as part of the post-CCE-40/41 verification cycle. The audit verdict: invariant holds.

## Relationship to CCE-40 and CCE-41

CCE-40 introduced durable state-in-git and the post-merge promotion workflow that replaced the earlier in-memory state model. CCE-41 added per-subagent forensics in CI (`DOCS_AGENT_DEBUG_DIR`). CCE-62 re-audited the §8 state-advancement contract against both changes to confirm neither introduced a regression.

The audit confirmed the promotion path (normal git merge of the docs-agent branch into main) is the only mechanism that needs to advance `head_sha` — no separate promote workflow is required. Merging the PR is sufficient.
