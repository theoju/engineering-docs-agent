---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/187
synthesized_into: []
doc_kind: decision
---

# CCE-122: Stable, line-free code citations

Docs prose used to cite code as `` `path:line` `` (e.g.
`` `scripts/orchestrator_runner.py:1240` ``). Line numbers are the single
most churn-sensitive part of a citation: any edit above the cited line
shifts it, so an unrelated change turns a correct citation "stale." The
nightly `fact-checker` agent read the cited file, checked the location, and
emitted `verdict: contradiction` whenever it drifted — even when the prose
was still true. Those contradictions populated
`state["current_run"]["fact_check_warnings"]`, and the CCE-101 auto-merge
gate requires zero fact-checker warnings, so a purely cosmetic line shift
was enough to block auto-merge and force a human to intervene. PR #179
(2026-07-16) surfaced eight such warnings in one run and was the immediate
trigger for this fix.

## Root cause: one checker doing two jobs

The fact-checker was conflating two different concerns: **behavioral
truth** ("does the code actually do what the prose says?" — genuinely
semantic, an LLM's job) and **citation-location precision** ("does this
line still point at the cited thing?" — deterministic and syntactic). A
line citation drifts on *every* edit above it, so it produced a constant
false alarm. A symbol citation only drifts on a rename, which is rare and,
when it happens, is a real staleness worth flagging.

## Decision

Split the two concerns. Citations are now line-free: `` `path/to/file.py` ``
for whole-file or non-symbol references, `` `path/to/file.py:symbol` `` for
a named function, class, or module constant (`` `file.py:Class.method` ``
for a method), and never `` `path:line` `` or `` `path:start-end` ``.
Citation *existence* — including symbol existence — moved to a
deterministic Tier-1 lint. The fact-checker was rescoped to behavioral
truth only.

### `citation_exists` now verifies cited symbols (block)

`citation_exists` (`scripts/lint/citation_exists.py`) already blocked pages
citing a nonexistent file or test. Its path grammar (`_REPO_PATH_RE`) was
widened to accept an optional `:symbol` suffix alongside the old `:line`
form, and a new pure helper, `extract_symbol_citations`, pulls
`(bare_path, leaf_symbol)` pairs out of prose — the leaf is the last
dotted component, so `` `Cls.method` `` resolves to `method`. `check_path`
then confirms each cited symbol is actually defined in its file via
`_symbol_defined`, which matches a `def`/`class` at any indent (so methods
count) or a column-0 module-level assignment. A citation to a symbol that
was never defined — a confabulated `run()` that doesn't exist, say — now
blocks the build exactly like a nonexistent file or test does today. The
check is file-scoped, not repo-wide, since the path already pins the file;
for a dotted `Class.method` citation, only the leaf `method` is verified,
not that it actually lives on `Class` — cheap and deterministic, with
deeper correctness left to the fact-checker's behavioral check.

Existence-check extension is careful not to touch the shared-helper
contract: `extract_citations`'s `{"paths", "tests"}` return shape, which
`scripts/orchestrator_runner.py` depends on for fact-checker grounding, is
byte-identical to before. Both `:line` and `:symbol` suffixes strip to the
same bare path.

### `citation_line_free` — a new advisory rule (warn)

A sibling rule, `scripts/lint/citation_line_free.py`, flags any surviving
`` `path:line` `` span. It reuses `citation_exists.line_pinned_citations`
as the single source of the `:line` grammar (deliberately broader than
`_REPO_PATH_RE` — it also catches bare filenames like
`` `orchestrator_runner.py:128` ``, which were previously unlinted *and*
drifting). `SEVERITY = "warn"`, registered in `lint_runner.TIER1_DEFAULT`
alongside `citation_exists`, so it runs by default but never fails a
build — a host still carrying legacy `:line` pins gets nudged, not broken.

### `fact-checker` scoped to behavior only

`agents/fact-checker.md` now states explicitly that the agent verifies the
**behavioral claim** against a cited source and must not emit
`verdict: contradiction` solely because a cited line number or location no
longer matches — that concern now belongs to `citation_exists`. A symbol
that's simply wrong still fails the behavioral check and is still a real
contradiction; no confabulation detection was lost, only line-position
policing.

### `page-author` required to cite line-free going forward

`agents/page-author.md`'s grounding procedure now instructs: cite code as
`` `path/to/file.py` `` or `` `path/to/file.py:symbol` ``, never a line
number — "line numbers drift under unrelated edits and are rejected by the
docs pipeline." The symbol should be named naturally in prose (`run()`);
the backtick token carries the `path:symbol` citation.

## Migrating the existing citations

The site carried 96 `` `path:line` `` citations across 21 pages before this
fix (the migration ultimately touched 99 as a couple more were caught along
the way). A one-time, committed, tested script,
`scripts/migrate_line_citations.py`, walked `docs/site-src/**.md` and
rewrote every inline `path:line` span. It's `ast`-based for `.py` files: it
maps the cited line to its innermost enclosing `def`/`class` (producing
`path:symbol` or `path:Class.method`), or, if the line is a module-level
assignment, to `path:NAME`. A bare filename with no `/` resolves against
`git ls-files` when the basename is unique in the tree; otherwise it's left
as-is with the `:line` suffix stripped. Anything unresolvable, or a
non-`.py` file, downgrades to a bare `path`.

That downgrade-by-default policy is deliberate, and it's the dangerous part
of this kind of migration: blindly resolving a stale line to *some* symbol
risks landing on a real-but-*wrong* symbol that passes the existence lint
while contradicting the prose — worse than the opaque line number it
replaced, because it now reads as authoritative. The migration corroborates
before it keeps a `:symbol`: it only survives when the page's own prose
backticks that symbol elsewhere or the symbol is the cited file's namesake;
everything else downgrades to bare `path`. Of the 96 original pins, 48 were
downgraded to bare `path` and 41 were kept as `:symbol`, then adversarially
audited by hand. The script is fence-aware (it never rewrites a citation
inside a fenced code block) and idempotent — a second run over the same
tree finds no `:line` spans left to rewrite. It's committed and tested
rather than throwaway, since any host carrying legacy `:line` pins can
reuse it.

Verification used the real consumer, not a filesystem check: after the
migration, every touched page had to pass `citation_exists.check_path`
directly, and a permanent repo-guard test now asserts no `` `path:line` ``
span remains anywhere under `docs/site-src`.

## What this does not change

- `scripts/verify_citations.py` — capability C1's `<!--pin:TOKEN-->`
  line-pin mechanism — is a separate, orthogonal, `info_only` check on
  pinned pages and is untouched by this fix.
- The CCE-101 auto-merge gate logic itself is unchanged; this fix removes
  the *warnings* that were tripping it, not the gate.
- Bare-`path` citation behavior is unchanged — every existing bare-path
  citation continues to check as before.

## A latent test-isolation bug found along the way

While adding `tests/scripts/test_migrate_line_citations.py`, a pre-existing
bug surfaced: `tests/scripts/` had no package marker, but `scripts/` itself
is a PEP 420 implicit namespace package (no `__init__.py`). Under pytest's
prepend import mode, a stray `tests/scripts/__init__.py` gets registered as
the top-level `scripts` package, shadowing the real one in `sys.modules` —
any later `from scripts.lint... import` in a different suite then fails
with an order-dependent `ModuleNotFoundError`. It was fixed by leaving
`tests/scripts/` unpackaged and importing scripts modules in tests via the
dotted namespace path rather than manipulating `sys.path` directly.

## Testing

- `tests/lint/test_citation_exists.py` — the widened `:symbol` grammar and
  extraction helpers; the new symbol-existence block (present symbol
  passes, confabulated symbol blocks, a missing file reports the path
  problem rather than a symbol problem); `resolve_cited_sources` still
  returns clean bare paths for `path`, `path:symbol`, and legacy `path:line`
  forms alike.
- `tests/lint/test_citation_line_free.py` — a `path:line` page yields a
  `warn` finding; a clean page passes; the rule's own exit code surfaces
  the finding without failing the aggregate lint run.
- `tests/lint/test_lint_runner.py` — `citation_line_free` is registered in
  `TIER1_DEFAULT`, and a page whose only issue is a `:line` citation does
  not fail the aggregate run.
- `tests/agents/test_fact_checker_contract.py` /
  `tests/agents/test_page_author_citation_contract.py` — contract-text
  assertions anchored on the load-bearing phrases in `agents/fact-checker.md`
  and `agents/page-author.md`, so deleting the rule breaks the test.
- `tests/scripts/test_migrate_line_citations.py` — function/method/module-
  constant resolution, range citations, unresolvable and non-Python
  downgrades, bare-filename resolution, fence-awareness, idempotency, and a
  consumer-verification test that runs the real `citation_exists.check_path`
  against a migrated fixture page.
- `tests/lint/test_site_citations_line_free.py` — the permanent repo guard:
  no page under `docs/site-src` carries an inline `:line` citation, and
  every page passes `citation_exists`.

## Provenance

Spec: `docs/superpowers/specs/2026-07-18-cce122-stable-code-citations-design.md`.
Plan: `docs/superpowers/plans/2026-07-19-cce122-stable-code-citations.md`.
Reference: CCE-122 (2026-07-22).
