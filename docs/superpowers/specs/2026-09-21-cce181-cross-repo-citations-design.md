# CCE-181 — cross-repo citations: declared external repos, rendered before lint

**Status:** design approved, not yet implemented
**Date:** 2026-09-21
**Ticket:** CCE-181
**Prototype:** `proto/CCE-181-sibling-render` @ `0c1f23b` — `scripts/PROTOTYPE-cce181-sibling-render.html`

## The problem

`page-author` sometimes must point at a file that lives in a **different repository**. On 2026-09-21 it
documented plugin work on `theoju/claude-code-self-assessment` and wrote the plugin's own path:

```
lint_block: docs/site-src/2026-09-13-cce101-eligibility-followup.md
            citation_exists: cites nonexistent path 'engineering-docs-agent/CLAUDE.md'
```

`citation_exists` is Tier-1 **block** and is right to fail it — that path cannot exist in the host
checkout. Post-CCE-140 a blocked page is not a stall: the deferral skip abandons the PR and the page is
**silently never written**. Host PR #253 carried this block and was closed by hand; its content is not on
the site. The block also fed the six-night baseline freeze that CCE-175 and CCE-178 worked around from the
orchestrator side. Those made the freeze survivable. This is one of the two things that caused it.

### Root cause: no escape for real-but-elsewhere

The grounding rule in `agents/page-author.md` (CCE-110) offers exactly two escapes for a token that must
not assert host-local existence:

- the reserved `example/` namespace — for **fictional** paths (CCE-131);
- a fenced block — for **dead** names: removed, renamed, never real.

Neither covers the third case: an artifact that is **real, current, and in another repository**. That
token is simultaneously true and uncitable. The rule also says "cite only files you confirmed exist"
without ever saying _exist where_ — the implicit answer is "in the host repo," and it is never stated.
Handed a true statement it has no legal way to write, the agent writes the natural thing and blocks the
build.

### There was no precedent to copy

Zero backticked cross-repo citations exist anywhere on the host site. A grep for `engineering-docs-agent/`
appears to find five pages using one happily, but all five cite `.engineering-docs-agent/config.yml` —
**leading dot**, the host's own config directory, which exists. `grep -o` for the backticked form returns
nothing across all 29 site pages while `citation_exists` passes 29/29. This is an unhandled case, not a
lapse in following a known pattern.

## Decisions

| Question                               | Decision                                                                   |
| -------------------------------------- | -------------------------------------------------------------------------- |
| Navigable or merely nameable?          | **Navigable**, via config-declared external repos                          |
| What entitles the agent to the escape? | **An explicit declared prefix in the token** — never absence-of-resolution |
| Does `citation_exists` change?         | **No.** Links, URLs and slash-free backticked names already pass           |
| Private external repos?                | **Artifact name only, repo never identified**                              |

### Why not absence-triggered

The intuitive trigger — "the path does not resolve in the host, and an external repo is declared, so link
it" — has as its entry condition exactly the confabulation population `citation_exists` exists to block.
CCE-141 measured **2086** unique-suffix non-resolving tokens against **887** tracked files. Every one of
them would become a link: a `BLOCK` turning into a silent `PASS`. That is the precise class CCE-141 failed
to guard across four adversarial rounds and ultimately deleted the capability over. The prefix is the
agent's **explicit claim** that a token is elsewhere; it cannot be reached by accident.

### Naming: `external_repos`, not `sibling_repos`

The design was drafted as `sibling_repos` and renamed after searching the tree. CCE-141 already owns
"sibling" in this exact subsystem, meaning **a file written during the same run** — see
`tests/orchestrator/fakes_sibling_citation/` and
`test_citation_repair.py::test_a_same_run_untracked_sibling_is_a_known_blind_spot`. Reusing the word for
"another repository" a few functions away would be actively confusing. "External" names the property
directly: outside this repo. The prototype predates the rename and still says _sibling_ internally.

