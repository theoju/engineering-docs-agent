---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/219
synthesized_into: []
doc_kind: decision
---

# Graphify: Reference-Aware Batching Tried and Rejected (2026-08-13)

## Context

`docs/runbooks/graphify-extraction-findings.md` had already established that spec and plan documents extract at ~1.02 nodes/file, and that `graphify/llm.py:_out_of_scope` — which drops any node whose `source_file` resolves to a real file not dispatched in the same call — was discarding 64% of the model's raw output. The runbook's own next step was to test the obvious fix: dispatch each spec together with the code files it cites, so cross-file attribution lands inside the batch's scope instead of outside it.

This PR runs that experiment and records what it actually does to the graph, rather than what it was expected to do.

## Decision

Reference-aware batching was implemented (`graphify-out/reference_aware_extract.py`) and run over 20 documents in 7 requests. **It works as a mechanism and is rejected as a fix.**

| Measure             | Flat batching | Reference-aware |
| -------------------- | ------------- | ---------------- |
| Target-nodes/doc      | 1.02          | **0.55**          |
| Out-of-scope loss      | 64%           | **16%**           |
| Code nodes rescued     | 0             | **84**            |

The rescue is real: 84 concept nodes about `scripts/orchestrator_runner.py`, `scripts/state_io.py`, `scripts/gh_client.py` and their companions survived, where every prior pass discarded them as out-of-scope. But they attach to those companion code files, not to the specs that cited them — the nodes were always *about* the companions, so widening scope to keep them doesn't add depth to the document node itself.

Doc depth got worse instead of better, and the cause is crowding: the model's response budget per request looks roughly fixed, and code wins the competition against prose. Two batches of 18 files returned **zero** nodes for their own spec documents while still producing 11 and 17 code nodes:

| Files dispatched | Target-nodes/doc |
| ----------------- | ------------------ |
| 11                 | 1.00               |
| 12                 | 0.67               |
| 13                 | 1.00               |
| 16                 | 0.33               |
| 18                 | **0.00**            |
| 18                 | **0.00**            |
| 19                 | 1.00                |

(n=7 — the 19-file batch scoring 1.00 breaks a clean threshold reading, so crowding is treated as real and the exact cutoff as unestablished.)

The run was **not merged**. `build_merge` replaces every `source_file` present in a new extraction, so merging this run would have swapped the existing 1.02 nodes/doc for 0.55 — a net deletion of doc coverage in exchange for code nodes that mostly belonged to the companion files anyway. It is quarantined at `graphify-out/.graphify_gemini_refaware.jsonl.rejected`, renamed off the `*.jsonl` glob so nothing picks it up by accident.

Two alternatives were also considered and rejected at the same time:

| Alternative | Why rejected |
| --- | --- |
| Patch the out-of-scope filter to keep cross-file attributions | The filter is correct behavior in general — the dropped nodes name files that get their own extraction pass, so re-attributing them to the dispatching document would create duplicate concepts. |
| Raise `graphify/llm.py:_FILE_CHAR_CAP` | Addresses truncation, and the doc-node ratio is already flat across file sizes (a 4.4 KB spec and a 120.9 KB plan both yield ~1 node), so it would not move the number that matters. |

The finding this closes out: four separate batching experiments (topup, progress, topoff, batch3) plus this reference-aware pass all agree the ~1-node ceiling doesn't move under any batching change. That pointed at the extraction prompt rather than the batch shape, which a same-day control/treatment test on this repo then confirmed directly — appending a `DOCUMENT MODE` instruction to the extraction prompt took the same file from 1 node to 6–8, at +11% output tokens, with zero code added to the batch.

## Durable fix landed in this PR: `.graphifyignore`

Separately, this PR closes a durability gap in the graph inputs themselves. `tests/fixtures/diagrams/render/mermaid.min.js` is a vendored, minified render fixture kept deliberately and therefore git-tracked — `.gitignore` cannot exclude a tracked file. AST extraction walks every minified symbol in it and emitted 2,167 nodes from that one file alone, 35% of the entire graph, all of it noise that distorted god-node and community analysis.

It had been filtered out by hand on 2026-08-10, then silently came back: the globally-seeded `.git/hooks/post-commit` runs `graphify update` after every commit, is AST-only, and knows nothing about a one-off manual filter applied to the graph output. Any fix applied to the graph rather than to its inputs gets undone by the next commit.

The durable fix is a `.graphifyignore` file at the repo root, gitignore syntax, which per graphify's loader can only ever exclude more than `.gitignore` — never re-include something git already ignores. It excludes `*.min.js` and `*.min.css`. With it in place, detection drops from 819 to 818 files and the graph goes from 6,196 to 4,029 nodes, with 0 dangling links and all 425 semantic nodes preserved.

The general lesson: a build artifact that is tracked defeats every git-status-based filter, so "is it tracked?" is not a sufficient proxy for "is it source?" — and a silent, automatic, cost-free refresh (the post-commit hook) is exactly the kind of process that quietly reverts manual curation. Check for one before concluding a graph regression came from your own last action.

## See also

- `docs/runbooks/graphify-extraction-findings.md`: the full findings log, including the batching table, the prompt-ceiling A/B test, and the subsequent switch to a `claude-cli`/Haiku backend that removed the crowding tax entirely.
- `.graphifyignore`: the durable exclusion this PR adds.
