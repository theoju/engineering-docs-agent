---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/224
synthesized_into: []
doc_kind: decision
---

# CCE-144: Blind-Run Detection (2026-08-14)

## Context

The docs-agent nightly could not report failure. Runs `31472240064` (2026-08-11) and `31579090583` (2026-08-12) both reported `conclusion: success`, but every subagent on both runs had been rejected by a weekly rate limit before making a single tool call — `source-collector` and `notifier` both returned `None`. Nothing alarmed, because no code path made the job exit non-zero for that condition: `run` returned `0` on every path except a config error (`2`) or a failed PR-open (`1`), and a rate-limited `source-collector` was coerced into a valid empty result set (`sources = {"prs": [], "jira_issues": []}`), so "prevented from judging" became indistinguishable from "judged: nothing to do."

The 08-11 run's PR was closed unmerged by the D2 auto-close sweep, so its watermark write was discarded. The 08-12 run's PR merged, and its watermark advance merged with it: `last_successful_run.head_sha` moved from `0c88411` to `08b27e2`, a window containing three feature PRs (#211/CCE-138, #212/CCE-139, #213/CCE-140) whose content was never authored. `last_successful_run` is a consume-once cursor — no future run reads that window again, so the loss is permanent.

A fallback diagnostic step, `Print partial-run reasons`, was supposed to catch exactly this, but it greps `.engineering-docs-agent/state.json` for `.current_run.partial_reasons`. `state_io.save_persistent_state` strips `current_run` before writing `state.json` (it's ephemeral; the reasons live in the sibling `current_run.json`), so the step had printed nothing on every run since that split shipped.

This document had briefly carried a "NOT IMPLEMENTED — archived, branch deleted" banner, added by PR #223 on the premise that `feat/CCE-144-blind-run-detection` was abandoned and unreachable. That premise was false — the branch was pushed at `5021f11` and landed under this ticket. The banner is removed; everything below is current behavior.

## Decision

Split the overloaded `partial` flag into two conditions with opposite operational meanings:

| | **Blind** | **Degraded** |
|---|---|---|
| Meaning | the pipeline was *prevented from judging* | the pipeline *judged, and rejected work* |
| Examples | `source_collector_invalid`, `content_validator_invalid`, `pr_summarizer_invalid`, `notifier_invalid`, `app_token_unavailable` | `lint_block`, `unsafe_page_path`, `unknown_lens`, `time_budget_exceeded`, `page_author_invalid`, `deferral_skip` |
| Recovery | needs a human or a quota reset | self-healing; the next run retries |
| Signal | red | green |

The criterion, when the two diverge: **blind** is a run that *consumed* input it could not process; **degraded** is a run that *held back* what it could not process. The complement writer in `scripts/orchestrator_runner.py` — the sole writer of `deferred_pages_by_pr` — decides which, but only on the time-truncated path; every advance-affecting read of that map sits inside `if time_truncated:`. On a non-truncated run the advance goes straight to window HEAD without reading it, so the only protection for a degraded failure there is CCE-140's cursor-backed merge gate.

That's why `page_author_invalid` is degraded and `content_validator_invalid` is blind, though they're one pipeline step apart: an unlanded authoring batch is folded into `deferred_pages_by_pr`, holding its PR out of the cursor prefix and re-authoring it next run; a page that fails validation is already in `landed_batches` — the run counts it as delivered and the cursor walks past it regardless.

**"Produced nothing" is explicitly rejected as the predicate.** A run with no new PRs since the watermark legitimately produces nothing and must stay green; a blind run can still author pages. Output volume doesn't separate the cases — provenance of the emptiness does.

The default is deliberately the loud one: an unclassified blocking failure turns the run red rather than passing silently, the same lesson CCE-127 learned from `conclusion` vs `outcome` — a diagnostic that reports healthy because it looked in the wrong place is worse than no diagnostic, because it suppresses inquiry.

## What changed

- **`state_io.add_partial`** gains a `degraded` keyword, in precedence order:
  - `info_only=True` — unchanged; touches neither `partial` nor `blind`, and `degraded` is ignored.
  - `degraded=True` — flips `partial` only. Today's behavior for content rejection.
  - **neither** — flips `partial` **and** `blind`, and records the reason in `blind_reasons`. This is the fail-safe default.

  `blind_reasons` is always a subset of `partial_reasons`, redacted and de-duplicated the same way.

- **`_record_dispatch_reasons(state, reasons, *, ok, degraded=False)`** — the single path all seven agent dispatches take — passes `degraded` through to `add_partial`. `page-author` and `gap-detector` are the two callsites that now pass `degraded=True`: an unlanded authoring batch is held back, not consumed, and a gap-detector verdict is advisory output outside the CCE-101 merge gate. The other five (source-collector, pr-summarizer, content-validator, notifier, and the CCE-127 `app_token_unavailable` block) take the blind default. Each agent's direct `add_partial` fallback (for when the dispatch returned nothing to explain itself) carries the matching classification, or a failure's color would depend on whether it managed to explain itself.

- **`_exit_code(state)`** — new function: returns `1` when `current_run.blind` is true, else `0`. Exit `1` is not a new code; it's the same class of signal `run` already used when a docs PR couldn't be opened.

- **`_should_advance_watermark(state)`** — new function: returns `False` when the run is blind. `run` reads this immediately before assigning `last_successful_run`, so a blind run's cursor stays exactly where it was and the next run re-reads the same window. Read at the moment of the advance; `notifier_invalid` (recorded near the end of `run`) sets the exit code but can't retroactively rewind a cursor that's already written — deliberately, since a failed digest means the operator wasn't told, not that the authoring work didn't happen.

- **`_maybe_auto_merge`** gains a `blind: bool = False` keyword. Inside the function, the gate order is: policy check → `merge_veto_reason` (the existing `_MERGE_VETO_REASON_PREFIXES` allowlist, currently just `app_token_unavailable`) → **`if blind: return skip("blind_run")`** → the CCE-140 `if partial and not advance_cursor_backed` carve-out. The blind check sits ahead of the cursor-backed carve-out on purpose: a cursor-backed advance proves the baseline is honest about what the run *saw*, and a blind run didn't see anything. The reachable gap this closes: a run that truncates on the CCE-109 time budget sets `advance_cursor_backed = True`; if its `content-validator` dispatch then returns `None`, the run is blind, partial, and cursor-backed all at once, and `content_validator_invalid` matches no entry in `_MERGE_VETO_REASON_PREFIXES` — before this change, nothing would have stopped that PR from merging.

- **Workflow repair** — `Print partial-run reasons` in both `.github/workflows/docs-agent-nightly.yml` and `templates/workflow-run.yml` now reads `.engineering-docs-agent/current_run.json` and prints `.current_run.partial_reasons[]?` plus `.current_run.blind_reasons[]?` under a distinguishing label, instead of the stripped `state.json`.

`templates/state.schema.json` is untouched — `blind` and `blind_reasons` live only on `current_run`, which `save_persistent_state` strips before every commit.

## Testing

- `state_io.add_partial`: a blocking reason with no kwargs flips both `partial` and `blind`; `degraded=True` flips `partial` only; `info_only=True` flips neither, and `degraded=True` alongside it is ignored; `blind_reasons` stays a subset of `partial_reasons`; a repeated reason appends once to each list; redaction applies to `blind_reasons` identically.
- `run` exit code: a blind run returns `1`; a degraded-only run returns `0`; a clean run returns `0`; a `ConfigError` still returns `2`.
- Watermark: a blind run leaves `last_successful_run` untouched; a degraded run and a clean run both advance it.
- Auto-merge interlock (`tests/orchestrator/test_blind_run_interlocks.py`, `tests/orchestrator/test_cursor_backed_merge.py`): blind **and** `advance_cursor_backed=True` skips with `auto_merge_skipped: blind_run` — the regression test for the case the old code merged; blind and `advance_cursor_backed=False` also skips, and asserting the specific reason string is the point, otherwise the CCE-140 gate could silently cover for a missing blind gate; degraded and `advance_cursor_backed=True` still merges, guarding against the blind classification over-reaching into the path CCE-140 exists to serve.
- Classification coverage (`tests/orchestrator/test_classification_coverage.py`): enumerates every blocking `add_partial` call site in `scripts/orchestrator_runner.py` and asserts each is explicitly classified, so the fail-safe default can't decay silently as the file grows.
- Fixture dry-run integration: a `source-collector` returning `None` produces a blind, exit-`1`, watermark-frozen run; a `lint_block`-only run is degraded, exit `0`, watermark advances; a run with zero new PRs and no failures is neither blind nor partial.

## Out of scope

- **Slack alarm.** Dropped on evidence: the dogfood carries no `SLACK_WEBHOOK_URL`, and `notifications.slack.enabled` is `false`. The design leaves the hook point — once `current_run.json` carries `blind`, a `curl` step is a self-contained follow-on for whoever provisions the webhook.
- **Moving the nightly cron.** A weekly rate limit resets once per week, so cron placement rescues at most one night in seven, and the 09:00 UTC boundary is a property of one Anthropic account's quota window, not something to encode as a fleet default.
- **Recovering the three lost PRs** (#211/CCE-138, #212/CCE-139, #213/CCE-140). They sit behind the advanced cursor and no future run will read them again. This change prevents the next occurrence; it can't replay the last one. Rewinding `last_successful_run.head_sha` back to `0c88411` would put that window back in scope at the cost of re-processing a week's worth of PRs in one docs PR — an operator decision about live host state, tracked separately.

## See also

- CCE-140: the cursor-backed auto-merge gate this decision adds a `blind` check ahead of.
- CCE-127: the App-token-degrade-to-partial pattern that first established `app_token_unavailable` as a blocking, merge-vetoing reason.
- CCE-125: the earlier, one-level-down precedent — a gap-detector verdict that came back "I couldn't judge" rather than "I judged no" — that this change promotes from one agent to the whole pipeline.
- `docs/superpowers/specs/2026-08-13-cce144-blind-run-detection-design.md`: design spec.
- `scripts/state_io.py`, `scripts/orchestrator_runner.py`: the changed surfaces.
