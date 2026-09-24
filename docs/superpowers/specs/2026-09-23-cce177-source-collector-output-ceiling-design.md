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

- `prs[].body` — emit **at most 1,000 characters in total**: cut the text at 988
  and append `…[truncated]` (12 chars), so a cut value is exactly 1,000
- `jira_issues[].description` — the same 1,000-character total, the same marker

The budget is **inclusive of the marker**, and that is not a detail. An earlier
draft said "cut at N characters, append `…[truncated]`", which makes a truncated
value N+12 long, while the Step 6 checklist asked whether the value was "at most
N characters, with `…[truncated]` appended" — a condition no correctly-truncated
value can satisfy. Step 6 closes with "If any check fails, return to the missing
step", so a model treating it as a gate would churn or re-cut. Steps 3, 5 and 6
now all state the same total.

This is an **instruction**, not a schema constraint. See "Rejected" below.

#### Budget check — the first version of this paragraph was wrong twice

It read: _"Budget check with CCE-169's cap live (10 PRs): 10 x 2,000 + ~40
issues x 2,000 = ~100,000 chars, roughly 25,000 tokens — comfortably under the
64,000 ceiling."_ Both premises are false, and both errors bias the estimate the
same way — too low — which is how a 2,000-char cap came to look comfortable.

**(a) CCE-169's window cap does not bound what the agent emits.**
`resolve_window_cap` (`scripts/orchestrator_runner.py:resolve_window_cap`) runs
in `run` _after_ the `dispatch_validated`
(`scripts/orchestrator_runner.py:dispatch_validated`) call that collects the
sources. It discards PRs the agent has **already paid the output tokens to
emit** — it trims the orchestrator's work list, never the agent's answer.
Nothing bounds the PR count on the way in: `sc_inputs` carries no cap, and
`agents/source-collector.md` states no PR-count bound. The worst case to budget
against is therefore the real observed window — **20 PRs / 38 Jira issues**, the
09-23 run — not 10.

**(b) The chars-per-token rate is ~2.5, not ~4.** The three production cut
points measure the ceiling directly rather than assuming it: the pre-resume half
was 161,217 / 164,105 / 159,475 characters. So 64,000 output tokens is roughly
**160,000 characters** of this payload shape, not the ~256,000 a
4-chars-per-token rule of thumb implies. JSON-escaped prose is denser than
English.

**Corrected arithmetic.** Replaying the recovered 09-23 payload (20 PRs / 38
issues, 247,174 chars uncapped) through each cap:

| Cap                             | Payload    | Share of the measured ~160,000-char ceiling |
| ------------------------------- | ---------- | ------------------------------------------- |
| **1,000 chars total** (shipped) | **80,249** | **~50%**                                    |
| 2,000 chars + marker (rejected) | 137,628    | ~86%                                        |

The 2,000-char cap is recorded here deliberately: at 86% of the ceiling it left
almost no headroom on a window that had already crossed it once, which is why it
was lowered to 1,000 rather than kept.

**Residual risk, named:** the cap bounds each value, not how many there are, and
`jira_issues` is the unbounded dimension — CCE-169 caps PR count (too late to
matter, per (a)), but nothing caps linked-issue count at any point. In the
capped 09-23 replay the 38 issues account for 46,097 of the 80,249 chars against
the 20 PRs' 34,126, so the unbounded dimension is already the larger one, and a
window with several times that many linked issues would reach the ceiling on
issue count alone. That is the widest remaining path, and B is what covers
it.

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

#### Measured findings — what the two conditions actually do

Measured across all seven runs in the 09-17…09-23 window, from their archived
`source-collector.stream.jsonl` forensics. Trimmed captures of three of them
are committed under `tests/fixtures/cce177/`.

**1. Condition 2 is inert. It discriminates nothing.**

`assistants_with_text > 1` is TRUE on all three failing runs **and** on all
four passing ones:

| run           | date  | outcome  | assistants with text | marker present | detector |
| ------------- | ----- | -------- | -------------------- | -------------- | -------- |
| `35221636293` | 09-17 | pass     | 10                   | no             | False    |
| `35343242932` | 09-18 | **fail** | 9                    | **yes**        | **True** |
| `35441305173` | 09-19 | pass     | 6                    | no             | False    |
| `35509910089` | 09-20 | **fail** | 9                    | **yes**        | **True** |
| `35608299979` | 09-21 | pass     | 7                    | no             | False    |
| `35727627405` | 09-22 | pass     | 8                    | no             | False    |
| `35862057776` | 09-23 | **fail** | 13                   | **yes**        | **True** |

