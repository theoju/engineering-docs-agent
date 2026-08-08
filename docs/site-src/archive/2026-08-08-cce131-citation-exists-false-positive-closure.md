---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/200
synthesized_into: []
doc_kind: decision
---

# CCE-131 — `citation_exists` false-positive closure

`citation_exists` is a Tier-1 **block** rule: when it fails a page, the
orchestrator drops that page from the nightly docs PR rather than merely
warning. That made a false positive expensive on two consecutive nightlies.
PR #197 blocked on `cce-capability-c-canonical-core-citations.md` and
`cce-capability-c2-canonical-core-authoring.md`; PR #198 blocked on the
citations page again plus `content-validator.md`. Because the nightly
re-authors from scratch, the same page kept getting re-authored and
re-blocked — the failure read as chronic even though the set of pages caught
rotated run to run.

Four tokens were behind the two blocks, and all four were false positives:
`scripts/auth/session.py` (a fictional-host example that had sat on the
citations page since CCE-36, roughly ten weeks, without regressing anything),
`test_snake_case` (a metasyntactic placeholder that appears exactly once in
the repo — in `scripts/lint/citation_exists.py`'s own module docstring, where
it stands for "a token shaped like a test identifier"; the page-author read
the rule's source to document the rule, quoted the placeholder, and the rule
blocked the page for citing its own documentation), `tests/scripts/__init__.py`
(a file that must not exist per the CCE-122 namespace-collision invariant in
`CLAUDE.md`), and `test_lint_runner` (a test-family shorthand naming a group,
not one exact test).

## Why a page-scoped severity downgrade was rejected

CCE-124 already downgrades `citation_exists` to advisory for the `archive`
lens, on the reasoning that archive pages are historical records. The
obvious next move was to extend the same per-result severity downgrade to
`architecture/`. Two findings ruled it out.

**Page granularity is too coarse.** Severity is keyed on the result's path,
so the finest available scope is the page — and pages mix genuine defects
with false positives. `architecture/structured-docs-site-generation.md`
cites four non-resolving paths; three are real confabulations
(`scripts/build_doc_source_map.py`, `scripts/generate_archive_indexes.py`,
and `scripts/verify_docs_diagrams.py` each name a file that was renamed —
the real files are `scripts/source_map.py`, `scripts/archive_indexes.py`,
and `scripts/verify_diagrams.py`). A page-scoped downgrade on that page would
silence three real defects to clear one false positive. A full-corpus scan
found six such near-miss confabulations on `main`, including
`agents/schemas/page-author-output.json`, whose real name is
`agents/schemas/page_author.schema.json` — the token that blocked PR #197.
The rule was earning its keep in the same lens where it misfired.

**The severity signal is LLM-mediated.** The orchestrator never invokes
`scripts/lint/lint_runner.py` directly; it dispatches the `content-validator`
subagent, which runs the linter and re-emits a `failed` array. Per-result
severity reaches the orchestrator only because `agents/content-validator.md`
instructs the model in prose to carry it across. The schema marks `severity`
required, so a model that drops the field fails schema — but a model that
*defaults* it to `block` is schema-valid and silently re-blocks the page. A
fix whose failure mode is "the fix silently does not apply" is worse than no
fix, because it reports success. That is the same lesson CCE-125 drew about
trusting a schema-valid field over verifying it against external state.

## What shipped instead

A corpus scan (all non-fenced inline code spans on `main`, resolved against
`git ls-files` and an AST scan of every tracked Python file) found 39
non-resolving tokens across 20 of 94 pages — about 0.4 per settled page,
versus roughly 1.1 per freshly authored page on the PR #198 branch. That gap
is an authoring-defect rate, not corpus rot, which is why the fix touches
both the resolver and the authoring contract. Sorting the 39 tokens by why
they failed showed only one class needed a policy surface; the rest were the
rule being wrong about what exists.

The fix, entirely in `scripts/lint/citation_exists.py` and
`agents/page-author.md`:

