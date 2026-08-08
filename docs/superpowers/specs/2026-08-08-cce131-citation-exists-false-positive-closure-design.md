# CCE-131 — `citation_exists` false-positive closure

**Status:** approved, ready for planning
**Date:** 2026-08-08
**Ticket:** CCE-131
**Extends:** CCE-110 (citation existence), CCE-122 (line-free citations), CCE-124 (archive-lens advisory)

## 1. Problem

`citation_exists` is a Tier-1 **block** rule. When it fails a page, the orchestrator does not merely warn — it reverts or deletes the page and drops it from the docs PR. That makes a false positive expensive: the page never lands, and because the nightly re-authors from scratch, the same page is re-authored and re-blocked the next night.

This has now happened on two consecutive runs. PR #197 blocked on `cce-capability-c-canonical-core-citations.md` and `cce-capability-c2-canonical-core-authoring.md`; PR #198 blocked on the citations page again plus `content-validator.md`. The set of pages caught rotates run to run, because the authoring batch is non-deterministic — which is why the failure reads as chronic rather than as one broken page.

Four tokens are blocking, and all four are false positives:

| token                       | page                                           | role                      |
| --------------------------- | ---------------------------------------------- | ------------------------- |
| `scripts/auth/session.py`   | `cce-capability-c-canonical-core-citations.md` | fictional-host example    |
| `test_snake_case`           | same                                           | metasyntactic placeholder |
| `tests/scripts/__init__.py` | `content-validator.md`                         | deliberately absent       |
| `test_lint_runner`          | same                                           | test-family shorthand     |

