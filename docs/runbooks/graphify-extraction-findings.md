# graphify semantic-extraction findings

Why the document layer of this repo's knowledge graph is ~1 node per file, what
was tried, and what would actually fix it. Recorded 2026-08-12 after four
extraction passes over `docs/superpowers/{specs,plans}`.

Code references below point into the **graphify library**
(`graphifyy`, installed as a uv tool), not into this repo.

## State when this was written

`graphify-out/graph.json` — 3,714 nodes, 5,294 links, 525 communities, built at
commit `e32b4764`.

- AST layer: 5,445 extracted nodes, 3,278 present in the graph. Carries the
  structure.
- Semantic layer: 439 nodes, 420 present. 144 of the graph's links are
  non-AST; 134 are semantic-to-semantic.
- The 58 previously-failed spec/plan files: 59 nodes, **1.02 nodes/file**,
  26/59 connected, mean degree 0.63.

## The core finding

**Extraction is not underproducing. It loses 64% of its output at a scope
boundary that spec and plan documents cross by definition.**

A batch-3 run over 42 of those files returned 63 nodes and dropped **114** as
out-of-scope — the model generated ~4.2 nodes per file and kept ~1.

`graphify/llm.py:_out_of_scope` drops any node whose `source_file` resolves to
a real file that was not dispatched in the same call. A design spec is not
about itself; it is about the code it changes. When the model reads
`docs/superpowers/plans/2026-06-10-cce101-auto-merge-gate.md` and emits a node
about `scripts/orchestrator_runner.py`, that attribution is correct, and the
filter discards it because `orchestrator_runner.py` was not in the same
three-file chunk.

What reliably survives per document is the one node genuinely about the
document itself — its title. Hence 86%+ of those nodes being the file's own H1,
and the flat ratio regardless of file size: a 4.4 KB spec and a 120.9 KB plan
both yield exactly 1.

The filter is well-designed in general. It is wrong for this document genre.

## What was tried

| Pass     | Batch | Files | Raw nodes/file | In graph   | Mean degree |
| -------- | ----- | ----- | -------------- | ---------- | ----------- |
| topup    | 20    | 220   | 0.75           | 0.80       | 0.40        |
| progress | 15    | 350   | 0.42           | 0.89       | 0.47        |
| topoff   | 2     | 20    | 2.45           | 1.10       | 0.95        |
| retry1   | 1     | 1     | 1.00           | 1.00       | 0.00        |
| batch3   | 3     | 42    | 0.98           | not merged | —           |

The topoff pass at batch 2 suggested small batches were ~6x better. **It did
not reproduce.** Batch 3 over the specs returned 0.98 nodes/file against a 1.02
baseline — 0.95x, no improvement. Topoff's 20 files were a more self-contained
set, and the signal did not generalize.

Shrinking the batch makes this _worse_, not better: a smaller chunk is a
smaller in-scope set for cross-file attribution to land in.

That run is preserved at
`graphify-out/.graphify_gemini_batch3.jsonl.rejected`. It is renamed off the
`*.jsonl` glob deliberately — merging it would make the graph marginally worse.

## Secondary limits

- **`graphify/llm.py:_FILE_CHAR_CAP`** is 20,000 characters and truncates every
  file before the prompt is built. 23 of the 58 specs exceed it; the model saw
  59% of the 1.42 MB corpus, and 16% of the 120.9 KB CCE-80 plan. Not the main
  cause — the ratio is flat across file sizes — but it caps the ceiling for
  large plans.
- **The Gemini free tier is 20 requests per _day_**, not per minute:
  `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: 20`,
  model `gemini-3-flash`. Re-extracting all 58 files at batch 3 costs ~20
  requests — the entire daily allowance. Iterating on extraction quality more
  than once a day requires leaving the free tier. An earlier session misread
  this as a per-minute ceiling and built a 7-second inter-batch sleep around it;
  the sleep is harmless but addresses the wrong limit.
- **`graphify/llm.py:extract_corpus_parallel` writes the semantic cache but
  never reads it.** Re-runs always hit the API. There is no cache-replay risk,
  and no cache-replay saving.

## What would actually fix it

**Reference-aware batching.** Parse each spec's cited code paths — this repo
cites them explicitly, per the line-free `path/to/file.py` convention in
CLAUDE.md — and dispatch the spec together with the files it cites, so
cross-file attribution lands in scope. This targets the 114 dropped nodes
directly. Untried; blocked on quota at time of writing.

Rejected alternatives:

- _Patching the out-of-scope filter._ The filter is correct. The dropped nodes
  name files that get their own extraction, so re-attributing them to the
  dispatching document creates duplicate concepts.
- _Raising the character cap._ Addresses truncation only, and the ratio is flat
  across file sizes, so it would not move the main number.

## Two measurement traps hit while diagnosing this

1. **`graph.json` is NetworkX node-link format: edges live under `links`, not
   `edges`.** Reading `graph["edges"]` with a `.get(..., [])` default returns an
   empty list rather than raising, so every connectivity metric computes as a
   confident zero. This produced a false "all 59 nodes are isolated, mean degree
   0.00" before it was caught. Same silent-failure shape as the driver bug that
   started this investigation: a default that makes absence look like a
   measurement.
2. **The driver's `done_files` subtracts failure records from the seen set.**
   Failure records exist so the evidence survives; if they also marked files
   done, a re-run would skip exactly the batches that need retrying. A new pass
   must therefore write to its own `GX_PROGRESS` file — pointing it at an
   existing pass file whose records already cover the inputs yields
   "nothing to do".

## Driver

`graphify-out/run_semantic_extraction.py` carries per-batch error capture. Its
`diagnose` helper parses HTTP status, `quotaId`, `retry_after_s`, and the
out-of-scope and omitted-file counts out of the library's console output, and a
`ProviderFailure` exception restores the retry path for the
zero-nodes-plus-provider-error case that otherwise records as a success.

Records written under the older six-key schema — the `progress`, `retry`,
`topup`, and `topoff` pass files — predate that capture and carry no failure
evidence. A zero-node batch in those files is indistinguishable from a
genuinely empty one.
