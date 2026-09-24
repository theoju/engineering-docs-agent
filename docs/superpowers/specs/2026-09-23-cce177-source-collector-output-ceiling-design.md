# CCE-177 — source-collector output ceiling: detect the split, bound the cause

**Status:** approved
**Date:** 2026-09-23
**Ticket:** CCE-177
**Supersedes hypothesis:** "prose contamination" (falsified — see Root cause)

## Problem

Three of the last eight `docs-agent-nightly` runs on `theoju/engineering-docs-agent`
failed identically:

```
docs-agent PARTIAL: prose_contamination_rescued: source-collector
docs-agent PARTIAL: schema_invalid: source-collector: 'prs' is a required property
docs-agent INFO:    auto_merge_skipped: blind_run
```

Failing runs `35862057776` (09-23), `35509910089` (09-20), `35343242932` (09-18).
Each exits non-zero and freezes the watermark (CCE-144 classifies a source-collector
`schema_invalid` as **blind**).

## Root cause

Measured, reproduced end-to-end against the archived production payloads, and
verified against the shipped code on `main`:

```
source-collector emits ~160KB of valid JSON
  -> Claude CLI hits maxOutputTokens (64,000) MID-OBJECT
  -> CLI injects a synthetic user turn: "Output token limit hit. Resume directly..."
  -> the model finishes the JSON in a SECOND assistant message
  -> _extract_final_assistant_text keeps ONLY the last message  <-- the defect
  -> the tail fragment starts mid-string; strict json.loads fails
  -> _rescue_json_object returns the first balanced {...} in the tail,
     which is a single jira_issues[] element -> no `prs` key
  -> schema_invalid -> CCE-144 blind -> exit 1, watermark frozen
```

`_extract_final_assistant_text` (`scripts/orchestrator_runner.py`) loops every
assistant event and **overwrites** `last_assistant_with_text` each time. On a split
answer the 159,475-char first half — the half containing `{"prs": [` — is discarded.

**The agent's answer was correct on all three nights.** Concatenating the two
assistant turns yields valid JSON with the full PR and Jira payload. The
orchestrator threw away a good answer.

### What this is NOT

| Ruled out              | Evidence                                                                                                                                                                                                           |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Prose contamination    | No prose, no fence, no preamble. The JSON was well-formed — just split.                                                                                                                                            |
| A rescue-path bug      | `prose_contamination_rescued` fires in **7/7** runs including every success (page-author, fact-checker, content-validator). Only the agent-qualified `: source-collector` form is unique to failures (3/3 vs 0/4). |
| A code regression      | **Zero commits** landed on `main` between 2026-09-12 and 2026-09-20. 09-18 (fail), 09-19 (pass), 09-20 (fail) all ran the identical `headSha` `f1232562`.                                                          |
| Window growth          | 09-17 (pass) and 09-20 (fail) collected the **identical** 15 PRs / 30 Jira issues. The widest window of the six **passed**.                                                                                        |
| Anything CCE-169 fixes | The window cap bounds PR _count_; 09-20 blew the ceiling on 15 PRs.                                                                                                                                                |

### The actual variable

Per-item verbosity, run to run, for the same input:

|                            | pass 09-17   | fail 09-20    |
| -------------------------- | ------------ | ------------- |
| PR #221 `body`             | 1,248 chars  | 4,289 chars   |
| Jira CCE-101 `description` | 842 chars    | 2,883 chars   |
| total payload              | 60,373 chars | 174,585 chars |

Every other field was byte-identical in size. All three truncation cut-points land
inside a `jira_issues[].description` string.

Nothing in `agents/source-collector.md` or `agents/schemas/source_collector.schema.json`
bounds `body` or `description`. The truncation observed on passing nights was the
model's own unprompted choice — accidental, not contractual.

## Design

Three changes. **A** reduces how often the ceiling is crossed; **B** makes the
residual case unmistakable instead of mysterious; **C** removes a competing cause
for B's signature.

