---
status: draft
doc_kind: decision
sources:
- https://github.com/theoju/engineering-docs-agent/pull/221
synthesized_into: []
---

# CCE-148: The Extraction Prompt, Not Batching, Was Graphify's Doc-Layer Ceiling

## Problem

Four prior extraction passes over `docs/superpowers/{specs,plans}` all landed
in the same place: roughly 1 semantic node per document, flat regardless of
file size or batch size. CCE-146's reference-aware batching experiment
rescued 84 code-attributed nodes but made per-document depth measurably
*worse* (1.02 → 0.55 target-nodes/doc) and closed by naming the prompt itself
as the untested suspect — three batching changes had already moved the ratio
by less than 0.5, which is consistent with a ceiling that batching cannot
reach.

CCE-148 tested that hypothesis directly instead of carrying it forward as
another guess.

## Method

The test runs a single file through graphify's **shared library path** — the
same parser, the same chunker, and the same `graphify/llm.py:_out_of_scope`
filter used by every prior pass — and varies only the extraction system
prompt, `graphify/llm.py:_extraction_system`. Every backend resolves that name
as a module-level global at call time, so reassigning it changes the prompt
without touching anything downstream. Holding the rest of the path fixed
means any change in output is attributable to the prompt, not to a
confounding pipeline difference.

The control run reproduced the ~1.02 nodes/file fleet baseline exactly on a
single file, which is what makes this an A/B rather than a comparison against
a fleet average — comparing one file's treatment directly against a 58-file
average would have confounded "this prompt is better" with "this file is
richer."

## Result: the prompt is the ceiling

| Run | File | Prompt | Nodes for doc | Internal edges | Dropped out-of-scope |
| --- | --- | --- | --- | --- | --- |
| control | cce125 spec, 8.1 KB | stock | **1** | 0 | 6 |
| treatment | cce125 spec, 8.1 KB | + DOCUMENT MODE | **6** | 3 | 4 |
| treatment | cce101 spec, 10.9 KB | + DOCUMENT MODE | **8** | 6 | 3 |

Swapping the stock prompt for a DOCUMENT MODE instruction — appended to the
stock prompt so the node-ID grammar, the `<untrusted_source>` guardrails, and
the output schema all stay in force — raised nodes produced per document from
1 to 6–8. Out-of-scope drops *fell* (6 → 4, 3) rather than rising: the
opposite of what CCE-146's reference-aware batching did, which rescued nodes
by widening the in-scope comparison set and paid for it in crowding.

The load-bearing part of the instruction is the attribution clause, not the
"emit more nodes" clause. `_out_of_scope` drops nodes based on `source_file`,
and `source_file` is a field the model itself chooses — so a prompt
instruction reaches the filter's input directly, while batching only ever
reaches its comparison set. That asymmetry is why one added paragraph beat
six requests' worth of batching work.

This does not reopen "patching the out-of-scope filter," which CCE-146
rejected and CCE-148 leaves rejected: nothing here patches the filter. It
changes what the model attributes, so the unmodified filter simply keeps the
nodes it would otherwise have discarded. Cost was +11% output tokens for 6x
the nodes on the cce125 file (2,091 → 2,329 tokens) — the stock prompt was
already spending that budget, just on nodes `_out_of_scope` then threw away.

### Limits of this result

The sample is small: n = 2 treatment runs, 1 control, both specs of similar
size. The effect (6x, 8x) is large enough that it's unlikely to be noise, but
an earlier batching pass (`topoff`, 2.45 nodes/file at n=20) also looked
convincing before it failed to reproduce at scale. Treat 6–8 as "clearly much
more than 1," not as a calibrated per-document expectation.

A third run, on the 123.8 KB CCE-80 plan, was discarded as a data point
rather than folded into the table above: oversized-file slicing (see below)
turned it into 7 requests, 5 of which hit the daily quota, so its 15 nodes
reflect partial coverage under different conditions than the single-chunk
runs.

## Secondary finding: `_FILE_CHAR_CAP` slices, it doesn't truncate

A separate check made while diagnosing the ceiling corrected an earlier claim
in the runbook: `graphify/llm.py:_FILE_CHAR_CAP` (20,000 characters) is a
*slice width*, not a truncation cap. The prior text said the model saw only a
prefix of any oversized file. That's wrong: `graphify/llm.py:expand_oversized_files`
replaces each oversized splittable-text file with N `FileSlice` objects before
chunking, so the model sees all of the file's content — spread across N
requests. A 123.8 KB plan expands to 7 slices and costs 7 requests, not 1,
even at `chunk_size=1`.

The correction doesn't change the node-ratio finding above — the ratio was
already flat across file sizes — but it matters for request budgeting: a
large plan silently costs roughly 7x its apparent share of any daily request
allowance.

## Source of truth

The full methodology, the complete measurement history this test closes out
(including the rejected reference-aware batching run and the topoff/topup/
progress/retry passes it's compared against), and the DOCUMENT MODE prompt
text in full live in `docs/runbooks/graphify-extraction-findings.md`. That
runbook sits outside this docs lens by design — it documents an internal
tuning investigation into the graphify tool itself, not this repo's shipped
behavior — so this page exists to make the CCE-148 conclusion discoverable
from the published site.

Reference: CCE-148 (2026-08-14).
