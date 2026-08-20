---
description: 'Documents architecture blind vs degraded runs: Splits the orchestrator''s overloaded `partial` flag into two distinct signals: `blind` (a blocking agent was prevented from judging its input, e.g. rate-limited or dispatch failure) and `degraded` (the pipeline judged input and rejected specific content). `state_io.add_partial` gains a `degraded` keyword with precedence: `info_only=True` touches neither flag, `degraded=True` flips only `partial`, and specifying neither flips both `partial` and `blind` (the loud, default-safe path). Three consumers now read `blind`: `_exit_code` returns 1 instead of 0, `_should_advance_watermark` freezes the cursor, and `_maybe_auto_merge` skips merging via a new `blind` kwarg gate placed ahead of the CCE-140 cursor-backed carve-out (since that carve-out''s `if partial and not advance_cursor_backed` no longer alone protects against a blind+cursor-backed run auto-merging). Also fixes the nightly workflow''s ''Print partial-run reasons'' step, which was grepping the wrong state file (`state.json` instead of the ephemeral `current_run.json`) and always printed nothing while exiting 0.'
source_files:
  - .github/workflows/docs-agent-nightly.yml
  - CLAUDE.md
  - docs/superpowers/plans/2026-08-13-cce144-blind-run-detection.md
  - docs/superpowers/specs/2026-08-13-cce144-blind-run-detection-design.md
  - scripts/orchestrator_runner.py
  - scripts/state_io.py
  - scripts/verify_runner.py
  - skills/engineering-docs-agent-setup/SKILL.md
  - templates/workflow-run.yml
  - tests/orchestrator/test_blind_run_interlocks.py
  - tests/orchestrator/test_classification_coverage.py
  - tests/orchestrator/test_cursor_backed_merge.py
  - tests/orchestrator/test_deferral_skip.py
  - tests/orchestrator/test_dispatch_reasons_classification.py
  - tests/orchestrator/test_pipeline_integration.py
  - tests/orchestrator/test_schema_invalid_soft_fail.py
  - tests/orchestrator/test_state_advancement_invariant.py
  - tests/state_io/test_add_partial_blind.py
last_reviewed: '2026-08-20'
status: draft
---
# Blind vs Degraded Runs

`current_run.partial` used to mean two different things at once: "the pipeline judged some input and rejected it" and "the pipeline was never able to judge the input at all." Those are not the same failure. A degraded run threw away work it looked at; a blind run never looked. CCE-144 splits them into two flags so you can tell which one you're reading.

The split exists because the conflation cost real content. On 2026-08-11 and 2026-08-12, two nightly runs reported `conclusion: success` while every subagent call was rate-limited — zero calls made. The second of those runs advanced the consume-once watermark past three merged PRs whose content was never authored. That window is gone permanently; the cursor never re-reads what it has already passed. Both runs looked identical to an ordinary partial run in every signal an operator would check, and both passed CI green.

## The two flags

- **`blind`** — a blocking agent (source-collector, pr-summarizer, page-author, content-validator, notifier) was *prevented* from judging its input: dispatch failed, the CLI errored, the output didn't parse, or schema validation rejected garbage. The pipeline has no opinion on the content because it never saw a valid answer.
- **`degraded`** — the pipeline *did* judge the input and held some of it back: a time-budget cut, a lint block, an unsafe page path, an unknown lens, a deferral skip. The judgment is trustworthy; the run just chose not to act on everything it saw.

