---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/279
synthesized_into: []
doc_kind: decision
---

# CCE-181: Cross-Repo Citations — Declared External Repos, Rendered Before Lint (2026-09-21)

## Context

`page-author` sometimes has to point at a file that lives in a **different repository** than the one it is documenting. On 2026-09-21 it was documenting plugin work on a host repo and wrote the plugin's own path as an ordinary citation:

```
lint_block: docs/site-src/2026-09-13-cce101-eligibility-followup.md
            citation_exists: cites nonexistent path 'engineering-docs-agent/CLAUDE.md'
```

`citation_exists` is a Tier-1 **block** rule, and it is right to fail that citation — the path cannot exist in the host checkout it is linting against. But post-CCE-140 a blocked page is not merely blocked: the deferral skip abandons the whole PR and the page is **silently never written**. That specific block was one of the two contributors to the six-night baseline freeze CCE-175 and CCE-178 worked around from the orchestrator side; this decision fixes the underlying content problem instead.

The grounding rule in `agents/page-author.md` (CCE-110) offered exactly two escapes for a token that must not assert host-local existence: the reserved `example/` namespace for fictional paths (CCE-131), and a fenced block for dead names — removed, renamed, or never real. Neither escape covers an artifact that is real, current, and simply **in another repository**. That token is simultaneously true and uncitable, and the rule never said "exists" meant "exists in the host repo" — it just implied it. Handed a true statement it had no legal way to write, the agent wrote the natural thing and blocked the build.

## Decision

Add a third, **explicit and opt-in** escape: a host declares neighbouring repositories under a new `lint.external_repos` config block, keyed by a single-segment prefix. `page-author` is handed the declared prefixes and, when it needs to cite a file in one of them, emits a prefixed token of the shape

```
<declared-prefix>/<path within that repo>
```

instead of guessing a URL itself. A new pipeline stage renders that token into a GitHub blob link (for a declared public repo) or a bare basename with the repo never identified (for a declared private one), and it does this **before** `citation_exists` ever runs. An undeclared prefix, or an ordinary in-repo path, is left completely untouched and still blocks exactly as it does today.

The trigger is deliberately the declared prefix, never "the path doesn't resolve, so link it":

| Alternative trigger | Why rejected |
| --- | --- |
| Absence-of-resolution ("doesn't exist here + a repo is declared, so link it") | Its entry condition is exactly the confabulation population `citation_exists` exists to block — CCE-141 measured 2086 unique-suffix non-resolving tokens against 887 tracked files, every one of which would silently become a link. |
| A lint rule that flags cross-repo tokens advisorily | The page still blocks and is still abandoned; it diagnoses without fixing anything. |
| `lint.citation_exempt_tokens` per external path | Works, but every path has to be listed by hand on every host and the citation stays permanently unverified — a blunt workaround. |
| Widening `lint.citation_source_roots` | That mechanism resolves package roots *within the same repo*, by construction; cross-repo is out of scope for it. |
| Validating external links over the network at lint time | Puts a network dependency inside a Tier-1 block rule (offline/rate-limited CI turns red), and a declared-private repo can never be validated that way anyway. |
| The agent building the final link itself | Equally safe in principle, but the agent would have to guess the default branch and the host's blob-URL grammar — every wrong guess is a silent dead link, recurring on every run. |

The prefix is the agent's explicit claim that a token belongs elsewhere; it can never be reached by accident, which is the property that keeps this out of the CCE-141 class.

## What changed

- **New module `scripts/external_refs.py`** — pure, stdlib-only, no file I/O, the same shape as the diagnose-only `scripts/citation_repair.py`. Two functions: `resolve_config(config)` validates and normalizes `lint.external_repos` (raising `ExternalRepoConfigError` on a bad declaration), and `render_external_refs(text, repos)` is the pure text-in/text-out transform. The orchestrator owns all reading and writing.
- **Config schema** (`templates/config.schema.json`) gains `lint.external_repos`, an object keyed by a single-segment prefix. Each entry declares **exactly one** of `url` or `private: true` — both or neither is a config-load error, so a typo can never silently downgrade a public link or upgrade a private repo into a published URL. `ref` defaults to `main`; `blob_template` defaults to `{url}/blob/{ref}/{path}` (a GitLab host overrides it for `{url}/-/blob/{ref}/{path}`). A prefix that collides with a real directory in the host checkout is rejected at load, alongside the existing `_validate_lens_paths_are_editable` check.
- **`agents/page-author.md`** gains a fourth documented input, `external_repos` (the declared prefixes for this dispatch), and a third escape in the grounding rule: cite a declared-external artifact with its prefix, never construct the URL yourself, and an undeclared prefix is treated as an ordinary repo path and blocks. The agent's JSON output shape is unchanged.
- **`scripts/orchestrator_runner.py:_render_external_refs_for_pages`** is the new pipeline stage: for every page authored this run, it reads the file, runs `render_external_refs`, and writes back only if the text actually changed, using a temp-file-plus-`os.replace` atomic write so a mid-write failure never leaves a page half old and half new. It runs immediately ahead of `scripts/orchestrator_runner.py:_diagnose_citation_paths` — render, then diagnose, then validate — so the CCE-141 shortened-citation diagnostic never reports suffix-match noise for a token that is about to become a link.
- **`scripts/state_io.py`** carries the config-load wiring so `resolve_config` runs once per host config, the same lifecycle as other lint config sections.

