# CCE-192 — bound the source-collector's input, not just its output

Status: proposed. Not implemented.

Companion to `2026-09-23-cce177-source-collector-output-ceiling-design.md`. That spec
bounded per-item verbosity and added a detector that refuses a split answer. This one
closes the remaining axis: the number of items. Read CCE-177's spec first — this spec
assumes its vocabulary (change A, change B, the ~160,000-character ceiling) and does not
restate its measurements.

## Problem

`source-collector` emits one JSON object carrying every merged PR in the review window.
The payload is O(number of PRs). CCE-177's change A bounds each `prs[].body` and
`jira_issues[].description` to 1,000 characters, which bounds the payload _per item_ and
says nothing about how many items there are.

On 2026-09-24 the window held **127 PRs**. Change A was in force — the agent's own
narration in the event stream reads "body (1000 chars) and files (200 entries)" — and the
answer still measured **210,254 characters** against the ceiling CCE-177 measured at
~160,000. The answer split across two assistant turns, change B's detector fired, and the
run went blind.

127 × 1,000 characters of `body` alone is 127,000. **At this window size change A cannot
fit the payload however correctly it is applied.** The arithmetic, not the model's
verbosity, is what fails.

### Why CCE-177 could not have seen this

CCE-177's "What this is NOT" table rules out window growth, and it is right on its own
evidence:

> 09-17 (pass) and 09-20 (fail) collected the **identical** 15 PRs / 30 Jira issues. The
> widest window of the six **passed**.

Every night it measured held ~15 PRs. At 15 PRs, count is not the binding constraint and
per-item verbosity is — exactly as it concluded. At 127 PRs count binds on its own. Both
causes are live; CCE-177 closed the one its data could see.

The correction is narrow and worth stating precisely: window growth is not _the_ cause of
the ceiling being crossed, and it is now _a sufficient_ cause. Nothing in CCE-177's
measurements is overturned.

### How the window reached 127

A blind run does not advance the watermark, so the next night's window is one day wider.
Each blind night therefore makes the next one more likely to be blind. Observed
`baseline_age`: 1.0d (09-24) → 2.0d (09-25) → 3.0d (09-26), against `stall_window=4d`.

This is a ratchet, and it is why the defect does not present as intermittent. It is not
itself the bug — it is the amplifier that moved the window from the regime CCE-177
measured into one where count alone breaches the ceiling.

## Root cause

`DEFAULT_WINDOW_PR_CAP = 10` exists (`scripts/orchestrator_runner.py:685`), is resolved by
`resolve_window_cap()` (`:834`) from `run.window_pr_cap`, and is applied at `:2854` under a
comment that states its position exactly:

```
# CCE-169: bound the window BEFORE admission.
```

Before _admission_ — which is after `source-collector` has already returned. The collector
fetches and emits all 127 PRs; the orchestrator then discards 117 of them. **The cap never
reaches the process whose output crosses the ceiling.**

This is consistent with, and explains, CCE-177's dismissal of the cap:

> Anything CCE-169 fixes | The window cap bounds PR _count_; 09-20 blew the ceiling on 15 PRs.

True as written. At 15 PRs the cap's _position_ does not matter, because the ceiling was
crossed by verbosity rather than by count. At 127 the position is the whole defect.

### What this is NOT

| Ruled out                    | Evidence                                                                                                                                                                                                                                                                 |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Change A regressed           | The 09-24 stream shows the agent applying the 1,000-character budget by name. `tests/agents/test_source_collector_output_budget.py` passes.                                                                                                                              |
| Change B misfires            | The split is real: first JSON half 156,270 chars (ev163), synthetic `Output token limit hit` marker (ev164), continuation 53,984 chars (ev173). Refusing it is correct behaviour.                                                                                        |
| Prose contamination          | The concatenated halves parse as JSON with no rescue applied.                                                                                                                                                                                                            |
| A code regression            | The failure predates and postdates every commit in the window; `847ae91`, `bd592fb` and `ce8a8fa` are unrelated.                                                                                                                                                         |
| The current nightly failures | Runs 09-27, 09-28 and 09-29 fail in 439 ms with `returncode 1`, zero tool calls, and stdout `You've hit your weekly limit · resets 9am (UTC)`. That is subscription quota exhaustion, a separate problem tracked separately. It masks this defect rather than fixing it. |

