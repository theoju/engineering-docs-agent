# graphify semantic-extraction findings

Why the document layer of this repo's knowledge graph is ~1 node per file, what
was tried, and what actually fixes it. Recorded 2026-08-12 after four extraction
passes over `docs/superpowers/{specs,plans}`; updated 2026-08-13 once the cause
was isolated.

**Answer, for anyone who reads only this far: the extraction prompt is the
ceiling, not the batching.** A document-genre instruction takes a spec from 1
node to 6–8. Three batching experiments moved the number by less than 0.5. See
"The prompt is the ceiling" below.

**Second answer, added 2026-08-13: the backend is now `claude-cli` on Haiku, not
Gemini.** A real corpus run then delivered **6.37 nodes/doc over 81 documents**,
so this document's original "untested at scale" caveat is discharged. Anything
below framed around Gemini's 20-requests-per-day ceiling describes a backend this
repo no longer uses — see "The Haiku backend" for what replaced it, and for which
of the findings below turned out to be Gemini-specific rather than universal.

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
| refaware | 3+cit | 20    | 0.55           | not merged | —           |
| control  | 1     | 1     | 1.00           | not merged | 0.00        |
| DOC MODE | 1     | 2     | **7.00**       | not merged | 1.29        |

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

- **`graphify/llm.py:_FILE_CHAR_CAP`** is 20,000 characters, and it is a _slice
  width_, not a truncation cap. This entry originally said the cap "truncates
  every file before the prompt is built" and that the model therefore saw only
  59% of the 1.42 MB corpus and 16% of the 120.9 KB CCE-80 plan. **That is
  wrong.** `graphify/llm.py:expand_oversized_files` replaces each oversized
  splittable-text file with N `FileSlice` objects before chunking, so the model
  sees all of it — spread across N requests. The 123.8 KB CCE-80 plan expands to
  7 slices and therefore costs 7 requests, not 1, even at `chunk_size=1`.

  The correction matters for budgeting, not for the node ratio: it explains the
  daily-quota burn rate far better than file count does, and it means a large
  plan silently costs ~7x its share of a 20-request allowance. The original
  claim came from reading the constant at its definition site without reading
  its caller — `_FILE_CHAR_CAP` genuinely looks like a truncation cap there.

- **(Historical — Gemini only; the repo now runs `claude-cli`/Haiku.)** **The
  Gemini free tier is 20 requests per _day_**, not per minute:
  `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: 20`,
  model `gemini-3-flash`. Re-extracting all 58 files at batch 3 costs ~20
  requests — the entire daily allowance. Iterating on extraction quality more
  than once a day requires leaving the free tier. An earlier session misread
  this as a per-minute ceiling and built a 7-second inter-batch sleep around it;
  the sleep is harmless but addresses the wrong limit.
- **`graphify/llm.py:extract_corpus_parallel` writes the semantic cache but
  never reads it.** Re-runs always hit the API. There is no cache-replay risk,
  and no cache-replay saving.

## Reference-aware batching: tried 2026-08-13, rejected

The fix this document originally proposed — dispatch each spec together with the
code files it cites, so cross-file attribution lands in scope — was implemented
(`graphify-out/reference_aware_extract.py`) and run over 20 documents in 7
requests. **It works as a mechanism and fails as a fix.**

| Measure            | Flat batching | Reference-aware |
| ------------------ | ------------- | --------------- |
| Target-nodes/doc   | 1.02          | **0.55**        |
| Out-of-scope loss  | 64%           | **16%**         |
| Code nodes rescued | 0             | **84**          |

The rescue is real: 84 concept nodes about `scripts/orchestrator_runner.py`,
`scripts/state_io.py`, `scripts/gh_client.py` and friends survived, where every
prior pass discarded them. They attach to the **companions**, though, not to the
specs — which is consistent, since those nodes were always _about_ the
companions.

Doc depth got worse, and the reason is **crowding**:

| Files dispatched | Target-nodes/doc |
| ---------------- | ---------------- |
| 11               | 1.00             |
| 12               | 0.67             |
| 13               | 1.00             |
| 16               | 0.33             |
| 18               | **0.00**         |
| 18               | **0.00**         |
| 19               | 1.00             |

