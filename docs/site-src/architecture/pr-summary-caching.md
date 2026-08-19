---
description: 'Documents architecture pr summary caching: The nightly orchestrator now caches each merged PR''s `pr-summarizer` output in `state.json` under a new `pr_summaries` key (keyed `{owner}/{name}#{pr}`, matching `deferral_counts`) and reuses it across runs instead of re-dispatching `pr-summarizer` against the same immutable merge commit night after night. A cached entry is served only when its stored `merge_sha` matches the PR''s current `merge_sha` and a hash fingerprint of `agents/pr-summarizer.md` matches the current agent file; an unreadable agent file yields an empty fingerprint that matches nothing, so unknown provenance never resolves to ''unchanged''. Entries are evicted by 30-day `last_seen_at` inactivity rather than by window membership, so a PR deferred night after night (and therefore absent from the discard window) keeps its cached summary alive instead of being re-bought. The feature is gated by a new `run.reuse_pr_summaries` config flag (default true, added to `templates/config.schema.json` since `run` is `additionalProperties: false`) and reports an `info_only` digest reason `pr_summaries_reused: n/m` — it never flips `partial`, since it only reports work the run skipped, not work it deferred or consumed unprocessed.'
source_files:
  - CHANGELOG.md
  - README.md
  - scripts/orchestrator_runner.py
  - templates/config.schema.json
  - templates/state.schema.json
  - tests/orchestrator/test_classification_coverage.py
  - tests/orchestrator/test_pr_summary_reuse.py
  - tests/schemas/test_config_schema.py
last_reviewed: '2026-08-19'
status: draft
---
# PR summary caching

A merged PR cannot change. Once `pr-summarizer` has produced a summary for a given merge commit, re-dispatching it against the same commit on a later night buys nothing but tokens. The orchestrator now knows this: it caches each PR's summary in `state.json` and reuses it until something that would invalidate it actually changes.

## Why this exists

The waste was measured, not estimated. On the advanced-data-import-system host, 52 of 58 PRs summarized on a given night had already been summarized the night before — 90% repeat work, at roughly 29,346 fresh input tokens per PR. That put a healthy run at ~1.53M tokens a night spent re-deriving summaries of code that, by construction, cannot have changed. Deferred PRs paid this cost repeatedly, and some were summarized only to be discarded later, wasting the spend entirely.

Eliminating the repeat work cuts a healthy run from ~61 subagent calls to ~9 — an 85% reduction — with no change to output quality. That matters directly against the weekly Claude quota exhaustion incident tracked as CCE-159.

## Cache identity: exact, not heuristic

The cache key is `{owner}/{name}#{pr}` — the same shape `deferral_key()` in `scripts/orchestrator_runner.py` already used for `deferral_counts`, so an operator reading `state.json` sees one vocabulary across both maps.

A stored entry is served only when three conditions all hold, checked by `scripts/orchestrator_runner.py:cached_pr_summary`:

- an entry exists under the PR's identity;
- its `merge_sha` matches the PR's current `merge_sha`; and
- its `fingerprint` matches the current agent definition.

The `merge_sha` check is what makes this cache exact rather than heuristic. A PR number alone is not identity — rewritten history or a reopened-and-remerged PR can put different content behind the same number. A `merge_sha` mismatch invalidates only that entry; sibling entries are untouched.

The fingerprint check covers the other axis of staleness: the instructions that produced the summary. `scripts/orchestrator_runner.py:pr_summarizer_fingerprint` hashes `agents/pr-summarizer.md` (truncated SHA-256), so editing that agent definition invalidates every cached entry automatically — there's no version constant to remember to bump, and nothing can silently drift out of date the way a hand-maintained one would. If the agent file can't be read, the fingerprint resolves to an empty string, which matches no stored entry. Unknown provenance never resolves to "unchanged" — the cache fails closed to a full re-summarize rather than serving a summary it can't prove is current.

`cached_pr_summary` returns the raw agent output; the caller re-stamps `pr_number` from the PR itself, exactly as it does for a fresh dispatch, so a fixture-static echo in a stored entry can't leak through.

## Eviction: last-seen, not window membership

Entries are evicted by 30-day `last_seen_at` inactivity (`PR_SUMMARY_RETENTION_DAYS` in `scripts/orchestrator_runner.py`), not by whether the PR is currently in the discard window.

That distinction matters for the PR most likely to benefit from the cache: one deferred night after night. Such a PR drops out of the processed window on every run that defers it, but `scripts/orchestrator_runner.py:next_pr_summaries` still refreshes its `last_seen_at` whenever it's asked for — so a repeatedly-deferred PR keeps its cached summary alive instead of being re-bought on every run that touches it. Evicting by window membership instead would also empty the cache exactly when the source-collector degrades and the window shrinks transiently — the worst possible night to lose it.

`next_pr_summaries` is pure (it never mutates the cache it's given) and applies these rules per PR in the window:

- a PR this run holds a fresh summary for → entry written, `merge_sha` and `fingerprint` stamped from this run;
- a PR in this window with no usable summary → its existing entry (if any) is kept and its `last_seen_at` refreshed;
- everything else → carried forward until it passes the 30-day cutoff.

A PR with no `merge_sha` is never stored — the sha is half the validity check, and an entry that can never be invalidated is worse than no entry at all.

## Configuration: the kill switch

The feature is gated by `run.reuse_pr_summaries` in the host config (`templates/config.schema.json`), default `true`. Because the `run` block is `additionalProperties: false`, this key had to be declared in the schema explicitly — an undeclared key doesn't degrade gracefully here, it aborts the nightly at config validation before any of this code runs.

Set `run.reuse_pr_summaries: false` to restore the pre-CCE-159 behavior, where every PR in the window is re-summarized on every run.

## What a run reports

A run that served cached summaries records an `info_only` digest reason of the form `pr_summaries_reused: n/m` (n reused of m PRs in the window). This never flips `partial` — it reports work the run *skipped* because it was provably unnecessary, not work the run deferred or consumed without processing, which is the distinction the CCE-144 blind/degraded split polices.

## State shape

Cached entries live under a new `pr_summaries` key in `state.json`, documented in `templates/state.schema.json`. Each entry is required to carry `merge_sha`, `fingerprint`, `last_seen_at`, and `summary` (the raw `pr-summarizer` output). Like `skipped_prs` and `deferral_counts`, the key is never seeded empty — a host that caches nothing keeps a byte-identical `state.json` to its pre-CCE-159 shape, and the key is runner-owned, not operator-edited.
