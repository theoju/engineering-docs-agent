# CCE-192 — refuse the watermark advance when the collector sheds part of the window

**Status:** proposed. Not implemented.
**Date:** 2026-09-30
**Ticket:** CCE-192

Extracted from the first draft of this ticket, which bundled this guard together with a
budget change that would have passed a PR-count ceiling into `source-collector`. That
half is now blocked: the cause of the shedding is not established, and is tracked as
CCE-198. The guard does not depend on it. **It is correct regardless of how or why the
collector sheds** — which is exactly why it should not sit behind an unsettled budget
design.

Prior art: `2026-09-23-cce177-source-collector-output-ceiling-design.md`. This spec
assumes its vocabulary — change A, change B, the ~160,000-character ceiling — and does
not restate its measurements. Read it first.

## Problem

`source-collector` returns one JSON object carrying the merged PRs in the review window.
Nothing in that object says how many PRs were in the window. The orchestrator therefore
cannot distinguish _"the window held 10 PRs"_ from _"the window held 139 and I am showing
you 10"_, and it treats both as the former.

The payload arrives at the `dispatch_validated("source-collector", sc_inputs, ...)` call
inside `run` and is read as `sources["prs"]`. There is no field in which a window size
could be reported: `agents/schemas/source_collector.schema.json` declares
`required: ["prs", "jira_issues"]` with `"additionalProperties": false`, so an undeclared
field is rejected outright rather than ignored.

What the orchestrator then does is the defect. Walking the code in `run`:

- `held_back` is built from `deferred_pages_by_pr`, `admission_deferred` and
  `window_capped`. A shed the collector performed contributes to none of them, so the set
  is empty.
- `time_truncated` is False — no clock was consulted.
- So the `if time_truncated or held_back:` branch that computes a bounded, cursor-backed
  advance through `advance_cursor_list` is never entered. Control falls to its `else`,
  where `advance_sha` is the full window HEAD.
- `_should_advance_watermark` is gated on one thing, `current_run["blind"]`, and a run
  like this is not blind. It returns True and the baseline is written.

The baseline then names a commit past every PR the collector dropped. The cursor is
consume-once, so no future window contains them again, and no run ever documents them.

### The shape has shipped three times

| Ticket      | How it got there                                                                               | Same shape                                 |
| ----------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------ |
| **CCE-138** | The authoring loop truncated without setting `time_truncated`, so the advance stayed full-HEAD | Did part of the window, reported all of it |
| **CCE-142** | A wholesale subagent failure computed a full advance and wiped `deferral_counts` with it       | Did none of the window, reported all of it |
| **CCE-151** | A degraded run advanced on the non-truncated path, where no cursor walk ran at all             | Did part of the window, reported all of it |

Each is the same bug reached by a different route: a run that does less than the full
window while reporting as though it did all of it. The guards that closed them are
route-specific — `tests/orchestrator/test_authoring_truncation_advance.py` for CCE-138,
`tests/orchestrator/test_degraded_advance_non_truncated.py` and
`tests/orchestrator/test_state_advancement_invariant.py` for CCE-151 — and none of them
watches the route this spec closes, because none of them can see inside the collector's
answer. CCE-142 leaves no trace in the tree; it is cited from the first draft of this
ticket rather than from code.

### Two sheds were observed, and only one of them is dangerous

**2026-09-24 — the ceiling was genuinely hit.** The answer measured 210,254 characters,
split across two assistant turns, change B's detector fired, and the run went blind. A
blind run does not advance, so nothing was lost. CCE-177 and CCE-144 already cover this
path end to end.

**2026-09-30 — nothing was near any limit and content was dropped anyway.** The collector
emitted 139 PRs with `body: null`, zero body characters in total, and a payload of 56,938
characters — 36% of the ~160,000-character ceiling, with roughly 100,000 characters
unused. Why it shed is unestablished and is filed as CCE-198.

The second is the dangerous one precisely because nothing failed. No detector fires, no
reason is recorded, the step summary reads clean, and the advance is full-HEAD. The first
failure mode is loud and costs one night; the second is silent and costs the work
permanently.