- **Resolve docs-relative and build-output paths.** `check_path` now also
  resolves a cited path against the host's `docs_dir`, so a page citing a
  sibling page passes, and skips citations naming the mkdocs build-output
  directory — parsed from `mkdocs.yml` with a permissive YAML loader that
  degrades unrecognized tags (like mkdocs-material's `!!python/name:`) to
  `None` instead of aborting the whole parse. When no mkdocs config parses at
  all, nothing is skipped — a host with no such config never gets `site/`
  treated as a permanently reserved prefix.
- **Match test-family shorthand.** `cited_test_exists` now also matches
  `def <name>_`, so `test_lint_runner` resolves against
  `test_lint_runner_missing_script_reports_block` without every citation
  having to spell out one exact member. The trailing-underscore boundary is
  deliberate: a wholly invented `test_foo` still blocks unless a real
  `test_foo_*` exists, preserving the guard CCE-111 built this rule for.
- **Fail closed on an unterminated fence.** `strip_fenced_blocks` previously
  treated an unclosed fence as opening a block that never closes, silently
  dropping every citation after it — for the rest of the file, with no
  report. It now stops stripping at EOF, so the trailing text stays checked.
  This is the one change in the set that could *increase* the blocked-token
  count, so it was verified with a full-corpus scan before merge rather than
  the unit suite alone.
- **A reserved `example/` namespace.** The generic-first mandate requires
  fictional-host examples in prose — a page describing the plugin cannot
  hardcode this host's own layout as if it were universal. A cited path
  under `example/` (configurable via `lint.citation_example_prefixes`) is
  never checked for existence, following RFC 2606's `example.com`
  precedent. This is the PR #198 unblock: `scripts/auth/session.py` becomes
  `example/auth/session.py` on the citations page.
- **`lint.citation_exempt_tokens`.** One residual class survives every
  resolver improvement: tokens whose *non-existence* is the claim, like
  `tests/scripts/__init__.py`. The exempt list is exact-match, plugin
  defaults (`test_snake_case`, which is plugin-intrinsic — every host that
  documents this lint hits it) unioned with the host's own entries so a host
  config can't accidentally drop a plugin default. A listed token that
  starts resolving emits a `warn` naming it a stale exemption, so the list
  can't silently accumulate dead entries.
- **A non-citation vocabulary in `agents/page-author.md`.** The authoring
  contract previously had one rule — cite only files and tests you confirmed
  exist — and no sanctioned way to write an illustrative path or a
  metasyntactic placeholder in prose. It now says explicitly: a backticked
  path or test identifier asserts the artifact exists; an illustrative or
  fictional-host path goes under `example/`; a placeholder standing for a
  shape rather than a real thing goes inside a fenced block. Without this,
  the fix would have bought one clean night — the citations page regenerates
  from the same grounding set every run, and an ungoverned author re-emits
  the old token.

Regression coverage for the original CCE-110 confabulation fixtures in
`tests/lint/test_citation_exists.py` stayed red-on-confabulation throughout —
the check that resolver completeness didn't relax the rule into uselessness.

## Deliberately out of scope

Two follow-on tickets exist and are excluded from this change:

- **CCE-132** — fix the six near-miss confabulations already on `main`
  (`scripts/build_doc_source_map.py` and its siblings above). These are real
  content defects, not lint defects, so they don't belong in a lint change.
- **CCE-133** — extend the CCE-124 archive-lens advisory downgrade to the
  `changelog` generator (`whats-new.md`), which carries roughly 20
  historical tokens that are correct as-of-writing but structurally
  condemned to cite deleted files. Deferred separately because it routes
  through the same LLM-mediated severity path this decision rejected for
  `architecture/` — extending it to another page is a scoped, deliberate
  acceptance on an advisory-only page, not a rider on this fix.

Inline cite-ignore markers and negation-aware citation checking (recognizing
a sentence that says a file deliberately does not exist) were both
considered and rejected as unnecessary: the reserved namespace and the
exempt-token list already cover every case either would have reached, at a
fraction of the implementation risk.
