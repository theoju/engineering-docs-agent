---
description: 'Documents architecture glossary: Adds two net-new documentation files to the repo: CONTEXT.md, a project-wide glossary defining the orchestrator''s domain vocabulary (window, baseline, cursor, window head, promotion, ephemeral advance, admission gate, deferral, owed page, forgiveness, held back, partial run, truncation, batch, block, drift), and docs/adr/0001-baseline-advances-on-disk-for-partial-runs.md, an ADR recording the decision behind how the baseline advance is persisted for partial runs. No code changes; the full test suite (1339 passed, 5 skipped) is unaffected.'
source_files:
  - CONTEXT.md
  - docs/adr/0001-baseline-advances-on-disk-for-partial-runs.md
last_reviewed: '2026-08-28'
status: draft
---
# Glossary

The orchestrator has accumulated overlapping terms — baseline, cursor, window
head, ephemeral advance, held back — across several tickets (CCE-144, CCE-152,
CCE-153) without a single place defining them precisely. This page is that
place. It mirrors `CONTEXT.md`, the repo's own domain-vocabulary reference:
definitions only, no implementation detail and no design rationale. Where a
term's rationale matters, it is recorded separately as an architecture
decision record — this page tells you what a word means, not why the system
was built that way.

## Run window

**Window** is the range of merged host PRs a single run considers, expressed
as `baseline..head`. A run never looks outside its window.

**Baseline** is the committed lower bound of the window, recorded in the
host's `state.json`. It answers "where did we get to last time?", and it is
the only value that decides what the next run collects.

**Cursor** is the position that moves through the window during a run. It
walks the window's PRs oldest-first and may stop before the end. Where it
stops is what the baseline becomes, if the run is permitted to advance at
all. Baseline is the recorded value; cursor is the moving position that
produces it.

**Head** is the host repository's commit at the moment the run starts — the
window's upper bound.

**Window head** is the head of a window that a run only partly processed.
It's recorded separately from the baseline so a re-dispatch in the same hour
can recognize the window as already seen, even though the baseline stopped
short of it.

## Progress and its refusal

**Promotion** is writing a run's result into the baseline. A run computes an
advance; promotion is what makes it the next run's lower bound.

**Ephemeral advance** is an advance that exists only on the run's own branch.
Because the host's `state.json` reaches the default branch solely by merging
the docs PR, an advance written on that branch is a proposal, not a fact.
Whether it becomes fact is decided at merge, not at write.

**Admission gate** is the stage that decides which of the window's PRs a run
will attempt at all. It may admit a prefix rather than the whole window.

**Deferral** is a PR the run admitted but did not finish. The PR remains
owed a page and is expected to be attempted again on a later run.

**Owed page** is a page that a PR requires and that no run has successfully
landed yet. A page reverted after authoring is still owed.

**Forgiveness** is abandoning a deferral that has failed too many times, so
the window can move past it. A forgiven PR is recorded durably rather than
silently dropped, because nothing will attempt it again.

**Held back** describes the PRs a run refuses to let the cursor pass,
because they are still owed pages.

**Partial run** is a run that completed but did not do everything it set
out to do. Partial is a statement about completeness, not about failure — a
partial run may still have produced good pages.

**Truncation** is stopping early because a budget ran out, as distinct from
stopping early because work could not be completed. Both produce deferrals;
only one is about time.

## Content

**Batch** is the unit of authoring: one page and the PRs it draws from. A
single PR may fan out to several batches.

**Block** is a validator verdict severe enough that the page does not ship.
The page is removed and the PRs that needed it go back to owing one.

**Drift** is a claim in a published page that no longer matches the source
it cites.

## See also

- [ADR 0001: The Baseline Advances on Disk Even When the Run Is Partial](../archive/0001-baseline-advances-on-disk-for-partial-runs.md) —
  the rationale behind **promotion** and **ephemeral advance** above: why a
  run computes and writes its advance regardless of whether it is partial,
  and why refusal to make that advance real belongs at promotion instead.
