---
description: 'Documents architecture advance path glossary: Adds two net-new, code-free documents: a top-level CONTEXT.md glossary defining the orchestrator''s advance-path vocabulary (window, baseline, cursor, window head, promotion, ephemeral advance, admission gate, deferral, owed page, forgiveness, held back, partial run, truncation, batch, block, drift) with explicit emphasis on the baseline-vs-cursor distinction, and ADR 0001 recording the decision that the state.json baseline advances on disk even for a partial run, because the on-disk advance is ephemeral (CCE-40) and only reaches the host''s default branch via merge. The ADR also documents two rejected alternatives: clamping the advance whenever a run owes pages (reverted after failing the CCE-40 §7 row 4 pinning tests), and re-running an old window as a retry mechanism (rejected because non-deterministic page slugs produce duplicate topics on re-run).'
source_files:
  - CONTEXT.md
  - docs/adr/0001-baseline-advances-on-disk-for-partial-runs.md
last_reviewed: '2026-08-16'
status: draft
---
# Advance-path glossary

The orchestrator's nightly run walks a window of merged PRs and, at the end,
proposes an advance of the host's `state.json` baseline. The vocabulary for
that walk — window, baseline, cursor, and the handful of terms describing why a
run stops short — is used near-interchangeably in conversation even though the
underlying concepts are distinct. This page is the docs-site mirror of
`CONTEXT.md`: definitions only, no design rationale. For the decision that
depends on these terms — why the baseline advances on disk even when a run is
partial — see the architecture decision record referenced at the bottom of
this page.

## Run window

**Window** — the range of merged host PRs a single run considers, expressed as
`baseline..head`. A run never looks outside its window.

**Baseline** — the committed lower bound of the window, recorded in the host's
`state.json`. It answers "where did we get to last time?" and it is the only
value that decides what the next run collects.

**Cursor** — the position that moves through the window *during* a run. It
walks the window's PRs oldest-first and may stop before the end. Where it
stops is what the baseline becomes, if the run is permitted to advance at all.
Baseline is the recorded value; cursor is the moving position that produces
it. Conflating the two is the single most common source of confusion in
advance-path discussion — they describe the same number at different moments,
not the same thing.

**Head** — the host repository's commit at the moment the run starts; the
window's upper bound.

**Window head** — the head of a window that a run only partly processed.
Recorded separately from the baseline so a re-dispatch in the same hour can
recognize the window as already seen, even though the baseline stopped short
of it.

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

**Block** — a validator verdict severe enough that the page does not ship. The
page is removed and the PRs that needed it are back to owing one.

**Drift** — a claim in a published page that no longer matches the source it
cites.

## Where the decision lives

This glossary is definitions only. The decision to keep the baseline
advancing on disk even for a partial run — and the two alternatives rejected
along the way — is recorded in `docs/adr/0001-baseline-advances-on-disk-for-partial-runs.md`,
under the archive's decision records. The canonical source for this glossary
is `CONTEXT.md` at the repository root; if the two ever disagree, `CONTEXT.md`
is authoritative.
