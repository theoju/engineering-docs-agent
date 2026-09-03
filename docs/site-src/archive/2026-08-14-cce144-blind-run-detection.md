---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/224
synthesized_into: []
doc_kind: decision
---

# CCE-144: Blind-Run Detection

**Date:** 2026-08-14
**Ticket:** CCE-144
**PR:** #224

The nightly docs-agent could not report failure. `run()` in `scripts/orchestrator_runner.py` had no exit path for a run whose subagents never answered — it returned `2` on a config error, `1` when the docs PR could not be opened, and `0` on every other path, including a run in which every subagent was rejected by a rate limit. That run was a green check by construction, not by accident.

## The incident

Two consecutive nightlies, runs `31472240064` (2026-08-11) and `31579090583` (2026-08-12), reported `conclusion: success` on GitHub Actions with every subagent quota-rejected. `source-collector` and `notifier` both returned `None` before making a single tool call. Nothing alarmed, for three independent reasons:

1. No exit path distinguished a dead run from a clean one.
2. The alarm and the work shared a failure mode: `notifier` is itself a Claude CLI subagent, so the same quota outage silenced both the pipeline and its own alarm.
3. The workflow's `Print partial-run reasons` step read `state.json`, but `save_persistent_state` strips the ephemeral `current_run` key before writing — the reasons live only in the sibling `current_run.json`, which the step never read. It printed nothing on every run, always.

`orchestrator_runner` also coerced the dead source-collector into a valid empty result: a `None` return became `{"prs": [], "jira_issues": []}`, and the run's `last_successful_run` watermark advance was unconditional. Run `31579090583` merged as PR #215 and advanced `last_successful_run.head_sha` from `0c88411` to `08b27e2` — a window that contained three feature PRs (#211/CCE-138, #212/CCE-139, #213/CCE-140). None of their content exists in `docs/site-src/`. The watermark is a consume-once cursor: no future run reads that window again. The loss is permanent.

## The distinction

`partial` had conflated two conditions with opposite operational meanings:

| | **Blind** | **Degraded** |
|---|---|---|
| Meaning | the pipeline was prevented from judging | the pipeline judged, and rejected work |
| Examples | `source_collector_invalid`, `content_validator_invalid`, `app_token_unavailable` | `lint_block`, `unsafe_page_path`, `time_budget_exceeded` |
| Recovery | needs a human or a quota reset | self-healing — the next run retries |
| Signal | red | green |

"Produced nothing" is explicitly rejected as the predicate: a run with no new PRs since the watermark legitimately produces nothing and must stay green, while a blind run can still author pages. What separates the cases is provenance of the emptiness, not its volume. The operational test settled on is:

> **Blind** — the run *consumed* input it could not process.
> **Degraded** — the run *held back* what it could not process.

That is why `page_author_invalid` classifies degraded (an unlanded batch keeps its PR out of the cursor's advance) while `content_validator_invalid` classifies blind (a page that fails validation is already recorded as landed and the cursor walks past it regardless) — two agent failures one pipeline step apart, opposite outcomes.

## What changed

`state_io.add_partial` gained a `degraded` keyword alongside the existing `info_only`. Precedence, in order:

- `info_only=True` — unchanged; touches neither `partial` nor `blind`.
- `degraded=True` — flips `partial` only. Today's behavior for content rejection.
- **neither** — flips `partial` *and* `blind`, and records the reason in the new `blind_reasons` list.

The default is deliberately the loud one: an unclassified blocking failure turns the run red instead of passing silently. `_record_dispatch_reasons`, the single path every one of the seven agent dispatches takes, gained the same passthrough — `page-author` and `gap-detector` are the two callsites that pass `degraded=True`, because their dispatch failures hold work back rather than consuming it; the other five keep the fail-safe blind default.

Three consumers read the resulting `current_run.blind` flag, all classified by call site rather than by matching reason strings:

- **Exit code.** `_exit_code` returns `1` when `current_run.blind` is true, `0` otherwise — joining the existing "docs PR could not be opened" `1` rather than adding a third value.
- **Watermark.** `_should_advance_watermark` refuses the `last_successful_run` advance whenever the run is blind. Re-processing a window is cheap and idempotent; skipping one, as the incident showed, is not.
- **Auto-merge.** `_maybe_auto_merge` gained a `blind` keyword and skips unconditionally, ahead of the CCE-140 `partial and not advance_cursor_backed` carve-out — a blind run is excluded from the CCE-101 auto-merge gate outright, not merely disfavored by it. That ordering matters: a run that time-truncates sets `advance_cursor_backed = True`, and if its `content-validator` dispatch then returns `None`, the run is blind, `partial`, *and* cursor-backed at once — the CCE-140 carve-out alone would let that PR merge.

A classification-coverage test enumerates every blocking `add_partial` call site in `scripts/orchestrator_runner.py` and fails on one left unclassified, so the audit performed for this change doesn't silently decay as the file grows.

## What stayed green on purpose

The four `time_budget_exceeded` sites (CCE-109 truncation) and `lint_block` stay `degraded=True`. Classifying truncation as blind would turn every truncated nightly red and, through the watermark interlock, freeze its advance — deleting the cursor-backed advance CCE-140 exists to produce and reinstating the CCE-109 doom loop permanently. `gap_detector_invalid` also stays degraded: gap-detector output feeds only a PR note and sits outside the CCE-101 auto-merge gate, so a dispatch failure there consumes no docs content.

## Out of scope

The design explicitly left several things untouched: provisioning a Slack alarm (no `SLACK_WEBHOOK_URL` was configured on the dogfood at the time), moving the nightly cron earlier in the week, and recovering the three PRs already lost behind the frozen cursor — rewinding `last_successful_run.head_sha` to replay that window is a live-state operator decision, tracked separately.

## Later correction: CCE-151

CCE-144's watermark and auto-merge interlocks only reached as far as the `if time_truncated:` branch — a run that was `partial` for a non-time reason (a lint block, a `page_author_invalid`) still advanced straight to window HEAD without ever reading `deferred_pages_by_pr`. CCE-151 (2026-08-21) hoisted the cursor walk to trigger on `time_truncated or held_back`, closing that gap; see `scripts/orchestrator_runner.py:_should_advance_watermark` and the surrounding cursor-walk block for current behavior. That correction does not change any of the blind/degraded classifications recorded above.

## Also on this ticket: CCE-150

A same-day PR (#223) briefly stamped this design "NOT IMPLEMENTED — archived, branch deleted," on the mistaken premise that the implementation branch had been abandoned unpushed. It hadn't: the branch was pushed and landed as PR #224, nine minutes after #223 merged. CCE-150 is superseded and carries no independent documentation action.

## References

- Design: `docs/superpowers/specs/2026-08-13-cce144-blind-run-detection-design.md`
- Implementation: `scripts/state_io.py:add_partial`, `scripts/orchestrator_runner.py:_record_dispatch_reasons`, `scripts/orchestrator_runner.py:_exit_code`, `scripts/orchestrator_runner.py:_should_advance_watermark`, `scripts/orchestrator_runner.py:_maybe_auto_merge`
