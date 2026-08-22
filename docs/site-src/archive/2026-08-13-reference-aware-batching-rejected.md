---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/219
synthesized_into: []
doc_kind: decision
---

# Reference-aware batching: rejected (2026-08-13)

## Decision

Reference-aware batching — dispatching each spec or plan to the extraction
agent together with the code files it cites, so cross-file attribution lands
in scope — is **rejected as a fix** for low document depth in the knowledge
graph. Do not re-attempt it without reading this record first.

## What it was supposed to fix

Flat batching (dispatching specs and plans in same-genre chunks, unaccompanied
by the code they reference) loses most of its output at a scope boundary:
`graphify/llm.py:_out_of_scope` drops any node whose `source_file` resolves to
a real file that was not dispatched in the same call. A spec that describes
`scripts/orchestrator_runner.py` generates a node about it, and the filter
discards that node because `orchestrator_runner.py` wasn't in the same chunk.
The result is a flat ~1.02 nodes per document, regardless of file size —
almost always just the file's own title surviving.

The proposed fix was mechanical: put the referenced code files in scope by
dispatching them alongside the spec, so the model's own cross-file
attribution stops tripping the filter.

## What was measured

The fix was implemented (`graphify-out/reference_aware_extract.py`, companion
batching) and run over 20 documents in 7 requests, against the same Gemini
backend used for every prior extraction pass in this investigation.

| Measure             | Flat batching | Reference-aware |
| -------------------- | ------------- | ---------------- |
| Target-nodes/doc     | 1.02          | **0.55**          |
| Out-of-scope loss    | 64%           | **16%**           |
| Code nodes rescued   | 0             | **84**            |

The mechanism works exactly as designed. Out-of-scope loss dropped from 64%
to 16%, and 84 concept nodes about companion files
(`scripts/orchestrator_runner.py`, `scripts/state_io.py`,
`scripts/gh_client.py`, and others) survived extraction where every prior
pass had discarded them.

But those rescued nodes attach to the **companion code files**, not to the
specs — consistent with what they were always about. The metric this fix was
meant to move, target-nodes-per-document, went the wrong way: from 1.02 down
to **0.55**. Widening scope to rescue code nodes does not add depth to the
document node; it reallocates it.

## Why: crowding

Doc depth fell because of **crowding**, not a flaw in the scope-widening
mechanism itself:

| Files dispatched | Target-nodes/doc |
| ----------------- | ----------------- |
| 11                 | 1.00               |
| 12                 | 0.67               |
| 13                 | 1.00               |
| 16                 | 0.33               |
| 18                 | **0.00**           |
| 18                 | **0.00**           |
| 19                 | 1.00               |

Two of the seven batches returned zero nodes for their spec documents while
still producing 11 and 17 code nodes each — the model omitted the
documentation targets outright. The response budget per request is roughly
fixed, and code wins the competition against prose, so adding companion files
reallocates capacity away from the document rather than adding to it. (n=7,
and the 19-file batch scoring 1.00 breaks a clean threshold reading — treat
crowding as real and the exact cutoff as unestablished.)

Crowding is a property of the model this was tested on, not of batching in
general: a later head-to-head found Haiku (`claude-cli`) shows no chunk-3
depth tax at all. Everything measured in this record ran on Gemini; do not
carry this crowding budget across a backend change. See
`docs/runbooks/graphify-extraction-findings.md` for the Haiku comparison and
the real-corpus run that superseded this whole line of investigation.

## Why the run is not merged

`build_merge` replaces every `source_file` present in a new extraction, so
merging the reference-aware run would swap 0.55 nodes/doc in for the existing
1.02 nodes/doc — a net deletion of document coverage in exchange for code
nodes that mostly duplicate what those code files' own extraction passes
already produce. The run is quarantined at
`graphify-out/.graphify_gemini_refaware.jsonl.rejected` and was never merged
into the graph.

## Rejected alternatives considered alongside this one

- **Patching the out-of-scope filter.** The filter is correct as designed.
  The nodes it drops name files that get their own extraction pass;
  re-attributing them to the dispatching document would create duplicate
  concepts.
- **Raising the character cap.** Addresses truncation, not scope loss — and
  the node ratio is flat across file sizes, so it would not have moved the
  number this experiment was chasing.

The eventual fix for the underlying low-depth problem was a prompt change
(a `DOCUMENT MODE` instruction appended to the extraction system prompt),
not a batching change — see "The prompt is the ceiling" in
`docs/runbooks/graphify-extraction-findings.md`.

## Related, unrelated fix shipped in the same PR

The PR that closed out this experiment also added `.graphifyignore` at the
repo root, excluding `*.min.js` and `*.min.css` from extraction. That fix is
durable and orthogonal to reference-aware batching: it stops a vendored,
git-tracked minified fixture from being re-extracted as 2,167 noise nodes
every time the repo's `post-commit` hook runs `graphify update`. It has no
bearing on the rejected-approach finding above.

Reference: CCE-146.