## Design

One change, in two halves that must land together. The second half is the reason this
needs a spec at all.

### A — Pass the cap into the collector

`dispatch_validated("source-collector", inputs, ...)` builds `inputs` today as:

```json
{
  "last_sha": "...",
  "head_sha": "...",
  "repo": {},
  "pr_branch_filter": [],
  "jira": {}
}
```

Add `max_prs`, set from `resolve_window_cap(config)`. `agents/source-collector.md` gains a
procedure step: collect the window, order it oldest-first by merge date, and emit at most
`max_prs` entries in `prs`. `0` means unlimited, matching `resolve_window_cap`'s existing
contract.

Oldest-first is not a detail. It must match the admission gate's existing prefix
semantics (`admission_deferred = prs[i:]`, documented at `:609` and `:1023`), or the two
would disagree about which PRs a run is responsible for.

At the default cap of 10, a payload of ~10 bodies plus metadata measures on the order of
10–20 KB against a ~160,000-character ceiling. Bounded by construction, not by the model's
restraint — and unlike change B, it does not depend on `DOCS_AGENT_DEBUG_DIR` being set,
which CCE-177's own change-A rationale notes is unset on the documented bare-host default.

### B — The collector must report what it left out, and a capped run must not advance

This is the safety-critical half.

If the collector returns the oldest 10 of 127 and says nothing about the remaining 117,
the orchestrator cannot distinguish "the window held 10 PRs" from "the window held 127 and
I am showing you 10". It would then compute a full-HEAD advance and move the watermark past
117 PRs no run ever documented — losing them permanently, because the watermark is the only
record of what has been covered.

That is the CCE-151 class, and this project has shipped it three times: CCE-138
(authoring-loop truncation did not set `time_truncated`), CCE-142 (wholesale subagent
failure computed a full advance and wiped `deferral_counts`), CCE-151 (a degraded run
advanced on the non-truncated path). Each was the same shape — a run that did less than the
full window while reporting as though it had done all of it.

So:

1. The collector emits `window_total`, the count of PRs in `last_sha..head_sha` before the
   cap was applied. This requires a schema change: `agents/schemas/source_collector.schema.json`
   is `"additionalProperties": false`, so an undeclared field is rejected outright. The
   canonical fenced block in `agents/source-collector.md` must change in lockstep —
   `tests/agents/test_schema_md_sync.py` asserts `json.loads`-equality between them.
2. When `window_total` exceeds the number of collected PRs, the orchestrator records the
   remainder as `window_capped` — the third category already defined at `:2858`,
   deliberately distinct from `admission_deferred` ("the run TRIED and ran out of time")
   because this is "the run deliberately DID NOT TRY".
3. `_should_advance_watermark` must refuse a full-HEAD advance whenever `window_capped` is
   non-empty, and advance only over the PRs actually collected and documented.

Point 3 is the invariant the whole change rests on. Without it this fix trades a visible
blind run for silent permanent data loss, which is strictly worse than the defect.

### Interaction with the ratchet

With A and B in place, a night that caps still advances over the 10 PRs it documented, so
`baseline_age` falls instead of growing. The ratchet runs backwards: each night drains a
bounded slice and narrows the window for the next. That is the property the current design
lacks, and it is why capping the input is worth more than raising the ceiling.

Note this makes the cap load-bearing for _recovery speed_: at 10 PRs a night, a 127-PR
backlog drains in about 13 nights. Whether that is acceptable, or the cap should be raised
once bounded draining is proven, is a tuning question for after this lands — not a reason
to leave the window unbounded.

