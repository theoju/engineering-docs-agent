---
title: Graphify extraction findings — the prompt is the ceiling
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/221
synthesized_into: []
doc_kind: decision
---

# Graphify extraction findings: the prompt is the ceiling

CCE-146 left one question open after reference-aware batching turned out to be
a net loss for document-layer node yield (1.02 → 0.55 nodes/doc): would a
prompt change, rather than a batching change, move the ~1-node-per-document
ceiling that graphify's semantic extraction hits on spec and plan files? CCE-148
tested it with a controlled A/B run and answered yes.

Full experimental detail — including the retained DOCUMENT MODE prompt text,
which lives only in this record because its driver sits in the gitignored
`graphify-out/` build directory — is in `docs/runbooks/graphify-extraction-findings.md`.
This page is the decision summary.

## The A/B test

One file went through the same library path twice — same parser, same
chunker, same out-of-scope filter — varying only the extraction system
prompt. A control run used the stock prompt; two treatment runs added a
DOCUMENT MODE instruction telling the model to emit one node per concept
(mechanism, invariant, decision, rejected alternative, trap) rather than
stopping at a single node for the document as a whole.

| Run       | File               | Prompt          | Nodes for doc |
| --------- | ------------------ | ---------------- | -------------- |
| control   | 8.1 KB spec        | stock            | 1              |
| treatment | 8.1 KB spec        | + DOCUMENT MODE  | 6              |
| treatment | 10.9 KB spec       | + DOCUMENT MODE  | 8              |

The control reproduced the fleet-wide 1.02 nodes/doc baseline on a single
file, so the comparison is a real A/B rather than one file's treatment
measured against a different fleet's average. Cost was +11% output tokens for
6x the nodes — the stock prompt was already spending that budget, just on
nodes the out-of-scope filter then discarded.

**Why a prompt change works where batching didn't:** the out-of-scope filter
drops a node based on `source_file`, a field the model itself chooses. A
prompt instruction reaches that field directly. Reference-aware batching could
only ever widen the set of files the filter compares against — it never
touched what the model attributes a node to, so it traded doc-layer depth for
rescued code nodes instead of fixing the ceiling.

## Scope

This confirms the prompt is the lever. It does not yet tell us the effect
survives at scale: n=2 treatment / n=1 control, both similarly-sized specs.
Applying the DOCUMENT MODE prompt across the corpus is explicitly out of
scope for now, pending free-tier request quota — a third run, on a 123.8 KB
plan, hit daily rate limits mid-run and is recorded as discarded rather than
as a data point.

## Correction to a published claim

An earlier changelog entry (What's New, PR #216) described `_FILE_CHAR_CAP`
as truncating oversized files before the extraction prompt is built, and
estimated the model saw only a fraction of certain large corpora as a result.
That's wrong. Oversized files are sliced into multiple full-content requests
rather than truncated, so the model sees all of the text — spread across more
requests. The correction matters for daily-quota budgeting, not for the node
ratio: a large file costs more requests than its file count suggests, not
less content per request.

The same entry also described reference-aware batching as an untried
candidate fix. CCE-146 tried it and rejected it before this test ran; see the
runbook for the batching results.
