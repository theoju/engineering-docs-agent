---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/224
synthesized_into: []
doc_kind: decision
---

# CCE-144: Blind-Run Detection (2026-08-13)

## Context

The docs-agent nightly could not report failure. `orchestrator_runner.run` had seven return points: `2` on a config error (three sites), `1` when the docs PR could not be opened, and `0` everywhere else — including the `no_pr` path a fully rate-limited run takes. A run in which every subagent was rejected by a rate limit was therefore a green check by construction.

Two production runs hit exactly this. Runs `31472240064` (2026-08-11) and `31579090583` (2026-08-12) both reported `conclusion: success` while `source-collector` was rejected before making a single tool call — `"You've hit your weekly limit"`, `total_calls: 0`. `source-collector` and `notifier` both returned `None`. Nothing alarmed.

`orchestrator_runner` coerces a dead source-collector into a valid empty result set (`sources = {"prs": [], "jira_issues": []}` when the dispatch returns `None`), so "prevented from judging" became indistinguishable from "judged: nothing to do." The `last_successful_run` watermark assignment is unconditional — gated only by the enclosing `try:`, not by any success check — so run `31579090583` advanced `last_successful_run.head_sha` from `0c88411` to `08b27e2` on zero real work. That window contained three feature PRs (#211/CCE-138, #212/CCE-139, #213/CCE-140); none of their content was ever authored, and the watermark is a consume-once cursor, so no future run will read that window again.

A third silent layer compounded the first two: the nightly workflow's `Print partial-run reasons` step greped `.engineering-docs-agent/state.json` for `.current_run.partial_reasons`, but `save_persistent_state` strips the ephemeral `current_run` key before writing `state.json` — the reasons live only in the sibling `current_run.json`, which the workflow never read. The step printed nothing, always, and exited 0 regardless.

### Superseded archive entry

An earlier merge, PR #223, archived this work as abandoned, on the premise that branch `feat/CCE-144-blind-run-detection` had never been pushed and its commits were unreachable. That premise was false — the branch was pushed and its work landed under this ticket, in PR #224. The archived claim that CCE-144 was **not implemented** is incorrect and superseded by this record; everything below is current, merged behavior.

## Decision

Split the overloaded `partial` flag into two signals with opposite operational meanings:

> **Blind** — the run consumed input it could not process.
> **Degraded** — the run held back what it could not process.

A blind run needs a human or a quota reset before it can be trusted; a degraded run is self-healing — the next run retries the same rejected content. "Produced nothing" is explicitly not the predicate: a run with no new PRs since the watermark legitimately produces nothing and must stay green, while a blind run can still author pages. Provenance of the emptiness is what separates the cases, not output volume.

The classifier that decides which a given failure is: the complement writer in `scripts/orchestrator_runner.py` that folds any batch failing to land into `deferred_pages_by_pr`, holding its PR out of the advance cursor's prefix. That holdback only happens on the CCE-109 time-truncated path, though — a non-truncated run advances straight to window HEAD without reading `deferred_pages_by_pr` at all, and the sole protection for a degraded failure there is the CCE-140 merge gate (`if partial and not advance_cursor_backed`) plus merge-as-promotion: the advance is real on disk, but reaching `main` still requires an operator to merge the PR by hand.

That is why `page_author_invalid` classifies as degraded — its batch does not land, so its PR is held back on the truncated path — while `content_validator_invalid` classifies as blind: a page that fails validation is already in `landed_batches` either way, so the run counts it as delivered and the cursor walks past it regardless.

## What changed

**`state_io.add_partial`** gains a `degraded` keyword, in precedence order:

- `info_only=True` — unchanged; touches neither `partial` nor `blind`. `degraded` is ignored when `info_only` is set.
- `degraded=True` — flips `partial` only. Today's behavior for content rejection.
- neither — flips `partial` **and** `blind`, and records the reason in a new `blind_reasons` list. This is the fail-safe default: a blocking failure mode nobody classified turns the run red rather than passing silently.

`blind_reasons` is always a subset of `partial_reasons`, carries the same `_redact_credentials` redaction, and follows the same idempotency rule (a reason recorded twice appends once). Both new fields live on `current_run` only — `templates/state.schema.json` is untouched, since `save_persistent_state` strips `current_run` before writing `state.json`.

**`_record_dispatch_reasons(state, reasons, *, ok)`**, the single path all seven subagent dispatch failures take, gains a passthrough `degraded: bool = False` kwarg and calls `add_partial(state, r, info_only=ok, degraded=degraded)`. Five of the seven dispatches (source-collector, pr-summarizer, content-validator, notifier, and the App-token check) keep the blind default; `page-author` and `gap-detector` dispatch failures pass `degraded=True`. Each agent still has a second path to a reason — a direct `add_partial` fallback for when the dispatch returned nothing to report at all — and that fallback carries the matching classification, so an agent's failure doesn't change color depending on whether it managed to explain itself.

**Three consumers now read `blind`:**

- `run`'s exit code returns `1` when `current_run.blind` is true, `0` otherwise — every existing `return 0` path is unaffected unless the run is blind. Exit `1` is not a new code; `run` already returned `1` when the docs PR couldn't be opened, and blind joins that class of signal rather than competing with it.
- The watermark advance is skipped entirely when the run is blind, read at the moment of the advance. Every blind reason except `notifier_invalid` is recorded upstream of that point; a failed notifier dispatch still sets the exit code but cannot retroactively rewind a cursor already written — the authoring work completed honestly, only the alarm failed.
- `_maybe_auto_merge` gains a `blind: bool = False` kwarg and skips unconditionally (`auto_merge_skipped: blind_run`) before the CCE-140 `if partial and not advance_cursor_backed` carve-out. This needed new code: CCE-140 narrowed the merge gate to exempt cursor-backed advances, and that exemption doesn't distinguish a degraded cursor-backed run (safe to merge) from a blind cursor-backed one (a truncated run whose `content-validator` dispatch then returns `None` is blind, `partial`, and cursor-backed all at once, and the hand-maintained `_MERGE_VETO_REASON_PREFIXES` allowlist doesn't cover it). Gating on the computed `blind` flag closes the whole class instead of requiring the allowlist to be extended by hand for every new blind reason — the same allowlist-decay problem CCE-125 and CCE-118 already solved one level down, at the agent level rather than the run level.

