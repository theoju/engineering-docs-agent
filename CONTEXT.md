# Context

The domain language of the engineering-docs-agent. Glossary only — no
implementation detail, no design decisions. Decisions live in `docs/adr/`.

## Run window

**Window** — the range of merged host PRs a single run considers, expressed as
`baseline..head`. A run never looks outside its window.

**Baseline** — the committed lower bound of the window, recorded in the host's
`state.json`. It is the answer to "where did we get to last time?" and it is the
only value that decides what the next run collects.

**Cursor** — the position that moves through the window _during_ a run. It walks
the window's PRs oldest-first and may stop before the end. Where it stops is
what the baseline becomes, if the run is permitted to advance at all. Baseline
is the recorded value; cursor is the moving position that produces it.

**Head** — the host repository's commit at the moment the run starts; the
window's upper bound.

**Window head** — the head of a window that a run only partly processed.
Recorded separately from the baseline so a re-dispatch in the same hour can
recognise the window as already seen, even though the baseline stopped short of
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
