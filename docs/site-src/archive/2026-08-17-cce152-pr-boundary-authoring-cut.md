---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/227
synthesized_into: []
doc_kind: decision
---

# CCE-152: PR-Boundary Authoring Cut (2026-08-17)

## Context

The ADIS host's baseline (`last_successful_run.head_sha`) sat frozen for 20.6 days. Four consecutive scheduled nightlies, 2026-08-13 through 2026-08-15, each authored 1-5 of roughly 75 page batches and ended in `no_advance_no_cursor` — despite PR admission itself never truncating: all 53 PRs in the window were admitted every single night. The stall was diagnosed from forensic capture on run 31878131334 (see [Subagent Forensic Capture in CI](../operations/2026-05-28-subagent-forensics.md)) and tracked host-side as ADIS-515 and ADIS-530.

| Nightly | Batches authored | Admission truncated? | Advance |
|---|---|---|---|
| 2026-08-13 | 1/~75 | No | none — `no_advance_no_cursor` |
| 2026-08-14 | ~4/~75 | No | none — `no_advance_no_cursor` |
| 2026-08-15 (a) | ~4/~75 (same leading pages) | No | none — `no_advance_no_cursor` |
| 2026-08-15 (b) | ~5/~75 | No | none — `no_advance_no_cursor` |

The root cause: PR #646 restructured `CLAUDE.md` into roughly six pages, which exceeded a single run's page-authoring budget. The CCE-109/CCE-114 soft time-budget check (`scripts/orchestrator_runner.py:run`) does cut the page-authoring fan-out mid-run once the clock passes `deadline`, but the cut fired at whatever batch index it happened to reach, guarded only by an `i > 0` escape hatch that made the *first batch* unconditional — it said nothing about finishing a PR's whole page group.

`per_target` (`scripts/orchestrator_runner.py:run`) is built by walking the admitted PRs oldest-first and `setdefault`-ing each doc target, and `setdefault` never re-positions an existing key — so the resulting batch list arrives already grouped by the oldest PR that references each page: group(PR1), then group(PR2), and so on. Cutting at an arbitrary batch index therefore split whichever group the clock landed inside. Because PR #646 was consistently the oldest unfinished PR in the window, the cut split group(PR #646) at close to the same point on every one of the four nightlies, re-authoring the same leading pages each time and never finishing the group.

That mattered downstream because `advance_cursor_list` walks the admitted PRs and stops at the oldest one whose pages didn't all land — the cursor is a prefix boundary. With group(PR #646) split, `advance_cursor_list` broke at index 0 and `_last_processed_merge_sha([])` returned `None`. The run had nothing to advance the baseline to, on 20.6 days' worth of nightlies, even though the pipeline was otherwise healthy: admission wasn't truncating, no PR was going `blind`, and the underlying budget was doing its job of bounding wall-clock time — the unit it was bounding was simply wrong.

## Decision

Move the unit of the authoring-loop's progress guarantee from **one page batch** to **one complete PR's page group**. The soft deadline (`scripts/orchestrator_runner.py:run`) may only cut where the batch about to be authored belongs to a different PR than the previous one (`_owner != _prev_owner`) — a PR boundary. That always leaves a complete prefix of PRs behind the cut, so `advance_cursor_list` has something non-empty to walk and the baseline can move again. `i > 0` survives only to keep the very first batch unconditional, same as before.

Deferring to a PR boundary is unbounded on its own — one PR fanning out to twenty pages could hold a run open past the GitHub App installation token's one-hour TTL and fail it outright, worse than the starvation this decision fixes. A second term, `authoring_hard_cap_seconds`, bounds the overrun: a run may keep authoring past a PR boundary only up to this second, harder deadline. It resolves from `run.authoring_hard_cap_seconds` in config, or `time_budget_seconds * 1.15` by default (`scripts/orchestrator_runner.py:resolve_authoring_hard_cap`), then is clamped down against the GitHub App installation token's TTL less the merge poll the host will actually run less a fixed post-run tail reserve. An explicit cap at or below the budget is rejected as a config error at load (exit 2) rather than silently clamped up to equal the budget — equal collapses the hard deadline onto the soft one and reinstates the exact mid-group cut this decision removes.

Past the hard cap while still mid-group is the one case where the run genuinely cannot avoid a forced cut, and it costs the advance — the same standstill as before this change, and never worse. Three distinct `time_budget_exceeded` reason strings now exist to make that failure mode legible: an ordinary boundary deferral (the group behind the cut is complete, the run advances), a forced hard-cap cut naming the PR whose group was split (no advance), and the same forced cut worded separately for a host whose hard cap was squeezed down to equal its budget by the token TTL — the stock `DEFAULT_TIME_BUDGET_SECONDS` default (2700s) is in that squeezed state.

