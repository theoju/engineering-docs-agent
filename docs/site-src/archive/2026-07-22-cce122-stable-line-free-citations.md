---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/187
synthesized_into: []
doc_kind: decision
---

# Code citations go line-free; citation-location precision moves to a lint

Docs used to cite code as `` `path:line` `` — e.g. `` `scripts/orchestrator_runner.py:1240` ``. Line numbers are the single most churn-sensitive part of a citation: any edit above the cited line shifts it, so an unrelated change turns a correct citation "stale." PR #179 (2026-07-16) surfaced eight fact-checker `contradiction` warnings that were all really this — benign line drift, not a real factual problem — and the CCE-101 auto-merge gate requires zero fact-checker warnings, so those warnings blocked auto-merge on docs that were otherwise correct.

## Root cause

One checker was doing two jobs. The `fact-checker` agent reads a page's cited source and checks two different things at once: (1) **behavioral truth** — does the code actually do what the prose says? — which is genuinely semantic and belongs to an LLM; and (2) **citation-location precision** — does this line still point at the cited thing? — which is deterministic and syntactic. A line citation drifts on *every* unrelated edit (constant false alarm); a symbol citation drifts only on a rename (rare, and then it's a real staleness worth flagging). Layering the syntactic concern onto the semantic checker made every code churn a potential auto-merge blocker.

There were also two token shapes in the wild, and only one of them was linted at all: a dir-qualified cite like `` `scripts/orchestrator_runner.py:1394` `` was checked for file existence by `citation_exists`, but a bare-filename cite like `` `orchestrator_runner.py:128` `` has no `/` and matched nothing — it drifted silently and the fact-checker still read it.

## The fix

Citations are now line-free by convention: `` `path/to/file.py` `` for whole-file or non-symbol references, `` `path/to/file.py:symbol` `` when pointing at a named function, class, or module constant (`` `file.py:Class.method` `` for a method), and never `` `path:line` `` or `` `path:start-end` ``. `agents/page-author.md` states this convention directly in its authoring procedure, and instructs naming the symbol in prose naturally (e.g. `run()`) while the backtick token carries the `path:symbol` citation.

Citation-location correctness moved to a deterministic lint instead of an LLM judgment call:

- **`citation_exists`** (Tier-1, block) now recognizes both suffix grammars — `:digits(-digits)` and `:symbol` — and, for a `:symbol` citation, verifies the symbol is actually defined in the cited file via `extract_symbol_citations` and `_symbol_defined`. A confabulated symbol still fails the build, the same block severity as a nonexistent file or test today. The check is file-scoped: for `Class.method` only the leaf `method` is verified, not that it's defined inside `Class` — cheap and deterministic, with deeper correctness left to the fact-checker's behavioral check.
- **`citation_line_free`** (Tier-1, warn — new) flags any surviving `` `path:line` `` span via `line_pinned_citations`, a helper shared with `citation_exists` so the `:line` grammar has one source of truth. It's advisory: `lint_runner.py` never fails a run on it, so a host that hasn't migrated its legacy pins yet isn't blocked, but the drift stops being invisible.

`agents/fact-checker.md` is narrowed to match. Its output contract now states explicitly that a `path:line`, `path:symbol`, or plain line-number location that no longer points exactly where the prose implies is **not** grounds for `verdict: contradiction` — citation existence is `citation_exists`'s job now. A genuinely wrong symbol still fails the behavioral check and is still a real contradiction; no confabulation-detection was lost, only line-position policing.

## Migration

96 existing `` `path:line` `` citations across 21 published pages needed rewriting, plus a few more that the AST walk over `docs/site-src/**.md` picked up — the migration (`scripts/migrate_line_citations.py`) converted 99 in total. For each cited `.py` file it resolves the path (a bare filename resolves only when its basename is unique across `git ls-files`; ambiguous or unresolvable tokens fall back to stripping `:line`), then AST-maps the pinned line to its innermost enclosing `def`/`class` — `path:Class.method` for a method — or, for a module-level `NAME = …` / annotated assignment on that exact line, to `path:NAME`. Anything non-`.py`, unresolvable, or landing outside a def/class/assignment strips to a bare `path`.

The corroboration policy that decided which rewrites to trust: keep `:symbol` only where the page's own prose corroborates it — the symbol is backticked elsewhere in the prose, or it's the cited file's namesake — and downgrade everything else to bare `path`. This mattered because migrating a stale `path:line` blindly is dangerous in a specific way: the AST mapping can resolve to a real-but-*wrong* symbol (the line drifted into a neighboring function since the citation was written) that then passes `citation_exists`'s existence check yet contradicts the prose — reading as authoritative when it's actually worse than the opaque line number it replaced. Under that policy, 48 of the 99 rewrites were downgraded to bare `path` and 41 kept their `:symbol` form; all were independently audited clean. The migration is idempotent — a second run over an already-migrated tree finds no `:line` spans and rewrites nothing — and was verified with the real consumer (`citation_exists.check_path` passing on every touched page), not `test -f`.

## What this does not change

`scripts/verify_citations.py` (capability C1, the `<!--pin:TOKEN-->` mechanism) is untouched — it's an orthogonal, `info_only` check that governs only pin-tokened pages. The CCE-101 auto-merge gate logic itself is unchanged; this fix removes the warnings that were tripping it, not the gate. Page prose beyond citation tokens was not rewritten.

## Incidental fix

While landing this, a latent test-isolation bug was fixed: `tests/scripts/__init__.py` was making `tests/scripts` register as the top-level `scripts` package under pytest's prepend import mode, shadowing the real namespace package (`scripts/` has no `__init__.py` by design) and causing order-dependent `ModuleNotFoundError` failures in `test_lint_runner`. The fix is to not have that `__init__.py` at all — `scripts/` modules under test are imported via the dotted namespace path (`from scripts.lint import citation_exists`), never via a `sys.path.insert`-and-bare-import that would poison namespace resolution for the rest of the session.

## Testing

`tests/lint/test_citation_exists.py` covers the extended grammar: a `:symbol` citation where the symbol is defined passes `check_path`; where it's absent, `check_path` blocks with a "cites nonexistent symbol" message; `resolve_cited_sources` and `extract_citations` keep returning clean bare paths for `path`, `path:symbol`, and legacy `path:line` forms alike, preserving the shared-helper contract that `orchestrator_runner.py`'s fact-checker dispatch depends on. `tests/lint/test_citation_line_free.py` checks that a page with a `path:line` span yields a `warn` finding while `lint_runner`'s exit code stays 0, and that a page with no `:line` spans yields none. `tests/agents/test_fact_checker_contract.py` and `tests/agents/test_page_author_citation_contract.py` pin the two contract-text changes directly, the same pattern used for other agent-contract assertions. `tests/scripts/test_migrate_line_citations.py` covers the migration's resolution and symbol-mapping logic, including the idempotent no-op re-run. `tests/lint/test_site_citations_line_free.py` asserts the published result: no `` `path:line` `` span remains anywhere under `docs/site-src`.

## Scope note

CCE-122 is fix-surface only: `scripts/lint/citation_exists.py`, the new `scripts/lint/citation_line_free.py`, `scripts/lint/lint_runner.py`, `agents/fact-checker.md`, `agents/page-author.md`, the new `scripts/migrate_line_citations.py`, and `docs/site-src/**` content. `docs/superpowers/specs/2026-07-18-cce122-stable-code-citations-design.md` and `docs/superpowers/plans/2026-07-19-cce122-stable-code-citations.md` are the planning artifacts, not doc-site targets.
