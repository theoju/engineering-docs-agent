---
description: 'Documents architecture lint severity model: citation_exists (a Tier-1 doc-lint rule that verifies code citations in docs still resolve to a real file/symbol) now emits per-result severity instead of a single rule-global severity. Pages that live under an archive-index-generator section (a frozen historical record) get severity ''warn'' for citation-existence failures, while pages in live lenses keep the hard ''block''. lint_runner''s block-gate now honors a result''s own severity field, falling back to the rule-global severity for the 18 rules that don''t set one. No orchestrator changes were needed since it already gates page-exclusion and the lint_block partial reason on fail.severity == ''block''.'
source_files:
  - agents/content-validator.md
  - docs/superpowers/plans/2026-07-23-cce124-archive-lens-citation-advisory.md
  - docs/superpowers/specs/2026-07-23-cce124-archive-lens-citation-advisory-design.md
  - scripts/lint/citation_exists.py
  - scripts/lint/lint_runner.py
  - tests/lint/test_citation_exists.py
  - tests/lint/test_lint_runner.py
last_reviewed: '2026-08-08'
status: draft
---
# Lint severity model

Every lint rule has a rule-global `severity` — `block` prevents the page from publishing, `warn` surfaces in the PR review only. Until CCE-124, that was the only granularity available: a rule was block for every page it ran against, or it wasn't. `citation_exists` now carries a **per-result** severity as well, and `lint_runner`'s block-gate honors it.

## The problem this closes

`citation_exists` (Tier-1, rule-global `severity = "block"`) verifies that every inline-code citation in a page's prose — a repo path, a `path:symbol` pair, a `test_*` identifier — actually resolves against the current tree. That's the right check for live-lens pages: a citation to a file or symbol that no longer exists is a confabulation.

It's the wrong check for archive pages. A nightly run hit a recurring `partial` (PR #189) because `citation_exists` hard-blocked a page under the archive-index section — a frozen historical record (the CCE-122 citation-migration writeup) that legitimately cites code removed, or a test-family shorthand symbol, by design. Enforcing current-HEAD existence against a record that's true *as of archival* is a category error: the citation was correct when the page was written, and the page isn't meant to track HEAD forward.

## Per-result severity contract

`agents/content-validator.md` already documents the shape `content-validator` must parse: each failing result carries `path`, `rule`, `severity`, `message`, and `severity` is constrained to `enum: ["block", "warn"]`. CCE-124 makes that field genuinely per-result rather than a copy of the rule-global value. Per the agent's procedure, `content-validator` takes a failing path's severity from that **result's own** `severity` field when present, and falls back to the rule's top-level `severity` only when the result doesn't set one.

## `citation_exists`: archive-lens advisory

`archive_dirs()` in `scripts/lint/citation_exists.py` resolves the on-disk directories of every `site.sections` entry whose `generator` is `archive-index`, anchored under the config's `docs_dir`. It returns an empty list when the host declares no such section — the generic-first default, identical to pre-CCE-124 pure-block behavior.

`main()` computes each result's severity as `"warn" if _under(p, arch) else SEVERITY` (`_under` resolves the page path and checks whether it falls inside one of the archive dirs), and only counts a failure toward `any_block_failed` — the script's own exit code — when that computed severity is `block`. So a bad citation on an archive page still fails (`ok: false`) and still carries a message, but it no longer flips `citation_exists.py`'s own exit code, and the JSON result carries `"severity": "warn"` even when the page is clean (an advisory tag present on passing results too, so the archive-lens exemption is visible in the raw output, not just inferred from a passing exit code). A live-lens page hitting the identical bad citation still gets `"severity": "block"` and still fails the run.

## `lint_runner`: honoring per-result severity

`lint_runner.main()` used to fail the aggregate run whenever any rule's own exit code, or its rule-global severity, indicated a block. It now walks each rule's `results` list directly:

```python
for r in out["results"]:
    if not r["ok"] and r.get("severity", out.get("severity")) == "block":
        any_block_failed = True
        break
```

That's the whole change: `r.get("severity", out.get("severity"))` reads the per-result field first and falls back to the rule-global severity when a result doesn't set one. Of the rules registered across Tier 1 default, Tier 2, and Tier 3 (`TIER1_DEFAULT`, `TIER2_CONFIG_KEYS`, `TIER3_CONFIG_KEYS` in `scripts/lint/lint_runner.py`), `citation_exists` is the only one that currently emits a per-result override — the other 18 keep the byte-for-byte prior behavior of inheriting the rule-global severity.

## No orchestrator change required

The orchestrator already gates page-exclusion and the `lint_block` partial reason on `fail.severity == "block"` rather than on `citation_exists` failing at all, so downgrading specific results to `warn` at the lint layer was sufficient — the orchestrator's own logic didn't need to change to respect the new granularity.

## Known gap

The CCE-124 change ships without an executing end-to-end test of the full `warn` → `content-validator` → orchestrator chain; coverage stops at `lint_runner`'s aggregation logic (`tests/lint/test_lint_runner.py`) and `citation_exists`'s archive-dir resolution (`tests/lint/test_citation_exists.py`). That's a ship-acceptable gap noted in the originating PR, not an oversight — flag it if you're extending the severity model further.
