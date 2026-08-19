---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/219
synthesized_into: []
doc_kind: decision
---

# Decision: reference-aware batching, rejected (2026-08-13)

## Context

The knowledge-graph extraction over `docs/superpowers/{specs,plans}` was
stuck at roughly one node per document — mostly just the file's own title.
The diagnosis was scope, not volume: the extraction model dispatched a spec
alone routinely emitted several nodes about the code it described, but the
library's out-of-scope filter drops any node whose `source_file` names a
file that was not part of the same dispatch. A design spec is about the code
it changes, not about itself, so almost everything it produced got dropped.

The obvious fix — dispatch each spec together with the code files it
cites, so cross-file attribution lands in scope — had been proposed but not
yet tried. This page records that it was tried, measured, and deliberately
not merged.

## What was tried

Reference-aware batching was implemented and run over 20 documents in 7
requests: each spec was dispatched alongside its companion code files
instead of alone or in a flat same-size chunk.

It works as a mechanism. It fails as a fix.

| Measure             | Flat batching | Reference-aware |
| -------------------- | ------------- | ---------------- |
| Target-nodes/doc      | 1.02          | **0.55**          |
| Out-of-scope loss     | 64%           | **16%**           |
| Code nodes rescued    | 0             | **84**            |

The rescue is real: 84 concept nodes about the code the specs cite survived,
where every prior pass had discarded them. They attach to the companion code
files, not to the specs — consistent with those nodes always having been
*about* the companions in the first place.

## Why it was rejected

Doc coverage got worse, not better, and the reason is crowding. Larger
batches reliably pushed target-document coverage toward zero:

| Files dispatched | Target-nodes/doc |
| ----------------- | ------------------ |
| 11                 | 1.00                |
| 12                 | 0.67                |
| 13                 | 1.00                |
| 16                 | 0.33                |
| 18                 | **0.00**            |
| 18                 | **0.00**            |
| 19                 | 1.00                |

Two of the seven batches returned zero nodes for their own spec document
while still producing code nodes for the companions — the model omitted the
target outright. The per-request output budget looks roughly fixed, and code
wins the competition against prose, so adding companion files reallocates
capacity away from the document rather than adding capacity for it.

Because the library's merge step replaces every `source_file` present in a
new extraction, merging this run would have swapped 0.55 nodes/doc in for
the existing 1.02 nodes/doc — a net deletion of document coverage bought
with code nodes the graph didn't need duplicated. The run was quarantined
instead of merged.

This finding was measured on the extraction backend in use at the time
(Gemini). Whether crowding is a property of that backend specifically or of
batching in general was not established by this experiment alone — treat
"crowding is real" as confirmed and the exact threshold as unestablished.

## What this settles

Four cumulative extraction passes, including this one, now agree that
roughly one node per document is set by the extraction prompt, not by the
batching strategy: shrinking batches, growing them, and making them
reference-aware all left the per-document yield within noise of the flat
baseline. Reference-aware batching was the mechanism most likely to move
that number, and it moved a different number instead (out-of-scope loss)
while making the original one worse.

Don't re-propose reference-aware batching, or a variant of it, as a fix for
low document-node yield without a new measurement — this experiment already
ran it and the result is quarantined, not undone.

## Related, same change

The same change also landed a durable fix for an unrelated graph-quality
regression: a git-tracked minified test fixture was being re-extracted as
2,167 noise nodes on every commit, because the repo's post-commit hook
regenerates the graph from source inputs and a prior hand-filter did not
survive that regeneration. The fix was a `.graphifyignore` file rather than
another one-off filter of the graph output.