Two batches returned **zero** nodes for their spec documents while producing 11
and 17 code nodes; the model omitted the targets outright. The response budget
per request looks roughly fixed, and code wins the competition against prose, so
adding companions reallocates capacity rather than adding it. (n=7, and the
19-file batch scoring 1.00 breaks a clean threshold reading — treat crowding as
real and the exact cutoff as unestablished.)

> **Crowding is a property of the model, not of batching.** Everything in this
> section was measured on Gemini. Haiku shows no chunk-3 depth tax at all — see
> "The Haiku backend". Do not carry a crowding budget across a backend change.

**Do not merge that run.** `build_merge` replaces every `source_file` present in
the new extraction, so merging would swap 0.55/doc in for the existing 1.02/doc
— a net deletion of doc coverage in exchange for code nodes. The run is
quarantined at `graphify-out/.graphify_gemini_refaware.jsonl.rejected`.

The correction this forces: rescuing a node and improving the metric it was
rescued _for_ are different claims, and the original text let the first imply
the second. Four passes now agree that a spec yields ~1 node about itself and
that the number does not move under any batching change — which points at the
extraction prompt, not the batching, as the ceiling. **That was tested on
2026-08-13 and confirmed; see the next section.**

Rejected alternatives:

- _Patching the out-of-scope filter._ The filter is correct. The dropped nodes
  name files that get their own extraction, so re-attributing them to the
  dispatching document creates duplicate concepts.
- _Raising the character cap._ Addresses truncation only, and the ratio is flat
  across file sizes, so it would not move the main number.

## The prompt is the ceiling: tested 2026-08-13, confirmed

Four passes agreed the ratio does not move under any batching change. It moves
under a prompt change, by 6-8x.

The test runs one file through the **same library path** — same parser, same
chunker, same `graphify/llm.py:_out_of_scope` filter — varying only
`graphify/llm.py:_extraction_system`. Every backend resolves that name as a
module-level global at call time, so reassigning it changes the prompt without
touching anything downstream. Only the prompt varies, so the difference is
attributable to the prompt.

| Run       | File                | Prompt          | Nodes for doc | Internal edges | Dropped out-of-scope |
| --------- | ------------------- | --------------- | ------------- | -------------- | -------------------- |
| control   | cce125 spec 8.1 KB  | stock           | **1**         | 0              | 6                    |
| treatment | cce125 spec 8.1 KB  | + DOCUMENT MODE | **6**         | 3              | 4                    |
| treatment | cce101 spec 10.9 KB | + DOCUMENT MODE | **8**         | 6              | 3                    |

The control reproduced the 1.02 fleet baseline exactly on a single file, so this
is an A/B and not a comparison against a fleet average. That distinction is the
reason the control was worth a request: comparing one file's treatment against a
58-file average would confound "this prompt is better" with "this file is
richer."

**The attribution clause is the load-bearing part, not the "emit more nodes"
clause.** `_out_of_scope` drops on `source_file`, and `source_file` is a field
the _model chooses_ — so a prompt instruction reaches the filter's input
directly, while batching only ever reaches its comparison set. That asymmetry is
why one added paragraph beat six requests' worth of batching work. Out-of-scope
drops _fell_ (6 → 4, 3) rather than rising: the opposite of reference-aware
batching, which rescued nodes by widening the scope and paid in crowding.

This does not contradict "patching the out-of-scope filter is rejected" above.
Nothing here patches the filter. It changes what the model attributes, so the
unmodified filter keeps the nodes.

The nodes are real concepts, not padding. The seven concepts extracted from the
CCE-101 spec were Auto-merge by Default, Merge Eligibility Gate, Fact-checker
Contradiction Block, Host CI Checks Grace Window, GITHUB_TOKEN Recursion
Suppression Trap, Explicit Build Workflow Dispatch, and Human-edit Guard —
the spec's named mechanisms, which is what you would want to traverse to, rather
than its section headings.

Cost was **+11% output tokens for 6x the nodes** (2,091 → 2,329 on cce125). The
stock prompt was already spending that budget; it was spending it on nodes that
`_out_of_scope` then discarded.

### The instruction

Appended to the stock system prompt, so the node-ID grammar, the
`<untrusted_source>` guardrails, and the output schema all stay in force. It is
recorded here in full because the driver lives in gitignored `graphify-out/` and
will not survive a clean — the same failure mode that made this runbook
necessary.