`scripts/auth/session.py` has been on that page since `da1446d` (2026-05-28, CCE-36 / PR #48) — roughly ten weeks. It is not a regression. The lint runs only on authored or edited pages, so a latent bad token sits silent until the page re-enters an authoring batch, then blocks every run until the page changes.

`test_snake_case` is worth stating plainly: it appears exactly once in the repository, in the module docstring of `scripts/lint/citation_exists.py`, where it is a placeholder standing for "a token shaped like a test identifier." The page-author read the rule's source in order to document the rule, quoted the placeholder, and the rule blocked the page for it. The rule rejected a page for citing the rule's own documentation of itself.

## 2. Why the obvious fix is wrong

The natural move is to reuse CCE-124's per-result severity and downgrade `citation_exists` to advisory for the `architecture/` lens, exactly as CCE-124 did for `archive/`. Two independent findings rule it out.

**Page granularity is too coarse, empirically.** Per-result severity is keyed on the result's path, so the finest available granularity is the page. `architecture/structured-docs-site-generation.md` cites four non-resolving paths, and three of them are genuine confabulations:

| token                                 | reality                                   |
| ------------------------------------- | ----------------------------------------- |
| `scripts/build_doc_source_map.py`     | real file is `scripts/source_map.py`      |
| `scripts/generate_archive_indexes.py` | real file is `scripts/archive_indexes.py` |
| `scripts/verify_docs_diagrams.py`     | real file is `scripts/verify_diagrams.py` |
| `backend/connectors/postgres.py`      | fictional host, legitimately absent       |

A page-scoped downgrade on this page silences three real defects to clear one false positive. Six such near-miss confabulations exist corpus-wide, and one of them — `agents/schemas/page-author-output.json`, whose real name is `agents/schemas/page_author.schema.json` — is what blocked PR #197. The rule is earning its keep in the same lens where it misfires.

The trap is that the page blocking PR #198 is a _pure_ false-positive page: one token, no real defects. A page-scoped fix would unblock the presenting case cleanly and be wrong for the class.

**The severity signal is LLM-mediated.** The orchestrator does not invoke `scripts/lint/lint_runner.py` directly. It dispatches the `content-validator` subagent, which runs the linter and re-emits a `failed` array. Per-result severity reaches the orchestrator only because `agents/content-validator.md` instructs the model in prose to carry it across. `agents/schemas/content_validator.schema.json` marks `severity` required with `enum: ["block", "warn"]`, so a model that _drops_ the field fails schema — but a model that _defaults it to_ `block` is schema-valid and silently re-blocks the page.

That is the CCE-125 lesson restated: the schema is the real gate, and a field the schema permits is a field the model may get wrong. A fix whose failure mode is "the fix silently does not apply" is worse than no fix, because it reports success.

## 3. What the corpus actually contains

A scan of all non-fenced inline code spans, resolved against `git ls-files` and an AST scan of every tracked Python file:

- **`main`:** 39 non-resolving tokens across 20 of 94 pages.
- **PR #198 branch:** roughly 22 additional tokens, concentrated on the ~20 pages the run touched.

That is ~0.4 non-resolving tokens per settled page against ~1.1 per freshly authored page. **The elevated rate is an authoring defect rate, not corpus rot.** An authoring-rate problem can only be closed at the authoring contract, which is why §4's contract change is load-bearing rather than a nicety.

Sorting the tokens by why they fail is what determines the fix. Two categories from an early draft of this analysis do not survive scrutiny and are recorded here so they are not re-proposed:

- **Glob patterns** (`scripts/*.py`, `agents/schemas/*.json`) — these never fire. `*` is already in `_PLACEHOLDER_MARKERS` in `scripts/lint/citation_exists.py`.
- **Runtime artifacts** — `.engineering-docs-agent/current_run.json` is gitignored but present on disk, and the existing disk fallback in `check_path` already passes it. The tokens in this shape that _do_ fire are neither gitignored nor present; they are confabulations.

The surviving taxonomy, with the verdict that drives the design:

| role                         | count on `main`           | lint is                | treatment                        |
| ---------------------------- | ------------------------- | ---------------------- | -------------------------------- |
| near-miss confabulation      | 6                         | **correct**            | none — fix the content (CCE-132) |
| docs-relative / build-output | ~6                        | false positive         | **resolver bug** → A1            |
| test-family shorthand        | 3                         | false positive         | **matching bug** → A2            |
| fictional-host example       | ~3                        | false positive         | **naming convention** → A4       |
| deliberately absent          | 3                         | false positive         | **policy** → B                   |
| historical reference         | ~20 (9 on `whats-new.md`) | correct but misapplied | lens policy (CCE-133)            |

The shape of that table is the central result. Only one row needs a policy surface. The rest are the rule being wrong about what exists, which is fixed by making the rule right rather than by adding a way to overrule it.

## 4. Design

Six changes. Every one of them acts before severity is computed, so none depends on the subagent relay described in §2.

### A1 — Resolve docs-relative and build-output paths

`check_path` in `scripts/lint/citation_exists.py` resolves candidates repo-root-relative only. A docs page that cites a sibling page (`api/reference/pkg/calc.md`) or names mkdocs build output (`site/api/http/index.html`) therefore fails, though both are correct references.

Add `<docs_dir>/<token>` as a second resolution candidate, reading `docs_dir` from the `site:` config block, and skip tokens whose first path segment is the build-output directory — mkdocs `site_dir`, which the host's mkdocs config may set and which defaults to `site`. Resolve it from that config when present; fall back to the `site` default otherwise. A host on a different generator with no such directory skips nothing, which is the correct no-op.

This requires threading config into `check_path`, whose signature is a declared shared-helper contract, making it `check_path(path, repo_root, files, config)` — which also aligns it with every other lint rule in `scripts/lint/`, all of which already take `(path, config)`. Its external call sites are exactly two, both tests: `tests/lint/test_site_citations_line_free.py` and `tests/scripts/test_migrate_line_citations.py`. `scripts/orchestrator_runner.py` and `scripts/lint/citation_line_free.py` import from this module but call `resolve_cited_sources` and `line_pinned_citations` respectively, neither of which changes signature. Hosts with no `docs_dir` configured degrade to today's repo-root-only behavior.

### A2 — Prefix-match test identifiers at a `_` boundary

`cited_test_exists` greps for `def <name>(`, an exact-name match. The corpus naturally writes test _families_: `test_lint_runner` names a group whose members are `test_lint_runner_missing_script_reports_block` and `test_lint_runner_empty_output_reports_block`.

Also grep `def <name>_`. The boundary anchor is deliberate: a confabulated `test_foo` passes only when a real `test_foo_*` exists. The CCE-111 confabulations this rule was built to catch were wholly invented names matching no prefix, so the guard that caught them is preserved.

This also narrows an existing asymmetry — cited paths get a disk-existence fallback for same-run untracked files, cited tests do not, because `cited_test_exists` searches tracked files only. A2 does not close that asymmetry; it is noted in §7.

### A3 — Fence stripping fails closed

`strip_fenced_blocks` treats an unterminated fence as opening a block that never closes, and returns everything before it. Every citation after a stray fence is silently unchecked, for the rest of the file, with no report. A Tier-1 block rule quietly stops running and nothing surfaces it.

Stop stripping at EOF instead, so an unterminated fence leaves the remaining text checkable.

**This is the only change in this spec that can increase the blocked-token count.** A3 must therefore be verified by a full-corpus scan before merge, not by the unit suite alone — the repo's "run the actual consumer tool" invariant applied to a linter. The net token delta across A1–A4 must be measured, not assumed.

### A4 — Reserved example namespace

The plugin's generic-first mandate _requires_ fictional-host examples: documentation that hardcodes this host's `scripts/` layout is wrong documentation. Those examples are safe inside fenced blocks, which the rule already strips, and unsafe the moment an author writes one in a prose bullet — which is exactly what happened on the citations page, where the fenced YAML at the top of the section is ignored and the same fiction in the following bullet blocks the build.

Skip any token whose first path segment matches a configured example prefix, defaulting to `example/`. The precedent is RFC 2606's reserved `example.com`: a namespace guaranteed never to resolve, so it can be used freely in documentation.

This converts a judgement call into a naming rule. `scripts/auth/session.py` stops being "an example the linter cannot recognize" and becomes "an example written in the wrong namespace," which has a deterministic fix.

**A4 is the PR #198 unblock.** The migration on `cce-capability-c-canonical-core-citations.md`:

```diff
- - A page with `source_files: [scripts/auth/**/*.py]` is flagged when
-   `scripts/auth/session.py` appears in a PR's file list.
+ - A page with `source_files: [example/auth/**/*.py]` is flagged when
+   `example/auth/session.py` appears in a PR's file list.
```

This is better than fencing the bullet: the prose stays prose, the list formatting stays consistent, and the fictional path stays fictional, which the generic-first mandate wants.

### B — `lint.citation_exempt_tokens`

One class survives every resolver improvement: tokens whose **non-existence is the claim**. `tests/scripts/__init__.py` must not exist — that is a recorded invariant in `CLAUDE.md`, and a page documenting it necessarily names it. No amount of resolver completeness helps, because the rule is right that the file is absent and wrong about what the absence means.

Add an exact-match exempt list under `lint.citation_exempt_tokens`, read the way `scripts/lint/stub_redirect.py` reads `lint.stub_paths`. `templates/config.schema.json` declares no `additionalProperties` on `properties.lint`, so the key is schema-additive and existing host configs keep validating.

Two properties the list must have:

- **Self-cleaning.** A listed token that _does_ resolve emits a `warn` naming it as a stale exemption. Without this the list silently accumulates entries that no longer suppress anything, and the next reader cannot tell which entries are load-bearing.
- **Plugin defaults, host extension** — the same shape as `lint.tier1: default`. The defaults are a module-level constant in `scripts/lint/citation_exists.py`, unioned with the host's `lint.citation_exempt_tokens` entries; host config extends the defaults and never replaces them. `test_snake_case` is plugin-intrinsic: it lives in that module's own docstring, so _every_ host that documents this lint hits it, and no host should have to discover that for themselves. `tests/scripts/__init__.py` is this host's invariant and belongs in this host's config.

Keep the shipped default list minimal. Every entry is a place the rule has been told to stop looking.

### C — `agents/page-author.md`

The authoring contract currently carries one citation rule — cite only files and tests you confirmed exist — and **no concept of a non-citation.** There is no vocabulary for an illustrative path, a fictional host, or a metasyntactic placeholder, and the only sanctioned escape (put it in a fence, per the rule's own docstring) is unavailable in the prose bullets where authors naturally write examples.

Add the missing distinction:

- A backticked path or test identifier **asserts that the artifact exists**. Write one only when it does.
- An illustrative or fictional-host path uses the `example/` namespace.
- A metasyntactic token — a placeholder standing for a shape rather than naming a thing — goes inside a fenced block.

Without C, A4's migration buys one night. The page regenerates nightly from the same grounding set (`CLAUDE.md` is a declared voice sample; `scripts/lint/citation_exists.py` is in the grounding set for any page about linting), and an author who has not been told the convention re-emits the old token. The §3 finding that fresh authoring produces roughly three times the settled corpus's defect rate is the quantitative form of the same point.

## 5. Testing

Red-green per change, following the repo's TDD convention. All tests use the fixture-driven dry-run path.

- **A1:** a page under `docs_dir` citing a sibling page passes; the same token on a host with no `docs_dir` still blocks (generic-first guard); a build-output path is skipped.
- **A2:** `test_lint_runner` passes when `test_lint_runner_missing_script_reports_block` exists; a confabulated `test_foo` still blocks when no `test_foo_*` exists; the boundary holds — `test_lintrunner` does not pass on `test_lint_runner_x`.
- **A3:** a page with an unterminated fence still has its trailing citations checked. This is a red-green discriminator with no existing coverage.
- **A4:** `example/auth/session.py` passes; `scripts/auth/session.py` still blocks; a host that configures a different prefix gets that prefix and not the default.
- **B:** a listed token passes; an unlisted sibling still blocks; a listed token that resolves emits the stale-exemption `warn`; plugin defaults apply with no host config present, and host entries extend rather than replace them.
- **Regression guard:** the CCE-110 incident fixtures in `tests/lint/test_citation_exists.py` must stay red-on-confabulation. They are the check that A1–A4 have not relaxed the rule into uselessness.
- **Corpus verification, pre-merge:** run the rule over every page under the docs source dir and record the before/after non-resolving token count. A3 can raise the count; A1, A2, and A4 lower it. The net must be measured. Passing pytest is not sufficient evidence here.

**Drive-by fix.** `tests/lint/test_citation_exists.py` does `sys.path.insert` followed by a bare `import citation_exists`, and `tests/lint/__init__.py` exists — precisely the pattern `CLAUDE.md`'s CCE-122 entry forbids, and one collection-order change away from the order-dependent `ModuleNotFoundError` that entry documents. Every change in this spec edits this file; convert it to the dotted namespace import in passing.

## 6. Out of scope

Each of these was considered and deliberately excluded.

- **The six near-miss confabulations already on `main`.** Real content defects, blocking nothing today because their pages are not being re-authored. CCE-132, so a lint change does not carry unrelated content edits.
- **`whats-new.md`'s historical tokens** — 9 on `main`, 15 on the branch. The page carries `generator: changelog` and is structurally condemned to cite deleted files. The fix is to add `changelog` to CCE-124's downgrade set beside `archive-index`, which is the same argument CCE-124 already accepted. CCE-133, separate because it routes through the LLM-mediated severity path described in §2, and that risk should be a scoped, deliberate acceptance on an advisory-only page rather than a rider on this change.
- **Inline cite-ignore markers.** CCE-124 deferred this explicitly as YAGNI, and the corpus evidence now supports that call: A4 and B reach every case the marker would. Its cost is real — `extract_citations`, `extract_symbol_citations`, and `line_pinned_citations` all share a `findall` loop that discards match offsets, so token-level marker association means converting all three to `finditer`, and `extract_citations` is a declared shared-helper contract.
- **Negation awareness.** Recognizing a sentence that says a file deliberately does not exist is natural-language inference inside a deterministic lint. B handles the three real instances at a fraction of the risk.
- **Generalizing archive-lens scoping into a full per-lens disablement config.** Two generators need advisory treatment. A config surface plus a setup-skill question is not warranted for two.

## 7. Known limitations

- **Gitignored-but-real paths.** `.engineering-docs-agent/current_run.json` passes locally because the disk fallback finds it mid-run, and would fail on a clean CI checkout before the runner writes it. The rule's verdict on a gitignored path therefore depends on when in the run it executes. No code change here; nobody has hit it. Recorded so the next person to see it recognizes it.
- **Test-existence asymmetry persists.** Cited paths get a disk fallback for same-run untracked files; cited tests do not, because `cited_test_exists` searches tracked files only. A test written in the same run in a new untracked file still false-blocks. A2 narrows the family case but not this one.
- **A4 depends on authors adopting the namespace.** The rule enforces the namespace deterministically once used, but nothing forces an author to use it rather than inventing another fictional root. C is what closes that, and C is a prose instruction to a model. The failure mode is benign — a blocked page, visible in `partial_reasons` — rather than silent, which is the property that matters.
- **The exempt list is a place the rule stops looking.** Its self-cleaning `warn` catches entries that became unnecessary. Nothing catches an entry that was wrong when it was added.

## 8. Follow-up tickets

| ticket  | scope                                                                             |
| ------- | --------------------------------------------------------------------------------- |
| CCE-132 | Fix the 6 near-miss confabulations on `main`                                      |
| CCE-133 | Extend CCE-124's advisory downgrade to the `changelog` generator (`whats-new.md`) |
