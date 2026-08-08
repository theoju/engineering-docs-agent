---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/193
synthesized_into: []
doc_kind: decision
---

# Advisory agents never flip a run to `partial`

`gap-detector` and `fact-checker` are advisory agents. A dispatch failure on either one is recorded info-only — it never flips a nightly run to `partial`. That gate belongs solely to the blocking pipeline: source-collector, pr-summarizer, page-author, content-validator, and notifier. Only those five flip `partial` on failure, via `_record_dispatch_reasons(state, reasons, ok=<dispatch produced usable output>)`.

## Why this distinction exists

An advisory agent's output only feeds a PR note. fact-checker's warnings land in `fact_check_warnings`; gap-detector's verdicts land in the "Gaps flagged" section. Neither is part of the CCE-101 auto-merge gate. So when an advisory agent merely "couldn't judge" — malformed input, a schema edge case, a transient dispatch failure — that must not degrade the run. Treating "couldn't judge" the same as "the pipeline broke" was the bug: it blocked the CCE-101 auto-merge gate on a signal that was never load-bearing for the gate in the first place.

fact-checker's dispatch failures were made info-only first, under CCE-118. gap-detector followed under CCE-125, closing the last recurring `partial` driver from nightly PR #189.

## The CCE-125 mechanism

gap-detector's documented malformed-input fallback returns `{"error": "malformed_input", "needs_spec": null}`. Before CCE-125, `needs_spec` was a required boolean in the schema, so this fallback failed its own schema — `validate_and_parse` returned `schema_invalid`, the callsite recorded it with `ok=False`, and the run flipped `partial`.

`needs_spec: null` is now a first-class "unjudged" value, not a schema failure:

- `gap_detector.schema.json` types `needs_spec` as `["boolean", "null"]` — the field is still `required`, only its type widened.
- A validated null verdict records an info-only `gap_detector_unjudged: pr_id=…` reason at the callsite.
- That verdict is **skipped** — never appended to the gaps list — so it's excluded from both "Gaps flagged" and the CCE-89 digest.
- The run stays non-`partial`.

Only *present*-`null` is downgraded. An absent `needs_spec` key, a wrong non-null type, or unparseable output still fails schema validation and still flips `partial`. The genuine-agent-malfunction signal is preserved — this change narrows what counts as a malfunction, it doesn't widen tolerance for actual breakage.

## Two traps this touched

**Schema and canonical block must move together.** When you change an agent's JSON schema, edit both `agents/schemas/<agent>.schema.json` and the canonical fenced block in `agents/<agent>.md` in lockstep. `tests/agents/test_schema_md_sync.py` asserts `json.loads`-equality between the two, so drift fails the build. After that, regenerate the published contract doc with `python scripts/contracts_doc.py --repo-root . --config <host-config>` — never hand-edit `docs/site-src/api/contracts/*.schema.md` directly.

**`dispatch_validated` returns the raw dict, not the dataclass.** Consumers reading a gap-detector verdict use `.get()`, not attribute access — the `GapVerdict.needs_spec: bool | None` type hint on the dataclass is cosmetic at runtime. The schema is the real gate, not the dataclass.

## What's still open

A general `ADVISORY_AGENTS` unification — one explicit set covering both fact-checker and gap-detector, rather than each callsite independently knowing which agents are advisory — is a deferred refactor.

## References

- Spec: `docs/superpowers/specs/2026-07-23-cce125-gap-detector-unjudged-advisory-design.md`
- CCE-125 (2026-07-23), CCE-118 (fact-checker precedent)
- `CHANGELOG.md` — Unreleased > Fixed