Condition 2 separates no pair in the sample, so the detector reduces in
practice to "the marker is present".

On this evidence that is **harmless, not dangerous**: the marker appears in
exactly the three failing runs and in none of the four passing ones — 3 true
positives, 0 false positives, 4 true negatives. Condition 2 costs nothing and
is kept as **documentation of intent** — it records which shape is being
looked for (one answer split across two turns, not the CCE-14 interleaved
multi-block answer inside a single turn). It is not a working discriminator,
and nothing should describe it as one. In particular it is not evidence that
the detector is selective; the marker is doing all of the work.

**2. A refinement was proposed and REJECTED on measurement.**

Reviewers argued the detector should additionally require the marker to appear
**after the last `tool_use`**, reasoning that a ceiling hit mid-conversation is
benign: the agent resumes, keeps working, and still emits a complete answer at
the end.

Measured, that predicate fires on only **two of the three** failing runs:

| run           | date  | marker at event | `tool_use` blocks after it     | refinement's verdict |
| ------------- | ----- | --------------- | ------------------------------ | -------------------- |
| `35343242932` | 09-18 | 157             | **4** (Bash, Bash, Read, Read) | **ACCEPT** — wrong   |
| `35509910089` | 09-20 | 265             | 0                              | refuse               |
| `35862057776` | 09-23 | 197             | 0                              | refuse               |

The premise is falsified by the payloads themselves. Counting `prs[]` entries
in each half of the split answer:

| run           | date  | head half | tail half |
| ------------- | ----- | --------- | --------- |
| `35343242932` | 09-18 | 15        | **0**     |
| `35509910089` | 09-20 | 15        | **0**     |
| `35862057776` | 09-23 | 20        | **0**     |

The `prs` array lives entirely in the head half every time. On 09-18 the
ceiling was hit **while the final answer was already being emitted**; the agent
then made four more tool calls and resumed the SAME truncated JSON. The tail is
not a fresh complete answer written after an interruption — it is the second
half of the interrupted one, and the four tool calls are the agent gathering
what it needed to finish it. Accepting that night means advancing the watermark
past 15 PRs the run never documented: exactly the CCE-151 harm this change
exists to prevent.

`tests/orchestrator/test_output_token_limit_real_streams.py` pins the 09-18
shape against its real stream, so adding the refinement turns that test red.

**Why the detector is allowed to be crude.** Its two failure modes are not
symmetric, and it fails the safe way:

- A **false positive** refuses a good answer. The run exits 1, the watermark
  freezes, the same window is re-read tomorrow. Cost: one night — bounded,
  recoverable, and loud.
- A **false negative** accepts a tail fragment as the whole answer. If the
  fragment parses and validates, the run advances the watermark past PRs it
  never read. Cost: **permanent** — the cursor is consume-once (CCE-151), so
  the skipped window is never re-read and that work is undocumented forever.

Any refinement narrows the detector, and narrowing trades false positives for
false negatives — the cheap failure for the expensive one. That is the standing
answer to "should we tighten this?": tightening has to be justified by a
false-positive rate, and the measured rate is zero. There is nothing to
reduce. Re-propose only with evidence of a false positive in production, not
with an argument about what the model _would_ do.

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

#### Known limitation — B's reason does not say WHICH item hit the ceiling

Surfaced in review, tracked rather than fixed here.

`source-collector` is dispatched once per run, so its reason needs no item
identity. The other three call sites — `pr-summarizer`, `page-author`,
`gap-detector` — dispatch inside a loop, and each is shaped:

```python
_record_dispatch_reasons(state, reasons, ok=out is not None, degraded=True)
if out is None:
    if not reasons:
        add_partial(state, f"page_author_invalid: {rel}", degraded=True)
```

The per-item identity — `pr=221`, the page path, `pr_id=...` — exists **only**
in that `if not reasons:` fallback. It is the branch for a dispatch that failed
without explaining itself, so the reason it writes has to supply the identity
itself.