Neither A nor B claims to eliminate the failure. A is model-dependent by
construction; B is the deterministic backstop that names what happened.

### A — Bound the cause in the agent contract

Add an explicit byte budget to `agents/source-collector.md`:

- `prs[].body` — truncate to **2,000 characters**, append `…[truncated]`
- `jira_issues[].description` — truncate to **2,000 characters**, append `…[truncated]`

This is an **instruction**, not a schema constraint. See "Rejected" below.

Budget check with CCE-169's cap live (10 PRs): 10 x 2,000 + ~40 issues x 2,000
= ~100,000 chars, roughly 25,000 tokens — comfortably under the 64,000 ceiling.

**Residual risk, named:** CCE-169 caps PR count but _not_ Jira issue count, so a
window with many linked issues remains the widest remaining path to the ceiling.
B covers it.

### B — Detect the split; refuse the fragment

In `dispatch_subagent`, where the full `events` list is already in scope:

1. Detect the CLI's synthetic output-token-limit continuation — a `type: "user"`
   event carrying `isSynthetic: true` whose text begins `Output token limit hit`.
2. When present **and** more than one assistant message carries text, record
   `output_token_limit_truncated: <name>` via the existing `out_reasons` collector.
3. **Return `None`.** The answer is known-incomplete; it must not be parsed.

Step 3 is the load-bearing half. Detection alone would leave the silent-corruption
case open: a tail fragment that _happens_ to parse and validate would be accepted
as the whole answer, and the run would advance the watermark past PRs it never
documented — the CCE-151 class of defect. All three observed nights failed to
parse, so refusing costs nothing observed and closes a hole.

**No new classification code.** The reason rides the existing
`out_reasons` -> `dispatch_reasons` -> `_record_dispatch_reasons(state, reasons, ok=...)`
path exactly as `prose_contamination_rescued` does, so it inherits each call
site's CCE-144 classification automatically: blind for source-collector
(`ok=False`), degraded where the call site passes `degraded=True`. This reuses
what is already there, in the spirit of CCE-127.

#### B's scope is narrower than it reads — say so plainly

The event stream only exists when `DOCS_AGENT_DEBUG_DIR` is set:

```python
argv = base_argv + ["--output-format", "stream-json", "--verbose"] if debug_dir else base_argv
...
if debug_dir:
    canonical_text = _extract_final_assistant_text(events)
else:
    canonical_text = raw_stdout          # simple --print mode, no events at all
```

`scripts/orchestrator_runner.py` documents _unset_ as the production default, and
the dogfood host sets it — which is precisely why this incident has forensics at
all. So:

- **Where debug is on** (the dogfood host, any host that opts in): B detects and
  refuses. This is the path on which the defect is proven.
- **Where debug is off** (the documented bare-host default): there are no events,
  so B never fires. Behaviour is unchanged from today. What simple `--print` mode
  does with a token-limit split — whether it returns the concatenation or only the
  final turn — is **not verified**, so we do not know whether bare hosts carry this
  defect at all.

This is graceful degradation in the plugin's usual sense (the capability is
detection-driven and silently skips when its input is absent), but it also means
**A is the more load-bearing of the two changes**: a byte budget prevents the
ceiling being crossed on _every_ host regardless of output mode, whereas B only
reports it where the stream is captured.

Determining bare-host behaviour is follow-up work, not a blocker: B is strictly
additive where it applies, and A covers both paths.

### C — Remove the competing cause for B's signature

`agents/source-collector.md` `## Failure handling` bullet 3 currently reads:

> On unrecoverable Git failure, return `{ "error": "git_unrecoverable: <reason>" }` and exit.

That object has neither `prs` nor `jira_issues`, both `required`. It produces the
**byte-identical** `'prs' is a required property`. The contract's own documented
failure path violates its own schema, and the logs cannot distinguish it from this
incident.

