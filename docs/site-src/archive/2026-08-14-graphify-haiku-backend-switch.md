---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/222
synthesized_into: []
doc_kind: decision
---

# graphify semantic extraction: switched to a Haiku backend

The graph's semantic layer runs through `claude-cli` on Haiku now, not Gemini.
The full investigation lives in `docs/runbooks/graphify-extraction-findings.md`
— that file sits outside `docs.lens_paths` by CCE-143 design, so if you only
read lens pages you won't see it land. This page is the pointer: what changed,
what got discharged, and the traps you'll hit if you touch the extraction
config.

## The backend switch discharges "untested at scale"

The runbook's DOCUMENT MODE prompt fix (a system-prompt addition that takes a
spec from 1 node to 6–8) originally carried a caveat: untested against the
full corpus, because Gemini's free tier caps out at 20 requests per day. That
caveat is now discharged. A real `/graphify . --update` run over 81 changed
documents, at chunk size 3, returned:

- **6.37 nodes/doc** (8.32 for prose-only documents)
- **0 of 37 chunks failed**
- **16 minutes** wall clock

The 158 KB CCE-140 plan — a document every prior Gemini pass collapsed to its
own title — produced 82 nodes in this run. The gain from the DOCUMENT MODE
prompt survives multi-file chunks on this backend; it was never a single-file
artifact.

## The old Gemini quota note stays, as history

You'll still find the "Gemini free tier is 20 requests per day" note in the
runbook. It isn't wrong — it's just describing a backend this repo no longer
runs. It's kept rather than deleted because it explains *why* the investigation
took three days: every batching experiment in that document was bounded by
that daily ceiling, and the ceiling is also why reference-aware batching and
the prompt-ceiling A/B were run as single-digit-request experiments instead of
fleet-wide ones. Read it as context for the shape of the investigation, not as
current operational guidance.

## Crowding tax was a Gemini property, not a graphify property

The reference-aware batching experiment found that adding companion code files
to a spec's dispatch degraded that spec's own node yield — two batches at 18
files returned **zero** target-doc nodes. The original writeup treated this as
a general crowding limit of the extraction pipeline.

It isn't. It's Gemini-specific. On an identical 3-file chunk with the identical
DOCUMENT MODE prompt, Haiku returned 6.33 nodes/doc — its own solo depth, no
degradation. Do not carry a Gemini-era crowding budget across the backend
change; if you're tuning chunk size or companion-file counts, re-measure on
whichever backend is actually configured.

## Head-to-head: Gemini vs. Haiku, same chunk, same prompt

| Measure         | Gemini | Haiku (claude-cli) |
| ---------------- | ------ | ------------------- |
| Nodes            | 10     | 19                  |
| Internal edges    | 5      | 30                  |
| Cross-doc edges   | 2      | 3                   |
| Out-of-scope      | 0      | 0                   |
| Wall clock        | ~40s   | 3m14s               |

Haiku is slower per chunk and produces more, and more precise, nodes — its
labels name the actual predicate ("Auto-merge eligibility: partial==false AND
no fact warnings AND no human edits") where Gemini's read like a section
heading ("Merge Eligibility Gate").

## Cost: the earlier estimate was ~10x low

An earlier ~$2.50 full-pass estimate came from Gemini's token accounting, and
that accounting doesn't transfer. `claude -p` carries the entire Claude Code
harness — system prompt, `CLAUDE.md`, MCP tool definitions — in every request,
and `--no-session-persistence` prevents reuse across chunks. Measured over the
81-document / 37-request corpus run: 5,026,334 input tokens and 426,871 output
tokens. Treat the input figure as an upper bound on billable volume — graphify
sums `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`
into that one number, and cache reads bill at a fraction of base input. On a
Claude subscription none of this is billed per token; the number is a
rate-limit draw, and wall clock — not request count — is the scarce resource
now.

## Four operational traps that fail silently

These cost real debugging time during the switch, because none of them raises
or logs when they misfire.

1. **Backend selection is by key presence, not configuration.** There is no
   `backend:` setting. Both the skill and `graphify.llm` choose Gemini whenever
   `GEMINI_API_KEY` or `GOOGLE_API_KEY` is set in the environment. Switching to
   Haiku means removing the key (it's parked under `GEMINI_API_KEY_DISABLED` in
   `~/.zshrc`), and re-exporting either key anywhere silently reverts extraction
   to Gemini with no warning.
2. **`GRAPHIFY_CLAUDE_CLI_PARALLEL` is compared with an exact-match `!= "1"`.**
   `true`, `yes`, and `TRUE` all fall through to sequential execution. That
   turned a 16-minute run into a projected 112-minute one, with nothing logged
   to explain why.
3. **An unset `GRAPHIFY_CLAUDE_CLI_MODEL` runs Opus** — roughly 15x Haiku's
   cost for what is structured-JSON extraction. graphify's own source calls
   Opus overkill for this task, but the fallback is Opus, not Haiku.
4. **A shell that already inherited a Gemini key keeps it.** `zsh -ic`
   inherits the calling environment, so verifying a backend switch from an
   already-running session reports the stale key and reads as "the edit didn't
   work." Check with `env -u GEMINI_API_KEY zsh -ic '...'` instead of a plain
   subshell.

## A debunked fix: don't filter `.stdout.txt`/`.stderr.txt` via `.graphifyignore`

The corpus run warned that 19 of 81 dispatched files produced no nodes — a
23% rate that looks like a real extraction failure. It isn't: 14 of those
files are literally 0 bytes and two more are 28 bytes; this repo carries 36
zero-byte tracked files.

The tempting fix is a pattern-based exclusion — "raw `stdout`/`stderr`
captures are structurally unextractable, filter them via `.graphifyignore`."
The data refutes it: `.prompt.txt`, `.stdout.txt`, and `.stderr.txt` all
appear on **both** sides of the zero/non-zero split. The split tracks file
*size*, not file *type*. A pattern-based exclusion on those extensions would
have deleted roughly 30 real nodes from captures that do carry content. Check
`stat` before treating a zero-node warning as a signal, and don't propose this
filter again — it was tried and the data says no.

## See also

- `docs/runbooks/graphify-extraction-findings.md` — the full investigation:
  the out-of-scope attribution bug, the batching experiments, the DOCUMENT
  MODE prompt fix, and the measurement traps hit while diagnosing all of it.
