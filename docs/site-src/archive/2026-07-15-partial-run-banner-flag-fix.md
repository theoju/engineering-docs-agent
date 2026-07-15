---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/177
synthesized_into: []
doc_kind: decision
---

# CCE-121: Partial-Run Banner Must Key Off the `partial` Flag, Not Reason Presence

**Date:** 2026-07-15
**PR:** #177
**Ticket:** CCE-121

## Problem

Nightly PR #176 (2026-07-14) auto-merged under the CCE-101 gate — proof the
run was non-partial — yet its PR body rendered a **"WARNING — Partial run"**
header. The run carried two `prose_contamination_rescued` reasons (one from
content-validator, one from fact-checker), both `info_only` per CCE-118. The
header treated their mere presence in `partial_reasons` as grounds for the
warning, mislabeling a clean, auto-merging run as broken.

## Root cause

`_format_partial_digest` (`scripts/orchestrator_runner.py:2352`) formats the
`partial_reasons` list for two consumers: the PR body composer and
`_write_step_summary`. Before this fix it took only `partial_reasons` as
input and always rendered the `"WARNING — Partial run"` header whenever the
list was non-empty:

```python
def _format_partial_digest(partial_reasons: list[str]) -> str:
    if not partial_reasons:
        return ""
    lines = ["WARNING — Partial run", ""]
    ...
```

That logic predates CCE-118. Before CCE-118, a non-empty `partial_reasons`
list and a `partial=True` run were the same fact — any reason was a
partial-flipping reason. CCE-118 broke that equivalence: it routed
blocking-pipeline dispatch reasons through `_record_dispatch_reasons`
(`scripts/orchestrator_runner.py:781`), which records a dispatch that
returned usable output as `info_only=True` — a benign JSON-rescue diagnostic
that does not flip `partial`. After that change, `partial_reasons` could be
non-empty on a genuinely non-partial run, but the banner logic never learned
the distinction. `_emit_exit_summary` already keyed its PARTIAL/INFO prefix
off the `partial` flag correctly — `_format_partial_digest` was the one
holdout still deriving state from list-presence instead of consulting the
flag that was already sitting on `state["current_run"]["partial"]`.

## Fix

`_format_partial_digest` gained a keyword-only `partial: bool = True`
parameter (the default preserves back-compat for any caller that hasn't been
updated to pass it):

```python
def _format_partial_digest(partial_reasons: list[str], *, partial: bool = True) -> str:
    if not partial_reasons:
        return ""
    header = (
        "WARNING — Partial run"
        if partial
        else "INFO — advisory notices (run not partial)"
    )
    lines = [header, ""]
    lines.extend(f"- {r}" for r in partial_reasons)
    return "\n".join(lines)
```

All three call sites now thread the run's actual `partial` flag through:

- `_compose_pr_body` (`scripts/orchestrator_runner.py:2410`) — two call
  sites internally: the partial-only early-return path at line 2447, and the
  full-sections path at line 2478.
- `_write_step_summary` (`scripts/orchestrator_runner.py:2533`) — passes
  `bool(cr.get("partial"))` from `current_run`.

A genuinely partial run (a real dispatch failure, a schema-invalid subagent
output, a dropped page) still renders the warning header — only a clean run
whose only `partial_reasons` entries are `info_only` advisories gets the new
`"INFO — advisory notices (run not partial)"` header. The reasons themselves
are still listed under either header; only the header text and severity
framing change.

## Non-goals

This is a display-only fix. It does not change:

- How `partial` is computed or when a reason flips it (`add_partial`,
  `_record_dispatch_reasons`) — that logic is CCE-118's.
- CCE-101 auto-merge eligibility, which already reads the `partial` flag
  directly and was never affected by the mislabeled banner.
- `add_partial`'s `info_only` semantics.

## Verification

`tests/orchestrator/test_partial_banner_flag.py` pins the behavior at three
levels:

- `_format_partial_digest` directly: `partial=True` keeps the warning header,
  `partial=False` switches to the INFO header, an empty reasons list is blank
  under either flag value, and the no-flag call defaults to the warning
  header (back-compat).
- `_compose_pr_body`: a non-partial run with only `prose_contamination_rescued`
  reasons renders the INFO header (the nightly #176 scenario, reproduced
  directly); a genuinely partial run still warns.
- `_write_step_summary`: same partial/non-partial split, asserted against the
  `$GITHUB_STEP_SUMMARY` file contents.

## Related

- CCE-118 — made benign `prose_contamination_rescued` reasons `info_only`
  (the change that first made `partial_reasons` non-empty on a non-partial
  run).
- CCE-120 — orchestrator-injected `pr_id` for gap-detector verdicts; the
  immediately preceding fix in the same nightly-partial incident series.
- CCE-101 — the auto-merge gate whose eligibility this banner was
  incorrectly implying was compromised.