Five properties of the rendering rule were treated as load-bearing rather than incidental, and each was checked by running the transform, not by reading the code:

1. Link text must be **slash-free**. Rendering a deep token (prefix plus a multi-segment path) to a link whose *visible text* still contains the full path still blocks, because `citation_exists`'s own citation extractor scans backticked spans wherever they appear and markdown link syntax exempts nothing from that scan — only the basename in the visible text is safe.
2. The `:line` / `:symbol` citation suffix is grammar, not a filesystem path, and must be stripped from the URL (kept in the visible text) — left in the address it produces a URL that 404s while still passing the linter, a silent dead link nothing downstream catches.
3. Fenced code blocks are never rewritten; they are samples, not citations.
4. A token is rendered only if it would otherwise have been recognized as a citation at all — the same grammar and placeholder exemption `citation_exists` itself uses, plus an explicit rejection of any `..` path segment (which would otherwise retarget the rendered link to an arbitrary repository on the configured forge via ordinary URL dot-segment resolution).
5. A rewrite never crosses a backtick run. A citation token is normally matched as a single backtick pair, but CommonMark pairs backtick *runs* of equal length anywhere in a paragraph, not single backticks; rewriting a match that abuts another backtick changes run lengths and can dissolve a **neighbouring** token's code span, letting content that was escaped before the rewrite become live markup after it. When either delimiter of the matched span abuts another backtick, the renderer declines and leaves the token untouched — it reverts to pre-CCE-181 behavior and blocks, which is the safe direction.

Properties 4 and 5 did not exist in the first design pass; they were found by a whole-branch review that rendered the output through an actual markdown parser rather than checking it against the linter's grammar alone, and are recorded because each closes a real BLOCK→PASS corruption that had already been produced and measured (100 payload-attributable flips for the code-span case, 0 the other way).

## Error handling / degradation

| Situation | Behavior |
| --- | --- |
| No `external_repos` declared | The renderer is a true no-op: zero filesystem I/O, tree byte-identical to today. |
| Declared prefix collides with a real host directory | Rejected at config load; every page stays exactly as it is. |
| Undeclared prefix used in a citation | Left unrendered; `citation_exists` blocks it exactly as before. |
| Token fails the render gate (placeholder, bad grammar, `..` segment) | Left unrendered; ships as an ordinary escaped code span. |
| Token wrapped in a mismatched backtick run | Left unrendered rather than published on delimiters the renderer cannot model. |
| A per-page render failure (unreadable/undecodable text, write error) | Recorded as a **blocking**, `degraded=True` reason. Outside an archive section the token's `/` survives, so `citation_exists` still blocks it and the page is caught by the ordinary lint-block-and-revert path; inside an `archive-index` section CCE-124 downgrades `citation_exists` to `warn`, so without `degraded=True` a swallowed failure there would ship the raw prefixed token as prose with no block at all. |

## Testing

TDD, fixture-driven, fixtures modeling an arbitrary host rather than this repo's own tree:

- `tests/scripts/test_external_refs_config.py` and `tests/scripts/test_external_refs_render.py` cover `resolve_config` schema validation and every row of the rendering table above, including the slash trap and the suffix trap as named regressions, and idempotency (rendering twice is a no-op).
- `tests/scripts/test_state_io_external_repos.py` covers the config-load wiring.
- `tests/orchestrator/test_external_refs_wiring.py` and `tests/orchestrator/test_external_refs_e2e.py` cover the orchestrator call site and an end-to-end run — including, per the CCE-179 lesson that a test reaching its assertion by a different code path than production is not coverage, exercising the non-time-truncated production shape rather than only the truncated one.
- `tests/orchestrator/test_classification_coverage.py` covers the `degraded=True` classification of a render failure.

## Out of scope

- Widening `citation_exists` itself to recognize the prefixed form — it never sees it, by design; the rendering happens first.
- Any absence-of-resolution trigger for the escape — rejected explicitly above as the CCE-141 class.
- Validating external links over the network — rejected above; a dead link from a wrong `url`/`ref` is visible to readers, which is judged an acceptable cost against putting a network call inside a Tier-1 block rule.

## See also

- CCE-141: the shortened-citation diagnostic this stage runs ahead of, and the precedent that a module which *rewrites* text inherits the linter's blind spots as mutations rather than mere gaps.
- CCE-140: the deferral skip that turns a blocked page into a silently unwritten one.
- CCE-175 / CCE-178: the baseline freeze this citation block contributed to.
- CCE-110: the `page-author` grounding rule this decision amends with a third escape.
- `docs/superpowers/specs/2026-09-21-cce181-cross-repo-citations-design.md`: full design spec, including the whole-branch review that found the code-span defect.
- `scripts/external_refs.py`, `scripts/orchestrator_runner.py`, `agents/page-author.md`, `templates/config.schema.json`: the changed surfaces.
