---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/216
synthesized_into: []
doc_kind: decision
---

# Graphify Semantic-Extraction Findings (2026-08-13)

**PR:** #216

PR #216 moves a semantic-extraction diagnosis out of the gitignored `graphify-out/` build directory and into a permanent file, `docs/runbooks/graphify-extraction-findings.md`, so it survives a directory rebuild or clean. No production code changed. The runbook is placed under `docs/runbooks/` rather than `docs/site-src/` deliberately — that keeps it outside the docs-agent lens path and its Tier-1 citation lints, since its code references point into the external graphify library, not into this repo.

## The core finding

Four extraction passes over `docs/superpowers/{specs,plans}` left the doc layer at roughly 1 node per file, regardless of document size — a 4.4 KB spec and a 120.9 KB plan both yielded exactly one. The runbook traces this to a scope boundary, not underproduction: a batch-3 run over 42 files generated ~4.2 nodes per file but kept only ~1, because `graphify/llm.py:_out_of_scope` drops any node whose `source_file` names a real file that wasn't dispatched in the same chunk. Spec and plan documents are about the code they change, not about themselves, so most of what the model correctly attributes to another file gets discarded — leaving mainly the one node that survives regardless: the document's own title.

## What was tried and ruled out

Reducing batch size from 15 to 3 made cross-file attribution measurably worse, not better — 0.98 nodes/file against a 1.02 baseline. An earlier batch-2 pass had suggested small batches helped; it didn't reproduce, because a smaller chunk is a smaller in-scope set for cross-file attribution to land in. The runbook records this as a negative result specifically so nobody re-runs it: re-extracting all 58 spec/plan files at batch 3 costs roughly the entire Gemini free-tier daily allowance.

That allowance is a secondary trap in its own right: the Gemini free tier is 20 requests **per day**, not per minute. An earlier session had misread it as a per-minute ceiling and built an inter-batch sleep around the wrong limit.

Two more constraints are recorded as secondary, not root-cause: `graphify/llm.py:_FILE_CHAR_CAP` truncates every file to 20,000 characters before building the prompt, which truncates 23 of the 58 spec/plan files — but the ratio stays flat across file sizes, so this caps the ceiling for large plans without explaining the pattern. And `graph.json` is NetworkX node-link format, with edges stored under `links`, not `edges`; reading `graph["edges"]` with a dict `.get(..., [])` default silently returns an empty list instead of raising, which produced a false "all nodes isolated, mean degree 0.00" reading before it was caught.

## What would actually fix it

The untried fix is reference-aware batching: parse each spec's cited code paths — this repo already cites them explicitly, per the line-free `path/to/file.py` convention — and dispatch the spec together with the files it cites, so cross-file attribution lands inside the scope boundary. This targets the 114 nodes dropped as out-of-scope in the batch-3 run directly. It's untried and was blocked on quota at time of writing. Patching the out-of-scope filter itself was considered and rejected: the filter is correct in general, and the files it names get their own extraction pass, so re-attributing their nodes to the dispatching document would create duplicate concepts.

## Where the detail lives

The full findings — the extraction-pass table, the two measurement traps, and the driver's error-capture behavior — live in `docs/runbooks/graphify-extraction-findings.md`. That file sits outside the core lens intentionally, so this archive entry is a pointer and summary rather than a duplicate of the runbook.
