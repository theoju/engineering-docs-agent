---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/224
synthesized_into: []
doc_kind: decision
---

# CCE-144: Blind-Run Detection (2026-08-13)

## Context

The docs-agent nightly could not report failure. `orchestrator_runner.run` returned `2` on a config error and `1` when the docs PR could not be opened — every other path, including a fully rate-limited run, returned `0`. A run whose subagents never answered was a green check by construction.

Two nightly runs proved it. Runs `31472240064` (2026-08-11) and `31579090583` (2026-08-12) both reported `conclusion: success` while every subagent was rejected by a weekly rate limit before making a single tool call (`returncode: 1`, `total_calls: 0`). `source-collector` and `notifier` both returned `None`. The 08-11 run's PR (#214) was closed unmerged by the D2 auto-close sweep, discarding its watermark write. The 08-12 run's PR (#215) merged, and its watermark write went with it: `last_successful_run.head_sha` advanced from `0c88411` to `08b27e2`, a window containing three feature PRs — #211 (CCE-138), #212 (CCE-139), #213 (CCE-140) — whose content was never authored. `last_successful_run` is a consume-once cursor, so that window is gone for good; no future run reads it again.

Three independent layers of silence let this through:

1. **No exit path distinguished a dead run.** `orchestrator_runner.py` coerces a `None` source-collector result into a valid empty result set (`sources = {"prs": [], "jira_issues": []}`) after recording a reason. "Prevented from judging" became indistinguishable from "judged: nothing to do."
2. **The alarm shared the failure mode.** `notifier` draws on the same Claude CLI quota as the agents it reports on, so a quota outage silences the work and its own alarm at once.
3. **The fallback diagnostic read the wrong file.** The nightly workflow's `Print partial-run reasons` step grepped `.engineering-docs-agent/state.json` for `partial_reasons`, but `state_io.save_persistent_state` strips `current_run` before writing state.json — the reasons only ever land in the gitignored sibling `current_run.json`. The step printed nothing, always, on every run.

An earlier draft argued the hazard was latent, held off by merge-as-promotion (zero PRs → zero pages → no docs PR → discarded local write). That reasoning missed that `.engineering-docs-agent/state.json` is a tracked file and `_stage_docs_run_changes` runs `git add -A .` unconditionally — `completed_at` is a fresh timestamp on every run, so state.json always diffs and a PR always opens. Merge-as-promotion promotes the advance; it does not gate it.

## Decision

Split the overloaded `partial` flag into two states with opposite operational meaning, rather than adding a third value or reworking the exit-code scheme from scratch:

> **Blind** — the run *consumed* input it could not process. The pipeline was prevented from judging.
> **Degraded** — the run *held back* what it could not process. The pipeline judged, and rejected some work.

"Produced nothing" is explicitly rejected as the predicate — a run with no new PRs since the watermark legitimately produces nothing and must stay green; a blind run can still author pages. Output volume doesn't separate the cases; provenance of the emptiness does.

This is the same idea the repo had already reached twice at the single-agent level: CCE-118 split advisory agents from the blocking pipeline, and CCE-125 named a third verdict state (`gap_detector_unjudged`) for "I could not judge" versus "I judged no." CCE-144 promotes that concept from one agent to the whole pipeline.

## What changed

**`state_io.add_partial`** gains a `degraded` keyword, in precedence order:

- `info_only=True` — unchanged; touches neither `partial` nor `blind`. `degraded` is ignored when set alongside it.
- `degraded=True` — flips `partial` only. The self-healing case: the next run retries.
- **neither** (the default) — flips `partial` **and** `blind`, and records the reason in the new `blind_reasons` list.

The default is deliberately the loud one: an unclassified blocking failure mode turns the run red rather than passing silently. `add_partial` remains the single writer of `partial_reasons` and becomes the single writer of `blind` and `blind_reasons`, which live only on `current_run` (`templates/state.schema.json` is untouched — these fields never reach the persisted `state.json`).

`_record_dispatch_reasons(state, reasons, *, ok)` is the single path all seven agent dispatch failures take, and it now accepts a `degraded` passthrough. All seven dispatch sites call it; `page-author` and `gap-detector` pass `degraded=True` (their two callsites), the remaining five take the fail-safe blind default. Each agent additionally has a direct `add_partial` fallback for a dispatch that returned nothing to explain itself (`source_collector_invalid: returned None` and its siblings) — both paths for a given agent carry the same classification, so a failure's color doesn't depend on whether the agent managed to describe itself.

**Classification** (audited by AST enumeration of every `add_partial` call site in `scripts/orchestrator_runner.py`, twenty-five direct sites plus the seven dispatch paths):

Blind (no `degraded` kwarg): `source_collector_invalid`/`_error`/`_partial`, `pr_summarizer_invalid`/`_error`, `content_validator_invalid`, `notifier_invalid`, `app_token_unavailable` (CCE-127).

Degraded (`degraded=True`): the four `time_budget_exceeded` sites, window-clip reasons, `unknown_lens`, `unsafe_page_path`/`lint_block_unsafe_path`, `page_author_invalid`, `lint_block`, `gap_detector_invalid`, the four cursor-resolution-failure sites, and `deferral_skip` (CCE-140's bounded forgiveness).

The `time_budget_exceeded` sites are the highest-stakes row: classifying them blind would turn every CCE-109 truncated run red and, through the watermark interlock below, freeze its advance — reinstating the CCE-109 doom loop as a permanent state. They stay degraded, and the auto-merge tests assert a degraded cursor-backed run still merges.

The criterion behind the split is which side of the complement writer a reason falls on. `orchestrator_runner.py` folds any batch that didn't land into `deferred_pages_by_pr`, holding its PR out of the advance cursor's prefix — but only on the time-truncated path; the non-truncated `else` branch advances straight to window HEAD without reading it. That's why `page_author_invalid` is degraded (a failed batch never lands, so it's held back and retried) while `content_validator_invalid` — one pipeline step later — is blind (its pages are already in `landed_batches`, counted as delivered, and the cursor walks past them regardless).

**Exit code.** `run` returns `1` when `current_run.blind` is true (via a new `_exit_code` helper), `0` otherwise. This isn't a new code — `run` already returned `1` when the docs PR couldn't be opened, and blind joins that "this run failed, read the reasons" class rather than competing with it. `2` stays with config-error paths.

**Watermark interlock.** `_should_advance_watermark` gates the `last_successful_run` write; a blind run leaves the cursor untouched, and the guard also encloses the `time_truncated` block so a blind truncated run can't write `window_head_sha` into the old cursor either. The one exception is `notifier_invalid`, recorded near the end of `run` after other blind reasons have already been recorded upstream — a failed digest sets the exit code but cannot retroactively rewind a cursor already written, because the authoring work itself completed honestly.

**Auto-merge interlock.** This needed new code, not a reuse of the existing `partial` gate. CCE-140 (`08b27e2`) had already narrowed `_maybe_auto_merge`'s gate to `if partial and not advance_cursor_backed`, which is correct for a degraded run (a cursor-backed advance moves the baseline only past PRs whose pages all landed) but not for a blind one — the cursor proves the baseline is honest about what the run *saw*, and a blind run didn't see. The gap was reachable: a time-budget truncation sets `advance_cursor_backed = True`, and if `content-validator` then returns `None` the run is blind, `partial`, and cursor-backed at once — `_MERGE_VETO_REASON_PREFIXES` (`("app_token_unavailable",)`) doesn't match `content_validator_invalid`, so nothing vetoes it and the merge would proceed.

`_maybe_auto_merge` gained a `blind: bool = False` keyword, checked unconditionally before the CCE-140 carve-out:

```
if blind:
    return skip("blind_run")
```

`_MERGE_VETO_REASON_PREFIXES` was left in place rather than pruned — once `app_token_unavailable` classifies as blind that entry is redundant, but removing it is a separate, unnecessary risk. The lesson the veto list itself teaches is why the fix gates on the computed `blind` flag rather than extending that allowlist: a hand-maintained allowlist decays every time a new blind reason is added and someone forgets to list it; a boolean derived from classification closes the whole class at once.

**Workflow repair.** `Print partial-run reasons` now reads `.engineering-docs-agent/current_run.json` and prints both `.current_run.partial_reasons[]` and `.current_run.blind_reasons[]` under a distinguishing label, in both `.github/workflows/docs-agent-nightly.yml` and `templates/workflow-run.yml`.

## Out of scope

- **The Slack alarm.** Dropped on evidence: the dogfood host carries no `SLACK_WEBHOOK_URL`, and notifications are disabled in config. The design leaves the hook point — once `current_run.json` carries `blind`, a `curl` step is a self-contained follow-on.
- **Moving the nightly cron.** A weekly rate limit resets once per week, so cron placement rescues at most one night in seven; it's also not cheap, since the hour is hardcoded across the dogfood workflow, the template, and `scripts/scaffold_workflow.py`.
- **Recovering the three lost PRs.** CCE-138, CCE-139, and CCE-140 sit behind the cursor and no future run reads them. This change prevents the next occurrence; it can't replay the last one. Rewinding `last_successful_run.head_sha` to reprocess that window is a separate operator decision about live host state.

## Testing

TDD throughout. `state_io.add_partial` is covered for all three classification branches plus idempotency and redaction of `blind_reasons`. `tests/orchestrator/test_blind_run_interlocks.py` drives the three consumers directly: exit-code truth table via `_exit_code`, the watermark guard both as an isolated mirror and through a real `orun.run()` invocation with a genuinely blind, time-truncated fixture run, and the auto-merge interlock via `_maybe_auto_merge(..., blind=...)` — including the regression case (blind, `partial=True`, cursor-backed) that the pre-CCE-144 gate would have merged, asserting the recorded reason is specifically `auto_merge_skipped: blind_run` rather than the weaker `partial_run` it would otherwise be masked by. `tests/orchestrator/test_classification_coverage.py` enumerates every blocking `add_partial` call site and fails on one left unclassified, which is what keeps the fail-safe default honest as the file grows.

## See also

- CCE-127: the `app_token_unavailable` classification and the CCE-140 merge-veto precedent this decision generalizes.
- CCE-140: the cursor-backed advance and its `partial and not advance_cursor_backed` merge gate, which this decision layers `blind` in front of.
- CCE-125: `gap_detector_unjudged`, the single-agent precedent for "prevented from judging" as a distinct state from "judged no."
- `docs/superpowers/specs/2026-08-13-cce144-blind-run-detection-design.md`: design spec.
- `scripts/state_io.py`, `scripts/orchestrator_runner.py`: the changed surfaces.
