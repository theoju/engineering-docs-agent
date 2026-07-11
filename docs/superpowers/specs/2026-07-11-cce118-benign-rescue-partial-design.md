# CCE-118 (item 1): a benign JSON rescue must not flip a run to `partial` — design

**Date:** 2026-07-11
**Ticket:** [CCE-118](https://designitright.atlassian.net/browse/CCE-118) — item 1 (fact-checker / dispatch output robustness)
**Status:** approved
**Fix surface:** in-repo (`scripts/orchestrator_runner.py` + tests). Ships via the plugin.

## Problem (the recurring nightly partial)

Every nightly `docs-agent` run that happens to trigger a JSON _rescue_ on a
blocking-pipeline subagent is marked **(partial)**, even when every page authored
cleanly and no lint or fact-check actually failed. A partial run is ineligible for
CCE-101 auto-merge, so hands-off publishing breaks and an operator must merge by
hand. PR #170 (2026-07-11) is the exemplar.

## Root cause (corrected from the ticket's hypothesis)

The ticket framed this as _"fact-checker output robustness"_ — implicating
`schema_invalid: fact-checker`, `fact_checker_unavailable`, and
`prose_contamination_rescued`. Investigation shows that framing is **wrong**:

- The fact-checker dispatch already records **all** its reasons `info_only=True`
  (`orchestrator_runner.py:1708` and `:1713`, per CCE-110's advisory-layer design).
  `schema_invalid: fact-checker`, `fact_checker_unavailable`, and the fact-checker's
  own `prose_contamination_rescued` therefore **never** flip `partial`. This is
  already correct and needs no change.

PR #170's `partial_reasons` were:

```
prose_contamination_rescued: page-author       ← the ONLY one that flipped partial
schema_invalid: fact-checker: 'ok' is a required property   (info_only — no effect)
fact_checker_unavailable: .../lint-rules.md                 (info_only — no effect)
prose_contamination_rescued: fact-checker                   (info_only — no effect)
```

The real bug is the **blocking-pipeline dispatch callsites**. Each does:

```python
for r in reasons:
    add_partial(state, r)          # default info_only=False → flips partial
```

`add_partial` with the default `info_only=False` flips `current_run.partial = True`
(`state_io.py:256-257`). So when a _successful_ dispatch returns a benign
`prose_contamination_rescued: <name>` reason — the subagent emitted valid JSON
wrapped in prose, which `_rescue_json_object` recovered and the schema then
validated — the whole run is marked partial even though the work succeeded.

### Why `prose_contamination_rescued` on a successful dispatch is benign

`dispatch_validated` returns usable output (`out is not None`) **only** when the
recovered object passed schema validation. A schema failure forces `out = None`
(`orchestrator_runner.py:757-765`). Therefore:

> **Invariant:** when a dispatch returns `out is not None`, its `reasons` can only
> contain `prose_contamination_rescued` — never a genuine-failure reason.

So `prose_contamination_rescued` riding on a successful dispatch is a diagnostic,
not a degradation. It should be recorded (visible in `partial_reasons`) but must
not flip `partial`.

## The five affected callsites

All are blocking-pipeline dispatches whose reasons currently flip partial:

| Dispatch          | Line | Success variable         |
| ----------------- | ---- | ------------------------ |
| source-collector  | 1333 | `sources is not None`    |
| pr-summarizer     | 1424 | `summary is not None`    |
| page-author       | 1549 | `out is not None`        |
| content-validator | 1584 | `validation is not None` |
| gap-detector      | 1814 | `verdict is not None`    |

Advisory layers (fact-checker `:1708/:1713`; the deterministic generators at
`:1228/:1232/:1236/:1748/:1766/:1777`) already record `info_only=True` directly and
are **out of scope** — unchanged.

Non-dispatch reasons at these sites stay blocking (correctly): `source_collector_error`,
`source_collector_partial`, the `_clip_prs_to_window` `clip_reasons` (`:1360`),
`pr_summarizer_error`, and the `*_invalid: returned None` fallbacks. These describe
real data problems, not benign rescues.

## Decision

**Record dispatch reasons with `info_only = (the dispatch produced usable output)`.**
A successful-but-rescued dispatch → `info_only=True` (diagnostic, no partial flip).
A failed dispatch (`out is None`) → `info_only=False` (real dropped work → partial).

This is preferred over string-matching the reason (`reason.startswith("prose_…")`)
because it is semantically exact and future-proof: _any_ reason a successful dispatch
emits is, by the invariant above, benign — so keying on dispatch success auto-classifies
future benign reason types without a maintained allow-list. (String-matching and
success-keying produce identical outcomes on today's reasons; success-keying generalizes.)

It is preferred over changing `dispatch_validated`'s return contract (e.g. returning
`(reason, info_only)` tuples) because that is a shared cross-callsite helper — per
CLAUDE.md, altering its signature would force a repo-wide caller migration for no
added correctness. The callsite already computes the success variable (`if out is None`).

### New helper

```python
def _record_dispatch_reasons(state: dict, reasons: list[str], *, ok: bool) -> None:
    """Record dispatch_validated reasons onto the run state. (CCE-118)

    A dispatch that returned usable output (ok=True) can only carry benign
    `prose_contamination_rescued` diagnostics — a schema failure forces the
    dispatch output to None — so its reasons are recorded info_only and must
    NOT flip `partial`. When the dispatch failed (ok=False) the reasons explain
    dropped work and DO flip `partial`.

    Advisory layers (fact-checker, deterministic generators) record info_only=True
    directly and do not route through this helper.
    """
    for r in reasons:
        add_partial(state, r, info_only=ok)
```

Each of the five callsites replaces its `for r in reasons: add_partial(state, r)`
loop with `_record_dispatch_reasons(state, reasons, ok=<success_var> is not None)`.
The `clip_reasons` loop at `:1360-1361` is left unchanged (not a dispatch rescue).

## What this fix does NOT change

- **Fact-checker _contradiction_ warnings still block auto-merge.** CCE-101 keys
  eligibility on _non-partial_ AND _zero fact-checker warnings_. A `verdict ==
"contradiction"` populates `fact_check_warnings` (a separate list) and correctly
  requires human review — docs contradicting source _should_ not auto-publish. This
  fix touches only the benign-rescue → partial path, never the warning gate. (#170
  also carried five contradiction warnings, so #170 itself would still have required
  a manual merge; the value here is that a _clean_ run no longer trips on a rescue.)
- Genuine dispatch failures (`out is None`) still flip partial.

## Testing (TDD)

The dry-run dispatch path (`dispatch_subagent:616-620`) returns the fixture JSON
directly and **cannot** produce a `prose_contamination_rescued` reason — so the test
must inject the reason at the `dispatch_validated` boundary and assert the public
`partial` flag through the real `run()` logic.

1. **Unit — the helper's contract.** `_record_dispatch_reasons(state, ["prose_contamination_rescued: page-author"], ok=True)`
   leaves `current_run.partial is False` yet records the reason in `partial_reasons`;
   `ok=False` flips `partial` to True. Fast, pins the policy.
2. **Integration — RED→GREEN through real `run()`.** Drive a full fixture dry-run
   `run()`, monkeypatching `orchestrator_runner.dispatch_validated` so the
   **page-author** call returns its normal fixture output plus a
   `prose_contamination_rescued: page-author` reason (simulating a prose-wrapped but
   valid page-author response). Assert `read_current_run(state)["partial"] is False`
   and the reason appears in `partial_reasons`. **RED before the fix** (callsite flips
   partial), **GREEN after**. Per CLAUDE.md: assert the real consumer's behavior (the
   partial flag) — not the helper directly.
3. **Regression — a real failure still flips partial.** Same harness, but the injected
   dispatch returns `out=None` with a `schema_invalid: page-author …` reason: assert
   `partial is True`. Guards against the fix silently swallowing genuine failures.
4. **Reason-string fidelity.** Confirm (reusing the existing CCE-15 rescue test if one
   exists, else add one) that a production `dispatch_validated` on prose-wrapped valid
   JSON actually returns `(dict, ["prose_contamination_rescued: <name>"])` — so the
   string the helper treats as benign matches what the dispatch really emits.
5. **Suite:** full `python3 -m pytest` green.

## Acceptance criteria (mapped to ticket item 1)

1. A blocking-pipeline dispatch that succeeds via prose-contamination rescue no longer
   flips the run to `partial`; the reason is still recorded in `partial_reasons`
   (info*only). *(AC 1)\_
2. A blocking-pipeline dispatch that genuinely fails (`out is None`) still flips
   `partial`. _(AC 2)_
3. Fact-checker advisory reasons and the contradiction-warning gate are unchanged.
   _(AC 3)_
4. Verifiable on the next nightly: a run whose only partial reasons are
   `prose_contamination_rescued` is marked non-partial and becomes auto-merge-eligible.
   _(AC 4 — observational, post-merge.)_

## Out of scope (tracked under CCE-118 items 2 & 3)

- Item 2: page-author verbatim frontmatter for agent-authored creates (deferred Option 3).
- Item 3: `_DESC_MIN_WORDS` host-override coupling.
  These are independent of the partial-flagging fix and get their own spec/plan when picked up.
