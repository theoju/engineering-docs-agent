---
description: 'Documents architecture external citations: page-author can now cite files that live in a different, declared repository. A host lists neighbouring repos under a new `lint.external_repos` config block; page-author emits a prefixed citation token (`<prefix>/<path>`), and the orchestrator renders that token into a GitHub blob link (for a public neighbour) or a bare basename (for a private one, so the repo is never named) before the linter runs. `citation_exists` never sees the prefixed form and required no change. Undeclared prefixes and ordinary in-repo paths are left untouched and still block as before. The renderer is config-gated: a host with no `external_repos` declared gets a byte-identical, zero-I/O no-op.'
source_files:
  - CLAUDE.md
  - agents/page-author.md
  - docs/superpowers/plans/2026-09-21-cce181-cross-repo-citations.md
  - docs/superpowers/specs/2026-09-21-cce181-cross-repo-citations-design.md
  - requirements-dev.txt
  - scripts/external_refs.py
  - scripts/orchestrator_runner.py
  - scripts/state_io.py
  - templates/config.schema.json
  - tests/orchestrator/fakes_external_repo/fake_content_validator.json
  - tests/orchestrator/fakes_external_repo/fake_gap_detector.json
  - tests/orchestrator/fakes_external_repo/fake_notifier.json
  - tests/orchestrator/fakes_external_repo/fake_page_author.json
  - tests/orchestrator/fakes_external_repo/fake_pr_summarizer.json
  - tests/orchestrator/fakes_external_repo/fake_source_collector.json
  - tests/orchestrator/test_classification_coverage.py
  - tests/orchestrator/test_external_refs_e2e.py
  - tests/orchestrator/test_external_refs_wiring.py
  - tests/scripts/test_external_refs_config.py
  - tests/scripts/test_external_refs_render.py
  - tests/scripts/test_state_io_external_repos.py
last_reviewed: '2026-09-26'
status: draft
---
# External citations

`page-author`'s grounding rule (CCE-110) requires a backticked path to assert that the artifact exists in the **host** repo. Until CCE-181, that left no legal way to cite something that is real, current, and simply lives somewhere else. A page documenting plugin work on a downstream host repo would write the plugin's own path:

```
engineering-docs-agent/CLAUDE.md
```

— and `citation_exists` (Tier-1 **block**) correctly failed it, because that path cannot exist in that host's checkout. Post-CCE-140 that block is not a stall: the deferral skip abandons the PR and the page is silently never written. This is the mechanism CCE-141 already named for a different trigger (a shortened in-repo path); CCE-181 hits the same "page is silently never written" outcome from a cross-repo citation instead.

## Declaring a neighbour repo

A host lists other repositories under `lint.external_repos` in its config, keyed by the single-segment prefix an author writes:

```yaml
lint:
  external_repos:
    engineering-docs-agent:
      url: https://github.com/theoju/engineering-docs-agent
      ref: main # optional, default "main"
    ship-skill:
      private: true # no url, ever
```

Each entry declares **exactly one** of `url` or `private: true`. `resolve_config` in `scripts/external_refs.py` rejects a declaration at config load if it has both, or neither, or if the prefix collides with a real top-level directory in the host repo, or if the prefix contains a `/`. It also format-checks `blob_template` against dummy values at load time — a malformed template (an extra placeholder, a stray unmatched brace) fails once at startup with a clear message instead of once per page at render time. `ref` defaults to `main`; `blob_template` defaults to `{url}/blob/{ref}/{path}` (a GitLab host would override this to `{url}/-/blob/{ref}/{path}`). A host that declares nothing gets an empty map, and every downstream step described below becomes a no-op.

## What page-author writes

Given a declared prefix, `page-author` cites the artifact as `` `<prefix>/<path within that repo>` `` — never constructing a URL itself. An undeclared prefix is treated as an ordinary in-repo path and still blocks, which is correct: the prefix is the agent's explicit claim that the token is elsewhere, and that claim is only legal for a prefix the host actually declared.

## Render-before-lint

`_render_external_refs_for_pages` in `scripts/orchestrator_runner.py` runs once over every page a batch authored, after the authoring loop and before `_diagnose_citation_paths` and the content-validator dispatch — so the diagnostic and the linter both see the rendered page, never the raw prefixed token. `citation_exists` was not changed at all: it never sees the prefixed form, because the rewrite already happened.

The rewrite is a plain function, `render_external_refs(text, repos)` in `scripts/external_refs.py`: pure, stdlib-only, no file I/O (the orchestrator owns reading and writing, the same shape as `scripts/citation_repair.py`). For a public entry it produces a markdown link to the file at the configured ref:

