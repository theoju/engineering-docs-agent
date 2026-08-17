---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/222
synthesized_into: []
doc_kind: decision
---

# Graphify Extraction Findings: Corrected for the Haiku Backend (2026-08-13)

**PR:** #222

PR #222 updates `docs/runbooks/graphify-extraction-findings.md` to reflect graphify's semantic-extraction backend switch from Gemini to Haiku (`claude-cli`), correcting three claims in that runbook that had gone stale once the switch happened. CCE-149 tracks the correction; CCE-143 is the earlier decision that put the runbook under `docs/runbooks/` so it survives a directory rebuild.

## What was stale

Three claims in the original runbook were written against the Gemini backend and no longer held once extraction moved to Haiku:

- **"Untested at scale."** The runbook's original caveat said the DOCUMENT MODE prompt fix — the change that took a spec from 1 extracted node to several — was unverified beyond a small file-level A/B test. A real `--update` run over 81 documents on the Haiku backend discharges that caveat: **6.37 nodes/doc**, 0 of 37 chunks failed, 16 minutes wall clock, and the graph grew from 4,011 to 4,446 nodes.
- **The 20-requests-per-day framing.** Gemini's free-tier daily quota shaped nearly every experiment in the runbook — it's the reason the original investigation took three days. That constraint doesn't apply on Haiku via a Claude subscription, so the runbook now marks the framing historical rather than deleting it: the quota is still the reason the earlier experiments were run the way they were, it just no longer bounds extraction going forward.
- **Chunk-3 crowding.** The runbook had found that batching a spec together with the code files it cites ("reference-aware batching") degraded doc depth as more files were added to a chunk — a "crowding" effect attributed to a fixed response-token budget. That effect was measured entirely on Gemini. Haiku shows no chunk-3 depth tax: 6.33 nodes/doc at chunk 3, matching its own solo depth. Crowding is now documented as a Gemini-specific property, not an inherent cost of batching.

## The Haiku backend, head-to-head

The runbook adds a new section comparing the two backends on an identical 3-file chunk with the identical DOCUMENT MODE prompt:

| Measure         | Gemini | Haiku (`claude-cli`) |
| --------------- | ------ | --------------------- |
| Nodes           | 10     | 19                     |
| Internal edges  | 5      | 30                     |
| Cross-doc edges | 2      | 3                      |
| Out-of-scope    | 0      | 0                      |
| Wall clock      | ~40s   | 3m14s                  |

Haiku produces roughly double the nodes and six times the internal edges on the same input, at the cost of wall clock rather than rate limit — on a Claude subscription, extraction isn't billed per token, so wall clock is now the scarce resource, not requests-per-day.

The 81-document corpus run is the runbook's evidence that the DOCUMENT MODE fix holds at fleet scale on the new backend, not just on individual files: the 158 KB CCE-140 plan alone produced 82 nodes in that run, where every prior Gemini-era pass had collapsed it to its own title.

## Where the detail lives

The full corrected findings — the pass-by-pass batching table, the out-of-scope filter mechanics, the operational traps around backend selection (Gemini is chosen whenever `GEMINI_API_KEY` or `GOOGLE_API_KEY` is set — there is no `backend:` config field), and the measurement traps hit along the way — live in `docs/runbooks/graphify-extraction-findings.md`. That file sits outside the core lens deliberately (CCE-143): its code references point into the external graphify library, not into this repo, so it stays out of Tier-1 citation lint scope. This page is a pointer and summary, not a duplicate.
