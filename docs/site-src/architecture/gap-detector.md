---
description: 'Documents architecture gap detector: The gap-detector agent''s documented "couldn''t judge" fallback, needs_spec: null, is now treated as a first-class advisory "unjudged" signal instead of a schema failure. The gap_detector.schema.json (and its lockstep canonical block in agents/gap-detector.md) now accepts ["boolean","null"] for needs_spec while still requiring the key. In the orchestrator, a validated null verdict records an info-only gap_detector_unjudged reason and is skipped (never appended to gap_verdicts or the CCE-89 digest), so the nightly run no longer flips to partial on this signal. Genuine structural failures — an absent needs_spec key, a wrong non-null type, or unparseable output — still fail schema validation and still flip the run to partial, preserving the malfunction signal. The contracts.py dataclass and the published API contract doc for gap_detector were updated to match.'
source_files:
  - agents/gap-detector.md
  - agents/schemas/gap_detector.schema.json
  - docs/site-src/api/contracts/gap_detector.schema.md
  - docs/superpowers/plans/2026-07-23-cce125-gap-detector-unjudged-advisory.md
  - docs/superpowers/specs/2026-07-23-cce125-gap-detector-unjudged-advisory-design.md
  - scripts/contracts.py
  - scripts/orchestrator_runner.py
  - tests/contracts/test_contracts.py
  - tests/orchestrator/test_fact_checker.py
  - tests/orchestrator/test_gap_detector_unjudged.py
last_reviewed: '2026-08-08'
status: draft
---
# Gap Detector

`gap-detector` (`agents/gap-detector.md`) judges whether a merged PR is non-trivial enough that a senior engineer would expect a spec or plan to accompany it. The orchestrator dispatches it once per admitted PR, in the gap-detection loop near the end of `run()` (`scripts/orchestrator_runner.py:run`), after page authoring, content validation, and the fact-checker warn layer have already run for that batch.

## Tiered heuristic

Per the agent's Job, the verdict comes from a tiered heuristic — allowlist beats size filter beats LLM judgment:

1. If the PR's `pr_id` is in `dismissed_flags` (host config carries `dismissed_gap_flags`, previously dismissed by a human), return `needs_spec: false`, `tier: "dismissed"`.
2. If any changed file matches `config.allowlist_paths`, return `needs_spec: true`, `tier: "allowlist"`.
3. If `total_loc` and `files_count` are both below `size_filter.{min_loc, min_files}`, return `needs_spec: false`, `tier: "size_filter"`.
4. Otherwise, apply LLM judgment against the PR title, body, and file list — `tier: "llm"`.

The orchestrator injects `pr_id` onto the verdict via `dispatch_validated`'s `inject` parameter (`scripts/orchestrator_runner.py`) rather than trusting the agent to echo it back, so identity is always orchestrator-authoritative regardless of what the LLM reproduces.

## Output schema and the `needs_spec` type

The canonical schema (`agents/schemas/gap_detector.schema.json`, mirrored verbatim in the fenced block of `agents/gap-detector.md`) requires `needs_spec` but types it as `["boolean", "null"]`:

```json
{
  "required": ["pr_id", "needs_spec"],
  "properties": {
    "needs_spec": { "type": ["boolean", "null"] }
  }
}
```

`null` is not a malfunction — it's the agent's documented fallback when inputs are malformed and it genuinely cannot judge: `{"error": "malformed_input", "needs_spec": null}`. The two files are kept in lockstep by `tests/agents/test_schema_md_sync.py`, which asserts `json.loads`-equality between the fenced block and the `.json` file; whenever one changes, the other must change in the same commit. `scripts/contracts.py`'s `GapVerdict` dataclass types the field as `needs_spec: bool | None` to match — cosmetic at runtime, since `contracts.validate_and_parse` (`scripts/contracts.py`) is the actual gate and `dispatch_validated` (`scripts/orchestrator_runner.py`) returns the raw dict to callers, not the dataclass instance.

