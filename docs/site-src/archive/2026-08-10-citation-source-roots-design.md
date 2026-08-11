---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/212
synthesized_into: []
doc_kind: decision
---

# CCE-139: citation source roots — widening `citation_exists` for nested monorepos

- **Status:** landed (PR #212)
- **Ticket:** CCE-139
- **Decision:** `citation_exists` accepts an additive, opt-in `lint.citation_source_roots` config list. Declared roots are tried strictly after the repo root and `docs_dir`, so a root can only widen what resolves — it can never redirect a path that already resolves.

## Problem

A flat-repo host cites code the way `citation_exists` already expects: `scripts/foo.py` resolves directly from the repo root. A nested monorepo host's prose instead cites the import-path form the code uses for itself — `app/core/destination_engine.py` — which is only repo-relative from inside a package root like `backend/`. Without a way to declare that root, every such citation reads as a confabulation and blocks the build.

This was not theoretical: two nightly runs on the ADIS host fact-checked 0 of 8 and 0 of 10 pages (runs #693 and #699) because every cited path failed existence resolution. Run #699 was rejected outright for an unrelated reason — a valid per-target `notes` caveat in a `pr_summarizer` `doc_targets` item was flagged as an unknown-key schema violation — which this change also fixes.

## Decision

Add `lint.citation_source_roots` as an array of single-segment package-root strings (`backend`, `frontend`). `citation_exists.source_roots(config)` is the single reader: it strips slashes, and it **drops** any entry containing a slash or starting with a dot rather than erroring — a nested tail like `backend/storage` is suffix-matching in disguise, and suffix-matching admits confabulated paths, so failing closed (no widening) is the correct degradation for a Tier-1 block rule. `templates/config.schema.json` backs this with a `pattern` that rejects slashed entries outright, so the constraint holds even for a hand-edited config.

Resolution order is additive by construction: repo root, then `docs_dir`, then each declared root in declaration order. A root is only ever consulted after the first two have already failed to resolve a citation, so declaring `[backend, frontend]` can only turn a `block` into a pass — it cannot change the outcome for a citation that already resolved.

### The four resolution sites

The spec named four sites that all need `roots` threaded through in lockstep, because a citation is only as safe as its weakest resolver:

1. **`_resolves()`** in `scripts/lint/citation_exists.py` — the core bool helper behind the reported-failure path. `roots` is a **required** positional parameter here, deliberately not defaulted: this is a private helper with exactly two call sites, and a default would let either one silently keep the narrow behavior — a block rule that has quietly stopped blocking reports nothing.
2. **Both `check_path()` call sites** — the problem-reporting branch (`if not _resolves(...)`) and the stale-exemption branch (`if cited in exempt: if _resolves(...)`). The second matters on its own: a host that exempts a token which has since started resolving under a package root needs that surfaced as `stale exemption: '<token>' now resolves`, or the exemption list rots silently.
3. **The symbol loop's target resolution**, via the new `_resolve_target()` helper. This is the site a first pass at the fix missed. The symbol loop reads `if target is None: continue` — once the paths loop resolves `app/core/real_module.py` under `backend/`, an un-widened symbol resolver skips the file entirely rather than reporting, so a confabulated symbol (`app/core/real_module.py:ghost_fn`) attributed to a real file ships with no report at all. That is worse than the original narrow behavior: it is a silent skip, not a phantom block.
4. **`resolve_cited_sources()`**, and the orchestrator call site in `scripts/orchestrator_runner.py` that feeds it. This is a second, independent resolver — it feeds the fact-checker's admission gate (`if not cited_sources: continue`), so widening only the lint rule would let the linter accept citations the fact-checker still can't see. `resolve_cited_sources` also returns paths in **resolved** form now (`backend/app/core/real_module.py`, not the as-written `app/core/real_module.py`), because the fact-checker opens each entry relative to `repo_root`. Its `roots` parameter defaults to `()` — unlike `_resolves()` — because it is a public shared-helper contract with an existing production caller and existing tests that pass two positional arguments; the orchestrator call site now explicitly passes `_citation_exists.source_roots(config)` as the third argument.

Repo root is always tried before any declared root at every site, so a package root can never shadow a real top-level file of the same relative path.

## Verification strategy

Every widened site carries a negative control alongside its positive test: an invented path or symbol under a declared root must still block. A widening without its control converts a blocking gate into a silent one — which is exactly the failure mode site 3 already demonstrated once. The test suite (`tests/lint/test_citation_source_roots.py`) pairs each of the four sites with both a resolving case and a confabulation case, plus a standing `test_no_declared_roots_keeps_todays_behavior` control that pins byte-identical behavior for a host declaring no roots at all — the safety property that makes this change mergeable ahead of any host actually adopting it.

A separate four-site sentinel (`tests/orchestrator/test_citation_source_roots_sentinel.py`) drives the real orchestrator through the fact-checker's admission gate with all four sites wired, so a regression at any one of them fails a single named test rather than requiring someone to remember to check four places independently.

## Measured impact

Against the live ADIS host corpus (152 pages under `docs/site-src`):

- Pages failing `citation_exists` at block severity: **33 → 17**, with declared roots `[backend, frontend]`.
- **Zero** pages newly fail — the widened set is a strict subset of today's 33.
- `resolve_cited_sources` empty-result pages: 29 → 26; only 3 pages flip from an empty `cited_sources` list to a non-empty one, since most rescued citations sit on pages that already had some other source resolving.

The 17 surviving failures are not fixable by this change and were not meant to be: they need roots this design deliberately forbids (`backend/connectors`, a skill-relative `.claude/skills/...` tree), a `docs/site-src/core/` prefix on cross-links rather than a source root, or they are genuinely dead citations. Those are host-side documentation fixes, not a plugin resolver gap.

## Related fix: `pr_summarizer` `doc_targets.notes`

`agents/schemas/pr_summarizer.schema.json` sealed the `doc_targets` array items with `additionalProperties: false` over `lens`, `action`, `page_hint`, and `doc_kind` only — `notes` was permitted on the root object but not on an individual item, so a valid per-target caveat failed schema validation and rejected the whole `pr-summarizer` output. The item schema now also allows `notes`. Per the plugin's agent-schema lockstep convention, this was mirrored into the `## Output schema (canonical)` fenced block in `agents/pr-summarizer.md` in the same change, and the generated contract page under `docs/site-src/api/contracts/` was regenerated rather than hand-edited.
