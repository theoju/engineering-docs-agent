---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/219
synthesized_into: []
doc_kind: decision
---

# Decision: reference-aware batching rejected for graphify extraction

**Status: rejected. Not merged.**

## The problem it tried to solve

graphify's semantic extraction pass over design docs was losing most of what
it generated. Spec and plan documents cross a scope boundary by definition —
they describe code they don't contain — and the library's out-of-scope filter
drops any node whose `source_file` points at a real file that wasn't
dispatched in the same batch. A spec read on its own therefore keeps almost
nothing except the node for its own title: flat baseline of 1.02 nodes per
document, regardless of document size.

The obvious fix is to widen the batch: dispatch each spec together with the
code files it cites, so a node about, say, `scripts/orchestrator_runner.py`
lands in scope instead of being discarded. That's reference-aware batching,
and it was built and run on 2026-08-13.

## What the experiment measured

Reference-aware batching ran over 20 documents in 7 requests, each spec paired
with its cited companions. Compared against flat batching over the same
corpus:

| Measure | Flat batching | Reference-aware |
| --- | --- | --- |
| Target-nodes/doc | 1.02 | **0.55** |
| Out-of-scope loss | 64% | **16%** |
| Code nodes rescued | 0 | **84** |

The rescue is real: 84 concept nodes about the companion files survived that
every prior pass had discarded. They attach to the companions, not to the
specs — which is consistent, since those nodes were always about the
companions, not about the document that happened to mention them.

But the metric the fix was meant to move — nodes per *document* — got worse,
not better, and the reason is crowding. The per-request node budget behaves
as roughly fixed, and code out-competes prose for it:

| Files dispatched | Target-nodes/doc |
| --- | --- |
| 11 | 1.00 |
| 12 | 0.67 |
| 13 | 1.00 |
| 16 | 0.33 |
| 18 | 0.00 |
| 18 | 0.00 |
| 19 | 1.00 |

Two of the seven batches returned zero nodes for their spec while still
producing 11 and 17 code nodes each — the model omitted the target document
outright when the companion set got large enough. (n=7, and the 19-file batch
scoring 1.00 breaks a clean threshold reading; treat crowding as real and the
exact cutoff as unestablished.)

Rescuing a node and improving the metric it was rescued for turned out to be
different claims. Widening scope pays for the rescue in crowding on the
document it was meant to help.

## Why it wasn't merged

Merging a graphify extraction replaces every `source_file` present in the new
run, so landing this output would have swapped the existing 0.55/doc result
in for 1.02/doc — a net deletion of document coverage traded for code nodes
that attach elsewhere. The run was quarantined as a rejected extraction
(renamed off the active output glob) rather than merged.

## What this rules out, and what it doesn't

This closes reference-aware batching as an approach to the coverage problem —
don't re-propose widening the dispatch batch to include cited code files
without new evidence, and don't re-run this experiment expecting a different
result absent a change to the crowding mechanism itself.

It does not touch two things that stayed live:

- The `.graphifyignore` mechanism recorded separately, which fixes an
  unrelated node-count regression from a vendored, git-tracked minified
  fixture — a different problem (noise from one file) from the one this
  experiment addressed (loss across many files).
- Later work found in the same investigation, on the same host document, that
  changing the extraction *prompt* — not the batching — moved the per-document
  yield 6-8x with no crowding penalty. That result and the reference-aware
  rejection above are companions: four separate batching experiments, of
  which this is one, agreed the ratio doesn't move under batching changes,
  which is what pointed the investigation at the prompt instead.

Crowding, as measured here, is specific to the backend used for the
experiment (Gemini). A later backend switch found no equivalent depth tax at
the same batch size — a reminder that a capacity-crowding result doesn't
automatically carry across a backend change, and shouldn't be assumed to
apply unmeasured to a different model.
