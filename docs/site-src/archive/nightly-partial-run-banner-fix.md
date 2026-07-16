---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/177
synthesized_into: []
doc_kind: decision
---

# Nightly partial-run banner now matches the actual `partial` flag

PR #177 fixes a display bug: a clean, auto-merge-eligible nightly run could still
show a scary "WARNING — Partial run" banner in its PR body and GitHub step
summary, purely because it carried benign advisory reasons.

## The bug

CCE-118 made prose-contamination rescues (a subagent's valid JSON arriving
wrapped in extra prose, recovered by `_rescue_json_object` and successfully
schema-validated) `info_only`. Those rescues get recorded in
`partial_reasons`, but they deliberately do not flip the run's `partial` flag
— the run is genuinely fine.

The banner logic didn't know that. `_format_partial_digest` inferred severity
from whether `partial_reasons` was non-empty, not from the `partial` flag
itself. So a non-partial run with only info-only reasons attached still
rendered the warning header. Nightly PR #176 is the exemplar: it auto-merged
under the CCE-101 gate — non-partial, zero fact-checker warnings — yet its PR
body displayed "WARNING — Partial run" over two
`prose_contamination_rescued` entries.

## The fix

`_format_partial_digest` in `scripts/orchestrator_runner.py` now takes an
explicit `partial` parameter instead of deriving severity from list
presence. That flag is threaded through all three call sites:
`_compose_pr_body`'s two invocations and `_write_step_summary`.

The result:

- `partial=True` → "WARNING — Partial run" header (unchanged for genuinely
  partial runs).
- `partial=False` → "INFO — advisory notices (run not partial)" header. The
  reasons themselves still list out for the operator — only the header
  severity changes.
- Callers that omit the flag keep the old warning-header default, for
  back-compat.

This is display-only. It does not touch the `partial` flag itself, auto-merge
eligibility under the CCE-101 gate, or `add_partial` semantics — those were
already correct after CCE-118; only the banner text was lying about them.

Regression coverage lives in
`tests/orchestrator/test_partial_banner_flag.py`, including a case that
mirrors nightly PR #176 directly (`test_compose_pr_body_non_partial_with_info_reasons_uses_info_header`).

## Where this fits

This is the latest entry in the nightly-partial-surface hardening series:
CCE-118 made benign rescues info-only, CCE-120 fixed gap-detector `pr_id`
injection, and CCE-121 (this page) aligns the banner with the flag both of
those already agree on.