## Config

```yaml
lint:
  external_repos:
    engineering-docs-agent: # key = the path prefix
      url: https://github.com/theoju/engineering-docs-agent
      ref: main # optional, default "main"
    ship-skill:
      private: true # no url, ever
```

New key `lint.external_repos`, an object keyed by prefix.

- Each entry declares **exactly one** of `url` or `private: true`. Both, or neither, is a schema error
  rejected at config load. Making absence-of-`url` a _loud_ error rather than an implicit "private" means
  a typo cannot silently downgrade a public link, and a missing declaration can never upgrade a private
  repo into a published URL.
- `ref` defaults to `main`. `blob_template` defaults to `{url}/blob/{ref}/{path}`; GitLab hosts override
  with `{url}/-/blob/{ref}/{path}`. The URL grammar lives in config, not in the agent's head — this is the
  whole argument for rendering in the pipeline rather than having the agent emit the link.
- Keys are **single-segment**. This follows `citation_source_roots`, where multi-segment entries are
  rejected as suffix-matching in disguise.

## The rendering rule

Deterministic prefix substitution. No inference of any kind.

| Input token                                                   | Declaration | Output                                                                             |
| ------------------------------------------------------------- | ----------- | ---------------------------------------------------------------------------------- |
| `` `engineering-docs-agent/CLAUDE.md` ``                      | `url:`      | ``[`CLAUDE.md`](https://…/blob/main/CLAUDE.md)``                                   |
| `` `engineering-docs-agent/scripts/orchestrator_runner.py` `` | `url:`      | ``[`orchestrator_runner.py`](https://…/blob/main/scripts/orchestrator_runner.py)`` |
| `` `engineering-docs-agent/scripts/x.py:Klass.method` ``      | `url:`      | ``[`x.py:Klass.method`](https://…/blob/main/scripts/x.py)``                        |
| `` `ship-skill/spokes/pre-flight.md` ``                       | `private:`  | `` `pre-flight.md` ``                                                              |
| `` `scripts/foo.py` ``                                        | undeclared  | unchanged → still blocks                                                           |

Three properties are load-bearing and each was verified by running the prototype, not by reading it:

1. **Link text must be slash-free.** ``[`scripts/orchestrator_runner.py`](url)`` **still blocks** —
   `extract_citations` scans backticked spans wherever they appear, and markdown link syntax exempts
   nothing. Only the basename is safe. The obvious rendering is the broken one.
2. **The `:line` / `:symbol` suffix is citation grammar, not a filesystem path.** Left in the address it
   yields `…/blob/main/scripts/x.py:Klass.method`, a 404 that **passes the linter** — a silent dead link
   nothing downstream can catch. Strip it from the URL with the existing `_SUFFIX_RE`; keep it in the
   visible text, where it is slash-free and therefore inert.
3. **Fenced blocks are never rewritten.** They are samples, not citations, and `strip_fenced_blocks`
   already makes them invisible to the linter.

The prefix names the _repo_, so it is stripped from the URL path. Private renders to the backticked
basename, with no link and the repo never named — matching what host PR #255 did by hand.

Rendering is idempotent: once a token is a link, the prefix is gone, so re-running over an edited page is
a no-op.

### Module

A new `scripts/external_refs.py`: pure, stdlib-only, no file I/O — the same shape as
`scripts/citation_repair.py`, which is a diagnose-only module the orchestrator calls and which never
writes. Two public functions:

- `resolve_config(config) -> dict` — parses and validates `lint.external_repos`, raising on the schema and
  collision errors below. Called at config load.
- `render_external_refs(text, repos) -> str` — the pure transform. Takes text, returns text.

The orchestrator owns all reading and writing; the module never touches the filesystem, which keeps it
unit-testable without a repo fixture.

`_SUFFIX_RE` is **imported from `scripts.lint.citation_exists`, not re-declared.** Per `CLAUDE.md`, shared
helpers are contracts: two copies of the suffix grammar would drift, and a drifted copy here means a URL
that keeps a suffix the linter strips — exactly the defect the prototype found, reintroduced by
duplication. Importing a module-private name across the boundary is deliberate; if that is unwanted,
promote it to `SUFFIX_RE` in `citation_exists` in the same change rather than copying it.

## Placement

A post-authoring pass that runs **immediately before `_diagnose_citation_paths`**
(`scripts/orchestrator_runner.py`), giving the order **render → diagnose → validate**.

This ordering is load-bearing, not cosmetic. `_diagnose_citation_paths` reports what a _blocked_ citation
was probably shortened from. Run first, it would see `engineering-docs-agent/CLAUDE.md`, fail to resolve
it, and emit suffix-match noise for a token that is about to become a link. Rendering first deletes that
false-positive class outright.

This is a normalization, not an inference, and it happens **before** the linter — unlike CCE-141's
withdrawn repair, which mutated a page the linter had **already blocked** using evidence the linter could
not verify. The distinction is the whole safety argument. The moment anyone proposes "and if it _looks_
like it might be cross-repo…", it becomes the CCE-141 class again.

## `page-author` contract change

Add the third escape to the grounding rule in `agents/page-author.md`:

> When the artifact lives in a repository the host has **declared as external**, cite it with the declared
> prefix — `` `<repo>/<path within that repo>` ``. The pipeline renders it. Never construct the URL
> yourself. Never use a prefix that is not declared: an undeclared prefix is an ordinary repo path and
> will block, which is correct.

Two consequences beyond the doc:

- the declared prefixes must be **passed into the page-author dispatch** — an agent that cannot see the
  declaration cannot use it;
- the rule must state that "exists" means _in the host repo_, the omission identified as root cause.

The agent's JSON output shape is unchanged, so `agents/schemas/page-author.schema.json` and its fenced
twin stay untouched: no `tests/agents/test_schema_md_sync.py` lockstep, no `contracts_doc.py`
regeneration.

## Guards and degradation

**Collision guard, load-time and loud.** A declared prefix that resolves as a real directory in the host
checkout is rejected at config load, alongside `_validate_lens_paths_are_editable`. Without it, a host
declaring an external repo named `docs` while genuinely having `docs/` would have real local paths
rewritten into foreign links. Rejecting the _declaration_ rather than filtering per-token means one guard
covers every token, and it fails closed — a refused config leaves every page exactly as it is today.

**Bare-host degradation.** No `external_repos` declared → the renderer is a no-op and the tree is
byte-identical. This follows `citation_source_roots` verbatim: "empty by default — a host that declares
nothing keeps today's exact behavior."

## Accepted risks

| Risk                             | Behaviour            | Why acceptable                                                                                             |
| -------------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------- |
| Agent uses an undeclared prefix  | Blocks, as today     | Fails closed                                                                                               |
| Agent writes a raw URL itself    | Passes, unverified   | A dead link is visible to readers, unlike a wrong code pointer that reads as authoritative                 |
| Declared `url` or `ref` is wrong | Dead links site-wide | The cost of not putting a network call inside a Tier-1 block rule                                          |
| `url` added to a private entry   | Publishes the URL    | Requiring _exactly one_ of `url`/`private` makes this an explicit, reviewable edit, never a silent default |

## Rejected

- **A lint rule that flags cross-repo tokens advisorily.** Tiny, but the page still blocks and is still
  abandoned. It diagnoses without fixing.
- **`lint.citation_exempt_tokens` for each external path.** Works, but every path is listed by hand on
  every host and the citation becomes permanently unverified. A blunt workaround, not a fix.
- **`lint.citation_source_roots`.** Widens resolution to package roots _within the same repo_, and is
  package-roots-only by construction. Cross-repo is out of scope.
- **Validating external links over the network at lint time.** Fully verified, but puts a network
  dependency inside a block rule — offline or rate-limited CI turns red — and private repos can never be
  validated anyway, so the carve-out is still required.
- **The agent emitting the final link itself.** Genuinely simpler, and _equally safe_: neither approach can
  compel the agent to use the prefix form, and both fail closed when it does not. Rejected only on URL
  correctness — the agent would have to guess the default branch (`main` vs `master`) and the host's URL
  grammar, and every wrong guess is a silent dead link recurring on every run.

## Test plan

TDD. Fixture-driven dry-run; fixtures represent an arbitrary host, not this repo's tree.

1. **Renderer units** — every row of the rendering table: root file, deep file, `:symbol` suffix, `:line`
   suffix, private, undeclared, and idempotency (render twice → identical).
2. **The slash trap, as a named regression.** Assert the rendered link text contains no `/` _and_ that
   `extract_citations` over the rendered output returns `[]`. Without this, someone "improves" the link
   text back to the full path and silently restores the block.
3. **The suffix trap, as a named regression.** Assert the rendered URL contains no `:` after the path, and
   that the suffix survives in the link text. This is the defect the prototype found.
4. **Collision guard** — a config declaring a prefix that exists as a host directory raises at load.
5. **Schema** — `url` and `private` together rejected; neither rejected; multi-segment key rejected.
6. **Ordering** — a page citing a declared external repo produces no `_diagnose_citation_paths` finding,
   pinning render-before-diagnose.
7. **True no-op on a bare host** — no `external_repos` → output byte-identical to baseline. This inverts
   CCE-141's "disabling it left the suite green" measurement: prove the inert path is genuinely inert.
8. **Fenced blocks untouched** — an external token inside a fence survives verbatim.
9. **End-to-end** — a run whose page cites a declared external repo lands and is not deferred, on the
   non-truncated (`time_budget_seconds=0`) production shape, per the CCE-179 lesson that a test reaching
   its assertion by a different path than production is not coverage.

New fixtures must **not** be named `fakes_sibling_*` — that namespace belongs to CCE-141's same-run-file
sense of the word. Use `fakes_external_repo_*`.

## Prototype evidence

`proto/CCE-181-sibling-render` @ `0c1f23b`. Single self-contained HTML file with five guided walkthroughs.

Structured per the CCE-179 lesson that a prototype modelling code instead of running it can confirm a
design about to fail. Two halves are kept apart: the **oracle** (`extract_citations`, the regexes,
placeholder rules, fence stripping) ported verbatim from `scripts/lint/citation_exists.py` at `77c6894`,
and the **design under test** (`renderSiblings`, `validateConfig`).

The oracle was differentially tested against production Python over 20 cases — unterminated fences,
`:symbol` suffixes, tilde paths, URLs, the dotted `.engineering-docs-agent/` prefix — with **0
disagreements**. Without that check every verdict below would be worthless.

Running it found the `:symbol` URL defect (item 3 of the test plan), which reading the design had not.
Confirmed by running: basename link text passes while full-path link text still blocks; an undeclared
token is untouched and still blocks; a refused config leaves pages as-is; fenced samples are never
rewritten; rendering is idempotent; a bare host is a true no-op.

## References

- CCE-141 — a blocked page is silently never written; the BLOCK→PASS class; why repair was withdrawn; the
  prior owner of the word "sibling"
- CCE-140 — the deferral skip that abandons a blocked PR
- CCE-175 / CCE-178 — the baseline freeze this block contributed to
- CCE-179 — path-divergent tests and self-agreeing prototypes are not evidence
- CCE-122 — the line-free citation grammar and the `:symbol` form
- CCE-131 — the reserved `example/` namespace and exempt tokens
- CCE-110 — the `page-author` grounding rule this amends
- Host fixes clearing the _other_ blocks: `claude-code-self-assessment` PR #254, PR #255
