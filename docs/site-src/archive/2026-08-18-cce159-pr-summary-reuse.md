---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/231
synthesized_into: []
doc_kind: decision
---

# PR-summary reuse (CCE-159)

The orchestrator's collection window is a slow-advancing lookback: a merged
PR stays in scope across many nightly runs until the baseline cursor finally
advances past it. Before this change, every one of those re-collections
re-dispatched `pr-summarizer` against the same merge commit, even though a
merged PR cannot change.

## The waste, measured

This was measured on the `advanced-data-import-system` host, not estimated.
Of the 58 PRs `pr-summarizer` processed on 2026-08-17, 52 had already been
summarized the night before — 90% repeat work, and it included every PR that
run went on to discard. At 29,346 fresh-input tokens per summarized PR, a
healthy run was spending roughly 1.53M tokens a night re-deriving summaries
of content that cannot change.

## Why a cache is safe here

A merged PR is immutable. That premise is what makes the cache exact rather
than heuristic, so the invalidation logic exists to prove the premise still
holds rather than to guess when it might not:

- **The content behind the PR number changed.** The number alone is not
  identity — a rewritten history or a re-merge can put different content
  behind the same PR number, and serving a stale summary in that case would
  be worse than any amount of re-summarizing. The cache key therefore checks
  `merge_sha`, not just the PR number.
- **The instructions that read the PR changed.** A summary is only valid for
  the prompt that produced it. `pr_summarizer_fingerprint()` in
  `scripts/orchestrator_runner.py` hashes `agents/pr-summarizer.md` (truncated
  sha256, 16 characters) rather than naming a version constant, so nobody has
  to remember to bump anything when the agent's instructions change — editing
  that file invalidates every cached entry at once. If the agent file can't be
  read, the fingerprint is `""`, and an empty fingerprint matches nothing:
  treating "unknown" as "unchanged" would serve summaries whose provenance
  can't be established, and do it silently.

`cached_pr_summary` in `scripts/orchestrator_runner.py` is the read side: it
serves an entry only when both checks pass, and returns `None` — a clean
cache miss, never a crash — on a missing key, a malformed entry, or a bad
merge_sha/fingerprint. `next_pr_summaries` is the write side that computes
the following run's cache from this run's window and dispatch results.

## What survives between runs

Storage is `state.json.pr_summaries`, keyed `{owner}/{name}#{pr}`, the same
shape as `deferral_counts`. `templates/state.schema.json` requires each entry
to carry `merge_sha`, `fingerprint`, `last_seen_at`, and the raw `summary`
object. The key is never seeded empty — a host that caches nothing writes a
state file byte-identical to its pre-CCE-159 content.

A few behaviors follow directly from how the collection window actually
behaves, not from the obvious implementation:

- **A deferred PR still gets its entry refreshed.** A PR the admission gate
  never reached that night has no fresh summary to store, but
  `next_pr_summaries` still bumps its `last_seen_at`. The PR most likely to
  benefit from the cache — one deferred night after night — is exactly the
  one that would otherwise age out of it.
- **Eviction is by last-seen, not by window membership.** Entries unseen for
  `PR_SUMMARY_RETENTION_DAYS` (30 days) are dropped. Pruning by "not in this
  run's window" was the obvious alternative and is wrong: a transient
  source-collector shrink would empty the whole cache on exactly the night
  the pipeline can least afford to re-buy every summary.
- **A PR with no `merge_sha` is never stored.** An entry that can't be
  invalidated is worse than no entry at all, because it can only ever be
  served blind.
- **`next_pr_summaries` is pure.** It never mutates the cache dict it's
  given, matching the existing contract of `next_deferral_counts` — callers
  diff before and after to decide whether anything changed.

Regression coverage for all of the above lives in
`tests/orchestrator/test_pr_summary_reuse.py`.

## Config

`run.reuse_pr_summaries` (boolean, declared in `templates/config.schema.json`)
defaults to `true`. Set it to `false` to restore the pre-CCE-159 behavior,
where every PR in the window is re-summarized on every run. It's declared
explicitly in the schema rather than read ad hoc because `run` is
`additionalProperties: false` — an undeclared key read by the runner doesn't
degrade gracefully, it aborts the host's nightly at config validation.

## Reporting

A run that served entries from cache records an `info_only`
`pr_summaries_reused: n/m` reason. This is deliberately non-blocking: the
saving describes work the run did *not* have to do, the opposite of a
degradation, and flipping `partial` on a successful optimization would cost
auto-merge every night through CCE-140's `partial and not
advance_cursor_backed` gate — turning the optimization itself into an
outage. It's recorded at all only because a saving nobody can see is
indistinguishable from a feature that silently stopped working.

## Related

- CCE-140 established the cursor-backed advance mechanics this reuse logic
  builds on — the same slow-advancing lookback window that makes PRs stay in
  scope long enough for this cache to matter.
- CCE-151 later made that cursor-backed advance run on every code path, not
  only the time-truncated one — a PR held back by a lint block or a failed
  dispatch is now excluded from the watermark the same way a time-budget cut
  already excluded it. This cache doesn't change with that fix: a PR held
  out of the advance stays in the window, keeps getting collected, and its
  cached entry is exactly what `next_pr_summaries` refreshes on sight rather
  than lets age out.
- See [Orchestrator](../architecture/orchestrator.md) for how PR-summary
  reuse fits into the rest of the nightly run loop.