```text
DOCUMENT MODE: the source files below are prose design documents (specs, plans,
runbooks), not code. Do not stop at a single node for the document itself.

Emit one node per distinct CONCEPT the document introduces or decides: each named
mechanism, invariant, failure mode, decision, rejected alternative, and trap. A
document with N sections should typically yield several nodes.

Attribution: set `source_file` on these concept nodes to the DOCUMENT's own path
-- the file the concept is described in -- never to a code file the document
merely mentions. Node IDs still follow {stem}_{entity} using the document's path
stem. Use file_type "concept" for the concept nodes and "document" for the node
representing the document as a whole.

Connect the concept nodes to the document node and to each other with edges
(references, conceptually_related_to), so the document does not land isolated.
```

### Limits of this result

- **n = 2 treatment, 1 control, both specs of similar size.** The effect is large
  enough (6x, 8x) that it is unlikely to be noise, but topoff's 2.45 reading also
  looked convincing at n=20 and did not generalize. Treat 6-8 as "clearly much
  more than 1," not as a calibrated expectation.
- **A third run, on the 123.8 KB CCE-80 plan, is discarded — not a data point.**
  Oversized files slice (see Secondary limits), so `chunk_size=1` became 7
  requests; 5 hit the daily 429 and only 2 slices returned. Its 15 nodes are a
  floor from partial coverage, measured under different conditions than the
  single-chunk runs. It is recorded here so the number is not mistaken for a
  comparable result later.
- ~~**Untested at scale.**~~ **Discharged 2026-08-13.** This read: "applying
  this to the full corpus costs the entire 20-request/day free-tier allowance
  across several days… whether the per-file gain survives multi-file chunks is
  unanswered." Both halves are now answered. On `claude-cli`/Haiku the free-tier
  ceiling does not apply, and a real `--update` over 81 documents returned
  **6.37 nodes/doc** at chunk 3 — the gain survives multi-file chunks on this
  backend. See "The Haiku backend".

## The Haiku backend: switched 2026-08-13

The repo now routes semantic extraction through `claude-cli` on Haiku against a
Claude subscription. Gemini's 20-requests-per-day ceiling was the binding
constraint on every experiment above — it is why this investigation took three
days — and it no longer applies.

### Head-to-head, identical 3-file chunk, identical DOCUMENT MODE prompt

| Measure         | Gemini | Haiku (claude-cli) |
| --------------- | ------ | ------------------ |
| Nodes           | 10     | **19**             |
| Internal edges  | 5      | **30**             |
| Cross-doc edges | 2      | **3**              |
| Out-of-scope    | 0      | 0                  |
| Wall clock      | ~40s   | 3m14s              |

Haiku's labels are also more precise: "Auto-merge eligibility: partial==false AND
no fact warnings AND no human edits" against Gemini's "Merge Eligibility Gate".
The first is the actual predicate; the second is a section heading.

**No crowding tax.** Haiku returned 6.33 nodes/doc at chunk 3 — its own solo
depth. The chunk-3 degradation documented in the reference-aware section is a
Gemini property and does not transfer.

### The real corpus run

`/graphify . --update` over 81 changed documents, chunk 3, concurrency 4:

| Measure               | Result              |
| --------------------- | ------------------- |
| Nodes/doc             | **6.37**            |
| Nodes/doc, prose only | **8.32**            |
| Failed chunks         | **0 of 37**         |
| Wall clock            | 16 min              |
| Graph                 | 4,011 → 4,446 nodes |

The 158 KB CCE-140 plan produced **82 nodes** where every prior pass collapsed it
to its title.

### Cost, and a correction

An earlier estimate of ~$2.50 for a full pass was **~10x low**. It was derived
from Gemini's token accounting, which does not transfer: `claude -p` carries the
entire Claude Code harness — system prompt, CLAUDE.md, MCP tool definitions — in
every request, and `--no-session-persistence` prevents reuse across chunks.

Measured over 81 docs / 37 requests: **5,026,334 input / 426,871 output tokens**.
Treat the input figure as an upper bound on billable volume — graphify sums
`input_tokens + cache_read_input_tokens + cache_creation_input_tokens` into that
one number, and cache reads bill at a fraction of base input.

