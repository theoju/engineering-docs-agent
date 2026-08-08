---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/191
synthesized_into: []
doc_kind: decision
---

# CCE-124: archive-lens `citation_exists` advisory via per-result lint severity

## Problem

`citation_exists` is a Tier-1 block rule: every inline-code span in a page's
prose that looks like a repo path or a `test_*` identifier must resolve
against the current HEAD, or the page fails the build. That contract is
correct for live documentation — a confabulated citation there is a real
navigation defect.

It is the wrong contract for an archive page. An archive page is a frozen
historical record; its citations were true as of archival and can legitimately
name code that has since moved or been removed by design. This is exactly what
happened to the CCE-122 archive page: it cited `tests/scripts/__init__.py` —
absent on purpose, per CCE-122's own rule that `tests/scripts/` must not be a
package — and `test_lint_runner`, a test-family shorthand rather than a real
identifier. `citation_exists` blocked the page every time page-author
re-authored it, the orchestrator excluded it from the PR, and the nightly run
went `partial` on repeat (root-caused from PR #189).

## Decision

Promote lint severity from rule-global to per-result, and scope the block to
live lenses only. `citation_exists` now resolves the host's archive-index
section from `site.sections` and emits `severity: "warn"` — not `"block"` —
for any page living under that section's directory, while every other page
keeps the existing hard block.

The resolution logic (`archive_dirs`) reads `site.docs_dir` and joins it to
each `sections` entry whose `generator` is `"archive-index"`; a page is
archive-lens if its resolved path falls under one of those directories
(`_under`), all in `scripts/lint/citation_exists.py`. A host with no such
section — or no `site:` block at all — gets an empty list back, so every page
stays hard-blocked: byte-for-byte the pre-CCE-124 behavior.

`check_path` in the same file is unchanged; it still decides `ok`/`not ok` by
checking whether a cited path, test, or `:symbol` actually exists. What
changed is only what happens to a `not ok` result: `main` now tags each result
with `severity` (`"warn"` under an archive dir, otherwise the module's
`"block"` default) instead of unconditionally treating every failure as
block-worthy.

`scripts/lint/lint_runner.py` had to learn to read that per-result field. Its
block-gate now checks `r.get("severity", out.get("severity")) == "block"` for
each failing result, falling back to the rule's top-level `severity` when a
result carries none — which is every rule except `citation_exists`, so their
behavior is byte-for-byte unchanged. `agents/content-validator.md` documents
the same per-result-first, rule-global-fallback contract for its own
`failed[]` parsing step, since it's the agent that ultimately turns lint
output into a structured pass/fail list for the orchestrator.

Nothing downstream of content-validator changed: the orchestrator already
gates page-exclusion and the `partial` reason on `fail.severity == "block"`,
so a `warn` result leaves the archive page in the PR with a note in the run
digest instead of a silent re-exclusion loop.

## Tradeoff accepted

A genuinely confabulated citation in a future archive page now only warns —
it will not block the build. That's accepted: archive pages are low-traffic
historical records generated from already-reviewed specs and plans, the
finding still surfaces in the digest, and a permanent partial-run loop on a
page that can never pass is strictly worse than an occasional missed warning.
Live-lens pages are unaffected; they keep the hard block.

## Known gap

There is no executing end-to-end test of the full chain from a `warn` result
through content-validator's parsing to the orchestrator's page-inclusion
decision. The middle link is an LLM prose contract (content-validator's own
job description), and the orchestrator endpoint it feeds is unchanged — it
already gated on `fail.severity == "block"` before this change — so the gap
was judged ship-acceptable rather than blocking.
