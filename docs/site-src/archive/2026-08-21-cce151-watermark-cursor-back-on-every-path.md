---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/238
synthesized_into: []
doc_kind: decision
---

# CCE-151: Watermark Advance Is Cursor-Backed on Every Path (2026-08-21)

## Context

CCE-140 built the cursor-backed advance: a PR list of PRs the run either processed or deferred, walked in window order by `advance_cursor_list`, that stops at the oldest PR the run did not finish. CCE-144 built the writer that decides which PRs those are — `deferred_pages_by_pr` — and the `held_back` set derived from it.

Both pieces were wired only inside `run()`'s `if time_truncated:` branch. The `else` branch — the ordinary, non-time-budget-truncated path — set `advance_sha` to the full window HEAD without ever reading `deferred_pages_by_pr`. So a run that was `partial` for any non-time reason (a lint block, `page_author_invalid`) still advanced the baseline to the whole window, silently discarding whatever it had held back. This gap was flagged in prose during CCE-144's own final review but carried no ticket until it produced a live incident.

The cursor is consume-once: a window `last_successful_run.head_sha` walks past is never re-read. Because the run still exited 0, nothing alarmed.

**Incident.** On 2026-08-21, two nightly runs against `theoju/claude-code-self-assessment` — `32460602658` and `32495019606` — each blocked a page on lint and advanced past the window that stranded it anyway. The second run then consumed the very window the first one had stranded. Recovery required a hand-written baseline rewind; the underlying PR content is unrecoverable through the pipeline itself.

## Decision

Make the cursor-backed walk unconditional rather than time-budget-specific. `partition_deferrals` and the `held_back` set are now computed on every run, not only inside the truncated branch, and the walk is entered whenever `time_truncated or held_back` is true. The plain window-HEAD advance survives only in the `else` of that combined check — i.e., only when `held_back` is empty — so a clean run's behavior is byte-identical to before.

This is a structural fix, not a new veto. The alternative — teaching `_should_advance_watermark` to refuse whenever `partial and not advance_cursor_backed` — was considered and rejected: it freezes the baseline on *every* lint block, including one that documented nothing wrong with the rest of the window, and reinstates the CCE-109 doom loop that CCE-140 exists to prevent. The fix instead bounds the advance at its source: the cursor still moves, just never past a PR the run held back.

### Four traps

1. **The obvious fix is wrong and actively harmful.** Gating `_should_advance_watermark` on `partial` would freeze the cursor on every lint block forever — one permanently-unlintable page would wedge the baseline for good. `tests/orchestrator/test_cursor_backed_merge.py::test_mixed_window_advances_to_the_last_fully_documented_pr` pins the requirement that the cursor still MOVES on a held-back run, just not past undocumented work.
2. **Hoisting the read wasn't enough — `partition_deferrals` had to move too.** With `still_deferred` defaulting to `[]` on the non-truncated path, every such run would silently clear the deferral counts of the PRs it held back, so no PR could ever accumulate enough consecutive deferrals to reach `resolve_deferral_threshold`'s skip hatch. Hoisting the call, not just the `deferred_pages_by_pr` read, is what keeps that release valve armed.
3. **Merge-as-promotion was never the containment it looked like.** The pre-fix assumption was that a human merging the docs PR by hand acts as a safety check. But merging is all-or-nothing: a PR can carry a recovered page and a poisoned watermark advance in the same diff, and an operator merging it has no way to accept one without the other.
4. **Reason strings are cause-dependent, deliberately.** The walk now serves two causes — time-budget truncation and held-back PRs — so the reason string returned distinguishes `time_budget_*` from `held_back_*`. The `time_budget_*` family stays byte-identical to its pre-CCE-151 text: `tests/orchestrator/test_time_budget.py` and the deferral-skip tests assert those exact strings, and existing runbooks tell operators to grep for them. Neither family was added to `_MERGE_VETO_REASON_PREFIXES` (still the single `app_token_unavailable` entry), and both sites keep `degraded=True`, so CCE-144's blind/degraded classification is unaffected by this change.

## Diagnostic reflex

If a nightly is green, `current_run.partial` is `true`, and the baseline still moved as far as full window HEAD, check `deferred_pages_by_pr` and the computed `held_back` set before suspecting the linter or the page-author. A populated `deferred_pages_by_pr` sitting next to a HEAD-valued baseline is this class of bug, not a page-authoring one.

## What changed

- **`scripts/orchestrator_runner.py:run`** — `partition_deferrals` and the derived `held_back` set are computed unconditionally each cycle, not only under `if time_truncated:`. The cursor-walk branch (built on `advance_cursor_list`) is entered on `time_truncated or held_back`; the plain window-HEAD assignment is gated on `held_back` being empty.
- **`scripts/orchestrator_runner.py:advance_cursor_list`** and **`scripts/orchestrator_runner.py:partition_deferrals`** are unchanged in signature and behavior — this fix is about where and how often they are called, not what they compute.
- **New fixture set `tests/orchestrator/fakes_degraded_advance/`** — a page-author-absent fixture set exercising the non-truncated, degraded (`page_author_invalid`) path end to end.
- **New fixture set `tests/orchestrator/fakes_mixed_block/`** — three PRs, three distinct doc targets (via the per-PR `fake_pr_summarizer__pr<N>.json` override), one blocked by `content-validator`. This is the first fixture set to give the CCE-140 rule ("advance only to the last PR whose pages all landed") something to actually test: without per-PR summarizer fixtures, every PR in a dry run reads the same summary and lands in one shared page batch, so a window could previously only land or fail as a whole.