## Advisory status: gap-detector never flips the run partial on its own account

`gap-detector` is an advisory agent, same category as `fact-checker`. Its verdict only ever produces a "Gaps flagged" note in the What's New entry — that note is not part of the CCE-101 auto-merge gate, which keys off `partial`, fact-checker warnings, and human commits. A PR the agent "couldn't judge" degrading the whole nightly run to `partial` was a bug, not a feature: it blocked auto-merge on a signal that was never meant to gate anything.

Before this fix, a present-but-`null` `needs_spec` failed `jsonschema.validate` outright — `contracts.validate_and_parse` returned `(None, ["schema_invalid: gap-detector: None is not of type 'boolean'"])`, and at the callsite `_record_dispatch_reasons(state, reasons, ok=verdict is not None)` saw `ok=False`, which calls `add_partial` with `info_only=False`. That's exactly the failure mode that produced PR #189's partial nightly run.

Now the schema accepts `null`, so the verdict validates and `_record_dispatch_reasons` sees `ok=True` — any reasons it carries are recorded `info_only`. Immediately after the dispatch, the gap loop checks the verdict explicitly:

```python
if verdict.get("needs_spec") is None:
    # CCE-125: a validated null needs_spec is the agent's "couldn't
    # judge" sentinel — advisory, not dropped work. Record it
    # info-only and skip it (never appended, so it stays out of
    # "Gaps flagged" and the digest); the run stays non-partial.
    add_partial(
        state,
        f"gap_detector_unjudged: pr_id={pr_id}",
        info_only=True,
    )
    continue
```

This lives in `scripts/orchestrator_runner.py`, between the dispatch and `gap_verdicts.append(verdict)`. The `null` verdict is recorded as an info-only `gap_detector_unjudged: pr_id=...` reason and then dropped — it is never appended to `gap_verdicts`, so it can't surface in the "Gaps flagged" What's New section or the CCE-89 digest. Without this explicit record, the dropped `error` field on the raw agent output would leave no trace of *why* that PR went unjudged; the reason exists purely for observability, not to gate anything.

## What still flips partial

Only genuine structural failure still flips the run:

| Agent output | Result |
| --- | --- |
| `needs_spec: null` (present) — the documented malformed-input fallback | validates → info-only `gap_detector_unjudged`, no partial, no gap-note |
| `needs_spec` absent (key omitted) | fails schema (`needs_spec` is still `required`) → partial |
| `needs_spec` wrong non-null type (e.g. `"yes"`) | fails schema → partial |
| unparseable / no JSON from the dispatch | `dispatch_validated` returns `None` → partial |

The absent-key case is locked by a separate regression test (`test_missing_needs_spec_still_flips_partial`, alongside `tests/orchestrator/test_gap_detector_unjudged.py`'s null-verdict coverage) precisely so a future change can't quietly widen the advisory carve-out to cover a real agent malfunction. `tests/orchestrator/test_gap_detector_unjudged.py` runs the null-verdict case through the real `run()` on the dry-run fixture path and asserts all three properties at once: `partial is False`, a `gap_detector_unjudged: pr_id=...` reason is present, and the What's New file contains no "Gaps flagged" section for that PR.

## Net effect

A PR that gap-detector can't judge no longer costs the nightly run its auto-merge eligibility. The distinction that matters — "the agent ran and genuinely couldn't decide" versus "the agent's output is structurally broken" — is now encoded in the schema itself (`["boolean", "null"]`, `null` present vs. key absent) rather than left for the orchestrator to infer, so it holds deterministically regardless of what the underlying LLM happens to emit on a given run. This closed the last recurring partial-run driver identified from PR #189, alongside the two already-fixed drivers: citation_exists severity (CCE-124) and `prose_contamination_rescued` (CCE-118, and locked here for the fact-checker path by `tests/orchestrator/test_fact_checker.py`).
