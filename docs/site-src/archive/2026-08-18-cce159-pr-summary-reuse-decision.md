---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/231
synthesized_into: []
doc_kind: decision
---

# CCE-159: cache pr-summarizer output instead of re-buying it every night

**Decision:** cache a merged PR's `pr-summarizer` output in `state.json` under a new `pr_summaries` key, and serve it instead of re-dispatching whenever the collection window still overlaps that PR. The cache is exact, not heuristic — it is served only when both the PR's `merge_sha` and a fingerprint of `agents/pr-summarizer.md` match what was stored, and it defaults ON (`run.reuse_pr_summaries: true`) with a per-host kill switch.

## Problem

The nightly window is `last_successful_run.head_sha..HEAD`, and a PR stays inside that window on every run until the baseline cursor advances past it. `pr-summarizer` was dispatched for every PR in the window on every run, regardless of whether that PR had already been summarized the night before. On the advanced-data-import-system host this was measured, not estimated: 52 of the 58 PRs summarized on 2026-08-17 had also been summarized the night before — 90% repeat work, at roughly 29,346 fresh-input tokens per PR, about 1.53M redundant input tokens in one night. It included every PR that run went on to discard.

A merged PR's content cannot change once its `merge_sha` is fixed. That immutability is what makes caching its summary safe rather than a bet — the premise doesn't degrade with time, it only breaks in two specific, detectable ways.

## Why the cache is exact, not heuristic

`cached_pr_summary` (`scripts/orchestrator_runner.py:cached_pr_summary`) serves a stored entry only when three conditions all hold: an entry exists under the PR's identity, its `merge_sha` matches the PR's, and its `fingerprint` matches the current agent definition. Either mismatch is a hard miss, not a soft one — there is no partial credit and no "probably still fine."

The two invalidation paths cover the two ways the premise can stop holding:

- **`merge_sha` mismatch.** The number is not the identity; the content is. A rewritten history or a reopened-and-remerged PR can point the same PR number at different content, and serving the old summary in that case would describe code that is no longer there — worse than any amount of re-summarizing.
- **Fingerprint mismatch.** A cached summary is only valid for the instructions that produced it. `pr_summarizer_fingerprint` (`scripts/orchestrator_runner.py:pr_summarizer_fingerprint`) hashes `agents/pr-summarizer.md` itself rather than naming a version constant, so editing the agent's prompt invalidates every cached entry automatically — nobody has to remember to bump anything, which is exactly the failure mode a hand-maintained version number has.

An unreadable agent file hashes to `""`, and `cached_pr_summary` treats an empty fingerprint as matching nothing. The alternative — treating "I couldn't read the agent" as "unchanged" — would serve summaries whose provenance can't be established, and would do it silently. Failing closed to a full re-summarize costs one dispatch; failing open costs correctness with no signal that it happened.

## Why eviction is by last-seen, not by window membership

`next_pr_summaries` (`scripts/orchestrator_runner.py:next_pr_summaries`) evicts an entry once its `last_seen_at` has gone `PR_SUMMARY_RETENTION_DAYS` (`scripts/orchestrator_runner.py:PR_SUMMARY_RETENTION_DAYS`, 30 days) unseen, and refreshes `last_seen_at` on every run that still asks for that PR — whether or not the run actually reuses its stored summary.

The obvious alternative is to prune whatever fell out of this run's window. That's wrong for the same reason a source-collector window shrink is already handled carefully elsewhere in the orchestrator: a window can shrink transiently when the source-collector degrades, and a PR deferred night after night is exactly the PR that benefits most from staying cached. Pruning by window membership would wipe its entry on the worst possible night — the one where the pipeline can least afford to re-buy every summary — and hand it right back to the re-summarize path it was cached to avoid.

## Why the digest reason is info-only, not partial

A run that reuses at least one cached summary records `pr_summaries_reused: n/m` (`n` cache hits out of `m` PRs in the window) as an `info_only` reason. It is deliberately not eligible to flip `partial`.

Reuse describes an optimization, not a degradation — the pipeline judged the same content it would have judged from a fresh dispatch, it just didn't pay for the dispatch. Routing it through the ordinary `partial` path would cost a run its CCE-101 auto-merge eligibility for doing exactly what it was supposed to do. The saving still has to be visible, though, or the one number that says whether the feature is working at all is invisible to the operator — hence a digest line rather than silence.

## Config

`run.reuse_pr_summaries` (`templates/config.schema.json`) is a boolean, default `true`. Absent, `null`, or a malformed `run:` block all resolve to the default, matching the posture of `run.deferral_skip_threshold` and the other `run.*` resolvers — an existing host gets the saving with zero config edits. Setting it `false` restores the pre-CCE-159 behavior: every PR in the window is re-summarized on every run.

The stored shape is `templates/state.schema.json`'s `pr_summaries` object, keyed `{owner}/{name}#{pr}` — the same identity shape `deferral_counts` and `dismissed_gap_flags` already use. Each entry carries `merge_sha`, `fingerprint`, `last_seen_at`, and the raw `summary`. `pr_number` inside a reused summary is re-stamped from the PR itself on every use, exactly as it is on a fresh dispatch, so a stale echo inside a stored summary can never leak through.

## Consequences

- A host that reuses nothing and summarizes nothing keeps a `state.json` byte-identical to its pre-CCE-159 content — `pr_summaries` is never seeded as an empty key, the same never-seed-empty contract `deferral_counts` and `skipped_prs` already follow.
- Cache eviction and cache hits are independent of `deferral_skip_threshold`: a PR abandoned by the CCE-140 skip hatch after repeated deferrals still carries a live cache entry until 30 days of true silence, in case it is ever revisited.
- Coverage: `tests/orchestrator/test_pr_summary_reuse.py` exercises the hit path, both invalidation paths, the retention/refresh lifecycle, the transient-window-shrink case, and the config kill switch through the real `load_config_validated` loader (not a raw dict), since `run:` is `additionalProperties: false` and an undeclared key aborts a host's nightly at config validation before any of this code runs.
