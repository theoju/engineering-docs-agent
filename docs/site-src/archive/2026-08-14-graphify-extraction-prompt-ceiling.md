---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/221
synthesized_into: []
doc_kind: decision
---

# CCE-146/148: The Graphify Extraction Prompt Is the Node-Yield Ceiling

## Problem

CCE-146 diagnosed graphify's low fleet-wide semantic-extraction yield on spec and plan documents — 1.02 nodes per file, averaged over 58 previously-extracted files — and traced 64% of the loss to `graphify/llm.py:_out_of_scope`, which drops any node whose `source_file` names a real file that was not dispatched in the same batch. That filter explains the loss, but it does not explain the low raw yield underneath it: even before the filter runs, the stock extraction prompt was producing roughly one node per document. Three separate batching experiments (topup, progress, topoff/retry variations) moved that number by less than 0.5 in either direction. CCE-146 left explicitly open whether the extraction system prompt itself — as opposed to the parser, the chunker, or the out-of-scope filter — was the actual ceiling.

## Decision

Run a controlled A/B on `graphify/llm.py:_extraction_system` alone, holding the parser, chunker, and `_out_of_scope` filter fixed. Every backend resolves `_extraction_system` as a module-level global at call time, so reassigning it changes only the prompt text; nothing downstream is touched, which makes the prompt the sole variable under test.

The treatment appends a DOCUMENT MODE instruction to the stock system prompt: treat the dispatched file as a prose design document rather than code, emit one node per distinct concept it introduces (mechanism, invariant, failure mode, decision, rejected alternative, trap) instead of stopping at a single node for the document itself, and — critically — attribute those concept nodes' `source_file` to the document's own path rather than to a code file the document merely mentions.

| Run | File | Prompt | Nodes for doc | Internal edges | Dropped out-of-scope |
| --- | --- | --- | --- | --- | --- |
| control | cce125 spec, 8.1 KB | stock | 1 | 0 | 6 |
| treatment | cce125 spec, 8.1 KB | + DOCUMENT MODE | 6 | 3 | 4 |
| treatment | cce101 spec, 10.9 KB | + DOCUMENT MODE | 8 | 6 | 3 |

The control reproduced the 1.02 fleet baseline exactly on a single file, so this is a genuine A/B rather than a single treated file compared against a fleet average — the point of running the control request at all was to avoid confounding "this prompt is better" with "this file happens to be richer."

Cost was +11% output tokens for roughly 6x the nodes (2,091 → 2,329 output tokens on the cce125 file). The stock prompt was already spending that budget; it was spending it on nodes that `_out_of_scope` then discarded, because the model's default attribution pointed those nodes at the code files the spec was about, not at the spec itself.

## Why this confirms the prompt, not the filter or the batching

`_out_of_scope` drops on `source_file`, and `source_file` is a value the model chooses. A prompt instruction that changes what the model attributes reaches the filter's input directly. Batching, by contrast, only ever reaches the filter's *comparison set* — which files count as "in scope" for a given call — and CCE-146 already showed that widening or narrowing that set moves the doc-yield number by less than 0.5. That asymmetry is why one added paragraph in the system prompt outperformed six requests' worth of reference-aware batching work, and why out-of-scope drops fell (6 → 4, 3) under the treatment instead of rising: the DOCUMENT MODE instruction does not widen scope, it changes what the model claims a node is about.

This result does not reopen CCE-146's rejection of "patch the out-of-scope filter" as a fix — nothing in this test patches the filter. It changes the model's attributions so the unmodified filter keeps the nodes instead of discarding them.

The extracted concepts are substantive, not padding: the seven nodes pulled from the CCE-101 spec were named mechanisms — Auto-merge by Default, Merge Eligibility Gate, Fact-checker Contradiction Block, Host CI Checks Grace Window, GITHUB_TOKEN Recursion Suppression Trap, Explicit Build Workflow Dispatch, and Human-edit Guard — the kind of node you would actually want to traverse to, rather than the document's own section headings.

## Limits of this result

- **n = 2 treatment, 1 control, both specs of similar size.** A 6–8x effect is unlikely to be pure noise, but an earlier topoff batching pass also looked convincing at n=20 (2.45 nodes/file) and did not generalize once retested. Treat 6–8 as "clearly much more than 1," not as a calibrated multiplier.
- **The instruction is recorded in the source-of-truth runbook, not just here**, because the driver script that ran this test lives in gitignored `graphify-out/` and does not survive a clean. `docs/runbooks/graphify-extraction-findings.md` carries the full DOCUMENT MODE prompt text verbatim, the control/treatment table, and the subsequent at-scale validation.
- **At-scale validation happened on a different backend than this test was run on.** This A/B ran on Gemini. The repo has since moved semantic extraction to `claude-cli` on Haiku, and a real corpus `--update` over 81 documents on that backend returned 6.37 nodes/doc (8.32 for prose-only documents) with the same DOCUMENT MODE prompt — confirming the per-file gain survives multi-file batching, and doing so on the backend the repo actually uses now. See the runbook's "The Haiku backend" section for that run and for the crowding effect (a Gemini-only property) it supersedes.

## See also

`docs/runbooks/graphify-extraction-findings.md` is the source of truth for this investigation: the full four-pass batching history that motivated this test, the corrected `_FILE_CHAR_CAP` finding, the rejected reference-aware batching alternative, the Haiku backend migration and its head-to-head numbers against Gemini, and three unrelated measurement traps hit along the way (a `graph.json` `links`-vs-`edges` silent-zero bug, a progress-file `done_files` retry hazard, and a "produced no nodes" warning dominated by zero-byte tracked files rather than genuine extraction failures).
