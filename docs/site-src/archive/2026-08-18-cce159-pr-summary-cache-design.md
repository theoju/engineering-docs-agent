---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/231
synthesized_into: []
doc_kind: decision
---

# CCE-159 — a merged PR's summary is bought once, not once per night

## Problem

The nightly window is a lookback from a baseline that advances slowly, so the
same PRs stay in the window and get re-collected until the cursor finally
passes them. Every one of those re-collections re-dispatched `pr-summarizer`
against the PR's merge commit — a commit that, by construction, cannot
change once the PR is merged.

Measured on the `advanced-data-import-system` host: of the 58 PRs
summarized on 2026-08-17, 52 had already been summarized the night before.
That's 90% repeat work, at 29,346 fresh-input tokens per summarized PR —
roughly 1.53M tokens a night spent re-deriving summaries of content that
cannot have changed. Deferred PRs paid this cost the most, some of them
summarized on multiple nights only to be discarded later without ever
landing a page. This lands directly against the weekly Claude quota
exhaustion incident referenced in CCE-159, and cuts a healthy run from
~61 subagent calls to ~9 (-85%) with no change to output quality.

## Decision

Cache each merged PR's `pr-summarizer` output in `state.json` and reuse it
on later runs instead of re-dispatching for it, gated by a new
`run.reuse_pr_summaries` config flag (default `true`).

### Cache key: exact, not heuristic

The cache serves an entry only when two independent checks both pass:

- **`merge_sha`** still matches the PR's current merge SHA.
- **fingerprint** still matches a hash of `agents/pr-summarizer.md`.

The PR number alone is not identity. History gets rewritten and PRs get
re-merged; if the cache trusted the number, it would serve a summary of code
that is no longer there, which is worse than paying to re-summarize. The
`merge_sha` check catches that.

The fingerprint check catches the other way provenance can go stale: the
summarizer's own instructions changing. It hashes `agents/pr-summarizer.md`
directly rather than tracking a hand-maintained version constant, so nobody
has to remember to bump anything when the agent file changes — editing the
agent invalidates every cached entry automatically.

`pr_summarizer_fingerprint` (`scripts/orchestrator_runner.py:pr_summarizer_fingerprint`)
returns an empty string when it cannot read the agent file. An empty
fingerprint deliberately matches nothing: "unknown provenance" must never
resolve to "unchanged," because that would silently serve summaries whose
origin can't be established. Lookup and write-back are two small, pure
functions — `cached_pr_summary` and `next_pr_summaries`
(`scripts/orchestrator_runner.py:cached_pr_summary`,
`scripts/orchestrator_runner.py:next_pr_summaries`) — both covered in
`tests/orchestrator/test_pr_summary_reuse.py`, including the case where a
sibling PR's entry stays untouched when one entry is invalidated.

### Eviction: last-seen, not window membership

Entries are evicted by 30-day `last_seen_at` inactivity
(`PR_SUMMARY_RETENTION_DAYS` in `scripts/orchestrator_runner.py`), not by
whether the PR is currently in the collection window. The obvious
alternative — prune whatever isn't in this run's window — was rejected on
purpose: it would empty the cache on exactly the night a degraded
source-collector can least afford to re-buy every summary, and it would age
out the PR that benefits most from caching in the first place. A PR deferred
night after night sits outside the window on every run that defers it, but
it has no fresh summary of its own to re-store — window-based eviction would
delete its only cached entry while it's still being asked for. Instead,
`next_pr_summaries` refreshes `last_seen_at` for any cached entry whose PR
is still in the window, whether or not that run produced a fresh summary for
it, so a repeatedly-deferred PR's cached entry stays alive.

### Storage shape

Cached under a new `pr_summaries` key in `state.json`
(`templates/state.schema.json`), keyed `{owner}/{name}#{pr}` — the same
shape as `deferral_counts` and `skipped_prs`. Each entry stores `merge_sha`,
`fingerprint`, `last_seen_at`, and the raw `summary` object. The key is
never seeded empty: a host that caches nothing writes a byte-identical
`state.json` to the pre-CCE-159 shape, so this doesn't force a migration or
a version bump. `pr_number` inside a reused `summary` is re-stamped from the
live PR on reuse rather than trusted from the stored echo.

### Kill switch

`run.reuse_pr_summaries` (boolean, default `true`) restores the pre-CCE-159
behavior — every PR in the window re-summarized every run — when set
`false`. It's declared in `templates/config.schema.json` rather than read
ad hoc, because `run` is `additionalProperties: false`: an undeclared key
read by the runner doesn't degrade gracefully, it aborts the host's nightly
at config validation. The kill-switch case is therefore tested through
`load_config_validated`, not a raw dict
(`tests/orchestrator/test_pr_summary_reuse.py`).

### Reporting

The run records an `info_only` digest reason, `pr_summaries_reused: n/m`. It
describes work the run did *not* have to do — the opposite of a
degradation — so it never flips `partial`: doing so would cost auto-merge
every night through CCE-140's `partial and not advance_cursor_backed` gate,
turning an optimization into an outage. It's still reported, because a
saving nobody can see is indistinguishable from a feature that silently
stopped working.

## Why this shape

- **Exact invalidation over heuristic freshness.** A merged PR's diff is
  immutable, which is the one property that makes an exact cache safe. The
  design deliberately does not try to detect "similar enough" content —
  either both the `merge_sha` and the agent fingerprint match, or the
  summary is re-bought in full.
- **Last-seen eviction over window-membership eviction.** Window membership
  is a proxy for relevance that fails precisely when the pipeline is
  degraded (a shrunk window) or when a PR is being deferred repeatedly (the
  case the cache exists to help most). Last-seen tracks actual demand
  instead.
- **Info-only reporting over a gating signal.** The auto-merge gate (CCE-101,
  CCE-140) reads `partial`, and this feature never produces output the gate
  needs to see — it only ever reports that less work happened. Advisory
  reporting keeps it visible without giving it veto power over a run it
  didn't degrade.