B breaks that in two steps. `output_token_limit_truncated: <name>` makes
`reasons` non-empty, so the fallback no longer fires and the identity-bearing
string is never built. And `<name>` is the agent name — a constant per call site
— so every item that hits the ceiling produces the same string, and `add_partial`
is idempotent by design ("a reason already present is not appended again"). Ten
pages truncated in one run collapse to a single digest line.

The cost is real and it is a regression in triage signal: an operator reading
the step summary learns that page-author hit the ceiling, but not on which page,
nor how many. Nothing in the run record distinguishes one occurrence from ten.
The per-call stderr emit does not rescue it either — `add_partial` writes a line
on every call, but they are the same constant line, so the job log gains
repetition without identity.

This does not affect the failures that motivated CCE-177 (all three were
source-collector, dispatched once) and it does not weaken the refusal: the work
is still held back, still classified, still visible. It degrades diagnosis, not
safety. That is why it is not being fixed inside this change — but it should not
stand.

**TODO:** open a follow-up ticket to carry the item identity into the reason at
the three looping call sites, so `output_token_limit_truncated` is
per-item-qualified the way `page_author_invalid: <rel>` already is. The fix is
not simply moving the fallback: the reason is built in `dispatch_subagent`,
which does not know the loop variable, so either the call sites qualify the
reasons they receive before recording them, or the loop context is threaded into
the dispatch. Choosing between those is the follow-up's first question.

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
7. **A is stated, and stated consistently** — Step 3, Step 5 and the Step 6
   pre-emit checklist each state the byte budget, all three state the same
   total, and each states it marker-inclusive. Each number is extracted from
   its own passage and compared against the others, never against a literal,
   because the original defect was the passages disagreeing. Added after
   mutation testing found that deleting all three of A's edits left the whole
   suite green — A is the load-bearing half, and it had no coverage at all.
8. **B is pinned to the real CLI event shape** — three trimmed production
   streams, parsed the way `dispatch_subagent` parses one, assert the
   detector's verdict on two failing runs and one passing one. Every other B
   test builds its own `isSynthetic` dicts, which agree with each other about
   a shape that had never been checked against the CLI's actual output.
9. **B's refusal sits above the returncode guard** — a split stream whose CLI
   also exited non-zero must still name the cause. Mutation testing moved the
   refusal below `if r.returncode != 0` and all 19 tests stayed green; below
   it, such a run returns `(None, [])` and the call site's `if not reasons:`
   fallback emits `source_collector_invalid: returned None`, the cause-free
   signature CCE-177 exists to eliminate. The mirror placement (refusal above
   the forensics write) was already pinned; this was a one-sided omission.

Most regression fixtures are synthetic and small. Three are **not**: trimmed
captures of real production streams live under `tests/fixtures/cce177/`, with
`tests/fixtures/cce177/README.md` recording what was dropped and truncated.
Everything else — the production payloads that prove the
root cause — lives in the per-run forensics artifacts and **expires 14 days after each
run — 09-18's on ~2026-10-02**; the trimmed evidence record taken while they were
still downloadable is committed at
`docs/superpowers/specs/2026-09-23-cce177-evidence.md` — per-run event counts and
sizes, the verbatim synthetic turn, the three cut points, the verbosity
comparison, and the reassembly results, but none of the 160–250KB payloads
themselves. After the expiry date that file is the only surviving record.

## Verification after merge

The failure is stochastic, so a single green nightly proves nothing. Watch for:

- absence of `prose_contamination_rescued: source-collector` (the misleading pair)
- if the ceiling is crossed anyway, `output_token_limit_truncated: source-collector`
  appears instead — that is B working, not a regression
- `jira_issues[].description` and `prs[].body` values no longer than 1,000 chars
  in total, a cut one ending in `…[truncated]`

## References

- CCE-144 — blind vs degraded; blocking reasons blind by default, classified by call site
- CCE-151 — consuming a window without documenting it
- CCE-141 — detect, never repair; why reassembly is deferred
- CCE-183 — unbounded agent payloads and outputs (the long-term fix)
- CCE-14 — `_extract_final_assistant_text` hardening that fixed _last turn has no text_
  but not _last turn has partial text_