On a Claude subscription none of this is billed per token; the figure is the size
of the rate-limit draw. Wall clock, not requests, is now the scarce resource.

### Operational traps

- **Backend selection is by key _presence_, not configuration.** There is no
  `backend:` setting. Both the skill and `graphify.llm` choose Gemini whenever
  `GEMINI_API_KEY` or `GOOGLE_API_KEY` is set, so switching means removing the key
  from the environment (it is preserved under `GEMINI_API_KEY_DISABLED` in
  `~/.zshrc`). Re-exporting one anywhere silently reverts extraction to Gemini
  with no warning.
- **`GRAPHIFY_CLAUDE_CLI_PARALLEL` is compared with `!= "1"`** — an exact string
  match. `true`, `yes`, and `TRUE` all fall through to sequential execution, which
  turned a 16-minute run into a projected 112-minute one with nothing logged.
- **An unset `GRAPHIFY_CLAUDE_CLI_MODEL` runs Opus**, roughly 15x Haiku's cost for
  what is structured-JSON extraction. graphify's own source calls Opus "overkill"
  for this task.
- **A shell that inherited a Gemini key keeps it.** `zsh -ic` inherits the calling
  environment, so verifying the switch from an already-running session reports the
  old value and reads as "the edit didn't work". Check with
  `env -u GEMINI_API_KEY zsh -ic '...'`.

## Three measurement traps hit while diagnosing this

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
3. **The "produced no nodes" warning is dominated by empty files.** The corpus
   run warned that 19 of 81 dispatched files produced nothing, which reads as a
   23% failure rate. It is not: **14 of those files are literally 0 bytes** and
   two more are 28 bytes. This repo carries 36 zero-byte tracked files. Check
   `stat` before treating that warning as a signal.

   This one is worth recording because it nearly produced a wrong fix. The
   obvious reading — "raw `stdout`/`stderr` captures are structurally
   unextractable, exclude them via `.graphifyignore`" — is refuted by the data:
   `.prompt.txt`, `.stdout.txt`, and `.stderr.txt` all appear on **both** sides
   of the zero/non-zero split. The split tracks file _size_, not file _type_, and
   a pattern-based exclusion would have deleted ~30 real nodes from captures that
   do carry content. A plausible category ("log files") explained the symptom;
   the actual variable was orthogonal to it.

   The residual genuine oddity: six _other_ 0-byte `.stderr.txt` files each
   produced exactly 1 node in the same run. Identical input, both outcomes. So
   the warning is not merely noisy, it is inconsistent — which is another reason
   not to build a filter on top of it.

## One minified fixture was 35% of the graph, and it kept coming back

`tests/fixtures/diagrams/render/mermaid.min.js` is a vendored, minified bundle
kept deliberately as a render fixture. It is therefore **git-tracked**, so
`.gitignore` cannot exclude it. AST extraction walks every minified symbol and
emits **2,167 nodes** from that one file — 35% of the whole graph, all of it
noise that distorts god-node and community analysis.

It was filtered out by hand on 2026-08-10 and silently came back, because the
globally-seeded `.git/hooks/post-commit` runs `graphify update` after every
commit. That hook is AST-only and costs nothing, which is why it goes unnoticed:
it re-extracts from a clean detect and knows nothing about a one-off manual
filter. Any fix applied to the graph rather than to the _inputs_ is undone by
the next commit.

The durable fix is `.graphifyignore` at the repo root (gitignore syntax;
graphify's loader guarantees it can only ever exclude more, never re-include).
With `*.min.js` / `*.min.css` excluded, detection drops from 819 to 818 files
and the graph goes 6,196 -> 4,029 nodes with 0 dangling links and all 425
semantic nodes preserved.

Two general lessons. A build artifact that is _tracked_ defeats every
git-status-based filter, so "is it tracked?" is not a sufficient proxy for "is
it source?". And a silent, free, automatic refresh is exactly the kind of
process that quietly reverts manual curation — check for one before concluding
that a graph regression came from your own last action.

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

Two experiment drivers sit beside it: `graphify-out/reference_aware_extract.py`
(companion batching, rejected) and `graphify-out/prompt_ceiling_test.py` (the
control/treatment A/B above). All three live in a gitignored directory and do
not survive a clean, which is why their _results_ and the DOCUMENT MODE prompt
text are reproduced in this file rather than referenced from it.