Fix: emit the canonical shape with the error carried in the sanctioned fields —
`{"prs": [], "jira_issues": [], "partial": true, "error": "git_unrecoverable: <reason>"}`
— matching the §6 pattern the same file already mandates for Jira auth failure.

`tests/agents/test_schema_md_sync.py` cannot catch this: it compares only the
`## Output schema (canonical)` fenced block, not prose elsewhere in the file.

## Rejected

**Schema `maxLength` on `body` / `description`.** A JSON Schema is a gate, not a
governor: it cannot make the agent emit less, only reject what it already emitted —
by which point the tokens are spent and the split has happened. Because
source-collector's `schema_invalid` is blind, adding `maxLength` would convert a
sometimes-failure into a deterministic one, failing every night any body is long
even when the payload would have fit. Strictly worse than today. Reinforcing this:
`jira_issues` is a bare `{"type": "array"}` with no item schema, so there is nothing
to constrain without inventing one.

**Reassembling the split answer** (concatenating the two assistant turns). Recovers
2 of the 3 observed nights; the third cut inside a JSON escape sequence. Deferred,
not refused — it is the only option that saves a night rather than failing it
cleanly, but it carries a corruption risk the schema cannot catch: one of the three
splits carried a duplicated seam, and a duplicated join can yield _parseable but
silently garbled_ text. That is the CCE-141 class ("a BLOCK became a silent PASS")
and deserves its own spec and its own adversarial review, not a subsection of this
one.

**Raising `maxOutputTokens`.** Moves the cliff without removing it, and 64,000 is
already the ceiling for this model.

**Not inlining bodies at all** (emit references, fetch downstream). The right
long-term answer and already tracked as CCE-183 ("agent payloads and outputs are
unbounded"). Out of scope here.

## Testing

All tests use the fixture-driven dry-run path; production CLI dispatch is
monkeypatched, per repo convention.

1. **B detection** — a synthetic event stream with two assistant text messages
   separated by an `isSynthetic` `Output token limit hit` user turn yields
   `output_token_limit_truncated: source-collector` and `dispatch_subagent`
   returns `None`.
2. **B refuses a parseable tail** — same stream shape, but the tail fragment is
   itself valid JSON that would satisfy the schema. Must still return `None`.
   This is the silent-corruption guard and the reason step 3 exists.
3. **B does not fire on a clean run** — a single-assistant-message stream is
   unaffected; no new reason appears. Guards against flagging every run.
4. **B does not fire on multi-block answers** — several text blocks inside _one_
   assistant message (the CCE-14 interleaved-tool_use case) must not trip it.
5. **B inherits classification** — the reason flips `blind` at the source-collector
   call site and `degraded` where the call site passes `degraded=True`.
6. **C is schema-valid** — the shape in `## Failure handling` bullet 3 validates
   against `source_collector.schema.json`.

Regression fixtures are synthetic and small. The production payloads that prove the
root cause live in the per-run forensics artifacts and **expire 14 days after each
run — 09-18's on ~2026-10-02**; a trimmed evidence record (the synthetic-turn
events plus per-run sizes, not the 250KB payloads) is captured alongside this spec.

## Verification after merge

The failure is stochastic, so a single green nightly proves nothing. Watch for:

- absence of `prose_contamination_rescued: source-collector` (the misleading pair)
- if the ceiling is crossed anyway, `output_token_limit_truncated: source-collector`
  appears instead — that is B working, not a regression
- `jira_issues[].description` values capped at 2,000 chars with the marker

## References

- CCE-144 — blind vs degraded; blocking reasons blind by default, classified by call site
- CCE-151 — consuming a window without documenting it
- CCE-141 — detect, never repair; why reassembly is deferred
- CCE-183 — unbounded agent payloads and outputs (the long-term fix)
- CCE-14 — `_extract_final_assistant_text` hardening that fixed _last turn has no text_
  but not _last turn has partial text_