## What changed

- `run.authoring_hard_cap_seconds` — new schema key (`templates/config.schema.json`), integer `> 0`; `additionalProperties: false` on the `run` block means a typo is rejected at config load rather than silently ignored.
- `resolve_authoring_hard_cap` (`scripts/orchestrator_runner.py:resolve_authoring_hard_cap`) — resolves the cap (explicit override, else the `* 1.15` ratio default), rejects a cap at or below the budget with `ConfigError`, and clamps the result against the GitHub App token TTL ceiling, appending an advisory `authoring_hard_cap_clamped` or `authoring_hard_cap_squeezed` reason when the ceiling narrows it.
- The authoring-loop cut condition in `scripts/orchestrator_runner.py:run` now checks both `_owner != _prev_owner` (PR boundary) and the resolved hard deadline before truncating, instead of cutting unconditionally once the soft deadline passes.
- `_prev_owner` is advanced on every loop iteration, including the `unknown_lens` and `unsafe_page_path` `continue` paths — moving that assignment to only the paths that author would strand `_prev_owner` on a stale PR and manufacture a false boundary inside a still-incomplete group.
- `CHANGELOG.md` and `README.md` document the new key and the three-way reason wording; `.engineering-docs-agent/config.yml` and `templates/workflow-run.yml` carry no behavior change beyond what the schema and resolver require.

## Testing

`tests/orchestrator/test_pr_boundary_authoring_cut.py` drives the fix end to end through `orchestrator_runner.run` against a real git repo and fake dry-run fixtures, one PR-summarizer fixture per PR so each PR contributes distinct doc targets (a shared fixture across PRs collapses the whole window into one group, which can never exercise a boundary):

- `test_cut_defers_to_the_pr_boundary_so_the_baseline_advances` — the regression test. Past the soft deadline but still inside group(PR1) and under the hard cap, the loop keeps going; it cuts only once it reaches the PR1 → PR2 boundary, and the baseline advances to PR1's merge SHA rather than standing still.
- `test_a_batch_two_prs_share_is_owned_by_the_older_of_them` — a page hint referenced by two PRs produces a batch whose summary list holds both; the batch is attributed to the *first* (older) summary, so the shared batch is read as still inside the older PR's group rather than manufacturing a boundary in the middle of it.
- `test_hard_cap_cuts_inside_a_group_and_says_the_baseline_cannot_advance` — the bound above the boundary deferral: once the clock is past the hard cap, the loop cuts inside the group, the reason names the split PR and says the baseline cannot advance, and the advance is withheld.
- `test_hard_cap_resolves_from_config_and_defaults_to_the_ratio`, `test_hard_cap_at_or_below_the_budget_is_rejected_not_clamped_up`, `test_hard_cap_is_clamped_against_the_app_token_ttl`, `test_a_clamped_override_is_announced_not_silent`, `test_a_ttl_squeeze_holds_the_cap_at_budget_and_says_so_loudly` — unit-level coverage of the resolver's three states (fits, clamped, squeezed) and its rejection path.
- `test_a_skipped_batch_still_advances_the_boundary_owner` — pins that `_prev_owner` advances on a `continue` path, not only on paths that author.
- `test_past_the_hard_cap_at_a_boundary_still_defers_rather_than_cutting_in` — being past the hard cap while standing exactly on a PR boundary is an ordinary deferral, not a forced cut; the two states must not collapse into one just because both check the same clock value.

## See also

- [Orchestrator](../architecture/orchestrator.md) — the authoring-loop checkpoint, the hard-cap arithmetic, and how this decision fits alongside the CCE-144 `blind`/`degraded` split (`time_budget_exceeded` reasons here are `degraded=True`, never `blind`).
- [Subagent Forensic Capture in CI](../operations/2026-05-28-subagent-forensics.md) — how to recognize this stall from `partial_reasons` and forensic artifacts on a live host.
- CCE-109 / CCE-114: introduced and then extended the soft time budget to the page-authoring fan-out; this decision corrects the unit its escape hatch measured progress in.
- CCE-140: the cursor-backed auto-merge gate that a PR-boundary advance now feeds cleanly, since a complete prefix of PRs is exactly what `advance_cursor_list` requires to produce one.
