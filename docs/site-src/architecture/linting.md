---
description: 'Documents architecture linting: Fixes the citation_exists Tier-1 lint check so it resolves Python symbol citations (`path:symbol`) against any definition site — methods, nested functions, class attributes — not just top-level module definitions. Previously the linter only recognized symbols defined at the top level of a Python file, so citations to real, correctly-defined symbols nested inside a class or function were incorrectly reported as nonexistent, causing the authored page to be dropped by content-validator. Because a dropped page is not retried and the collection window still advances, this silently and permanently stranded documentation for legitimately-cited code.'
source_files:
  - docs/superpowers/specs/2026-08-21-cce145-citation-symbol-definition-forms-design.md
  - scripts/lint/citation_exists.py
  - tests/lint/test_citation_exists.py
last_reviewed: '2026-08-23'
status: draft
---
# Linting: citation existence

Every page a `page-author` subagent writes cites code — a file, a test, or a
`path:symbol` reference. `citation_exists` (Tier-1, **block**) is the rule
that keeps those citations honest: it verifies each cited path, test, and
symbol is real before the page is allowed to land. A page that fails this
rule is dropped by content-validator, and because a dropped page is not
retried and the run's collection window still advances regardless, a false
positive here does not just annoy you once — it permanently strands
documentation for code that was cited correctly.

## What a `path:symbol` citation asserts

A citation of the form `path/to/file.py:symbol` asserts one specific claim:
**this file defines this identifier** — a definition site you can navigate
to. It does **not** assert "this is an importable binding." The CCE-122
grammar already settled this by shipping `file.py:Class.method`: a method is
not importable, so the grammar was never about export tables. `citation_exists`
checks bare existence; a separate rule, `citation_line_free` (Tier-1, warn),
flags any citation that still pins a fragile `:line` suffix instead of a
symbol.

## Symbol resolution covers any definition site, not just the top level

You resolve a `path:symbol` citation against `_DEFINITION_FORMS` in
`scripts/lint/citation_exists.py` — one language-agnostic set of four named
binding *positions*, composed into a single cached regex alternation per
symbol:

| Form               | Matches                                                          | Example                                                    |
| ------------------- | ----------------------------------------------------------------- | ----------------------------------------------------------- |
| `declaration`       | a declaration keyword before the name, at any indent, behind any modifier chain | `export default function f`, `export const X`, `def f`, `type T` |
| `named_export`      | a named export list                                                | `export { evaluatePredicate }`, `export { other as name }` |
| `binding`           | a key or field bound at any indent                                  | a scorer key inside an exported object map, an indented Python class attribute |
| `member_shorthand`  | a method shorthand **with a body**                                  | `async handle(req) {`                                       |

That "at any indent" clause is the fix. The rule previously matched Python
`def`/`class` at any indent, but its second arm — a bare `name =` /
`name:` assignment — was anchored at column 0. A method, a nested function,
or a class attribute never starts at column 0, so none of them resolved:
the linter reported real, correctly-defined symbols as nonexistent, purely
because of where inside the file they were defined. Widening `binding` to
match at any indent, and adding `declaration`, `named_export`, and
`member_shorthand` as their own forms, closes that gap without weakening the
rule's actual job, which is catching confabulation — a name the page-author
invented that appears nowhere in the file under any definition.

Regex, not a parser, is the deliberate choice here: a host may be Python,
JS/TS, Go, Rust, or Kotlin, and a Python-`ast` path would cover exactly one
of those languages while a third-party JS parser is a runtime dependency the
plugin's stdlib-first rule rejects. One shared set of binding-position
patterns serves every host equally.

## Strictness is preserved, not traded away

Widening where a symbol can be *defined* is not the same as widening where it
can merely *appear*. The forms match only a binding, so none of the
following resolve a citation, and each one still blocks:

- a name inside a `//` or `/* */` comment
- a name inside a string literal
- a bare `import { name } from …` with no re-export (the symbol is defined
  elsewhere — `named_export` is anchored on `export` for exactly this reason)
- a bare call, `name();` (`member_shorthand` requires the trailing `{`,
  which is what separates a definition from a call)
- a quoted dict/JSON key — data, not an identifier

A citation to a symbol that is merely mentioned, not defined, still fails
`citation_exists` for the same reason it always did: matching a mention
instead of a definition would let a citation point at the wrong file while
still reading as authoritative, which is the exact hazard the `:symbol`
grammar exists to prevent. `export * from './x'` re-exports, destructured
`const { a, b } = …` bindings, and quoted dict keys are known, accepted
gaps — each fails **closed** (the citation blocks), which is the safe
direction for a Tier-1 block rule.

## Gitignored paths are unverifiable, not missing

A related, independently-caused false positive: a cited path that is real
but gitignored by design (a generated artifact like an assessment or
progression data file) exists on the author's machine and not in a fresh CI
checkout, so naive existence checking reports it missing. `citation_exists`
now asks `git check-ignore -q --no-index` before failing such a citation; if
the host's own `.gitignore` excludes the path, the citation is downgraded
from a blocking problem to an advisory note —
`unverifiable (gitignored): '<path>'` — rather than a hard block. Any other
exit code from `check-ignore` (not ignored, or an error such as a path
outside the repo) fails closed and the citation still blocks.

## Why this mattered: pages don't get a second try

The collection window that drives the nightly docs run advances past
whatever `last_successful_run.head_sha` records, whether or not every
authored page landed. A page dropped by `citation_exists` on a false
positive is not queued for a retry — it simply falls out of range. Three
consecutive nightly runs against a JS/TS host blocked roughly 11 authored
pages per run this way before the fix, because no JavaScript or TypeScript
definition form matched at all under the old symbol resolver: not
`export const`, not `export function`, not `export class`. On a JS host,
every `path.mjs:symbol` citation blocked, full stop.

Reference: CCE-145 (2026-08-21).

## What this rule is not

`citation_exists` is scoped to deterministic existence: does the path
resolve, does the test exist, is the symbol defined somewhere in the cited
file. It does not judge whether the page's prose about that code is
*correct* — that behavioral-truth judgment belongs to the `fact-checker`
agent, which is explicitly out of scope for citation location or line drift.
Keeping the two concerns on separate sides of that line is what lets
`citation_exists` block hard on Tier-1 without also becoming a second,
redundant fact-checker.
