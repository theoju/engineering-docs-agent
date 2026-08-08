---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/191
synthesized_into: []
doc_kind: decision
---

# Archive-lens citations are advisory, not blocking

`citation_exists` (Tier-1, normally `block`) now emits **per-result** severity
instead of one severity for the whole rule. A page that lives under an
`archive-index`-generator section gets `warn` for an unresolved code citation;
every other lens still gets the hard `block`. Nothing else about the check
changes — it still verifies that a cited `path/to/file.py`, `path/to/file.py:line`,
`path/to/file.py:symbol`, or `test_snake_case` token actually resolves against
the repo.

## Why archive pages need a different contract

An archive page is a frozen historical record generated from a spec or plan at
a point in time. Its citations were true *as of archival* — they can legitimately
name code that has since moved, been removed, or is being described as
forbidden-by-design. Requiring those citations to resolve against current HEAD
is a category error, and it wasn't hypothetical: the CCE-122 archive page cites
`` `tests/scripts/__init__.py` ``, which is absent *by design* per CCE-122's own
rule ("`tests/scripts/` must NOT be a package"), and `` `test_lint_runner` ``, a
test-family shorthand rather than a real symbol. `citation_exists` blocked that
page every run, the orchestrator excluded it, and the nightly build went
`partial` on a loop — tracked as the recurring failure in PR #189.

Demoting the check to advisory on archive-lens pages keeps the signal (the
warning still lands in the run digest) while removing its power to gate the
page out of the build or flip the run `partial`.

## How the lens is resolved

`citation_exists.py:archive_dirs` reads the host config's `site.sections` and
collects the resolved directory of every section whose `generator` is
`archive-index`, joined under `site.docs_dir` and the git repo root. A path is
archive-lens if it resolves inside one of those directories
(`citation_exists.py:_under`). A host with no `archive-index` section — or no
`site` block at all — gets an empty list, so every page keeps the hard block:
identical to the pre-CCE-124 behavior. An unreadable or invalid config YAML
degrades the same way, via `citation_exists.py:_load_config`.

`main()` in `scripts/lint/citation_exists.py` computes this per invocation and
sets each result's `severity` to `"warn"` when the checked path is under an
archive dir, else the module default `"block"`. The rule's top-level
`severity` field stays `"block"` for backward compatibility; only the
per-result value carries the archive-lens downgrade, and only a failing
`block`-severity result flips the process exit code to `1`.

## Where the gate actually lives

`scripts/lint/lint_runner.py`'s block-gate reads that per-result field:

```python
for r in out["results"]:
    if not r["ok"] and r.get("severity", out.get("severity")) == "block":
        any_block_failed = True
        break
```

A result with no `severity` key falls back to the rule's top-level value, so
every other Tier-1 rule behaves exactly as before — only `citation_exists`
currently emits a per-result override. `agents/content-validator.md` forwards
that same per-result-over-rule-level precedence when it turns lint output into
`failed[]` entries for the run.

The orchestrator needed no change: it already excludes a page and records the
`lint_block` partial reason only when `fail.get("severity") == "block"`, so a
`warn` result leaves the page in the PR and adds nothing to the partial-reason
list.

## Accepted tradeoff

A genuinely confabulated citation in a *future* archive page now warns instead
of blocking. That's accepted: archive pages are low-navigation historical
records derived from already-reviewed specs and plans, the finding still
surfaces in the digest for a human to catch, and a permanent partial-run loop
on a page that can never be fixed (because the citation is correct-as-archived)
is strictly worse. Live lenses — `api`, `architecture`, `host-onboarding`,
`whats-new`, and this `core` lens itself — are unaffected; a bad citation there
still blocks the build.
