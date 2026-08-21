# CCE-145 — `citation_exists` false positives: symbol resolution and gitignored paths

**Status:** implemented
**Date:** 2026-08-21
**Ticket:** [CCE-145](https://designitright.atlassian.net/browse/CCE-145)
**Touches:** `scripts/lint/citation_exists.py`, `tests/lint/test_citation_exists.py`

## The defect, as reproduced

The `citation_exists` Tier-1 block rule reported real code as nonexistent and
dropped the authored page. A dropped page is not re-attempted: the run still
advances `last_successful_run.head_sha`, so the collection window moves past it
permanently.

Live reproduction, run `32460602658` on host `theoju/claude-code-self-assessment`
(nightly of 2026-08-21, PR #201, merged as `2707b31`):

```
lint_block: docs/site-src/2026-08-21-memory-execution-scorer-redesign-cce163.md
  citation_exists: cites nonexistent symbol 'memory' in 'scripts/score.mjs'
```

`memory` is real. It is a property key inside the object literal opened by
`export const EXECUTION_SCORERS = {` in the host's `scripts/score.mjs`. Exported
code, at a reachable citation target — just not a top-level export _binding_.

## Root cause

`_symbol_defined` matched two patterns:

```python
rf"(?m)^\s*(?:async\s+)?(?:def|class)\s+{name}\b|^{name}\s*[:=]"
```

Arm 1 is Python `def`/`class` at any indent. Arm 2 is a **column-0**
assignment or annotation. That is a Python-shaped matcher, and it produced two
independent failures:

1. **No JavaScript or TypeScript definition form matched at all.** Not
   `export const`, not `export function`, not `export class`, not plain
   `function`. Verified by probing the real host file: `withGates`,
   `EXECUTION_SCORERS`, `normalize`, `classifySessionKind` — every symbol the
   ticket listed — returned `False`. On a JS host, _every_ `path.mjs:symbol`
   citation blocked. The ticket's phrasing ("only matches top-level exports")
   understated it; the matcher recognised no JS export form whatsoever.
2. **A symbol bound inside an object or dict literal never resolved, in any
   language** — the column-0 anchor on arm 2 excluded every indented binding,
   including Python class attributes.

The second, independent class the ticket names — **gitignored generated files
reported as missing paths** — has a different cause. `_resolves` accepts a path
that is tracked by git _or_ present on disk. A generated artifact the host
ignores by design (`app/data/assessment.json`, `app/data/progression.json`,
`app/data/progression-config.json`) is neither in a fresh CI checkout, so the
citation blocks in CI while passing on the author's machine.

## Decision: what a `path:symbol` citation means

> A `path:symbol` citation asserts **"this file defines this identifier"** — a
> definition site a reader can navigate to. It does **not** assert "this is an
> importable binding."

Three things settle it, none of them new:

- The CCE-122 grammar already ships `file.py:Class.method`. A method is not
  importable. The grammar was never about export tables.
- `agents/fact-checker.md` states the boundary in the same words: citation
  existence — "the file exists, the cited symbol is defined in it" — is owned by
  this lint. No contract change was needed; the contract already said
  _defined_, and the implementation was narrower than the contract.
- The rule's purpose is catching **confabulation**. A name the page-author
  invented appears nowhere in the file under any definition. Widening from
  "importable binding" to "definition site" does not weaken that.

## Implementation

### Symbol resolution: named binding forms, one language-agnostic set

`_DEFINITION_FORMS` enumerates the meaning above as four named binding
_positions_, composed into one cached alternation per symbol:

| Form               | Matches                                                                              | Example                                                                                          |
| ------------------ | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| `declaration`      | a declaration keyword followed by the name, at any indent, behind any modifier chain | `export default function f`, `export const X`, `def f`, `type T`, `interface I`                  |
| `named_export`     | a named export list                                                                  | `export { evaluatePredicate }`, `export { other as name }`                                       |
| `binding`          | a key or field bound at any indent                                                   | a scorer key inside an exported object map, an indented Python class attribute, a TS class field |
| `member_shorthand` | a method shorthand **with a body**                                                   | `async handle(req) {`, `handle(): void {`                                                        |

Why regex rather than a parser: the plugin is generic-first — a host may be
Python, JS/TS, Go, Rust or Kotlin. A Python-`ast` path would cover exactly one
of those, and a JS parser is a third-party runtime dependency the stdlib-first
rule rejects. One language-agnostic set of binding positions serves every host
equally.

One mechanical trap worth recording: Python 3.11 rejects an inline `(?m)` that
is not at position 0, so composing per-form patterns into an alternation raises
`re.error: global flags not at the start of the expression`. Each fragment is
individually valid; only the composition fails. `re.MULTILINE` is passed to
`re.compile` instead.

### Strictness is preserved deliberately

The forms match only where an identifier is **bound**. A name that merely
_appears_ is not a definition site, and matching it would let a citation point
at the wrong file while still reading as authoritative — the exact `:symbol`
hazard CCE-122 warned about. Regression-tested as blocking:

- a name in a `//` or `/* */` comment
- a name inside a string literal
- a bare `import { name } from …` with no re-export (the symbol is defined
  elsewhere; `named_export` is anchored on `export` for this reason)
- a bare call, `name();` or `if (name()) {` — `member_shorthand` requires the
  trailing `{`, which is what separates a definition from a call
- a quoted dict/JSON key — data, not an identifier

### Known limits, all failing closed

`export * from './x'` cannot be followed; a destructured `const { a, b } = …`
binding is not detected; a quoted dict key does not resolve. Each of these makes
the citation **block**, which is the safe direction for a block rule.

### Gitignored paths: unverifiable, not missing

`_is_gitignored` asks `git check-ignore -q --no-index`. When a cited path fails
every resolution route _and_ the host's own `.gitignore` excludes it, the path is
downgraded from a blocking problem to an advisory note:

```
unverifiable (gitignored): 'app/data/assessment.json'
```

The `.gitignore` entry is the repo's own evidence that the path is expected.
Exit codes: 0 ignored, 1 not ignored, 128 error — anything but 0 fails **closed**
and the citation still blocks, so a `../../`-relative citation (outside the repo,
exit 128) is unaffected.

Accepted trade-off: a broad ignore pattern (`node_modules/`, `dist/`) exempts
everything beneath it. That region is unverifiable by construction on any
checkout, and the advisory note keeps it visible in the run output rather than
silent.

## Verification

Run against the real consumer (`scripts/lint/lint_runner.py` and
`scripts/lint/citation_exists.py`), not `test -f`:

1. **All 16 ticket symbols, on the real host repo.** A probe page citing every
   symbol from the ticket's table plus `memory` and the re-export form in the
   host's `app/lib/assessment.ts` → `citation_exists: ok`.
2. **Gitignored class, in the real CI condition.** A fresh shallow clone of the
   host (no generated artifacts on disk, exactly what the workflow checks out) →
   `ok: True` with three `unverifiable (gitignored)` notes.
3. **Strictness, on that same clone.** A confabulated symbol, a missing file,
   and a symbol defined in another module → exit 1, all three reported.
4. Full plugin suite: 1449 passed, 4 skipped.

## Deliberately out of scope

The ticket lists a third class — **non-path strings validated as paths**: a
release-branch name whose dotted tail reads as a file extension, and a
cross-repo `owner/repo/path` reference. A fourth appears in the run output but
not the ticket: docs-relative citations such as `../../scripts/predicate.mjs`.

These are **extraction** defects — what counts as a repo-path token — not
**resolution** defects. They live in `_REPO_PATH_RE` and `_relativize`, a
different layer from `_symbol_defined` and `_resolves`, and fixing them means
changing the citation grammar rather than the existence check. They are also
plausibly page-author defects rather than lint defects: a cross-repo path and a
docs-relative path are both things the page-author should not emit. Folding them
in would make one change that edits the grammar and the resolver at once.

Filed separately rather than silently widened.

## Measured impact

Reclassifying the two reference runs the ticket cites, by defect class:

| Run             | Pages blocked | Fixed by this change | Out of scope                              | Genuine |
| --------------- | ------------- | -------------------- | ----------------------------------------- | ------- |
| PR #184 (08-11) | 11            | 8                    | 2 cross-repo, 1 docs-relative             | 1       |
| PR #187 (08-13) | 11            | 7                    | 3 cross-repo/branch-name, 1 docs-relative | 0       |

The ticket's headline figure — "~11 docs pages per nightly run" — was accurate
for those two runs but **is no longer current**. The 2026-08-21 run blocked
**one** page on `citation_exists`, out of five authored. The drop is CCE-152:
authoring now cuts at a PR boundary, so far fewer pages are authored per run.
The per-run count fell; the false-positive _rate_ on JS symbol citations did not
— it was 100% until this change.