**Workflow repair.** `Print partial-run reasons` in both `.github/workflows/docs-agent-nightly.yml` and `templates/workflow-run.yml` now reads `.engineering-docs-agent/current_run.json` and prints `.current_run.partial_reasons[]?` alongside `.current_run.blind_reasons[]?` under a distinguishing label. CI's `actionlint.yml` only searches `.github/workflows/`, so template changes are linted explicitly with `actionlint templates/workflow-run.yml` — the gap that plausibly let the template drift from the dogfood during CCE-127 in the first place.

**`scripts/verify_runner.py`** carries three further blocking `add_partial` sites — publish-verifier dispatch (blind), the CCE-63 CircleCI degrade (degraded), and notifier (degraded) — classified for the coverage test's exhaustiveness. `verify_runner` is a separate entry point; this change does not alter its exit code.

## Classification table

Audited by AST enumeration of every `add_partial` call site: 25 direct blocking sites in `orchestrator_runner.py`, plus the seven dispatch paths through `_record_dispatch_reasons`.

**Blind** (no `degraded` kwarg): `source_collector_invalid`/`_error`/`_partial`, `pr_summarizer_invalid`/`_error`, `content_validator_invalid`, `notifier_invalid`, `app_token_unavailable`.

**Degraded** (`degraded=True`): the four `time_budget_exceeded` sites, window-clip reasons, `unknown_lens`, `unsafe_page_path`/`lint_block_unsafe_path`, `page_author_invalid`, `lint_block`, `gap_detector_invalid`, the four cursor-resolution-failure sites, `deferral_skip`.

The `time_budget_exceeded` sites are the highest-stakes row: classifying them blind would turn every CCE-109 truncated run red and, through the watermark interlock, freeze its advance — deleting the cursor-backed advance CCE-140 exists to produce, and reinstating the CCE-109 doom loop permanently. They stay degraded, and the auto-merge tests assert a degraded cursor-backed run still merges.

## Explicitly out of scope

- **A Slack alarm.** Dropped on evidence: the dogfood repo has no `SLACK_WEBHOOK_URL` secret and both `notifications.slack.enabled` and `notifications.email.enabled` are `false` in host config. This change ships nothing that depends on a secret; once `current_run.json` carries `blind`, a `curl` step is a self-contained follow-on.
- **Moving the nightly cron.** A weekly rate-limit resets once per week, so cron placement rescues at most one night in seven, and the 09:00 UTC boundary is a property of one Anthropic account's quota window, not something a generic-first plugin default should encode.
- **Recovering the three lost PRs.** CCE-138, CCE-139, and CCE-140 sit behind the advanced cursor and no future run will read them. This change prevents recurrence; it cannot replay what already happened. Rewinding the watermark to reprocess that window is a live-host operator decision, tracked separately.
- **Enabling notifications on the dogfood.** An operator decision.

## Testing

TDD throughout. Coverage spans: the `add_partial` semantics matrix (blocking-default, `degraded=True`, `info_only=True`, idempotency, redaction) in `tests/state_io/test_add_partial_blind.py`; the `_record_dispatch_reasons` passthrough in `tests/orchestrator/test_dispatch_reasons_classification.py`; exit code, watermark, and auto-merge interlocks in `tests/orchestrator/test_blind_run_interlocks.py`; and an anti-decay classification-coverage test (`tests/orchestrator/test_classification_coverage.py`) that enumerates every blocking `add_partial` call site and fails the build on any left unclassified. `tests/orchestrator/test_cursor_backed_merge.py` and `tests/orchestrator/test_deferral_skip.py` pin that a degraded, cursor-backed, CCE-109-truncated run still auto-merges — the alarm-fatigue guard for the whole change.

## See also

- CCE-140: the cursor-backed merge exemption whose gap this change closes.
- CCE-127: the App-token failure classification this design reuses as its `app_token_unavailable` blind reason, and whose `outcome`-vs-`conclusion` trap set the precedent for "a diagnostic that reports healthy from the wrong place is worse than none."
- CCE-125, CCE-118: the agent-level advisory/unjudged split that this run-level `blind`/`degraded` split generalizes.
- `docs/superpowers/specs/2026-08-13-cce144-blind-run-detection-design.md`: design spec.
- `docs/superpowers/plans/2026-08-13-cce144-blind-run-detection.md`: implementation plan.
- `scripts/state_io.py`, `scripts/orchestrator_runner.py`, `scripts/verify_runner.py`: the changed surfaces.