**One piece of arithmetic from the first draft must not be inherited.** It argued: _"127 ×
1,000 characters of `body` alone is 127,000. At this window size change A cannot fit the
payload."_ 127,000 is **under** the ~160,000-character ceiling, so bodies alone do fit and
the conclusion does not follow. The real figure for that capture is bodies-at-budget
≈128K plus ≈82K of per-PR metadata, totalling the measured 210,254. Nothing in this spec
rests on the discarded claim.

## Root cause

Two absences, and the second is only reachable because of the first.

1. The collector's contract has no field in which the window size could be stated, so the
   orchestrator has no way to learn that the answer is short.
2. No refusal is keyed on the answer being short. `_should_advance_watermark` asks only
   whether the run was blind.

`window_capped` already exists for exactly this category of held-back work — it is
established at the `# CCE-169: bound the window BEFORE admission.` site in `run`, where
the comment states its intent directly: it is a **third** category, not a reuse of
`admission_deferred`, because `admission_deferred` means the run tried and ran out of time
while `window_capped` means the run deliberately did not try. But only the orchestrator's
own cap, resolved by `resolve_window_cap`, ever writes it.

### Why the existing cursor machinery cannot cover this on its own

The orchestrator's own cap and the collector's shed look alike and are not alike, and the
difference is **identity**.

When `resolve_window_cap` holds PRs back, the orchestrator ordered the window itself with
`_order_prs_oldest_first` and still holds every held-back PR's record — including its
`merge_sha`, which the cap's own filter requires. Those PR numbers enter `held_back`,
`advance_cursor_list` stops the walk at the oldest of them, and the advance is a sound
prefix. That is why `tests/orchestrator/test_window_cap.py` can pin a capped run
advancing to the cap boundary.

When the collector sheds, the orchestrator has no records at all for what was dropped — no
numbers, no SHAs, and no assurance that the PRs it did receive form a prefix of the window
rather than an arbitrary subset of it. Nothing establishes an ordering, because nothing
establishes why the collector shed (CCE-198). So there is nothing to put in `held_back`,
nothing for `advance_cursor_list` to stop at, and no sound prefix to advance to.

That is the whole reason the refusal has to live in `_should_advance_watermark` rather than
in the cursor walk: the cursor walk needs an anchor, and this failure mode supplies none.

## Design

Three parts. They must land together — parts 1 and 2 without part 3 add a diagnostic and
change no behaviour, and part 3 without them has nothing to read.

### Part 1 — the collector reports `window_total`

`window_total` is the number of PRs in `last_sha..head_sha` **before any cap or shedding
was applied**, counted at a precisely stated point in the collector's procedure in
`agents/source-collector.md`:

- **after** `### Step 1.5 (REQUIRED if Step 1 returned ≥1 PR) — Clip to SHA range` and
  **after** `### Step 2 — Apply branch filter`;
- **before** any budget, cap, or shedding of any kind.

That boundary is load-bearing, not pedantry. `sc_inputs` in `run` hardcodes
`"pr_branch_filter": ["docs-agent/*"]`, and this host's own nightly branches are named
`docs-agent/*`, so the branch filter excludes real merged PRs on essentially every night.
A `window_total` counted before the filter would exceed the emitted count almost always,
the guard in part 3 would fire almost always, and the baseline would never advance again.
A guard that cannot tell its own trigger apart from normal operation is worse than no
guard.

Contract changes:

- `agents/schemas/source_collector.schema.json` gains `window_total` as an integer with
  `minimum: 0`. It is **not** added to `required`. Three shapes the contract already
  mandates must keep validating without it: `### Step 0 — Empty-window short-circuit (only
valid skip path)`, and all three bullets of `## Failure handling`, which
  `tests/agents/test_source_collector_failure_payload.py` pins.
- The canonical fenced block under `## Output schema (canonical)` in
  `agents/source-collector.md` changes in lockstep.
  `tests/agents/test_schema_md_sync.py::test_md_schema_block_matches_canonical_schema_file`
  compares the two sides with `json.loads` equality, so a one-sided edit is red.
- `### Step 6 — Emit final JSON` gains a pre-emit check, matching the form the existing
  checks there already use.

### Part 2 — the orchestrator records the remainder as `window_capped`

When `window_total` exceeds the number of PR records received, the remainder is recorded
as `window_capped`: the third category the CCE-169 site already defines, carrying the same
classification it carries today — `degraded=True`, because the run held back what it did
not process rather than consuming and losing it.

Three details decide whether this is correct:

**Compare at receipt.** The comparison is `window_total` against the count of PR records
as the payload arrived — before `_clip_prs_to_window` and before
`_order_prs_oldest_first`. The clip's drops are the orchestrator's own judgement about
out-of-window PRs, are already reported by their own reason, and folding them into the
capped remainder would double-count them. Reconciling a `window_total` that disagrees with
the clip is a separate question and is not in scope here.

**The remainder is count-only.** Unlike the admission cap's remainder, this one is a
number, not a list of PR records — the collector never sent the dropped PRs, so there is
nothing to list. Two consequences follow and both must be stated in the implementation
rather than discovered: it cannot enter `held_back`, which is a set of PR numbers; and the
`cursor:` log line renders `capped=` by PR number, so a count-only remainder renders as
`none` there unless that emit is taught to print the count. Left unaddressed, the only
operator-visible signal is the partial reason.

**Record it in `state`.** `_should_advance_watermark(state)` takes nothing but `state`, so
the remainder has to be on `current_run` before the advance is computed. This also gives
the run's PR a durable record of a window that was not fully covered.

**An absent `window_total` is not zero.** A payload that omits the field makes no claim and
must not fire the guard. Two live paths reach that state: a dispatch that returned `None`,
which `run` replaces with `{"prs": [], "jira_issues": []}`, and a host whose checked-out
`agents/source-collector.md` predates part 1. Absent means unknown; behaviour there is
unchanged from today, and part 1's lockstep edit is what makes the claim present.

### Part 3 — `_should_advance_watermark` refuses

`_should_advance_watermark` returns `not blind` today. It must additionally return False
whenever the **collector-sourced** `window_capped` remainder is non-empty.

The qualifier is not optional, and getting it wrong is the one way this change can do
damage. `tests/orchestrator/test_window_cap.py::test_a_capped_run_advances_to_the_cap_boundary_and_says_so`
pins that a run capped by the orchestrator's own admission cap **does** advance, to the cap
boundary — that is the CCE-169 behaviour that makes a capped backlog drain instead of
wedging. A refusal keyed on `window_capped` being non-empty without qualification turns
that test red, freezes the baseline on every deliberately capped night, and reinstates the
CCE-109 doom loop. The refusal keys on the identity-less remainder from part 2, which the
admission cap never produces.

This is consistent with the two invariants already pinned nearby, not an exception to
them. `tests/orchestrator/test_state_advancement_invariant.py` asserts that a degraded
run's hold must come from the cursor walk rather than from `_should_advance_watermark` —
that run has PR identities, so the walk can express its hold. And
`tests/orchestrator/test_degraded_advance_non_truncated.py` states the converse rule this
spec invokes: a run with no PR to anchor a cursor-backed advance on must hold the baseline.
A collector shed is the second case. There is no anchor, so the cursor walk cannot express
it, and `_should_advance_watermark` is the only site left.

**The cost, stated.** A night that sheds does not advance at all, so its window is one day
wider the next night. That is CCE-144's asymmetry taken deliberately: re-reading a window
is cheap and idempotent, skipping one is permanent. It also means this guard does not by
itself stop the window from widening — whether a shedding night should advance over the
slice it _did_ document is a budget question, it requires an ordering guarantee the
collector does not currently give, and it belongs to CCE-198.

## Out of scope

Each of these is deliberately excluded, and none is a gap in this spec.

- **Change A — passing `max_prs` into the collector.** That is a ceiling on the input, and
  the budget question behind it is open under **CCE-198**. Nothing here caps what the
  collector collects.
- **Any claim about why the collector sheds.** CCE-198 records the cause as unestablished.
  This spec states only that a shed is detectable from `window_total` and must stop the
  advance; it asserts nothing about the mechanism.
- **Reassembling a split answer.** CCE-177 deferred it on CCE-141 grounds — detect, never
  repair, because a duplicated join can be parseable but silently garbled. That deferral
  stands and is not revisited.
- **Raising `maxOutputTokens`.** Rejected in CCE-177; 64,000 is already this model's
  ceiling. Inherited by reference, not re-argued.
- **Schema `maxLength` on `body`.** Rejected in CCE-177, because a gate cannot make the
  agent emit less and `schema_invalid` on this agent is blind. Inherited by reference, not
  re-argued.

