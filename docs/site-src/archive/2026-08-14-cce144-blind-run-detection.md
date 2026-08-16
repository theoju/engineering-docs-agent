---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/224
synthesized_into: []
doc_kind: decision
---

# CCE-144: Blind vs. Degraded — Why a Rate-Limited Nightly Reported `conclusion: success`

**Date:** 2026-08-14
**Ticket:** CCE-144
**PR:** #224

Two consecutive nightly runs — `31472240064` on 2026-08-11 and `31579090583` on 2026-08-12 — both reported `conclusion: success`. On the second one, `source-collector` was rejected before it made a single tool call:

```
"You've hit your weekly limit · resets 9am (UTC)"
```

`returncode: 1`, `total_calls: 0`. `source-collector` and `notifier` both returned `None`. Nothing alarmed, because nothing was wired to notice.

The first run's PR (#214) closed unmerged, so its watermark write was discarded harmlessly. The second run's PR (#215) merged, and its watermark advance merged with it: `last_successful_run.head_sha` moved from `0c88411` to `08b27e2`, a window containing three feature PRs — #211 (CCE-138), #212 (CCE-139), #213 (CCE-140) — whose content was never authored. The cursor is consume-once; that window is gone for good. This page documents the fix and its context. The three lost PRs are not recovered — that would mean re-processing a week's worth of merged work in one docs PR, and the design spec deliberately leaves that as a separate operator decision rather than something this change performs silently.

## Three independent layers of silence

1. **No exit path distinguished a dead run.** `run()` in `scripts/orchestrator_runner.py` returned `1` only when the docs PR could not be opened, and `2` on a config error. Every other path, including a fully rate-limited run that produces zero output, returned `0`.
2. **The alarm shared the failure mode.** `notifier` is a Claude CLI subagent drawing on the same quota as the agents it reports on. A quota outage silences the work and its own alarm at once.
3. **The diagnostic read the wrong file.** The nightly workflow's "Print partial-run reasons" step grepped `.engineering-docs-agent/state.json` for `partial_reasons`, but `save_persistent_state` in `scripts/state_io.py` strips the ephemeral `current_run` key before writing that file — the reasons live in the sibling `current_run.json`, which the step never read. It had printed nothing, always, since it was added.

## The fix: blind vs. degraded

`partial` used to conflate two conditions with opposite operational meanings. CCE-144 splits it:

- **Blind** — the run was *prevented from judging*. It consumed input it could not process. Recovery needs a human or a quota reset. Signal: red.
- **Degraded** — the run *judged, and rejected work*. It held back what it could not process. Self-healing — the next run retries the same page. Signal: green.

The distinguishing question is not how much a run produced — a run with no new PRs since the watermark legitimately produces nothing and must stay green. It's whether the emptiness was *chosen* or *forced*. `scripts/orchestrator_runner.py`'s complement writer answers that: any batch that doesn't land folds its PR into `deferred_pages_by_pr`, holding it out of the advance cursor — but only on the time-truncated path. On a non-truncated run the advance goes straight to window HEAD regardless, and the only thing standing between a degraded failure there and `main` is CCE-140's cursor-backed merge gate.

`state_io.add_partial` carries the classification as a keyword, in precedence order:

- `info_only=True` — advisory; touches neither `partial` nor `blind` (unchanged from before this change).
- `degraded=True` — flips `partial` only. This is the pre-existing behavior for content rejection: `lint_block`, `unsafe_page_path`, `unknown_lens`, the CCE-109 `time_budget_exceeded` sites, `page_author_invalid`, `gap_detector_invalid`.
- neither — flips `partial` **and** `blind`, and records the reason in `blind_reasons`. This is the fail-safe default: a blocking failure mode nobody classified turns the run red instead of passing silently. `source_collector_invalid`, `content_validator_invalid`, `notifier_invalid`, and `app_token_unavailable` all land here.

The default matters more than any individual classification. It's the same lesson CCE-127 already taught about `conclusion` vs. `outcome`: a diagnostic that reports healthy because it looked in the wrong place is worse than no diagnostic, because it actively suppresses inquiry. Failing open toward "assume it's fine" is what produced this incident.

`page_author_invalid` is degraded while `content_validator_invalid` is blind, even though they're one pipeline step apart — because on the time-truncated path a page that fails authoring never lands and its PR is held back for retry, while a page that fails validation is already counted in `landed_batches` regardless of the outcome, so the run has no way to walk the cursor back past it.

## Three consumers

`current_run.blind` (and its companion list, `blind_reasons`) is read in three places:

- **Exit code.** `run()` now returns `1` when the run is blind, joining the existing `1` for "PR could not be opened" rather than competing with it — same operator action, same channel. The exit code needs zero provisioning: no secret, no webhook, no config, and it survives total quota exhaustion because nothing on that path calls the Claude CLI.
- **Watermark advance.** A blind run leaves `last_successful_run` untouched. A degraded run still advances it — the whole point of CCE-109/CCE-140's cursor-backed truncation is that a degraded run is self-healing, so freezing the cursor on every degraded reason would reinstate the doom loop CCE-140 was built to close.
- **Auto-merge.** `_maybe_auto_merge()` gained an unconditional `blind` skip, placed *ahead of* CCE-140's `partial and not advance_cursor_backed` carve-out. That ordering closes a real gap: CCE-140 narrowed the merge gate so a cursor-backed advance can merge even while `partial` is set, on the reasoning that a cursor-backed advance only moves past PRs whose pages all landed. That reasoning holds for a degraded run but not a blind one — the cursor proves the baseline is honest about what the run *saw*, and a blind run didn't see. Before this fix, a run that time-truncates (setting `advance_cursor_backed = True`) and then takes a blind `content-validator` failure would merge unreviewed, because `_MERGE_VETO_REASON_PREFIXES` was a hand-maintained allowlist that only matched `app_token_unavailable`. Gating on the computed `blind` flag instead of extending that allowlist by hand closes the whole class rather than one member of it.

## Workflow repair

The nightly workflow's "Print partial-run reasons" step now reads `.engineering-docs-agent/current_run.json` — the file that actually carries `partial_reasons` and `blind_reasons` — instead of `state.json`. Applied to both the dogfood workflow and `templates/workflow-run.yml`, since CI's `actionlint` job only lints `.github/workflows/`, not `templates/`, and that gap is plausibly how the two drifted apart during CCE-127.

## Supersedes CCE-150

A prior PR (#223, merged 2026-08-14) stamped the CCE-144 design spec "NOT IMPLEMENTED — archived, branch deleted," on the premise that `feat/CCE-144-blind-run-detection` had been abandoned unpushed. That premise was wrong — the branch was pushed and PR #224 landed it nine minutes after #223 merged. CCE-150 is obsolete; this page and the design spec (`docs/superpowers/specs/2026-08-13-cce144-blind-run-detection-design.md`) describe current behavior, not a proposal.

## Coverage

A dedicated test enumerates every blocking `add_partial` call site in `scripts/orchestrator_runner.py` and asserts each one is explicitly classified (`tests/orchestrator/test_classification_coverage.py`), so an unclassified new failure mode fails the suite instead of silently defaulting into whichever bucket happened to be convenient. The regression case for the whole auto-merge fix — blind *and* cursor-backed must still skip, and it must skip with reason `auto_merge_skipped: blind_run`, not `partial_run` — lives in `tests/orchestrator/test_blind_run_interlocks.py` and `tests/orchestrator/test_cursor_backed_merge.py`. `tests/state_io/test_add_partial_blind.py` covers the `add_partial` precedence rules directly, including idempotency and the redaction path shared with `partial_reasons`.

## What this doesn't fix

The Slack alarm remains out of scope — the dogfood repo carries no `SLACK_WEBHOOK_URL`, and provisioning one is an operator action no code change can perform. Moving the nightly cron off its current hour was considered and rejected: a weekly rate limit resets once per week, so cron placement rescues at most one run in seven, and the hour is hardcoded across `templates/workflow-run.yml`, the dogfood workflow, and `scripts/scaffold_workflow.py` in a way that isn't a cheap change. And the three PRs lost to the 2026-08-12 incident — CCE-138, CCE-139, CCE-140 — stay lost; rewinding the watermark to replay them is a separate operator decision, not something this change makes for you.
