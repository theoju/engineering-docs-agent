---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/222
synthesized_into: []
doc_kind: decision
---

# Graphify semantic-extraction findings

`graphify` builds this repo's knowledge graph. If you've looked at
`graphify-out/graph.json` and wondered why the document layer is thin — roughly
one node per spec or plan, mostly just the file's own title — this page tells
you why, and what actually fixes it.

The full investigation, with every experiment table and the exact prompt text,
lives in `docs/runbooks/graphify-extraction-findings.md`. This page is the
operational summary: what to know before you touch extraction, not the record
of how it was diagnosed.

## The backend is Haiku, not Gemini

Semantic extraction now runs through `claude-cli` on Haiku against a Claude
subscription. It used to run on Gemini's free tier, capped at 20 requests per
day — that ceiling was the binding constraint on every earlier experiment, and
it no longer applies.

Backend selection is by environment-key **presence**, not by an explicit
setting: extraction chooses Gemini whenever `GEMINI_API_KEY` or
`GOOGLE_API_KEY` is set in the environment. There is no `backend:` config
field to flip. If you need to force Haiku, remove those keys rather than
looking for a setting — re-exporting either one anywhere silently reverts
extraction to Gemini with no warning.

Two more environment traps worth knowing before you run a corpus pass:

- `GRAPHIFY_CLAUDE_CLI_PARALLEL` is compared with an exact string match against
  `"1"`. `true`, `yes`, and `TRUE` all fall through to sequential execution —
  turning a 16-minute run into something over 100 minutes, with nothing logged
  to tell you why it's slow.
- An unset `GRAPHIFY_CLAUDE_CLI_MODEL` runs Opus, roughly 15x Haiku's cost for
  what is structured-JSON extraction.

## The finding: the extraction prompt is the ceiling, not the batching

Four separate batching experiments — different batch sizes, a reference-aware
variant that dispatched each spec alongside the code it cites — moved the
node yield by less than 0.5 nodes/file. None of them touched the real
bottleneck.

The bottleneck is the out-of-scope filter. It drops any node whose
`source_file` resolves to a real file that wasn't dispatched in the same
call. A spec document is about the code it changes, not about itself — so
when the model correctly attributes a node to the code file the spec
describes, the filter throws it away because that code file wasn't in the
same batch. What survives per document is almost always the one node that's
genuinely about the document itself: its title.

Changing the extraction prompt, not the batching, is what moves the number.
Appending a "DOCUMENT MODE" instruction to the system prompt — telling the
model to treat specs and plans as prose design documents, emit one node per
distinct concept, and attribute those concept nodes to the document's own
path rather than to code it merely mentions — took a spec from 1 node to 6–8
in a controlled A/B, at +11% output tokens. On the real corpus (81 changed
documents, `/graphify . --update`, chunk size 3), that held up at **6.37
nodes/doc**, with 0 of 37 chunks failing.

If you're tuning extraction, start with the system prompt's attribution
instructions before you touch batch size or chunking. Batching only ever
reaches the filter's comparison set; a prompt instruction reaches its input
— `source_file` — directly, and that's why the prompt change beat every
batching experiment combined.

## Three things the original runbook got wrong, now corrected

The runbook's earlier drafts made three claims that turned out to be false
and have since been corrected in place:

- It claimed the extraction pipeline's daily-quota-driven character cap
  truncates files before the prompt is built. It doesn't — oversized files
  are sliced into multiple `FileSlice` requests instead, so the model sees
  the whole file, spread across more requests. The correction matters for
  budgeting: a large plan silently costs several times its "one file, one
  request" share of a rate-limited allowance.
- It carried an "untested at scale" caveat on the DOCUMENT MODE prompt fix.
  That's discharged: the 81-document corpus run above is the at-scale
  result, and it confirms the per-file gain survives multi-file chunks on
  the Haiku backend. (It does not survive on Gemini — the crowding tax
  measured in the reference-aware batching experiment is a Gemini-specific
  property, not a property of the fix itself.)
- An earlier estimate put a full corpus pass at roughly $2.50. That was
  **~10x low**. It was derived from Gemini's token accounting, which doesn't
  transfer to the Haiku backend: `claude -p` carries the entire Claude Code
  harness — system prompt, `CLAUDE.md`, MCP tool definitions — in every
  request, and disabled session persistence prevents reuse across chunks.
  The 81-document run measured 5,026,334 input / 426,871 output tokens
  across 37 requests. On a Claude subscription none of that is billed per
  token, so treat the figure as the size of the rate-limit draw rather than
  a dollar cost — wall clock, not requests, is the scarce resource now.

## When you touch extraction

Two operational pitfalls are worth carrying forward:

- **Vendored, tracked, minified files distort the graph.** A git-tracked
  minified bundle can't be excluded by `.gitignore`; only `.graphifyignore`
  (loaded with gitignore syntax) is respected by the extraction pipeline and
  survives a repo-wide `graphify update`. If a single file's AST node count
  looks disproportionate, check whether it's a tracked build artifact before
  assuming the graph is wrong.
- **A zero-node batch isn't automatically a failure.** A meaningful fraction
  of "produced no nodes" warnings on a real corpus run come from genuinely
  empty or near-empty tracked files, not from extraction failures. Check file
  size before treating a zero-node warning as a signal to fix.

For the experiment-by-experiment detail — batching tables, the full DOCUMENT
MODE prompt text, cost figures, and the measurement traps hit along the way —
see `docs/runbooks/graphify-extraction-findings.md`.
