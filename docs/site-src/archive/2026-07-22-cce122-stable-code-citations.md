---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/187
synthesized_into: []
doc_kind: decision
---

# CCE-122: stable code citations — line-free, split across a lint and the fact-checker

Docs prose used to cite code as `` `path:line` ``. Line numbers are the single
most churn-sensitive part of a citation: any edit above a cited line shifts
it, so an unrelated change turns a correct citation "stale." The nightly
fact-checker read the cited file, saw the location had drifted, and emitted
`verdict: contradiction` — on every benign drift, not just real ones. Those
contradictions populate `fact_check_warnings`, and the CCE-101 auto-merge gate
requires zero of them. PR #179 (2026-07-16) surfaced eight such warnings in a
single run, none of them a real behavioral problem, all of them blocking
auto-merge until a human intervened.

## Root cause: one checker doing two jobs

The fact-checker was policing two different concerns at once: **behavioral
truth** ("does the code actually do what the prose says?" — genuinely
semantic, belongs to an LLM) and **citation-location precision** ("does this
line still point at the cited thing?" — deterministic and syntactic). A line
citation drifts on every edit, so that second concern was a constant false
alarm layered onto a checker meant to catch real confabulation. A symbol
citation, by contrast, only drifts on a rename — rare, and then it's a
genuine staleness worth flagging.

## Decision

Split the two concerns. Citations are now line-free: `` `path/to/file.py` ``
for whole-file or non-symbol references, `` `path/to/file.py:symbol` `` for a
named function, class, or module constant (`` `file.py:Class.method` `` for a
method). Never `` `path:line` `` or `` `path:start-end` ``.

Citation *existence* moved to a deterministic lint. Citation-location
*drift* got an advisory nudge, also deterministic. The fact-checker's job
narrowed to behavior only.

### `citation_exists` (Tier-1, block)

`scripts/lint/citation_exists.py` already verified that a cited file or test
exists. It now also verifies a cited `:symbol` is actually defined in that
file: `extract_symbol_citations` pulls `(bare_path, leaf_symbol)` pairs out of
prose, and `check_path` checks each leaf against a `def`/`class` or
module-level assignment in the cited file's source. A citation naming a
symbol that was never written — the same confabulation risk this lint exists
to catch for files and tests — now fails the build the same way.

### `citation_line_free` (Tier-1, warn)

A new rule, `scripts/lint/citation_line_free.py`, flags any surviving
`` `path:line` `` span via `citation_exists.line_pinned_citations` (the single
source of the `:line` grammar). It's registered in `lint_runner.TIER1_DEFAULT`
alongside `citation_exists`, but at `SEVERITY = "warn"` — it never fails a
run. A hard block would break every host that hasn't migrated yet; leaving it
unenforced would let drift creep back in silently. Warn is the middle ground:
visible, never blocking.

### `fact-checker` scoped to behavior only

`agents/fact-checker.md` now says explicitly: verify the behavioral claim
against the cited file, and do not emit `contradiction` solely because a
line number, `path:line`, or `path:symbol` location no longer points exactly
where the prose implies. Citation existence is `citation_exists`'s job now.
A wrong symbol — one that genuinely doesn't do what the prose claims — is
still a real contradiction; no confabulation detection was lost, only
line-position policing.

### `page-author` writes the new grammar

`agents/page-author.md` now instructs: cite code as `` `path` `` or
`` `path:symbol` ``, never `` `path:line` ``.

## Migrating the existing 99 citations

A one-time script, `scripts/migrate_line_citations.py`, walked
`docs/site-src/**.md` and rewrote every `` `path:line` `` span it found —
99 of them across 21 published pages. For a `.py` file, it AST-parses the
source and maps the pinned line to its enclosing `def`/`class`
(`_enclosing_symbol`), producing `path:symbol` (`path:Class.method` for a
method) or, for a module-level assignment, `path:NAME`. Anything it can't
resolve to a symbol — a non-`.py` file, or a line that isn't inside a
def/class/assignment — gets stripped to a bare `path`. A bare filename with
no `/` resolves against `git ls-files` only when the basename is unique;
ambiguous matches are left as a bare, unresolved token rather than guessed.

The script is idempotent — a second run finds no `:line` spans left to
rewrite — and it's committed and unit-tested rather than run-once-and-discard,
since any host carrying legacy `:line` pins can reuse it. Migrated pages were
verified with the real consumer, `citation_exists.check_path`, not a
filesystem check.

## Why not simpler alternatives

- **Drop paths from citations entirely.** Rejected: `resolve_cited_sources`
  feeds the fact-checker by path, so the path itself is load-bearing.
- **Leave symbol citations unverified.** Rejected: that reopens the exact
  confabulation risk `citation_exists` exists to catch, just shifted from
  files/tests to symbols.
- **Hard-block any leftover `:line` pin.** Rejected: breaks any host that
  hasn't run the migration yet, with no transition path.
- **Keep the fact-checker policing location.** Rejected: that's the source
  of the drift-warning noise this change removes.

## What this does not change

The CCE-101 auto-merge gate logic is untouched — this removes the spurious
warnings that were tripping it, not the gate itself. Capability C1's
`<!--pin:TOKEN-->` line-pin mechanism (`scripts/verify_citations.py`) is
orthogonal and unaffected; it governs only pin-tokened pages and is already
`info_only`.

## Testing

- `tests/lint/test_citation_exists.py` — a defined `:symbol` passes; an
  absent one blocks with the "cites nonexistent symbol" message; bare `path`
  behavior and `resolve_cited_sources` output are unchanged for all citation
  forms.
- `tests/lint/test_citation_line_free.py` — a page with a `:line` span
  yields a `warn` finding; `lint_runner` still exits 0 (warn never fails a
  run); a page with no `:line` span yields nothing.
- `tests/lint/test_lint_runner.py` — `citation_line_free` is registered in
  `TIER1_DEFAULT`.
- `tests/agents/test_fact_checker_contract.py` — contract-text assertion
  that `agents/fact-checker.md` carries the behavior-only, exclude-location
  instruction.
- `tests/agents/test_page_author_citation_contract.py` — contract-text
  assertion that `agents/page-author.md` forbids `path:line` and states the
  `path` / `path:symbol` convention.
- `tests/scripts/test_migrate_line_citations.py` — a `.py` line cite inside
  a def/class migrates to `path:symbol`; a range cite resolves off its start
  line; a non-`.py` cite strips to bare `path`; a unique bare-filename cite
  resolves to its full path; a second run is a no-op.
- `tests/lint/test_site_citations_line_free.py` — after running the
  migration over `docs/site-src`, no `` `path:line` `` span remains anywhere
  in the tree.

Full `python3 -m pytest` green.

## Note on this page

This entry documents the CCE-122 design; the pages it directly touches
(`docs/site-src/architecture/cce-capability-c-canonical-core-citations.md`,
`docs/site-src/architecture/cce-capability-c2-canonical-core-authoring.md`)
were edited in the same PR. The design spec lives at
`docs/superpowers/specs/2026-07-18-cce122-stable-code-citations-design.md`.
