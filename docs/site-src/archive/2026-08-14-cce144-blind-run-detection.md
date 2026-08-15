---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/224
synthesized_into: []
doc_kind: decision
---

# CCE-144: Blind-Run Detection (2026-08-14)

Two nightly runs — `31472240064` on 2026-08-11 and `31579090583` on 2026-08-12 — both reported `conclusion: success` while every subagent was rate-limited and made zero tool calls. Nothing alarmed. `run()` in `scripts/orchestrator_runner.py` had no exit path for a run whose agents never answered: it returned `2` on a config error, `1` when the docs PR could not be opened, and `0` on every other path, including the `no_pr` path a fully rate-limited run takes.

That silence had already cost real content. The 08-11 run's PR (#214) was closed unmerged by the D2 auto-close sweep, so its watermark write was discarded. The 08-12 run's PR (#215) merged, and it carried a `last_successful_run.head_sha` advance from `0c88411` to `08b27e2` with it. That window contains three feature PRs — #211 (CCE-138), #212 (CCE-139), #213 (CCE-140) — and none of their content was ever authored: `grep -rl 'CCE-138\|CCE-139\|CCE-140' docs/site-src/` returns nothing. `last_successful_run` is a consume-once cursor. The cursor now sits at `956144f`, far past `08b27e2`, so that window is gone for good — this change prevents a recurrence, it cannot replay the one that already happened.

Three independent layers of silence compounded: `orchestrator_runner` coerces a dead `source-collector` into a valid empty result set (`sources = {"prs": [], "jira_issues": []}` when the dispatch returns `None`), turning "prevented from judging" into "judged: nothing to do" — downstream code cannot tell the difference. `notifier` is itself a Claude CLI subagent drawing on the same quota as the work it reports on, so a quota outage silences the alarm along with the work. And the workflow's `Print partial-run reasons` step greps `.engineering-docs-agent/state.json` for `.current_run.partial_reasons`, but `state_io.save_persistent_state` strips the ephemeral `current_run` key before writing — the reasons live in the sibling `current_run.json`, which the step never reads. It printed nothing, always, regardless of whether the run had reasons to report.

## The blind/degraded split

CCE-144 splits the overloaded `partial` flag into two conditions with opposite operational meanings:

- **Blind** — the run was *prevented from judging*. Inputs are incomplete; the run cannot know what it missed. Recovery needs a human or a quota reset. Signal: red.
- **Degraded** — the run *judged, and rejected work*. Inputs are complete; the run saw everything and dropped some of it deliberately (a lint block, an unsafe path, a time-budget truncation). Self-healing — the next run retries. Signal: green.

The operational criterion: blind is when the run *consumed* input it could not process; degraded is when the run *held back* what it could not process. "Produced nothing" is explicitly not the predicate — a run with no new PRs since the watermark legitimately produces nothing and must stay green, while a blind run can still author pages.

This is the same idea the repo had already reached twice, one level down: CCE-118 split advisory agent failures from blocking ones, and CCE-125 named a third state — `gap_detector_unjudged` — for a verdict that came back "I could not judge" rather than "I judged no." CCE-144 promotes that concept from one agent to the whole pipeline.

## Classification is per call site, not per reason string

`state_io.add_partial` gained a `degraded` keyword. In precedence order: `info_only=True` touches neither `partial` nor `blind` (and ignores `degraded`); `degraded=True` flips `partial` only; passing neither flips both `partial` and `blind` and records the reason in the new `blind_reasons` list. **The default is the loud one** — a blocking failure mode nobody explicitly classified turns the run red rather than passing silently, the same fail-open-loud posture CCE-127 established for the app-token step.

An AST audit of every blocking `add_partial` call site in `scripts/orchestrator_runner.py` and `scripts/verify_runner.py` backs a dedicated coverage test (`tests/orchestrator/test_classification_coverage.py`) that fails if a new call site omits an explicit `degraded=` or `info_only=` kwarg — a registry mapping site to classification was prototyped and rejected because its keys collide in `verify_runner.py`, where three separate reason loops share an enclosing function but carry different classifications.

`page_author_invalid` and `content_validator_invalid` land on opposite sides of the split despite being agent failures one pipeline step apart, and the reason is the complement writer: any authoring batch that doesn't land is folded into `deferred_pages_by_pr`, holding its PR out of the advance cursor — but only on the time-truncated path, since a non-truncated run advances straight to window HEAD without reading that map at all. A page-author failure is therefore degraded (held back, retried next run — protected on the truncated path by the complement writer, and on the non-truncated path by CCE-140's cursor-backed merge gate). A page that fails validation is already recorded in `landed_batches` regardless of which path the run took — it's counted as delivered, and the cursor walks past it — so `content_validator_invalid` is blind.