## Error handling / degradation

| Scenario | Before CCE-151 | After CCE-151 |
| --- | --- | --- |
| Time-budget-truncated run, real in-window cursor | Cursor-backed advance to the last processed PR | Unchanged |
| Clean run, nothing held back | Full window-HEAD advance | Unchanged |
| Single PR admitted, its only page blocked by lint (`fakes_block`) | Advanced to full window HEAD — the window was consumed and the content unrecoverable | Baseline holds at the prior `last_successful_run.head_sha`; run stays `partial=True`, `blind=False` (degraded); window stays re-readable |
| Three PRs, two land, one blocked by lint (`fakes_mixed_block`) | Advanced to full window HEAD — the blocked PR's window was consumed | Advances to the last fully-documented PR's `merge_sha` (PR 2); PR 3's window stays re-readable |
| Non-truncated run, `page_author_invalid` on the only admitted PR (`fakes_degraded_advance`) | Advanced to full window HEAD | Baseline holds; run stays `partial=True`, `blind=False`; window stays re-readable |

`_LAST_ADVANCE_CURSOR_BACKED` — the module-level flag `_maybe_auto_merge` reads to decide whether a `partial` run may auto-merge — is set `True` whenever the walk anchors on a real cursor (truncated or held-back) and `False` when nothing anchors an advance at all, so the CCE-140 merge gate's refusal is unaffected by this change; it now simply sees the flag set correctly on a wider set of runs.

## Testing

- **`tests/orchestrator/test_cursor_backed_merge.py::test_lint_block_partial_run_holds_the_cursor_and_is_not_cursor_backed`** — amended from a single-layer assertion (the auto-merge flag stays `False`) to a two-layer one: the baseline also holds on disk, and `_LAST_ADVANCE_CURSOR_BACKED` stays `False`. The second layer is retained deliberately — it is what still catches a partial run that legitimately advanced its cursor but still shouldn't auto-merge.
- **`tests/orchestrator/test_cursor_backed_merge.py::test_mixed_window_advances_to_the_last_fully_documented_pr`** — new. Three PRs against `fakes_mixed_block`, no time budget (the non-truncated path). Asserts the baseline advances past the two documented PRs' merge SHAs and stops short of the blocked PR's, and that `_LAST_ADVANCE_CURSOR_BACKED` is `True`.
- **`tests/orchestrator/test_state_advancement_invariant.py::test_partial_run_via_lint_block_holds_state_when_nothing_was_documented`** — inverted from its pre-CCE-151 assertion. It used to require the watermark to advance to full HEAD per CCE-40 §7 row 4; it now requires the baseline to hold, since the fixture's only admitted PR documents nothing.
- **`tests/orchestrator/test_degraded_advance_non_truncated.py`** — new file, two tests: `test_degraded_non_truncated_run_holds_the_cursor_for_an_undocumented_pr` pins the full shape of the fixed behavior field by field (`partial=True`, `blind` stays falsy, baseline holds, exit code stays 0); `test_degraded_non_truncated_run_must_not_silently_consume_a_pr_invariant` pins the weaker property directly — a run that documented nothing must either exit non-zero or leave the cursor where it was — independent of which mechanism satisfies it.

## Out of scope

- Exiting non-zero on a held-back, non-truncated run was considered and rejected: it would fail the nightly on a condition that is routine and self-healing (one page blocked, the rest published), training operators to ignore red runs — the exact failure mode CCE-127 was made of.
- The general `ADVISORY_AGENTS` unification and any change to fact-checker or gap-detector's own dispatch paths are untouched by this ticket.

## See also

- CCE-140: the original cursor-backed advance and `advance_cursor_list`.
- CCE-144: the `deferred_pages_by_pr` complement writer and the blind/degraded `partial` split this fix's reason strings are careful not to disturb.
- CCE-109: the doom-loop failure mode that makes an unconditional cursor freeze the wrong fix.
- `scripts/orchestrator_runner.py`: `run`, `advance_cursor_list`, `partition_deferrals`, `_should_advance_watermark`.
- `tests/orchestrator/fakes_mixed_block/README.md`: the per-PR fixture override this incident's regression coverage depends on.
- `tests/orchestrator/fakes_degraded_advance/README.md`: the page-author-absent fixture that reproduces the non-truncated, degraded (`page_author_invalid`) path this record covers.
- `docs/superpowers/specs/2026-08-13-cce144-blind-run-detection-design.md`: the spec whose known residual this ticket closes.
- `docs/site-src/architecture/orchestrator.md`: the current-state description ("Cursor-backed watermark advance holds on every path") kept in sync with this record; read that page for the mechanism as it stands today, this one for why it changed.
