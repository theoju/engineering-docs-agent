# CCE-141: deterministic repair of shortened citation paths

**Status:** design
**Date:** 2026-08-21
**Ticket:** CCE-141

## Context

`page-author` sometimes emits a citation as a bare relative path.
`citation_exists` resolves citations from the repo root, correctly finds
nothing there, and blocks the page. From ADIS run `31463975395`:

```
lint_block: .../connector-builder-skill.md citation_exists:
  cites nonexistent path 'references/checklist.md'
```

The file exists. The _committed_ page already cited it correctly, at three
separate sites — frontmatter `sources:` (line 6), prose (line 27), and a table
(line 92) — all as
`.claude/skills/connector-builder/references/checklist.md`. The bare
`references/checklist.md` form appears only in the author's proposed rewrite.
The author took a correct, resolvable citation that was already on the page and
shortened it into an unresolvable one.

On an `edit` the author receives only `target_path` and reads the file itself,
so the full path was in front of it. This is not a case of the author never
having seen the correct form.

### Why this matters more than one blocked page

Post-CCE-140 the deferral skip abandons a repeatedly-blocked PR and the baseline
moves past it. The failure mode is therefore not a stall — **the page is simply
never written and nothing is red anywhere.** The run reports success, the
baseline advances, and a documentation gap is created silently.

### Why it cannot be fixed host-side

The obvious host workaround is a `citation_exempt_tokens` entry. That is wrong
here and was deliberately not done: the path is genuinely resolvable, and the
host config's own rule states exemptions are _"NOT a place for a path that
merely has the wrong prefix — those get rewritten... Adding a resolvable path
here converts a blocking gate into a silent one."_

## What we verified, and what we did not

Verified in this repo:

- `page-author.md:77` gives extensive citation guidance — line-free citations,
  the reserved `example/` namespace, fenced metasyntactic tokens, dead names —
  but **never states what root a citation is relative to**, and never says "do
  not rewrite a citation that already resolves."
- On `edit`, the orchestrator passes only `target_path`
  (`orchestrator_runner.py:2289` selects the action); the author reads the
  existing page itself.
- Deterministic repair of agent output already has precedent:
  `_rescue_json_object` salvages contaminated LLM output and reports
  `prose_contamination_rescued`. `_enforce_agent_frontmatter` (CCE-119)
  rewrites agent-authored frontmatter after the fact.
- `citation_exists` already carries a suffix-resolution concept from the other
  direction: `lint.citation_source_roots` (CCE-139) retries `<root>/<rel>`.

**Not verified:** the originating mechanism. ADIS is not available locally, so
the ticket's hypothesis — that the author resolves relative to the skill's own
directory, or copies a display label rather than the citation target — remains
unconfirmed. This design deliberately does not depend on which it is. Repair
corrects the _observable_ defect (an unresolvable citation that is a suffix of a
real path) regardless of why the author produced it.

## Decision: repair deterministically, do not rely on prompt guidance

Rejected: adding "citations are repo-root-relative, never shorten a resolving
citation" to `page-author.md` and calling it done.

The rejection is not about effort — the prompt edit is cheap and may still be
worth making later. It is that **the fix would be unverifiable.** Both of
CCE-141's stated acceptance criteria ask for a regression test that the _author_
preserves a citation. That is a test of non-deterministic LLM behaviour, and
this pipeline produced three demonstrations of that variance on 2026-08-21
alone:

1. A page blocked on an invented link target `docs/runbook.md`.
2. The same page, re-authored, blocked on a _different_ target `docs/foo.md`.
3. The same page, re-authored again after the `internal_links` fix, contained
   **no markdown links at all** — it described the three syntaxes in prose
   instead of demonstrating them.

A test asserting "the author preserves citation X" would pass or fail by luck.
We therefore substitute a different, achievable acceptance: deterministic tests
of the repair. This substitution is a conscious deviation from the ticket and
is recorded here rather than left implicit.

## Mechanism

After a page is authored, for each citation token that **fails** to resolve:

