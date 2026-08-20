---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/224
synthesized_into: []
doc_kind: architecture
---

# Nightly workflow: finding partial-run reasons

When a nightly `docs-agent-nightly` run misbehaves, the run's reasons live in
two places: the GitHub Actions log and `.engineering-docs-agent/state.json`
after the operator merges the PR. This page is the operator's checklist for
finding them fast, and it documents a fix (CCE-144) to the step that prints
them — if you're troubleshooting a run from before this fix landed, the step
you'd normally check printed nothing.

## The "Print partial-run reasons" step

The workflow's final step exists so a reader running `gh run view --log`
doesn't have to expand the collapsed `$GITHUB_STEP_SUMMARY` block to see why a
run went red. It greps the run's `partial_reasons` (and, since CCE-144,
`blind_reasons`) straight into the log:

```bash
run_file=".engineering-docs-agent/current_run.json"
if [ -f "$run_file" ]; then
  jq -r '.current_run.partial_reasons[]? // empty' "$run_file" || true
  jq -r '.current_run.blind_reasons[]? // empty | "BLIND: " + .' "$run_file" || true
fi
```

Before CCE-144 this step read `.engineering-docs-agent/state.json` instead of
`current_run.json`, and it always printed nothing while exiting 0. That
wasn't a `jq` bug — it was reading the wrong file. `save_persistent_state`
(`scripts/state_io.py`) strips `current_run` before writing `state.json`
(it's listed in `_EPHEMERAL_KEYS`; only `state.json`'s persistent fields are
committed and promoted by merging the docs-agent PR). The ephemeral run
record — `partial`, `partial_reasons`, `blind`, `blind_reasons` — only ever
lands in the sibling `current_run.json`, written by `save_current_run`. A
step that greps `state.json` for `current_run` is grepping a key that's
never there, and a missing key reads exactly like a clean run.

If you're looking at an old run and the step printed nothing, that's not
evidence the run was clean — check `$GITHUB_STEP_SUMMARY` instead (the "Run
summary" step cats the post-run `state.json` in full) or pull the forensics
artifact (`docs-agent-subagent-forensics-<run_id>-<attempt>`, uploaded by the
"Upload subagent forensics" step with `if: always()`).

## Reading the two reason kinds

Every line the step prints is a `partial_reasons` entry. Lines prefixed
`BLIND:` are the subset also present in `blind_reasons` — that subset is what
turns the run red. `add_partial` (`scripts/state_io.py`) is the single writer
of both lists, and it classifies every call site:

- `info_only=True` — advisory. Touches neither `partial` nor `blind`.
  Retry/warning noise, hygiene results (auto-close, auto-merge outcomes),
  and things like `pr_summaries_reused` land here.
- `degraded=True` — the pipeline judged input and rejected it (a lint block,
  a time-budget cut, a deferral skip). Flips `partial` only. Self-healing:
  the next run retries the held-back work.
- neither kwarg (the default) — the pipeline was **prevented** from judging
  at all: a blocking subagent dispatch returned nothing, or a step it
  depends on failed outright. Flips both `partial` and `blind`, and the
  reason is duplicated into `blind_reasons`. This is the fail-safe default:
  an unclassified new blocking failure mode is loud, not silent.

If a line has no `BLIND:` counterpart, the run judged that input and moved
on — read it, but it isn't why the run is red.

## What a `BLIND:` line means for this run

Three places read the `blind` flag once the run reaches the end of `run()`:

- `_exit_code` (`scripts/orchestrator_runner.py`) returns `1` instead of
  `0`. This is deliberately the same exit-code class as "the docs PR could
  not be opened" — a red run tells the operator to read the reasons either
  way, no separate vocabulary to learn.
- `_should_advance_watermark` (`scripts/orchestrator_runner.py`) refuses to
  move `last_successful_run` for this run. The window the run couldn't see
  stays unprocessed and gets retried on the next nightly fire, rather than
  being silently skipped.
- `_maybe_auto_merge` (`scripts/orchestrator_runner.py`) skips with
  `auto_merge_skipped: blind_run` — ahead of the CCE-140 cursor-backed
  carve-out that would otherwise let a partial-but-cursor-backed run merge.
  A cursor-backed advance proves the baseline is honest about what the run
  *saw*; a blind run didn't see, so it can't be evidence for anything.

A run that's merely `degraded` (partial, not blind) still exits `0` and can
still auto-merge if it's cursor-backed — that's the expected, self-healing
common case. Only a `BLIND:` line should send you looking for a fix before
the next nightly fire, since re-processing a skipped window is cheap but a
watermark that silently advanced past unread content is not recoverable.

## Operator checklist

1. Check the run conclusion. Exit `1` (red) means `blind` was set at some
   point during the run; exit `0` (green) means it wasn't, even if the run
   was partial.
2. Open the "Print partial-run reasons" step log. `BLIND:`-prefixed lines
   are the ones that mattered for the exit code and the frozen watermark.
3. Match the reason prefix to its cause — most blind reasons are a blocking
   subagent dispatch returning nothing (`source_collector_invalid`,
   `pr_summarizer_invalid`, `content_validator_invalid`, `notifier_invalid`)
   or `app_token_unavailable` (the GitHub App installation token failed to
   mint — see the App-token comments in `.github/workflows/docs-agent-nightly.yml`
   for the 404-vs-401 triage). Pull the forensics artifact for the failing
   dispatch's prompt/stdout/stderr if the reason string alone isn't enough.
4. Fix the root cause. Nothing needs to be replayed by hand: the watermark
   didn't move, so the next scheduled or manually dispatched run picks up
   the same window.
