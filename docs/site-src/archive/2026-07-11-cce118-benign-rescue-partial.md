---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/171
synthesized_into: []
doc_kind: decision
---

# A benign JSON rescue no longer flips a run to `partial`

Every nightly run that triggered a JSON rescue on a blocking-pipeline subagent
used to come out marked `(partial)` — even when every page authored cleanly
and nothing actually failed. A partial run is ineligible for CCE-101
auto-merge, so a run that did everything right still needed a human to merge
it by hand. PR #170 (2026-07-11) is the exemplar this fix closes.

## Root cause

The ticket that opened this investigation (CCE-118) assumed the culprit was
fact-checker output robustness — `schema_invalid: fact-checker`,
`fact_checker_unavailable`, and the fact-checker's own
`prose_contamination_rescued`. That hypothesis was wrong. The fact-checker
dispatch already records all of its reasons `info_only=True`
(`scripts/orchestrator_runner.py:run` and `:1713`, per the CCE-110 advisory-layer
design), so none of those three ever flipped `partial`.

PR #170's actual `partial_reasons` were:

```
prose_contamination_rescued: page-author       ← the ONLY one that flipped partial
schema_invalid: fact-checker: 'ok' is a required property   (info_only — no effect)
fact_checker_unavailable: .../lint-rules.md                 (info_only — no effect)
prose_contamination_rescued: fact-checker                   (info_only — no effect)
```

The real bug was in the **blocking-pipeline dispatch callsites** —
source-collector, pr-summarizer, page-author, content-validator,
gap-detector, and notifier. Each recorded its dispatch reasons with:

```python
for r in reasons:
    add_partial(state, r)          # default info_only=False → flips partial
```

`add_partial` with the default `info_only=False` unconditionally sets
`current_run.partial = True`. So when a dispatch *succeeded* — the subagent
returned valid JSON wrapped in prose, `_rescue_json_object` recovered it, and
the schema validated it — the reason `prose_contamination_rescued: <name>`
still flipped the whole run to partial, even though no work was lost.

The invariant that makes this fixable cleanly: `dispatch_validated` returns
usable output (`out is not None`) *only* when the recovered object passes
schema validation; a schema failure forces `out = None`. So a reason riding
on a successful dispatch can only ever be `prose_contamination_rescued` —
never a genuine-failure reason. It's a diagnostic, not a degradation.

## The fix

A new helper, placed next to `dispatch_validated` in
`scripts/orchestrator_runner.py`:

```python
def _record_dispatch_reasons(state: dict, reasons: list[str], *, ok: bool) -> None:
    for r in reasons:
        add_partial(state, r, info_only=ok)
```

The six blocking-pipeline callsites now call
`_record_dispatch_reasons(state, reasons, ok=<success_var> is not None)`
instead of looping over `add_partial` directly. A successful-but-rescued
dispatch records its reason `info_only=True` (visible in `partial_reasons`,
no partial flip); a genuinely failed dispatch (`out is None`) still records
`info_only=False` and flips `partial` as before.

Keying on dispatch success — rather than string-matching
`reason.startswith("prose_...")` — was the deliberate choice: it's
semantically exact, and it auto-classifies any future benign reason type a
successful dispatch might emit, without a maintained allow-list. Changing
`dispatch_validated`'s return contract to carry `(reason, info_only)` tuples
directly was considered and rejected — it's a shared cross-callsite helper,
and per the plugin's shared-helper-as-contract convention, changing its
signature would force a repo-wide caller migration for no added correctness.

## What this does not change

Fact-checker advisory reasons and the contradiction-warning auto-merge gate
are untouched. CCE-101 eligibility still keys on *non-partial* **and** *zero
fact-checker warnings* — a `verdict == "contradiction"` still populates
`fact_check_warnings` and still requires a human merge, because docs that
contradict their source should not auto-publish. This fix only touches the
benign-rescue-to-partial path. (PR #170 itself also carried five
contradiction warnings, so it would still have needed a manual merge under
this fix — the payoff is that a genuinely clean run no longer trips on a
rescue.)

Genuine dispatch failures (`out is None`) still flip `partial`, unchanged.

## Testing

`tests/orchestrator/test_record_dispatch_reasons.py` pins the helper's
contract directly: `ok=True` records the reason without flipping `partial`;
`ok=False` flips it; an empty reasons list is a no-op.

`tests/orchestrator/test_benign_rescue_not_partial.py` drives the real
`run()` end to end, monkeypatching `dispatch_validated` so the page-author
call returns its normal fixture output plus an injected
`prose_contamination_rescued: page-author` reason, and asserts
`partial is False` with the reason still present in `partial_reasons`. A
paired regression test injects a genuine page-author failure
(`out=None` with a `schema_invalid` reason) and asserts `partial is True`.

## Scope note

CCE-118 originally bundled three items. This fix covers only item 1 (the
partial-flag defect above). The other two — page-author's verbatim
frontmatter handling for agent-authored creates, and the `_DESC_MIN_WORDS`
host-override coupling — were split out to CCE-119 as unrelated residuals.