```
'references/checklist.md' does not resolve
  → suffix-match against the tracked-file set
  → exactly 1 match  → rewrite the token in the page text
  → 2+ matches       → tiebreak against the previous committed version of
                       the page; if exactly one candidate was cited there,
                       use it; otherwise leave the token alone
  → 0 matches        → leave the token alone
```

Both non-unique outcomes leave the page byte-identical, so `citation_exists`
blocks exactly as it does today. Repair can only ever convert a block into a
correct citation; it can never convert a block into a silent pass.

### What "suffix-match" means precisely

A tracked path `F` is a candidate for cited token `C` when `C` equals a
**segment-boundary suffix** of `F`: splitting both on `/`, the segments of `C`
are exactly the final `len(C)` segments of `F`.

Segment boundaries are required, not substring matching.
`references/checklist.md` matches
`.claude/skills/connector-builder/references/checklist.md`, but
`erences/checklist.md` matches nothing, and `checklist.md` alone matches on the
1-segment row of the ambiguity table (with its correspondingly higher collision
rate).

`C == F` is excluded: an exact match means the path already resolved and the
token was never a repair candidate. The candidate set is therefore always a
strict shortening.

The tracked-file set is the same `files` set `check_path` already receives, so
repair and the lint rule agree on what exists by construction rather than by
convention.

### Why uniqueness is necessary but NOT sufficient

**This section previously claimed a proof. The proof was wrong, and the error is
the reason this design was revised. The original text is preserved in git
(`0f6b224`) rather than quietly replaced.**

The original argument: if the page previously cited `X` and now cites
`suffix(X)`, then `suffix(X)` necessarily matches `X` — a path is always a suffix
of itself — so a unique match **is** `X`.

Every step of that is true. It is also **conditional on the token having been a
shortening of something**, and the code never establishes that antecedent.
`repair_text`'s only entry condition is that the token does not resolve — which
is precisely the confabulation population `citation_exists` exists to block. An
invented path is also a path that does not resolve.

Uniqueness is therefore necessary but not sufficient. Reproduced against the
plugin's own tree at `5c72145`:

```
does .github/workflows/ci.yml exist here?  False
BEFORE: (False, "cites nonexistent path '.github/workflows/ci.yml'")
repairs: [('.github/workflows/ci.yml'
           -> 'tests/fixtures/setup_repos/js_docusaurus/.github/workflows/ci.yml')]
AFTER : (True, 'ok')
```

A brand-new page writing an ordinary sentence — "the workflow lives at
`.github/workflows/ci.yml`" — is silently re-pointed at a Docusaurus **test
fixture**, and the block becomes a pass. No shortening occurs anywhere in that
story.

### The invariant that IS true

Repair never introduces a reference to a file the pipeline had not already
accepted a reference to. **The set of files the finished page points at is
invariant under repair; only the spelling of an existing pointer changes.**

That is a testable property rather than a conditional whose antecedent nothing
checks, and it is what the corroboration precondition below delivers. It is
deliberately weaker than the original claim: it does not say the repaired
citation is correct, only that the reference was pipeline-sanctioned. A page can
still be re-pointed at a real, batch-touched file while the surrounding sentence
is wrong. That residual is bounded to files the batch demonstrably touched, and
it is the same residual `citation_exists` already tolerates for every
correctly-spelled citation.

### Measured ambiguity — and why it was read backwards

**The table below is accurate. The conclusion originally drawn from it was
exactly inverted, and that inversion is the second defect in this design.**

The original text presented near-zero ambiguity as evidence of safety. It is
evidence of **inertness**. If a tail-shaped token is essentially always unique,
then the `len(candidates) == 1` gate carries zero bits of information about
whether a shortening occurred, and the mechanism collapses to "is this string a
tail of some tracked file."

Measured on the plugin's own tree (886 tracked files): **2109 distinct
non-resolving proper-tail tokens have a unique match.** The set of invented
strings that would flip block into pass is *larger than the repository*. A
citation-shape-filtered count puts it at 1281 with zero ambiguous cases; both
counts support the same conclusion, and the unfiltered one is worse.