`partial` is the union of both. A run can be `partial` without being `blind` (a normal degraded run, self-healing on the next pass) or `partial` and `blind` at once (the dangerous case, because the run's other signals — including whatever it *did* manage to write — cannot be trusted as complete).

## `add_partial`'s three states

`add_partial` in `scripts/state_io.py` is the single writer of `partial_reasons`, `partial`, `blind`, and `blind_reasons`. It takes two independent keyword flags, and their precedence decides which state a reason lands in:

- `info_only=True` — advisory. Touches neither `partial` nor `blind`. `degraded` is ignored when this is set.
- `degraded=True` — the run judged and rejected work. Flips `partial` only. This is the self-healing path: the next run retries whatever was held back.
- neither flag set — the run was prevented from judging. Flips **both** `partial` and `blind`, and appends the reason to `blind_reasons` (always a subset of `partial_reasons`, same redaction and idempotency rules).

The third case — specify nothing — is the fail-safe default. An unclassified blocking failure mode turns the run red rather than passing silently. This is deliberate: classifying a call site as `degraded` is an explicit opt-out that a contributor has to choose; leaving it unclassified is loud by construction.

## Call-site classification is by call site, never by reason string

The same reason prefix, `schema_invalid:`, is emitted by three different call sites carrying two different classifications — source-collector defaults to blind, while page-author and gap-detector pass `degraded=True`. You cannot infer blind-vs-degraded from the text of a reason; you have to know which stage emitted it.

`_record_dispatch_reasons` in `scripts/orchestrator_runner.py` is the shared path for all seven agent dispatches. When a dispatch succeeds (`ok=True`), its reasons are retry/warning noise recorded `info_only`. When a dispatch fails (`ok=False`), the reasons flip `partial` — and, unless the call site passes `degraded=True`, `blind` too. Only two call sites pass `degraded=True`: page-author (an unlanded page batch holds its PR out of the advance cursor, so the content is held back rather than consumed) and gap-detector (purely advisory, outside the CCE-101 merge gate). Every other blocking dispatch failure — source-collector, pr-summarizer, content-validator, notifier — is blind by default.

## Three consumers

`current_run.blind` is read by three places, each acting on a different consequence of "the pipeline could not see":

- **`_exit_code`** returns 1 instead of 0 when `blind` is set. This reuses the exit-code channel `run()` already returns 1 on when the docs PR can't be opened — the same class of "this run failed, read the reasons" signal — rather than adding a third code. Exit 2 is still reserved for config-error paths. The exit code is the alarm channel of last resort: it needs no webhook, no secret, and it survives total Claude-CLI quota exhaustion, which is exactly the outage a blind run is often reporting.
- **`_should_advance_watermark`** returns `False` when `blind` is set, freezing `last_successful_run` at its prior value. The cursor is consume-once, so re-processing a window is cheap but skipping one is not — the asymmetry is the whole design: when in doubt, do not advance. Two blind reasons are deliberately recorded *downstream* of the advance-watermark check: `notifier_invalid` (a failed digest doesn't mean the authoring work was wrong, so the watermark stays honest) and any non-`info_only` failure inside `open_or_append_pr` (a failed PR-open means nothing reached `main`, so the next nightly starts clean regardless).
- **`_maybe_auto_merge`** takes `blind` as a kwarg and skips merging (`auto_merge_skipped: blind_run`) unconditionally, checked *ahead of* the CCE-140 cursor-backed carve-out. That ordering matters: CCE-140 narrowed the merge gate from `if partial` to `if partial and not advance_cursor_backed`, so that a partial-but-cursor-backed run — one whose advance provably covers only PRs whose pages all landed — could still auto-merge. But a cursor-backed advance only proves the baseline is honest about what the run *saw*; it says nothing when the run never saw its input at all. The reachable case is a time-truncated run (`advance_cursor_backed=True`) whose content-validator dispatch returned nothing — blind, partial, and cursor-backed simultaneously, matching no entry in the hand-listed `_MERGE_VETO_REASON_PREFIXES` allowlist. Gating on the computed `blind` flag rather than adding another prefix to that allowlist closes the whole class instead of one member of it.

The merge gate's veto order, in full, is: `merge_veto_reason` (matching `_MERGE_VETO_REASON_PREFIXES`, currently just `app_token_unavailable`), then the CCE-144 `blind` gate, then the CCE-140 `if partial and not advance_cursor_backed` carve-out. `blind` is read before `notifier_invalid` can be recorded, so a run that is blind *only* because its digest dispatch failed may already have merged by the time that reason lands — deliberately, since a failed digest means the operator wasn't told while the authoring work itself completed honestly. The alarm isn't lost: `_exit_code` still reads `blind` at the end of `run()` and the run still exits 1.

## Why this shape

The reviewer for CCE-144 rejected a hand-maintained registry mapping reasons to classifications — its keys collided across `verify_runner` and decayed as new reasons were added. Classification by call site, enforced by `tests/orchestrator/test_classification_coverage.py` requiring an explicit kwarg at every blocking `add_partial` call, is the version that stays correct as the pipeline grows new failure modes: a new blocking call site that forgets to classify itself is blind by default, which is loud rather than silently wrong.
