---
description: 'Documents architecture glossary: Adds two net-new documentation files with no code changes: CONTEXT.md, a glossary defining the orchestrator''s watermark-advance vocabulary (window, baseline, cursor, window head, promotion, ephemeral advance, admission gate, deferral, owed page, forgiveness, held back, partial run, truncation, batch, block, drift) in one place, distinguishing in particular baseline (the committed lower bound of the next window) from cursor (the in-run position that produces it); and ADR 0001, which records the decision that the on-disk baseline is allowed to advance even for a partial run, per the CCE-40 ephemeral-advance model, and documents why an earlier attempt to clamp the advance at computation time was implemented and then reverted (it broke a pinned CCE-40 invariant test).'
source_files:
  - CONTEXT.md
  - docs/adr/0001-baseline-advances-on-disk-for-partial-runs.md
last_reviewed: '2026-08-20'
status: draft
---
# Glossary

The domain language of the engineering-docs-agent orchestrator's watermark-advance
machinery. This page defines terms only — no design rationale. For the decision
record behind why the baseline advances on disk even for a partial run, see
[ADR 0001](../archive/0001-baseline-advances-on-disk-for-partial-runs.md).

## Run window

**Window** — the range of merged host PRs a single run considers, expressed as
`baseline..head`. A run never looks outside its window.

**Baseline** — the committed lower bound of the window, recorded in the host's
`state.json`. It answers "where did we get to last time?" and is the only value
that decides what the next run collects.

**Cursor** — the position that moves through the window during a run. It walks
the window's PRs oldest-first and may stop before the end. Where it stops is what
the baseline becomes, if the run is permitted to advance at all. Baseline is the
recorded value; cursor is the moving position that produces it.

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
Because the host's `state.json` reaches the default branch solely by merging the
docs PR, an advance written on that branch is a proposal, not a fact. Whether it
becomes fact is decided at merge, not at write.

**Admission gate** — the stage that decides which of the window's PRs a run will
attempt at all. It may admit a prefix rather than the whole window.

**Deferral** — a PR the run admitted but did not finish. The PR remains owed a
page and is expected to be attempted again on a later run.

**Owed page** — a page that a PR requires and that no run has successfully
landed yet. A page reverted after authoring is still owed.

**Forgiveness** — abandoning a deferral that has failed too many times, so the
window can move past it. A forgiven PR is recorded durably rather than silently
dropped, because nothing will attempt it again.

**Held back** — the PRs a run refuses to let the cursor pass, because they are
still owed pages.

**Partial run** — a run that completed but did not do everything it set out to
do. Partial is a statement about completeness, not about failure: a partial run
may still have produced good pages.

**Truncation** — stopping early because a budget ran out, as distinct from
stopping early because work could not be completed. Both produce deferrals; only
one is about time.

## Content

**Batch** — the unit of authoring: one page and the PRs it draws from. A single
PR may fan out to several batches.

**Block** — a validator verdict severe enough that the page does not ship. The
page is removed and the PRs that needed it are back to owing one.

**Drift** — a claim in a published page that no longer matches the source it
cites.
