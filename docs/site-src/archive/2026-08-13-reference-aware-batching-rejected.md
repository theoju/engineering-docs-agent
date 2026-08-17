---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/219
synthesized_into: []
doc_kind: decision
---

# Reference-Aware Batching: Tried and Rejected (2026-08-13)

**PR:** #219

The earlier graphify extraction-findings record (see "Where the detail lives" below) proposed an untried fix for the extraction pipeline's out-of-scope node loss: dispatch each spec together with the code files it cites, so cross-file attribution lands inside the scope boundary that `graphify/llm.py:_out_of_scope` enforces. PR #219 ran that experiment. **It works as a mechanism and fails as a fix**, and the change is deliberately not merged into `build_merge`. Only this findings write-up and a separate, durable `.graphifyignore` fix land.

## What was tested

The experiment dispatched 20 documents in 7 requests, each spec paired with the code files it cites. Out-of-scope loss dropped from 64% to 16%, and the run rescued 84 concept nodes — about `scripts/orchestrator_runner.py`, `scripts/state_io.py`, `scripts/gh_client.py`, and similar files — that every prior flat-batching pass had discarded. As a scope-boundary mechanism, reference-aware batching does exactly what it was designed to do.

## Why it was rejected

Target-nodes/doc — nodes about the spec itself, not about its companions — fell from 1.02 under flat batching to 0.55 under reference-aware batching. The rescued code nodes attach to the companion files, not to the specs, which is consistent with what they were always about; but doc depth for the spec itself got worse, not better.

The cause is crowding: the per-request response budget looks roughly fixed, and code nodes win the competition against prose. Two batches in the run returned zero nodes for their spec documents while producing 11 and 17 code nodes each — the model omitted the intended targets outright. Rescuing a node and improving the metric it was rescued for turned out to be different claims.

Because `build_merge` replaces every `source_file` present in a new extraction, merging this run would have swapped 0.55 nodes/doc in for the existing 1.02 — a net deletion of doc coverage in exchange for code nodes. The run is quarantined rather than merged.

## The `.graphifyignore` fix

A separate, durable fix landed alongside the experiment: `.graphifyignore` at the repo root. It excludes `*.min.js` and `*.min.css` from extraction, addressing a vendored, minified render fixture that AST extraction had been walking symbol-by-symbol into thousands of noise nodes. The file is git-tracked (kept deliberately as a fixture), so `.gitignore` could never exclude it, and a hand-applied filter kept silently reverting because a globally-seeded post-commit hook re-extracts on every commit and knows nothing about a one-off manual filter. `.graphifyignore` uses gitignore syntax and, per graphify's loader, can only ever exclude more than `.gitignore` — never re-include something git ignores.

## Where the detail lives

The full experiment data — the crowding table by files-dispatched, the rejected alternatives, and the prompt-level fix that superseded this line of investigation entirely — lives in `docs/runbooks/graphify-extraction-findings.md`. That file sits outside the core lens intentionally, so this archive entry is a pointer and summary rather than a duplicate. See also the prior archive entry recording the original diagnosis and the now-superseded "untried fix" proposal this PR tested.