The gradient runs the wrong way, too: the deeper and more specific-looking the
invented path, the more likely it is accepted (1-segment 80.0% unique,
2-segment 99.5%, 3-segment 100%).

Read the table as bounding ambiguity **among genuine shortenings only**. It says
nothing about the population that breaks the design, because it samples only
from the population where the antecedent already holds.

Proper suffixes (those that are genuinely a shortening of a longer tracked
path), over citation-shaped file types:

| suffix shape                                           | engineering-docs-agent | claude-code-self-assessment |
| ------------------------------------------------------ | ---------------------- | --------------------------- |
| 1 segment (bare filename)                              | 6.3% ambiguous         | 1.6%                        |
| 2 segments (`references/checklist.md`, the ADIS shape) | **0.6%**               | **0.0%**                    |

The shape this ticket is actually about is nearly always unambiguous. The
residual ambiguous cases degrade to today's behaviour.

## Exclusions the repair MUST honour

`check_path` deliberately skips several token classes. Repair has to skip the
same ones, or it will "fix" paths that are unresolvable _by design_:

| class                                 | source                                      | why repair must skip it                                                                          |
| ------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `lint.citation_exempt_tokens`         | `exempt_tokens(config)`                     | The host declared these unverifiable on purpose.                                                 |
| Reserved illustrative namespace       | `example_prefixes(config)`, e.g. `example/` | `example/auth/session.py` is fictional; a suffix match would be a coincidence, not a correction. |
| Gitignored paths                      | `_is_gitignored` (CCE-145)                  | Absent from a fresh checkout but legitimately declared.                                          |
| Tokens `_relativize` returns None for | `_relativize(cited, repo_root)`             | Not a repo-relative citation at all.                                                             |

Getting this wrong would be worse than the original defect: it would rewrite a
deliberately-illustrative token into a real path, making a fictional example
silently claim to cite real code.

**Post-implementation correction (2026-08-21, adversarial review): the table
applies to BOTH ends of a repair, not just the cited token.** The shipped code
tested only `rel`, so a repair could move a citation *into* an excluded class
rather than out of one. Reproduced: cited `auth/session.py` with a corroborated
candidate `example/auth/session.py` was repaired, and the page then claimed a
path in the reserved namespace — where `check_path` skips it permanently and it
is never verified again. `check_path` went `(False, "cites nonexistent path …")`
→ `(True, 'ok')`, which is the same harm the table exists to prevent, in the
other direction. A candidate in any excluded class is now **declined**, under
its own reason string (`candidate_exempt_token`, `candidate_example_namespace`,
`candidate_gitignored`, `candidate_outside_repo`) so the digest distinguishes it
from a plain `uncorroborated` decline. One predicate helper,
`_excluded_reason`, serves both ends — there is no second copy.

## Placement

A new `_repair_citation_paths(target_path, repo_root, config, files)` runs in
the authoring loop, immediately after `_enforce_agent_frontmatter`:

```
per authored page:
    page-author writes target_path
    _enforce_agent_frontmatter(...)   # exists (CCE-119)
    _repair_citation_paths(...)       # new
        ↓
content-validator sees an already-correct page
```

Chosen over two alternatives:

- **A separate repair pass before content-validator.** Adds a pipeline stage and
  separates repair from the authoring context that produced the page, for no
  gain — repair is inherently per-page.
- **`citation_exists --fix`.** Colocated with the resolution logic it reuses,
  but it makes a lint rule mutate files. Every rule in `scripts/lint/` follows
  `check_path(path, config) -> (ok, message)`, and `lint_runner`'s CLI contract
  has exit codes for _passed_ and _failed_ with no notion of _mutated_.
  Breaking that for one rule is a category change.

