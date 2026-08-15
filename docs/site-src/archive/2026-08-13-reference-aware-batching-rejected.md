---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/219
synthesized_into: []
doc_kind: decision
---

# Reference-Aware Batching: Rejected (2026-08-13)

**PR:** #219

`docs/site-src/archive/2026-08-13-graphify-extraction-findings.md` (PR #216) left one fix untried: dispatch each spec together with the code files it cites, so cross-file attribution lands inside `graphify/llm.py:_out_of_scope`'s scope boundary instead of outside it. PR #219 implements that fix (`graphify-out/reference_aware_extract.py`), runs it over 20 documents in 7 requests, and rejects the result. It changes no production code.

## The result

| Measure             | Flat batching | Reference-aware |
| -------------------- | -------------- | ---------------- |
| Target-nodes/doc     | 1.02           | **0.55**          |
| Out-of-scope loss    | 64%            | **16%**           |
| Code nodes rescued   | 0              | **84**            |

The mechanism works exactly as designed: 84 concept nodes about `scripts/orchestrator_runner.py`, `scripts/state_io.py`, `scripts/gh_client.py`, and similar companions survived, where every prior pass discarded them, and out-of-scope loss dropped from 64% to 16%. But the metric the fix was meant to move — target-nodes per document, the density of nodes attached to the spec or plan itself — got worse, falling from 1.02 to 0.55.

## Why: crowding, not attribution

The rescued nodes attach to the companion code files, not to the specs, which is consistent — they were always about the companions. The drop in doc-node density is a separate effect: the response budget per request is roughly fixed, and code nodes win the competition against prose nodes for that budget. Adding companion files to a batch reallocates capacity toward the code rather than adding capacity for the doc.

| Files dispatched | Target-nodes/doc |
| ----------------- | ------------------ |
| 11                 | 1.00                |
| 12                 | 0.67                |
| 13                 | 1.00                |
| 16                 | 0.33                |
| 18                 | **0.00**            |
| 18                 | **0.00**            |
| 19                 | 1.00                |

Two of the seven batches returned zero nodes for their spec while still producing 11 and 17 code nodes each — the model omitted the target document outright. At n=7 the exact crowding threshold isn't established, but the direction is: rescuing a node and improving the density it was rescued for are different claims, and reference-aware batching only delivers the first.

Rescuing an out-of-scope node and raising target-doc density turned out to trade against each other under this approach: batching widens the in-scope set (which rescues code nodes) at the cost of the response budget the target document competes for (which lowers its own density).

## Disposition

**Not merged.** `build_merge` replaces every `source_file` present in a new extraction, so merging this run would swap the existing 1.02 nodes/doc for 0.55 — a net loss of doc coverage traded for code nodes the doc-density metric was never asking for. The run is quarantined at `graphify-out/.graphify_gemini_refaware.jsonl.rejected`, renamed off the `*.jsonl` glob deliberately so nothing accidentally picks it up.

Patching `graphify/llm.py:_out_of_scope` directly was rejected for the same reason it was rejected in PR #216: the filter is correct. The files it drops get their own extraction pass, so re-attributing their nodes to the dispatching document would create duplicate concepts rather than new ones.

## What this pointed at instead

Four passes — including this one — now agree that a spec's own target-node density does not move under any batching change. That result is what motivated testing a prompt change instead of a batching change: an appended "DOCUMENT MODE" instruction telling the model to emit one node per concept, with `source_file` attribution kept on the document rather than the code it references. That test moved a single-file baseline from 1 node to 6–8, confirming the extraction prompt — not the batch shape — was the ceiling. See `docs/runbooks/graphify-extraction-findings.md` for that result and for the later switch to a `claude-cli`/Haiku backend, which turned out not to reproduce this crowding effect at all: Haiku held 6.33 nodes/doc at the same chunk size where Gemini fell to 0.55. Crowding, in other words, was a property of the model tested here, not of batching in general — a caveat worth carrying forward before assuming this rejection still holds on a different backend.

The same PR also lands a durable fix for an unrelated extraction problem — a git-tracked minified fixture repeatedly re-polluting the graph — via a new `.graphifyignore` file. See `docs/site-src/operations/2026-08-13-graphifyignore-minified-fixtures.md`.