**CCE-183** — "agent payloads and outputs are unbounded", emit references and fetch
downstream — supersedes this work eventually, and should not be pre-empted. One part of
this spec outlives it: whatever replaces the inline payload, a run that documents less than
its window must still refuse to advance past the remainder. Parts 1 and 2 are tied to the
current payload shape and would be rewritten by CCE-183; part 3's invariant is not.

## Testing

1. **The load-bearing test.** `_should_advance_watermark` returns False whenever the
   collector-sourced `window_capped` remainder is non-empty. **It must fail against `main`
   today**, because nothing currently sets `window_capped` from the collector: the guard
   has nothing to read, `held_back` stays empty, and the run advances to full window HEAD.
   An adversarial review should attack this test hardest — **constructing a capped
   collection that still advances is the failure this spec exists to prevent**, and a test
   that passes against `main` is not testing the guard.
2. **`window_total` round-trips schema validation.** Validated against
   `agents/schemas/source_collector.schema.json` as the dispatcher validates it: a payload
   carrying `window_total`, one carrying `window_total: 0`, and one omitting it entirely
   must all be accepted; a negative value must be rejected by `minimum: 0`.
3. **`tests/agents/test_schema_md_sync.py` still passes after the lockstep edit** — the
   `.md` canonical block and the `.json` file remain `json.loads`-equal.
4. **End to end, a shedding run holds the baseline.** A fixture payload whose
   `window_total` exceeds its `prs` count leaves `last_successful_run.head_sha` at the
   prior baseline, never at window HEAD, and the run records a degraded reason naming the
   remainder.
5. **The admission-cap path is unchanged.**
   `tests/orchestrator/test_window_cap.py::test_a_capped_run_advances_to_the_cap_boundary_and_says_so`
   and `::test_a_capped_run_still_auto_merges` stay green. Any formulation of part 3 that
   reds either of them is wrong, not a test to update.
6. **An absent `window_total` does not fire the guard** — the older-agent-file path and the
   `sources is None` fallback both advance exactly as today.
7. **`window_total` equal to the received count does not fire the guard.** The analogue of
   CCE-177's "does not fire on a clean run" test for change B, and the guard against
   flagging every night.
8. **A branch-filtered night does not fire.** With `pr_branch_filter` excluding PRs, a
   `window_total` counted at part 1's stated boundary equals the emitted count even though
   the raw window was larger. This is the false-positive that would freeze the baseline
   permanently, so it is pinned rather than reasoned about.

## Verification after merge

A green suite is not verification, because the trigger is a property of a live collector
answer rather than of the code.

- A night whose collector reports `window_total` equal to its emitted count advances
  exactly as before. This is the no-regression observation and it comes first.
- A night whose collector sheds: `last_successful_run.head_sha` unchanged from the prior
  baseline, a degraded reason naming the remainder in the step summary, and the run's PR
  carrying a `.engineering-docs-agent/state.json` that records it. All three, because the
  first alone is also what a crash looks like.
- The `cursor:` log line names the remainder. If it still prints `capped=none` on such a
  night, part 2's count-only caveat went unaddressed and the only signal is the partial
  reason.

The first draft of this ticket records runs 09-27, 09-28 and 09-29 exiting in ~439 ms with
`returncode 1`, zero tool calls, and stdout `You've hit your weekly limit · resets 9am
(UTC)`. If that still holds, no nightly can run and every observation above waits on the
quota reset. That is a reason to wait, not a reason to report the suite as verification.

## References

- `2026-09-23-cce177-source-collector-output-ceiling-design.md` — change A, change B, the
  ceiling measurement, and the rejected alternatives this spec inherits rather than
  re-argues
- `2026-09-23-cce169-window-cap-design.md` — `run.window_pr_cap`, `resolve_window_cap`, and
  the `window_capped` category this spec extends to a second source
- CCE-198 — the collector shed whose cause is unestablished, and the budget question this
  spec deliberately does not answer
- CCE-183 — unbounded agent payloads; supersedes parts 1 and 2, not part 3
- CCE-144 — blind versus degraded, and the re-read-is-cheap asymmetry part 3 relies on
- CCE-141 — detect, never repair; why reassembly stays deferred
- CCE-151, CCE-142, CCE-138 — the advance-past-undocumented-work class this guard closes a
  fourth route into
- CCE-109 — the doom loop a wrongly-unqualified refusal in part 3 would reinstate
