---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/222
synthesized_into: []
doc_kind: decision
---

# graphify extraction backend switch: Gemini → Haiku

Semantic extraction for this repo's knowledge graph moved from the Gemini
backend to `claude-cli` on Haiku. The full findings — head-to-head numbers,
corpus run, and the operational traps that go with the switch — live in
`docs/runbooks/graphify-extraction-findings.md`, which is intentionally kept
outside the lens system to avoid citation-lint churn on a fast-moving
investigation doc. This page is a pointer and decision digest for readers
browsing lens docs rather than the runbook directly.

## What changed

Three claims in the runbook had gone false once the backend switched, and PR
#222 corrected them in place rather than leaving them to mislead the next
reader:

- **"Untested at scale" is discharged.** A real `--update` run over 81
  documents on Haiku returned 6.37 nodes/doc at chunk 3. The runbook's earlier
  caveat — that the per-file gain from the DOCUMENT MODE prompt might not
  survive multi-file chunks — is answered: it does.
- **The 20-requests/day quota is now historical, not deleted.** That number
  was Gemini's free-tier ceiling (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`)
  and was the binding constraint on every experiment in the runbook — it is
  why the investigation took three days. It no longer applies on a Claude
  subscription, but the runbook keeps the number rather than erasing it,
  labeled as Gemini-only history.
- **Crowding is reclassified as a Gemini property, not a batching property.**
  The reference-aware batching section had shown doc-node depth degrading as
  more companion files were added to a chunk. Haiku shows no such tax at
  chunk 3 — it holds its own solo depth (6.33 nodes/doc). Don't carry a
  crowding budget across the backend change.

## New content added

- A **head-to-head section** comparing Gemini and Haiku on an identical
  3-file chunk with the identical DOCUMENT MODE prompt: node count, internal
  edges, cross-doc edges, and wall clock. Haiku produces roughly double the
  nodes and more precise labels, at longer wall clock (3m14s vs ~40s).
- **Four operational traps** that fail silently when switching backends:
  backend selection by API-key *presence* rather than explicit config,
  `GRAPHIFY_CLAUDE_CLI_PARALLEL` being compared with an exact `!= "1"` match
  (so `true`/`yes`/`TRUE` fall through to sequential execution with nothing
  logged), an unset model variable defaulting to Opus (~15x Haiku's cost for
  a structured-JSON task), and a shell that inherited a stale Gemini key
  continuing to use it even after the key is unset elsewhere.
- A **corrected cost estimate**. An earlier ~$2.50 full-pass estimate was
  ~10x low — it was derived from Gemini's token accounting, which doesn't
  transfer because `claude -p` carries the full Claude Code harness (system
  prompt, CLAUDE.md, MCP tool definitions) in every request. The corrected
  figures, measured over 81 docs / 37 requests, are 5,026,334 input and
  426,871 output tokens. On a Claude subscription this isn't billed per
  token; the number represents rate-limit draw, not cost.

## The rejected `.graphifyignore` fix

A separate finding, not backend-related: 19 of 81 dispatched files produced
no nodes in the corpus run, which read as a 23% failure rate. The tempting
fix — exclude raw `stdout`/`stderr` captures via `.graphifyignore` on the
theory that they're structurally unextractable — is wrong. 14 of the 19
files are literally 0 bytes and two more are 28 bytes; `.prompt.txt`,
`.stdout.txt`, and `.stderr.txt` all appear on both sides of the zero/non-zero
split. The variable is file **size**, not file **type**, and a pattern-based
exclusion would have deleted real nodes from non-empty captures. The runbook
documents this explicitly so the fix isn't attempted again.

There's a residual, unexplained inconsistency in the same data: six other
0-byte `.stderr.txt` files each produced exactly one node in the same run —
identical input, both outcomes. The runbook records this as unresolved rather
than papering over it; it's a reason not to build a filter on top of the
"produced no nodes" warning at all.
