---
title: "CCE-145: `citation_exists` Symbol Resolution Widened to Any Definition Site"
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/237
synthesized_into: []
doc_kind: decision
---

# CCE-145: `citation_exists` Symbol Resolution Widened to Any Definition Site

`citation_exists` is the Tier-1 **block** rule that verifies a `path:symbol`
citation names something real. Until this fix, it recognized Python syntax
only — and a narrower slice of Python than it looked like. Real, correctly
cited symbols were reported as nonexistent, and a page that fails this rule is
dropped, not retried: `last_successful_run.head_sha` still advances, so the
page falls permanently out of the collection window.

## What was actually reported

Live reproduction, nightly run `32460602658` on `theoju/claude-code-self-assessment`
(2026-08-21, PR #201, merged as `2707b31`):

```
lint_block: docs/site-src/2026-08-21-memory-execution-scorer-redesign-cce163.md
  citation_exists: cites nonexistent symbol 'memory' in 'scripts/score.mjs'
```

`memory` is real. It's a property key inside the object literal opened by
`export const EXECUTION_SCORERS = {` in the host's `scripts/score.mjs`. The
symbol is defined and exported — it just isn't a top-level export *binding*,
which is the only shape the old matcher understood.

## Root cause

`_symbol_defined` matched two arms: a `def`/`class` keyword at any indent, and
a **column-0** `name =` / `name:` assignment. That's a narrow, Python-shaped
matcher, and it failed two independent ways:

1. No JavaScript or TypeScript definition form matched at all — not
   `export const`, not `export function`, not `export class`. On a JS host,
   every `path.mjs:symbol` citation blocked.
2. A symbol bound inside an object or dict literal never resolved, in any
   language — the column-0 anchor on the assignment arm excluded every
   indented binding, including Python class attributes.

A second, unrelated defect shipped in the same ticket: `_resolves` treats a
path as missing unless it's tracked by git or present on disk. A generated
artifact a host gitignores by design (`app/data/assessment.json` on the
reference host) is neither, in a fresh CI checkout — so the citation blocked
in CI while passing on the author's own machine.

## What a `path:symbol` citation means

A `path:symbol` citation asserts **"this file defines this identifier"** — a
definition site a reader can navigate to. It does not assert "this is an
importable binding." The CCE-122 grammar already implies this: it ships
`file.py:Class.method`, and a method is not importable. `agents/fact-checker.md`
draws the same boundary in the same words. Widening the matcher from
"importable binding" to "definition site" tightens the implementation to match
a contract that was already written that way — it does not weaken the rule's
purpose, which is catching confabulation: a name the page-author invented that
appears nowhere in the file under any definition.

## The fix

`scripts/lint/citation_exists.py:_symbol_defined` now resolves against
`_DEFINITION_FORMS`, four named binding positions composed into one cached
regex alternation per symbol, deliberately language-agnostic rather than
AST-based:

- **declaration** — a declaration keyword at any indent behind any modifier
  chain: `export default function f`, `export const X`, `def f`, `type T`,
  `interface I`.
- **named_export** — a named export list: `export { evaluatePredicate }`,
  `export { other as name }`. Anchored on `export` so a bare
  `import { name }`, which binds a symbol defined elsewhere, does not resolve.
- **binding** — a key or field bound at any indent: an object-literal scorer
  key, an indented Python class attribute, a TS class field.
- **member_shorthand** — a method shorthand with a body: `async handle(req) {`.
  The trailing `{` is load-bearing: it's what separates a definition from a
  bare call, `handle();`, which must not resolve.

Regex, not a parser, is the deliberate choice: the plugin is generic-first,
and a Python-`ast` path covers exactly one of the languages a host might use,
while a JS parser is a third-party runtime dependency the stdlib-first
convention rejects. One language-agnostic set of binding positions serves
every host the same way.

Strictness held constant. The forms match only where an identifier is
*bound*: a name that merely appears in a comment, a string literal, a bare
`import`, or a call is not a definition site. Matching those would let a
citation point at the wrong file while still reading as authoritative — the
`:symbol` hazard CCE-122 already warned about. Regression tests pin all of
these as still-blocking: a commented-out name, a name inside a string, a bare
re-export-free `import`, a call with no trailing `{`, and a quoted dict/JSON
key. Known limits — `export * from './x'`, destructured
`const { a, b } = …` bindings, quoted dict keys — stay unresolved, and each
fails closed: the citation blocks, which is the safe direction for a block
rule.

Gitignored paths got a parallel fix. `_is_gitignored` asks
`git check-ignore -q --no-index`; when a cited path fails every resolution
route *and* the host's own `.gitignore` excludes it, the citation is
downgraded from a blocking problem to an advisory `unverifiable (gitignored)`
note rather than a block — the `.gitignore` entry is the repo's own evidence
that the path is expected. Any other exit code (not-ignored, or 128 for a
path outside the repo) fails closed and the citation still blocks.

## Verification

Run against the real consumer, not `test -f`:

- All symbol forms from the ticket, plus `memory` and a re-export form, cited
  against the real host repo → `citation_exists: ok`.
- A fresh shallow clone matching the CI checkout (no generated artifacts on
  disk) → `ok: True` with `unverifiable (gitignored)` notes, not a block.
- The same clone with a confabulated symbol, a missing file, and a symbol
  defined in another module → still blocks, all three reported.
- Full plugin suite green.

## Deliberately out of scope

The ticket named a third defect class — non-path strings validated as paths
(a release-branch name whose dotted tail reads like a file extension, a
cross-repo `owner/repo/path` reference) — and a fourth seen in run output but
not the ticket, docs-relative citations like `../../scripts/predicate.mjs`.
Both live in extraction (`_REPO_PATH_RE`, `_relativize`), a different layer
from the resolution logic this fix touches, and both are plausibly
page-author defects rather than lint defects. Filed separately rather than
silently folded in.

## Measured impact

Reclassifying the two reference nightly runs the ticket cited: PR #184
(08-11) blocked 11 pages, 8 fixed by this change; PR #187 (08-13) blocked 11
pages, 7 fixed. The ticket's headline "~11 pages per nightly run" is no
longer current on its own — the 2026-08-21 run blocked one page on
`citation_exists` out of five authored, because CCE-152 separately cut
authoring at a PR boundary. The per-run *count* fell for an unrelated reason;
the false-positive *rate* on JS symbol citations was 100% until this change.

## Reference

Ticket: [CCE-145](https://designitright.atlassian.net/browse/CCE-145). PR:
[#237](https://github.com/theoju/engineering-docs-agent/pull/237). Spec:
`docs/superpowers/specs/2026-08-21-cce145-citation-symbol-definition-forms-design.md`.
Touches: `scripts/lint/citation_exists.py`, `tests/lint/test_citation_exists.py`.
Related: CCE-122 (line-free citation grammar), CCE-141/CCE-152 (stranding
prevention for pages dropped by a blocking-pipeline failure).