```
`engineering-docs-agent/CLAUDE.md`  ->  [`CLAUDE.md`](https://github.com/theoju/engineering-docs-agent/blob/main/CLAUDE.md)
```

For a private entry it produces the bare basename, with no link and the repo never named:

```
`ship-skill/spokes/pre-flight.md`  ->  `pre-flight.md`
```

A `:line`/`:symbol` citation suffix is stripped from the rendered URL (it is citation grammar, not a filesystem path, and left in the address it would 404 while still passing the linter) but kept in the visible link text, where it is slash-free and inert. An undeclared prefix, or an ordinary repo-local path with no prefix at all, is left untouched and still blocks exactly as before.

The write in `_render_external_refs_for_pages` only touches a page whose text actually changed, and it writes atomically — a temp file named as a dotfile in the same directory, then `os.replace` — so a failure partway through (disk full, permission revoked mid-write) can never leave a page on disk as neither its old content nor its new one. A per-page render failure is caught and recorded as a blocking, `degraded=True` partial reason rather than sinking the whole run: on a live lens the untouched page still carries its raw `prefix/path` token, which `citation_exists` still recognizes and blocks, so the failure is loud and self-healing via the existing lint-block-and-revert path. The one case that reasoning does not cover is a section whose generator is `archive-index`, where CCE-124 downgrades `citation_exists` to `warn` — there a swallowed render failure would ship the raw token as prose with no block at all, which is exactly why the failure path is classified `degraded=True` rather than `info_only`: it flips `partial`, and the CCE-101 auto-merge gate already treats a partial run as ineligible, forcing human review instead of a silent ship.

## The delimiter guard

The rewrite gates on the same predicate `citation_exists` itself uses to decide whether a token is even a citation — `_REPO_PATH_RE.match(token) and not _is_placeholder(token)` — imported from `scripts/lint/citation_exists.py` rather than copied, so the two can never drift apart. It also rejects any token containing a `..` path segment: `_REPO_PATH_RE`'s character class admits `.` and `/` and does not by itself reject a `..` segment, and (confirmed by running it) a `../../../../evil-org/evil-repo.md` token renders to a syntactically valid link whose destination RFC 3986 dot-segment resolution retargets to an arbitrary repository on the configured forge — a link-retargeting primitive, not XSS, but real enough that no legitimate citation ever needs a `..` segment in the first place.

The subtler guard is about backtick delimiters, not content. `render_external_refs`'s own inline-code regex models a code span as exactly one backtick per side, but CommonMark does not: a delimiter is a *run* of backticks, and an opener pairs with the next run of equal length anywhere in the paragraph. Rewriting a token whose delimiter abuts another backtick consumes exactly one backtick from each side, changing the run lengths the rest of the paragraph pairs against — content that was safely escaped inside a code span before the rewrite can fall out of one after it. This was measured, not assumed: a prior review found 100 payload-attributable Tier-1 BLOCK→PASS flips this way (84 in `citation_exists`, 16 in `internal_links`), every one requiring the accepted token to sit inside a run-length mismatch. The fix is not to model backtick runs correctly — reusing `internal_links.CODE_SPAN_RE` would mean correctly identifying the span and then still rewriting it, which needs run-pairing to be exactly right, more machinery in the direction CCE-141 already condemned. Instead the renderer declines: if either delimiter of a matched token abuts another backtick, the token is returned untouched. The consequence is the point, not a regrettable side effect — a token wrapped in a doubled backtick reverts to pre-CCE-181 behavior, `citation_exists` reads the raw prefixed token and blocks it, loud and self-healing.

## Why not trigger on non-resolution

The tempting design is "if the path doesn't resolve in the host, and an external repo is declared, link it." Its entry condition is exactly the confabulation population `citation_exists` exists to block — CCE-141 measured 2086 unique-suffix non-resolving tokens against 887 tracked files, and under that design every one becomes a link, turning a BLOCK into a silent PASS. That is the same class of defect that cost CCE-141 four adversarial review rounds before the repair capability there was deleted outright rather than patched a fifth time. CCE-181 avoids it structurally: the escape is opt-in *per token*, gated on an explicit declared prefix the agent must name, never on the token's failure to resolve. A rejected token's page text never changes, so nothing this renderer declines to touch is any less safe than it was before CCE-181 existed.

## Config-gated no-op

A host that declares no `lint.external_repos` gets `resolve_config(config)` returning an empty map, and `_render_external_refs_for_pages` returns immediately without reading or writing anything. There is no reachability today on this repo's own dogfood config — no host declares `external_repos` yet — so this path is exercised only by `tests/scripts/test_external_refs_config.py`, `tests/scripts/test_external_refs_render.py`, `tests/orchestrator/test_external_refs_wiring.py`, and `tests/orchestrator/test_external_refs_e2e.py`.
