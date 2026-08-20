---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/227
synthesized_into: []
doc_kind: decision
---

# CCE-152: PR-Boundary Authoring Cut (2026-08-17)

## Context

The authoring loop's soft time-budget deadline (CCE-109/CCE-114) was checked at every page batch, and a batch is not a PR. `per_target` — the dict the loop iterates — is built by walking admitted PRs oldest-first and `setdefault`-ing each `(lens, page_hint)` doc target, so batches arrive already grouped by the oldest PR that references each page: group(PR1), then group(PR2), and so on. CCE-114's deadline guard fired at whatever batch index the clock happened to cross, with an at-least-one-progress escape of `i > 0` measured **per batch**, not per PR.

That mismatch starves a specific, common shape of run: a window whose oldest PR fans out to more pages than the authoring budget can finish. The deadline check crosses somewhere inside group(PR1) every single time, so PR1 never completes. `advance_cursor_list` (`scripts/orchestrator_runner.py:advance_cursor_list`) stops the moment it meets a held-back PR number, and PR1 sits at index 0 of the oldest-first list — so it breaks immediately, `_last_processed_merge_sha([])` returns `None`, and the run reports `no_advance_no_cursor` no matter how much work it actually did.

A host repo (tracked host-side as ADIS-515) hit exactly this for 20.6 days: four consecutive nightlies each authored only a handful of the roughly 75 pending batches — two of them the identical four pages — and every one ended in `no_advance_no_cursor`. The baseline never moved.

## Decision

Move the unit the deadline guarantee applies to from **one batch** to **one complete PR group**. The soft deadline may now only cut where the batch's owning PR changes (`_owner != _prev_owner`), never inside a group. That always leaves a complete prefix of PRs behind the cut, so the cursor is non-empty and the baseline can advance to the last PR whose pages all landed — the same guarantee CCE-140's `advance_cursor_list` was built to honor, now actually reachable from a truncated run.

Ownership of a batch shared by two PRs (a page hint two PRs both target) belongs to the **older** of them: `per_target` accumulates summaries oldest-first, so the first element of a shared batch's summary list is always the older PR, and the loop reads that element to decide which group the batch belongs to. Reading the last element instead would invent a group boundary in the middle of an unfinished PR's own pages.

`_prev_owner` has to advance on every batch the loop visits, including the ones it skips outright (`unknown_lens`, `unsafe_page_path`) — those branches `continue` before the end of the loop body, and stranding `_prev_owner` on a stale PR would report a boundary that isn't there and cut mid-group at the very next past-deadline batch.

Deferring the cut to a PR boundary is unbounded on its own: a single PR fanning out to, say, twenty pages could hold the run open past the GitHub App installation token's one-hour TTL and fail the whole run rather than merely truncating it. `resolve_authoring_hard_cap` (`scripts/orchestrator_runner.py:resolve_authoring_hard_cap`) bounds that overrun. Past the hard cap the loop cuts wherever it stands, even mid-group — which costs the baseline advance for that run (the same standstill authoring hit before this change, and never worse) but never costs the run itself.

## What changed

**The cut point.** The authoring loop tests `_owner != _prev_owner` at the top of each iteration in addition to the soft-deadline clock; a past-deadline batch that is still inside the current PR's group is authored anyway. `_prev_owner` is updated unconditionally, including on the `continue` paths.

**`resolve_authoring_hard_cap(config, budget, *, out_reasons=None)`.** Resolves the ceiling the authoring loop may never cross, with this precedence:

1. `run.authoring_hard_cap_seconds` if set, else `budget * DEFAULT_AUTHORING_HARD_CAP_RATIO` (1.15, `int()`-floored).
2. Clamped against a computed ceiling: `GITHUB_APP_TOKEN_TTL_SECONDS` (3600s — the App-token lifetime, not the workflow's `timeout-minutes`, which no longer bounds anything here) minus the merge-check poll the host will actually run (`merge.checks_timeout_seconds`, default 900s; zero for a `merge.policy: manual` host, which never polls) minus a fixed 285s post-run tail reserve (`AUTHORING_TTL_SAFETY_SECONDS`) for the work that happens after the last authoring dispatch returns — draining in-flight batches, running the site generators, `git push`, opening/appending the PR, and the notifier dispatch.

The resolver lands in one of four states:

- **Rejected.** An explicit `run.authoring_hard_cap_seconds` at or below `budget` raises `ConfigError` at startup (exit 2, reason names both numbers) rather than being clamped up to `budget`. Equal is as broken as under: it collapses the hard deadline onto the soft one and silently restores the mid-group cut this change exists to remove. JSON Schema cannot express "greater than a sibling key," so `templates/config.schema.json` only types and bounds the key (`integer`, `minimum: 1`) and the cross-field check lives in the resolver.
- **Normal.** The resolved cap is at or under the computed ceiling and is returned unchanged — no advisory, nothing logged.
- **Clamped.** The resolved cap (override or ratio) exceeds the ceiling, but the ceiling still exceeds `budget`: the host keeps a real overrun, just a smaller one than it asked for or than the ratio would have produced. An `authoring_hard_cap_clamped` advisory reason names the resolved cap, the ceiling, and the poll term that produced it — fired on the ratio path too, not just an explicit override, because the ceiling moves with the host's own `merge.checks_timeout_seconds` and a default that fit yesterday can be narrowed today with nothing said otherwise.
- **Squeezed.** The ceiling is at or below `budget` — the budget plus the merge poll plus the tail reserve already fills the token, leaving no overrun to grant. The cap is held flat at `budget`; behavior degrades to the pre-CCE-152 mid-group cut (never worse, never silent), and an `authoring_hard_cap_squeezed` advisory names the two keys an operator can lower. **This is the default state for a stock host**: `DEFAULT_TIME_BUDGET_SECONDS` (2700s) plus the default 900s poll plus the 285s tail is 3885s against a 3600s token, so the squeeze — not the ratio's 1.15 overrun — is what a host on defaults actually gets. The cut-reason wording accounts for this explicitly: on a squeezed host, "hard cap 2700s over budget 2700s" would read as a number over itself, so the reason instead reads "hard cap held at budget 2700s by the App-token TTL."

Both advisory reasons and the squeeze are `info_only` — they reach the digest and the PR body but never flip `partial`, since a squeeze describes the host's configuration, not a failure of this run's work.

**Config schema.** `run.authoring_hard_cap_seconds` is now declared in `templates/config.schema.json` (`integer`, `minimum: 1`) under the `run` block, which stays `additionalProperties: false`. Before this, the resolver read and documented the key while the schema rejected it — a host that followed the documentation and wrote `run.authoring_hard_cap_seconds` exited 2 at config load, every night, before authoring ever ran. Every existing unit test had missed this because it called `resolve_authoring_hard_cap` with a raw dict, bypassing `load_config_validated` entirely.

**Docs and CHANGELOG.** Removed stale arithmetic that treated the workflow's job `timeout-minutes` as the binding ceiling on a run — CCE-140 already raised both workflows to `timeout-minutes: 90`, which is not what this change bounds against — and a stale citation invalidated by that same CCE-140 change.

## Explicitly out of scope

- **Splitting the `no_advance_no_cursor` message** by cause (starvation vs. genuine first-run truncation) is deferred to a follow-up.
- Pre-existing, unrelated debt in the docs around merge-check-poll windows (`docs-agent-nightly.md`, `nightly-cron-cadence.md`) is untouched by this change.

## Testing

TDD throughout. `tests/orchestrator/test_pr_boundary_authoring_cut.py` drives `orchestrator_runner.run` end-to-end: a regression test proving a run that crosses the soft deadline mid-group keeps going to finish the group and the baseline advances; a shared-batch test proving ownership resolves to the older PR; a hard-cap test proving the cap still forces a mid-group cut (and costs the advance) when a group alone would exceed it; a squeezed-host wording test; a clamped-vs-runtime test proving the clamp reaches the actual deadline the loop runs against, not just the resolver's return value; and a skipped-batch test proving `_prev_owner` advances across `continue` paths. `tests/orchestrator/test_authoring_hard_cap_bounds.py` pins the resolver's branch contract in isolation — the rejection boundary, the TTL clamp and its ceiling arithmetic, the squeeze boundary, and the config round-trip through `load_config_validated` that exposed the schema gap.

## See also

- CCE-140: `advance_cursor_list` and the prefix-boundary cursor invariant this change makes reachable from a time-truncated authoring run.
- CCE-114: the original per-batch time-budget guard whose batch-granularity cut this change replaces.
- CCE-109: the soft run time budget (`run.time_budget_seconds`) this change's hard cap bounds the overrun of.
- `scripts/orchestrator_runner.py`: `resolve_authoring_hard_cap`, `advance_cursor_list`, `_order_prs_oldest_first`.
- `templates/config.schema.json`: the `run.authoring_hard_cap_seconds` schema entry.
- `CHANGELOG.md`: the CCE-152 entry.