`_record_dispatch_reasons(state, reasons, *, ok, degraded=False)` is the single path all seven agent dispatch failures take, so the blind default reaches all of them unless a callsite opts out. Only `page-author` and `gap-detector` pass `degraded=True`.

## Three consumers

- **`_exit_code(state)`** — `run` returns `1` when `current_run.blind` is true, `0` otherwise. This is not a new exit code: `run` already returns `1` when the docs PR could not be opened, the same "this run failed, read the reasons" class. `2` stays reserved for config errors.
- **`_should_advance_watermark`** — the `last_successful_run` advance is skipped entirely when the run is blind, including the CCE-43 `window_head_sha` write, which must sit inside the same guard: mutating it unguarded would silently corrupt the *previous* run's cursor rather than merely failing to advance the current one.
- **`_maybe_auto_merge`** — gains a `blind: bool = False` keyword and skips unconditionally ahead of CCE-140's `if partial and not advance_cursor_backed` carve-out. This closes a real gap: CCE-140 narrowed the merge gate so a cursor-backed advance could still merge a degraded-but-partial run, but that reasoning doesn't transfer to blind — a cursor-backed advance proves the baseline is honest about what the run *saw*, and a blind run didn't see anything. A run that truncates on the CCE-109 time budget sets `advance_cursor_backed = True`; if its `content-validator` dispatch then also returns `None`, the run is blind, `partial`, and cursor-backed simultaneously, and the pre-CCE-144 gate would have merged it. `_MERGE_VETO_REASON_PREFIXES` — the hand-maintained allowlist CCE-127 added for `app_token_unavailable` — stays in place but becomes redundant for that one entry; gating on the computed `blind` flag instead closes the whole class rather than requiring the allowlist to be extended by hand for every new blind reason.

The workflow's `Print partial-run reasons` step is repointed at `.engineering-docs-agent/current_run.json`, reading both `.current_run.partial_reasons[]` and `.current_run.blind_reasons[]` under a distinguishing label, in both `.github/workflows/docs-agent-nightly.yml` and `templates/workflow-run.yml`.

## Supersedes the CCE-150 archive

A prior archive entry, PR #223 (merged 2026-08-14), stamped the CCE-144 spec "NOT IMPLEMENTED — archived, branch deleted," on the premise that `feat/CCE-144-blind-run-detection` had been abandoned unpushed and its commits were unreachable. That premise was false: the branch was pushed at `5021f11` and landed under this ticket. This page and the underlying spec (`docs/superpowers/specs/2026-08-13-cce144-blind-run-detection-design.md`) supersede that archive entry; CCE-150 is now obsolete.

## Out of scope

A Slack alarm was dropped from scope on evidence — the dogfood repo carries no `SLACK_WEBHOOK_URL`, so a `curl` alarm step has nothing to call; the design leaves the hook point (`current_run.json` carrying `blind`) for a self-contained follow-on once one exists. Moving the nightly cron off its current hour was considered and rejected: a weekly quota limit resets once a week, so cron placement rescues at most one night in seven, and the hour is hardcoded across `templates/workflow-run.yml`, the dogfood workflow, and `scripts/scaffold_workflow.py`'s regex substitution. Recovering the three PRs already lost behind the cursor (#211/CCE-138, #212/CCE-139, #213/CCE-140) is also out of scope — rewinding `last_successful_run.head_sha` would re-process a week's worth of merged PRs in one docs PR, which is an operator decision about live host state that belongs in its own ticket.