## Rejected

**Reassembling the split answer.** CCE-177 deferred this, and the deferral stands. Its
stated ground — one of three observed splits carried a duplicated seam, and a duplicated
join can be _parseable but silently garbled_, the CCE-141 class — is not addressed by
anything here.

Recording one new datapoint, because it slightly strengthens the case for a _future_
spec and must not be mistaken for clearance: the 09-24 split rejoins cleanly. Joining
ev163 and ev173 yields valid JSON with **127 PRs and zero duplicate numbers**. That is 3
of 4 observed nights recoverable. It remains its own spec and its own adversarial review,
per CCE-177.

**Raising `maxOutputTokens`.** Unchanged from CCE-177 — moves the cliff without removing
it, and 64,000 is already this model's ceiling.

**Schema `maxLength` on `body`.** Unchanged from CCE-177 — a gate cannot make the agent
emit less, and because source-collector's `schema_invalid` is blind it would convert a
sometimes-failure into a deterministic one.

**Lowering change A's 1,000-character budget further.** Fitting 127 PRs under the ceiling
needs roughly 250 characters per body, which is too short for a PR summary to carry
meaning, and it would still fail at 500 PRs. It treats the symptom on the wrong axis.

**Waiting for CCE-183** ("agent payloads and outputs are unbounded", the emit-references
design CCE-177 calls "the right long-term answer"). CCE-183 supersedes this spec when it
lands and should not be pre-empted — but it is a larger change to every agent's payload
contract, and the nightly is blind now. This spec is deliberately the smaller, narrower
fix on the one agent that is failing.

## Testing

The existing corpus covers the ceiling; these are the gaps this change opens.

1. `resolve_window_cap`'s value reaches the collector's `inputs` — asserted on the dict the
   dispatcher composes, not on a mock's call signature.
2. `max_prs` of 0 is passed through as unlimited, preserving `resolve_window_cap`'s contract.
3. A collector payload whose `window_total` exceeds its collected count populates
   `window_capped` with the remainder, and the remainder is oldest-first.
4. **`_should_advance_watermark` returns False whenever `window_capped` is non-empty.** The
   load-bearing test. It should fail against `main` today, since nothing sets
   `window_capped` from the collector.
5. `window_total` round-trips schema validation, and `test_schema_md_sync.py` still passes
   after the lockstep edit.
6. A capped run's `state.json` records the capped remainder, so a reader of one PR can see
   the window was not fully covered — the diagnostic CCE-177 notes goes quiet on blind
   nights.

Test 4 is the one an adversarial review should attack hardest. Constructing a capped
collection that still advances is the failure this spec exists to prevent.

## Verification after merge

Not satisfied by a green suite. A capped night must be observed:

- `cursor:` reports a non-empty `capped=` list and a `baseline_age` **lower** than the
  previous night's. A capped run that does not lower `baseline_age` means the advance is
  still refused for another reason and the ratchet is unbroken.
- No `output_token_limit_truncated: source-collector` on a night whose window exceeds the
  cap.
- The PR carries `.engineering-docs-agent/state.json` naming the capped remainder.

The quota exhaustion in "What this is NOT" blocks all three — no nightly can run until it
resets. Verification waits on that, and a green suite must not be reported as verification.

## References

- `2026-09-23-cce177-source-collector-output-ceiling-design.md` — change A, change B, the
  ceiling measurement, and the rejected alternatives this spec inherits
- CCE-169 — `run.window_pr_cap`, whose position at admission is this spec's root cause
- CCE-183 — unbounded agent payloads; supersedes this spec
- CCE-141 — detect, never repair; why reassembly stays deferred
- CCE-151, CCE-142, CCE-138 — the advance-past-undocumented-work class change B guards
- ADIS-513 — the host-repo merge blocker downstream of every blind night
- Run 36012365616 forensics, artifact `10814495165` (expires ~2026-10-08) — the 127-PR
  capture all measurements here come from
