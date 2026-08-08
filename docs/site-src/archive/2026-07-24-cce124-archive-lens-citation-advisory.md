---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/191
synthesized_into: []
doc_kind: decision
---

# CCE-124 — archive-lens `citation_exists` advisory via per-result lint severity

Ticket: CCE-124 · PR #191 · 2026-07-23

## Problem

`citation_exists` (Tier-1, rule-global `severity = "block"`) treats every inline-code span in a page's prose as a repo citation that must resolve against the current tree. That's correct for live-lens pages — a confabulated citation there is a real navigation defect.

It's the wrong contract for an archive page. An archive page is a historical record generated from a spec/plan; its citations are true *as of archival* and can legitimately name code that has since moved, been removed, or is discussed as a thing that must *not* exist. The CCE-122 archive page (its own citation-migration writeup) cites `` `tests/scripts/__init__.py` `` — absent by design, per CCE-122's own rule that `tests/scripts/` must not be a package — and `` `test_lint_runner` `` as a test-family shorthand rather than a single defined identifier. `citation_exists` hard-blocked that page, the orchestrator excluded it, and every nightly run went `partial` re-authoring it. That was the recurring-partial root cause tracked as PR #189: enforcing current-HEAD existence against a frozen historical record is a category error.

## Decision

Promote lint severity from rule-global to per-result. `citation_exists` now resolves the archive-lens directories declared in the host config (`site.sections` entries with `generator: archive-index`, joined under `site.docs_dir`) via `archive_dirs()` in `citation_exists.py`, and computes each result's severity as `"warn" if _under(p, arch) else SEVERITY`. A page under one of those dirs gets `warn` for citation-existence failures; every other page keeps the hard `block`. `lint_runner`'s aggregation in `main()` walks each rule's `results` list and honors a result's own `severity` field, falling back to the rule-global value for rules that don't set one:

```python
for r in out["results"]:
    if not r["ok"] and r.get("severity", out.get("severity")) == "block":
        any_block_failed = True
        break
```

Of the 18 Tier-1/2/3 rules registered in `TIER1_DEFAULT`/`TIER2_CONFIG_KEYS`/`TIER3_CONFIG_KEYS`, `citation_exists` is the only one that currently sets a per-result override; every other rule inherits the rule-global severity exactly as before.

`agents/content-validator.md` already documented the parsing contract for a per-result `severity` field (`content_validator.schema.json` already permits `enum: ["block", "warn"]`), so the only doc change needed there was clarifying that a `failed[]` item's severity comes from the result itself when present, falling back to the rule's top-level severity otherwise.

## Why this shape

The orchestrator already gates page-exclusion and the `lint_block` partial reason on `fail.severity == "block"` rather than on `citation_exists` failing at all — so downgrading specific results to `warn` at the lint layer was sufficient. `scripts/orchestrator_runner.py` needed **no change**. That made per-result severity the smallest change that fixes the actual defect: the policy applied to a citation-existence failure, not the detection of one.

Per-result severity is also durable independent of how the archive page is regenerated — it's a property of *where the page lives*, not of a specific generation run — and it's general enough that a future rule can reuse the same `severity` per-result convention without inventing a new mechanism.

## Alternatives considered (rejected)

- **Exempt archive pages from `citation_exists` entirely.** Rejected: it would silence a genuinely confabulated citation on an archive page with no signal at all. Advisory `warn` keeps the finding visible in the run digest.
- **A per-token "negative citation" opt-out marker** for the rare live-page case where a citation intentionally names absent code. Deferred as YAGNI — no live-page case has needed it yet.

## Tradeoff accepted

A genuinely confabulated citation in a *future* archive page now only warns, it doesn't block. Accepted because archive pages are low-navigation historical records derived from already-reviewed specs/plans, the finding still surfaces in the run digest, and a permanent partial-run loop is strictly worse than a missed block on a low-traffic page. Live-lens pages are unaffected — they keep full enforcement.

## Known gap

This shipped without an executing end-to-end test of the full `warn` → `content-validator` → orchestrator chain. Coverage stops at `lint_runner`'s aggregation logic (`tests/lint/test_lint_runner.py`) and `citation_exists`'s archive-dir resolution (`tests/lint/test_citation_exists.py`). Noted in the originating PR as ship-acceptable, not an oversight.

## Outcome

Generic-first: a host config with no `archive-index` section resolves zero archive dirs, so every result stays `block` — byte-for-byte identical to pre-CCE-124 behavior. On this repo, the archive-lens citation on the CCE-122 page now warns instead of blocking, and the recurring-partial pattern from PR #189 stops. See `architecture/lint-severity-model.md` for the resulting mechanism as it applies going forward.
