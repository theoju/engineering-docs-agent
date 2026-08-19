---
description: 'Documents architecture glossary: Added two net-new documentation files to the plugin repo: CONTEXT.md, a glossary defining the orchestrator''s advance-path vocabulary (window, baseline, cursor, window head, promotion, ephemeral advance, admission gate, deferral, owed page, forgiveness, held back, partial run, truncation, batch, block, drift), and ADR 0001, which records the decision that the on-disk baseline advance is ephemeral by design (CCE-40) and only becomes durable via merge-as-promotion — and that the real defect the CCE-153 investigation uncovered is that the promotion gate is merely advisory (`_maybe_auto_merge` has no standing with the forge), not that the advance computation needs clamping. No code changed; the earlier clamp-the-advance approach was implemented and reverted for violating a pinned CCE-40 §7 invariant test.'
source_files:
  - CONTEXT.md
  - docs/adr/0001-baseline-advances-on-disk-for-partial-runs.md
last_reviewed: '2026-08-19'
status: draft
---
# Glossary

The orchestrator's advance-path vocabulary. These terms describe how a run
decides what it has done and what it still owes — they carry no implementation
detail and no design rationale of their own. For the decision behind why the
on-disk advance behaves the way it does, see ADR 0001, "The baseline advances
on disk even when the run is partial."

## Run window

**Window** — the range of merged host PRs a single run considers, expressed as
`baseline..head`. A run never looks outside its window.

**Baseline** — the committed lower bound of the window, recorded in the host's
`state.json`. It answers "where did we get to last time?", and it is the only
value that decides what the next run collects.

**Cursor** — the position that moves through the window during a run. It walks
the window's PRs oldest-first and may stop before the end. Where it stops is
what the baseline becomes, if the run is permitted to advance at all. Baseline
is the recorded value; cursor is the moving position that produces it.

**Head** — the host repository's commit at the moment the run starts; the
window's upper bound.

**Window head** — the head of a window that a run only partly processed.
Recorded separately from the baseline so a re-dispatch in the same hour can
recognize the window as already seen, even though the baseline stopped short of
it.

## Progress and its refusal

**Promotion** — writing a run's result into the baseline. A run computes an
advance; promotion is what makes it the next run's lower bound.

**Ephemeral advance** — an advance that exists only on the run's own branch.
Because the host's `state.json` reaches the default branch solely by merging
the docs PR, an advance written on that branch is a proposal, not a fact.
Whether it becomes fact is decided at merge, not at write.

**Admission gate** — the stage that decides which of the window's PRs a run
will attempt at all. It may admit a prefix rather than the whole window.

**Deferral** — a PR the run admitted but did not finish. The PR remains owed a
page and is expected to be attempted again on a later run.

**Owed page** — a page that a PR requires and that no run has successfully
landed yet. A page reverted after authoring is still owed.

**Forgiveness** — abandoning a deferral that has failed too many times, so the
window can move past it. A forgiven PR is recorded durably rather than
silently dropped, because nothing will attempt it again.

**Held back** — the PRs a run refuses to let the cursor pass, because they are
still owed pages.

**Partial run** — a run that completed but did not do everything it set out to
do. Partial is a statement about completeness, not about failure: a partial
run may still have produced good pages.

**Truncation** — stopping early because a budget ran out, as distinct from
stopping early because work could not be completed. Both produce deferrals;
only one is about time.

## Content

**Batch** — the unit of authoring: one page and the PRs it draws from. A
single PR may fan out to several batches.

**Block** — a validator verdict severe enough that the page does not ship.
The page is removed and the PRs that needed it are back to owing one.

**Drift** — a claim in a published page that no longer matches the source it
cites.

## Why baseline and cursor are worth keeping distinct

You'll see `baseline` and `cursor` used near-interchangeably in conversation,
but they are not the same value. The cursor moves while a run is in progress;
the baseline is what gets written once the run decides how far the cursor is
allowed to count. A run can compute a cursor position and still write a
baseline that stops short of it — that gap is exactly what a partial run
produces, and it is why "the baseline advanced" and "the work is accepted" are
different claims. Whether an advance written to `state.json` on a docs branch
ever reaches the default branch is a merge decision, not a computation one —
see ADR 0001 for why that split is deliberate.