Repair **imports** the extraction and resolution helpers from
`citation_exists` — `extract_citations`, `extract_symbol_citations`,
`_relativize`, `_resolves`, `exempt_tokens`, `example_prefixes`,
`source_roots`, `_is_gitignored`. That module's docstring already declares these
a shared-helper contract ("imported by scripts/orchestrator_runner.py … grep
callers repo-wide before changing signatures"). Reimplementing resolution would
guarantee the two drift, and repair skipping a class that `check_path` skips is
precisely the drift that would hurt.

## Reporting

`citation_path_repaired: <page>: '<old>' → '<new>'`, recorded **info-only**.

- Info-only because nothing was lost. The page is correct, the run is not
  degraded, and flipping `partial` would veto auto-merge for a successful
  self-correction — the CCE-109 over-correction shape.
- But it **must** appear in the digest. Repairing silently forever means nobody
  ever learns the author is still shortening citations. The log line is the only
  thing that would justify revisiting the prompt later.

This matches `prose_contamination_rescued` exactly, which is the closest
existing precedent: a successful rescue of malformed agent output, reported
without degrading the run.

## Scope

**In scope**

- Backticked citation tokens in prose — the tokens `citation_exists` checks.
- Both the bare `path` form and the `path:symbol` form. `extract_citations`
  strips a trailing `:line`/`:symbol` suffix when returning bare paths, so the
  rewrite must operate on the full token as it appears in the page and preserve
  any `:symbol` suffix.

**Out of scope, deliberately**

- **Frontmatter.** `extract_citations` only reads inline code spans, so YAML
  `sources:` entries are not linted by this rule and are not repaired by it.
  The ADIS page had the correct path at line 6 in frontmatter; that site was
  never the blocker.
- **Markdown link targets.** Those belong to `internal_links`, a different rule
  with a different failure mode (see the 2026-08-21 fix stripping code spans and
  fenced blocks before matching links).
- **The author prompt.** Unchanged by this design. Adding repo-root guidance to
  `page-author.md` remains available as a separate, unverifiable improvement.
- **CCE-167** extraction-layer defects (`_REPO_PATH_RE`, `_relativize`).

## Testing

All deterministic — this is the reason for choosing repair over prompt guidance.

1. Unique suffix match rewrites the token to the full repo-root path.
2. The ADIS shape specifically: `.claude/skills/<skill>/references/<file>.md`
   shortened to `references/<file>.md` is repaired.
3. Ambiguous suffix (2+ tracked matches, no prior version) → no rewrite, page
   byte-identical, `citation_exists` still blocks.
4. Zero matches (a genuinely confabulated path) → no rewrite, still blocks.
   **This is the strictness guard**: repair must not weaken the confabulation
   gate that `citation_exists` exists to be.
5. A citation that already resolves is left byte-identical.
6. Idempotence: running repair twice produces no second change.
7. Ambiguity tiebreak: 2 candidates, one of which the previous committed version
   cited → that one is chosen.
8. `path.py:Class.method` form: the path is repaired and the `:symbol` suffix
   preserved.
9. Exclusion honouring, one test per row of the exclusions table: an exempt
   token, an `example/` token, and a gitignored token are each left untouched
   even when a unique suffix match exists.

## Risks

- **Repair masks a worsening author.** Mitigated by the info-only digest line,
  not eliminated. If `citation_path_repaired` starts appearing on most pages,
  that is the signal to revisit the prompt.
- **Ambiguity rate is repo-dependent.** Measured on two repos; a host with many
  parallel skill directories could see a higher 2-segment collision rate. The
  failure is safe (block, as today), so this degrades coverage rather than
  correctness.
- **The originating mechanism stays unknown.** If the author's shortening is
  caused by something that also produces _non_-suffix corruption, repair will
  not catch that class. Nothing in the observed evidence suggests it, but the
  ADIS case was never reproduced locally.

---

# Revision 2 — corroborated repair (2026-08-21)

**Status:** design, supersedes the mechanism above
**Reason:** the safety proof in Revision 1 was conditional on an antecedent the
code never checks. See "Why uniqueness is necessary but NOT sufficient" above.

## Decision

Corroboration becomes the **entry condition**, not the ambiguity tiebreak.

A unique suffix match is accepted only if the **candidate path** — never the
cited token — can be corroborated from a source the authoring agent did not
write. Uncorroborated matches are declined, the page stays blocked, and the
decline is reported loudly enough to act on.

Two changes make this cheap, and both were verified in the current tree:

- `_prior_page_text` (`orchestrator_runner.py:1566`) already runs and is already
  passed into `repair_text`. It is merely wired to the `len(candidates) > 1`
  branch. Promoting it to a precondition is moving an existing filter, not new
  plumbing.
- `grounding = _pr_changed_files(batch_prs)` (`orchestrator_runner.py:2347`) is
  already computed unconditionally — outside the create/edit branch — and handed
  to page-author as `source_paths`. It is live and unshadowed at the repair call
  site.

## The corroborator ladder

Ranked, computed in `_repair_citation_paths`:

| Rung | Source | Available on | Authored by |
| --- | --- | --- | --- |
| 1 | `extract_citations` over the prior committed page, intersected with the tracked set | edits | git |
| 2 | Membership in the batch's `grounding` set, with a **≥2-segment suffix floor** | every authoring | the orchestrator |
| 3 | *(optional)* the same path cited in full **and resolving** elsewhere on the page | same-page | the agent — weakest rung |
| 4 | *(additive)* for a `path:symbol` token, `_symbol_defined` on the candidate | symbol citations | the target file's contents |

**Rung 1 must use a raw substring scan, not `extract_citations`.** This is the
one non-obvious implementation requirement. `extract_citations` reads only
backticked spans in unfenced prose; measured on this repo's 108-page corpus it
sees 69.9% of path tokens and misses 19.7% bare-prose, 5.0% frontmatter-only and
2.5% link-target-only. The originating incident's three sites include frontmatter
and a table cell, so an `extract_citations`-based rung 1 could fail the very case
this ticket exists for. A raw scan does not violate the imported-never-
reimplemented contract: it is not deciding what a citation *is*, only whether a
known-tracked path was already present.

> **Post-implementation correction (2026-08-21, adversarial review).** The
> paragraph above is **wrong and was reverted in code**. Rung 1 is
> `set(extract_citations(prior_text)["paths"]) & files`.
>
> The coverage argument is backwards. The ~30% of path tokens
> `extract_citations` does not see is invisible *precisely because
> `citation_exists` never validates it* — fenced blocks ("fenced examples are
> legitimately hypothetical", its own docstring), URL bodies, HTML comments,
> and substrings of longer paths. A token the linter never checked cannot
> evidence that the pipeline **accepted** a reference to that file, which is
> the only thing rung 1 is allowed to assert.
>
> Reproduced twice: a prior page naming
> `tests/fixtures/setup_repos/js_docusaurus/.github/workflows/ci.yml` **only
> inside a ```` ```text ```` fence** corroborated that path, and a new page
> citing an invented `.github/workflows/ci.yml` was silently repointed at the
> fixture — `check_path` went from `(False, "cites nonexistent path …")` to
> `(True, 'ok')`. That is the exact defect the corroboration gate exists to
> prevent.
>
> Losing the frontmatter/table sites is the correct trade: those sites are
> unvalidated, and an unvalidated mention is evidence of nothing. Rung 1 now
> also inherits the linter's fence semantics for free rather than duplicating
> them, which is what *import, never reimplement* actually asks for. Tests:
> `test_rung1_ignores_a_path_named_only_inside_a_fence`,
> `test_rung1_ignores_sites_the_linter_never_validates`,
> `test_a_fenced_mention_on_the_prior_page_does_not_corroborate`.

**Circularity is closed.** On a create, `_enforce_agent_frontmatter` writes
`grounding` into the page's `source_files`, **overwriting whatever the agent
wrote**. On an edit, rung 1 is `git show HEAD:`. Every action therefore has at
least one corroborator the agent did not author. `evidence.files_read` is
deliberately **excluded** as a source: an author that confabulates a citation can
equally confabulate a files_read entry.

**Globs are excluded from corroboration.** `docs/site-src/.doc-core-manifest.json`
carries glob `source_files` (`core/**`, `docs/superpowers/**`). Expanding them
would make the gate ceremony while the diff still reads `if candidate in
corroborated`. Literal paths only, stated here so it is a decision rather than an
oversight.

## Declines must be loud

An uncorroborated citation blocks the page. Left silent, that reproduces the
CCE-141 harm in a narrower band: block → deferral → forgiveness → page never
written.

So `repair_text` returns `(new_text, repairs, declines)`, and each decline is
reported as a **non-`info_only`** partial naming the candidate it refused:

```
citation_repair_declined: <page>: '<old>' -> candidate '<new>' (uncorroborated)
```

The same string threads into the `lint_block` partial and into a new `reason`
field on the `skipped_prs` record. Successful repairs stay `info_only=True` — a
corroborated repair is a genuine rescue and must not veto auto-merge.

## Measured cost, stated plainly

- **Coverage lost: ~38%** of genuine resolving citations on real authored pages
  are absent from their batch's source set. On a create there is no second arm.
  Those pages block. The bias is adverse: the shortening pathology targets
  deeply-nested support files, which are exactly what a PR diff does not contain.
- **Residual retained: ~56%** of the files in a real batch's source set still
  expose a unique non-resolving suffix. Corroboration narrows the confabulation
  surface by roughly two orders of magnitude — 812 tracked files down to a
  per-page set of 5–15 — but does **not** close it.
- **Host shape dominates.** Pooled across three hosts: 65% creates / 35% edits.
  On `claude-extensions` specifically it is 82% create, and all four measured
  "edits" were the agent re-authoring its own hours-old pages after a baseline
  rewind — genuine edits of a pre-existing curated page: zero. Rung 1 contributes
  essentially nothing there; rung 2 is the whole gate.

## The uncomfortable number

Measured against the complete production record — 19 archived PRs, 15 distinct
blocked citations in `.engineering-docs-agent/stale-prs-archive/` — **this
feature would have fired zero times.** The four genuine `architecture/*.md`
shortenings already resolve via the `docs_dir` branch added in CCE-139/145, so
repair never reaches them. Measured harm on one plausible page in the same repo:
three wrong repairs.

This is recorded because it is the strongest argument for a smaller change, and
whoever revisits this should see it without having to re-derive it.

## Downstream-owner audit

No layer below repair catches a wrong repair. This is what makes an unsound
repair unrecoverable rather than merely wrong:

- `verify_citations` is pin-based and never sees a bare repaired path.
- `source_drift` matches on frontmatter globs.
- **Drift** as defined in `CONTEXT.md` structurally cannot classify it — the page
  matches the source it cites, because repair changed what it cites.
- `fact-checker` is non-gating, is explicitly scoped away from citation existence,
  and is handed the **repaired** `cited_sources` — so repair steers the only agent
  that opens the file onto the wrong file, where it returns a silent
  `unverifiable`.

## Reconciliation with CCE-139

`templates/config.schema.json` still rejects any `citation_source_roots` entry
containing a slash, because "a nested tail like `backend/storage` is
suffix-matching in disguise and admits confabulated paths."

Revision 1 contradicted that ruling and inverted the consent boundary: an
operator opting into *one* narrow suffix match is schema-refused, while the agent
performed unbounded suffix matching with no declaration and no opt-out. Under
corroborated repair the two are consistent. Stated explicitly so the next reader
does not have to rediscover the conflict.

## Out of scope, still

Unchanged from Revision 1: frontmatter, markdown link targets (`internal_links`),
the author prompt, and CCE-167. `run_bootstrap_core` (`orchestrator_runner.py:3145`)
has no PRs by construction, so core-authoring pages get no repair coverage — that
is correct, and is stated rather than papered over.
