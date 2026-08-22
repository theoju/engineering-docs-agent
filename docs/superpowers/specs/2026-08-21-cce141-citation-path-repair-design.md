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

Re-measured 2026-08-21 on the plugin's own tree, **887 tracked files**
(`git ls-files | wc -l`): **2086 distinct non-resolving proper-tail tokens have
a unique match.** The set of invented strings that would flip block into pass is
*larger than the repository*. A citation-shape-filtered count — restricted to
the tails `_REPO_PATH_RE` can actually emit, which is the only population that
ever reaches repair — puts it at **1387 unique out of 1388 non-resolving shaped
tails, one ambiguous**; both counts support the same conclusion, and the
unfiltered one is worse.

The gradient runs the wrong way, too: the deeper and more specific-looking the
invented path, the more likely it is accepted — unfiltered, 1-segment 94.9%
unique, 2-segment 99.7%, 3-segment and deeper 100%.

Every figure in this section, and the surface figure under "Measured cost" in
Revision 2, comes from one command:

```bash
PYTHONPATH=scripts:scripts/lint .venv/bin/python -c '
from pathlib import Path
from citation_exists import (_REPO_PATH_RE, _build_dir, _docs_dir, _relativize,
                             _resolves, source_roots, tracked_files)
from citation_repair import suffix_candidates
root = Path(".").resolve(); files = tracked_files(root)
d, b, r = _docs_dir({}), _build_dir(root), source_roots({})
tails = {"/".join(f.split("/")[-k:]) for f in files for k in range(1, len(f.split("/")))}
assert all(_relativize(t, root) is not None for t in tails)
nr = [t for t in tails if not _resolves(t, root, files, d, b, r)]
uniq = [t for t in nr if len(suffix_candidates(t, files)) == 1]
sh = [t for t in nr if _REPO_PATH_RE.match(t)]
shu = [t for t in sh if len(suffix_candidates(t, files)) == 1]
print("tracked", len(files), "| non-resolving tails", len(nr), "| unique", len(uniq))
print("citation-shaped", len(sh), "unique", len(shu), "ambiguous", len(sh) - len(shu))
print("surface: unfiltered", len({suffix_candidates(t, files)[0] for t in uniq}),
      "| citation-shaped", len({suffix_candidates(t, files)[0] for t in shu}))
'
```

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

**Superseded on the candidate side (2026-08-21, correction 4).** This table is a
blacklist, and a blacklist enumerates only what someone thought of. It went on to
miss two more rows — a candidate the linter cannot PARSE, and a candidate under
the mkdocs build dir — with the same consequence each time. The candidate side is
now a positive verifiability gate; the table still governs the CITED token
unchanged. See "Post-implementation correction 4".

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

> **Post-implementation correction (2026-08-21, fourth adversarial review).**
> The mechanism named in the paragraph above is **false on the reference host**,
> and the ladder's rung-2 "Authored by: **the orchestrator**" cell overstates the
> provenance. Both are corrected in correction 5 below. The text stays as
> written.
>
> `_enforce_agent_frontmatter` runs only under `if agent_fields is not None`
> (`orchestrator_runner.py:2454`), and `agent_fields` is set only when
> `action == "create"` **and**
> `fmc.section_generator_for(rel, config) == "agent-authored"`
> (`orchestrator_runner.py:2384-2386`). The reference host's
> `.engineering-docs-agent/config.yml` declares **no `site:` block at all**, so
> `section_generator_for` returns `None`, `agent_fields` stays `None`, and that
> call never runs there.
>
> The **conclusion** survives, by a different mechanism than the one stated: on
> a create, corroboration comes from `source_paths=grounding` being handed to
> `build_corroborators` directly (`orchestrator_runner.py:1608`), never from
> reading a page's frontmatter back. `extract_citations` does not see
> frontmatter in any case, so a prior page's `source_files` could not be a
> rung-1 corroborator even on a host where enforcement does run.

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
  surface by roughly two orders of magnitude — **788** tracked files down to a
  per-page set of 5–15 — but does **not** close it. 788 is a **different set**
  from the 887 above, not a drifted copy of it: 887 is every tracked file,
  while 788 is the subset actually reachable as a repair target — the distinct
  tracked files that are the unique match of some non-resolving,
  `_REPO_PATH_RE`-shaped tail. Same command, its
  `surface: … | citation-shaped` field.
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

---

# Post-implementation correction 3 — the shipped module, re-audited (2026-08-21)

**Status:** correction, applied in code and in `CLAUDE.md`
**Reason:** a second adversarial review of what actually shipped.

Two of this round's three code fixes already carry an in-place note above — the
candidate-side exclusions under "Exclusions the repair MUST honour", and the
rung-1 revert under "The corroborator ladder". Neither is repeated here. This
section records the round as a whole, the one fix that had no note, and the
figures that turned out not to survive re-derivation. **The earlier corrections
stay exactly as written**; having been wrong twice is part of the record.

## The fence mirror was decorative until this round

`_closed_fence_lines` exists so `rewrite_token` never edits a line that
`extract_citations` could not see. It iterated `text.split("\n")` while
`strip_fenced_blocks` iterates `text.splitlines()`, and those are **not** the
same walk: six characters survive `Path.read_text()`'s universal-newline
translation yet ARE `splitlines()` boundaries — U+2028, U+2029, `\x85`, `\x0b`,
`\x0c`, `\x1c`. With any of them on the page, the `split("\n")` walk sees a
fence opener glued to the end of the preceding line, never opens the fence, and
returns an empty set — while `extract_citations`, on `splitlines()`, strips that
fence correctly. `rewrite_token` then rewrote the deliberate fenced
illustration, turning an example into a false claim about real code, and
`repair_text` reported a repair at a site the linter never checked. Both
functions now iterate `splitlines()`, and `rewrite_token` rejoins using each
line's OWN terminator from `splitlines(keepends=True)` — `"\n".join()` would
silently rewrite all six of those bytes on every page it touched.

## The "≥2-segment suffix floor" is not a check

The rung-2 row of the corroborator ladder above describes a **≥2-segment suffix
floor**. There is no such guard anywhere in `scripts/citation_repair.py` —
`repair_text` tests `_resolves`, `_excluded_reason` on both ends,
`len(candidates) != 1` and `candidate not in corroborators`, and nothing counts
segments except the suffix arithmetic inside `suffix_candidates` itself.

The floor holds today as a **property of the extractor**, not as a property of
the repairer: `_REPO_PATH_RE` (`scripts/lint/citation_exists.py`) is
`^[\w.\-/]+/[\w.\-]+\.\w{1,8}(?::…)?$` and requires a literal `/`, so
`extract_citations` never yields a slash-free token and `repair_text` never sees
one. Verified both halves rather than assumed: 0 of the 887 tracked basenames
match `_REPO_PATH_RE`, and running `extract_citations` over a line that spans
`checklist.md`, `README.md` and `scripts/citation_repair.py` returns
`['scripts/citation_repair.py']` alone — the two slash-free tokens are
dropped before repair ever sees them. But
`suffix_candidates` is in `__all__` and accepts one happily —
`suffix_candidates("citation_repair.py", files)` returns
`['scripts/citation_repair.py']`. **A future caller of the exported function
does not inherit the floor.** Stated as the contingent fact it is; if the floor
is ever wanted as a guarantee, it has to be written down as a check.

## Figures that did not survive re-derivation

- **887 vs 886 vs 812.** This spec carried 886 tracked files in one place and
  812 in another for the same tree. Both are gone. The tracked count is 887
  today and the two sentences measure genuinely different sets — see the
  re-derived numbers and the single command under "Measured ambiguity", and the
  set distinction spelled out under "Measured cost". Re-derived, not picked.
- **The citation-visibility split is unreproducible.** The superseded rung-1
  paragraph reports `extract_citations` seeing 69.9% of path tokens over the
  108-page `docs/site-src` corpus, missing 19.7% bare-prose, 5.0%
  frontmatter-only and 2.5% link-target-only. No method was recorded with it. A
  reconstruction — raw substring scan of every tracked path over all 108 pages,
  each of the 673 resulting page/path mentions classified by the region its
  occurrences fall in — lands at **54.8% visible, 12.0% bare-prose-only, 22.1%
  link-target-only, 3.7% frontmatter-only**, with the remainder fenced-only,
  inside spans the linter skips, or mixed. That is a different split, so the
  original numbers are not carried anywhere. The paragraph itself is preserved
  unchanged: it is the record of the reasoning that was backwards, and the
  numbers in it were never what made it wrong.

## What `CLAUDE.md` now says

Its CCE-141 bullet describes rung 1 as the linter's own view of the prior
committed page intersected with the tracked set, names **why** the raw scan was
wrong (the invisible
remainder is invisible *because* the linter never validates it, so it cannot
evidence acceptance — it admitted a fenced-only mention as a corroborator and
restored the block-becomes-pass defect), names all three miss-buckets including
the link-target-only one it had dropped, states the segment floor as a property
of `_REPO_PATH_RE` rather than a guard, and records the candidate-side
exclusions and the `splitlines()` fence mirror.

---

# Post-implementation correction 4 — the candidate blacklist becomes a gate (2026-08-21)

**Status:** correction, applied in code, in this spec and in `CLAUDE.md`
**Reason:** the candidate-side exclusion list missed a third and a fourth row.

Correction 3 fixed the candidate side by applying the cited-side exclusion table
to both ends of a repair. That was the right direction and the wrong shape. The
table is a **blacklist** of the classes `citation_exists` declines to check, and
a blacklist can only ever enumerate what someone thought of.

## The two rows it missed

Both share one shape: **repair moves the citation into a region the linter does
not verify, so the page flips from BLOCK to `ok` and is never checked again.**
Both were reproduced end to end through `repair_text`, and in both the target
file was then `git rm`-ed and `check_path` still answered `(True, 'ok')`.

| miss | fixture | before | after repair |
| ---- | ------- | ------ | ------------ |
| candidate the extractor cannot PARSE | tracked `app/(marketing)/guides/setup.md`, page cites `guides/setup.md` | `(False, "cites nonexistent path 'guides/setup.md'")` | `(True, 'ok')`, and `extract_citations(page)["paths"] == []` |
| candidate under the mkdocs build dir | `mkdocs.yml` with `site_dir: site`, tracked `site/refs/notes.md`, page cites `refs/notes.md` | `(False, "cites nonexistent path 'refs/notes.md'")` | `(True, 'ok')` |

The first is `_REPO_PATH_RE`, which admits only `[\w.\-/]`: a tracked candidate
containing a space, `(`, `)`, `@`, `+`, `~`, `,` or `&` clears rung 2's
`_GLOB_CHARS` filter, gets written into the page, and is then not SEEN by
`extract_citations` at all. Bracketed and parenthesised route paths are ordinary
— this repo's own reference host tracks `app/dimensions/[id]/page.tsx` and
`app/tips/[n]/page.tsx`.

The second is the first arm of `_resolves`, which returns True for ANY path under
`site_dir` **with no existence check whatsoever** — structurally identical to the
`example/` namespace, and `repair_text` was already computing `build_dir` for the
cited side without consulting it for candidates.

## The gate

A candidate is acceptable only if, once written into the page, `citation_exists`
would both **SEE** it and verify it **BY EXISTENCE**. Both properties are
established by asking the linter, not by re-deriving its rules:

- **Seen** — `_extractor_sees` round-trips the candidate through
  `extract_citations` in the span `rewrite_token` would write. That inherits
  `_INLINE_CODE_RE`, `_REPO_PATH_RE`, `_is_placeholder` and any future extractor
  change for free.
- **Verified by existence, not by a skip class** — `_resolves_absent` runs the
  linter's own `_resolves` against a world where the file is gone (an EMPTY repo
  root, and the tracked set minus the candidate) with the path string untouched.
  Three of the four arms of `_resolves` test existence — of the path itself, or
  of it rebased under `docs_dir` or a declared source root. The `build_dir` arm
  does not, and it is the one that bites today. The probe catches the next such
  arm too, without this module being told about it.
- **The classes check_path skips in its own branch structure** — exempt token,
  `example/` prefix, gitignored, `_relativize` None — stay NAMED rather than
  probed, because they live in branches rather than in a resolution result and
  because each earns its own digest reason.
- **Anything else** — `_linter_reports_an_absent_file` asks `check_path` itself
  whether it would report an absent file in the candidate's directory, with the
  candidate's extension. This is the fail-closed catch-all: a cause nobody
  anticipated declines instead of shipping.

Reasons, in the order the gate applies them. The first four are unchanged from
correction 3, so operator greps of the digest keep working:

| reason | cause |
| ------ | ----- |
| `candidate_outside_repo` | `_relativize`: not a repo-relative path |
| `candidate_exempt_token` | host declared this exact token unverifiable |
| `candidate_example_namespace` | reserved illustrative namespace |
| `candidate_gitignored` | ignored by design; CCE-145 downgrades it to a note |
| `candidate_unextractable` | the linter's extractor does not return it |
| `candidate_unresolvable` | it does not resolve at all |
| `candidate_unverified_namespace` | resolves without its existence being tested |
| `candidate_unverified` | `check_path` would not report an absent file here; cause unknown |

## Why a twin path, and what it costs

The catch-all asks about a TWIN — same directory, same extension, a filename stem
that cannot exist — because the candidate itself exists, so asking about it
directly could only ever return `ok`. The twin is asked against the **real** repo
root, so `mkdocs.yml`, `.gitignore` and git are the host's own.

Reconstructing an absent WORLD instead (a scratch root plus copies of whichever
files `check_path` happens to read) was rejected for failing **open**: the first
file the copy list had not been told about would go missing, missing files
produce more blocking, and more blocking is exactly what the gate reads as
"verified".

Two residuals, both accepted and both in the safe direction:

- A skip keyed on the exact filename **stem** evades the twin. Those are the
  enumerable kind — `lint.citation_exempt_tokens` is one — and they are named
  above it. Measured: deleting the named-class branch makes the exempt-token and
  gitignored tests repair rather than decline, which is precisely this residual,
  and is why the named classes are kept rather than folded into the probe.
- The twin can decline a candidate the linter would really verify: a
  `.gitignore` that ignores the directory and re-admits this one file by
  negation. A false decline leaves the page blocking, which is where it already
  was.

## Coverage

Five tests, all through `repair_text`, all mutation-checked (delete or invert the
guard the test names, confirm the test FAILS, restore, confirm it PASSES):

- `test_candidate_the_extractor_cannot_parse_is_declined` — miss 1's fixture.
- `test_candidate_with_a_placeholder_marker_is_declined_despite_corroboration` —
  the fail-closed property on the extractor half, reached through a DIFFERENT
  extractor rule (`_is_placeholder`), with corroboration present.
- `test_candidate_under_the_mkdocs_build_dir_is_declined` — miss 2's fixture.
- `test_candidate_outside_the_build_dir_is_still_repaired` — the build-dir probe
  must discriminate, not blanket-decline.
- `test_a_cause_the_gate_does_not_name_fails_closed` — the catch-all, with
  `check_path` patched to answer `ok` on an otherwise perfect repair.

Fixture guards are asserted inline in each: the candidate is tracked, the cited
token does not resolve, `suffix_candidates` returns exactly one, and — for the
build-dir tests — `_build_dir(repo) == "site"`, without which the arm under test
is inert and the test is vacuous.

---

# Post-implementation correction 4 — the fence mirror, and three untested guards (2026-08-21)

**Status:** correction, applied in code, tests and `CLAUDE.md`
**Reason:** a third adversarial review of what shipped.

Correction 3 above says the fence mirror "is real now". **It was not.** That
sentence, and the docstring it was drawn from, stay exactly as written — being
wrong three times about the same twenty lines is the useful part of this record.

## The mirror recorded only CLOSED fences, and that is not what the linter does

`_closed_fence_lines` walked `splitlines()` correctly after correction 3, but it
recorded a fence's lines only once the fence CLOSED. `strip_fenced_blocks` does
something different with a fence that never closes: it `continue`s past the
opener before appending it, so the opener is dropped, and the
`del out[fence_start:]` that would cut the body back out never runs because
nothing was appended for it to cut. **An unterminated fence loses its opener and
keeps its body.** The mirror reported neither.

Both halves were observable with no mutation at all:

- ` ```python\nprose `refs/x.md`\n ` — `strip_fenced_blocks` returns
  `` 'prose `refs/x.md`' `` (the opener is gone), the linter-dropped source
  index is `[0]`, and `_closed_fence_lines` returned `[]`.
- ` ~~~ see `refs/x.md`\nbody\n ` — `extract_citations(text)["paths"] == []`,
  the linter reads NOTHING; `rewrite_token` rewrote it anyway.

The second is the harm: the page is edited at a site `citation_exists` cannot
see, so `repair_text` reports a repair that the rule meant to police it will
never check. It is the report/apply divergence this module forbids, inverted.

## The fix: stop maintaining a parallel implementation

`_linter_dropped_lines` replaces `_closed_fence_lines`. It RUNS
`strip_fenced_blocks` and reads back which source lines survived, so the answer
is the linter's by construction and any future fence rule — a new syntax, a
different unterminated policy — is inherited rather than re-implemented.

Reading survivors back needs each line to be identifiable by a tag that does not
perturb the function being measured. The tag is a fixed-width binary index code
written in **leading whitespace**, tab for 1 and space for 0, prepended to each
line. `strip_fenced_blocks` computes `stripped = line.lstrip()` once and every
branch it takes reads only `stripped`, so leading whitespace is discarded before
any decision is made — `(code + line).lstrip()` is `line.lstrip()`, character for
character — while the function appends the ORIGINAL line to its output, so the
code survives into the result. Neither tab nor space is a `splitlines()`
boundary, so the code cannot forge a line break either.

An APPENDED marker was written first and rejected. It reads identically today,
but only because `fence` is `stripped[:3]`; the moment fence matching considered
the whole opener — full info strings, which is what CommonMark actually
specifies — an appended marker would silently stop two identical fences from
matching. That was not hypothetical: it was caught by mutating `stripped[:3]`
to `stripped` and watching unrelated bare-fence tests go red.

Two self-checks make the derivation verified rather than merely argued, because
a silent misalignment here is exactly the forbidden outcome:

1. Each survivor must decode to a well-formed index whose body is that source
   line — the `strip_fenced_blocks` appends-verbatim contract.
2. The surviving bodies, rejoined, must equal `strip_fenced_blocks` of the
   UNMARKED text — the marker-neutrality contract. This is what catches a marker
   that has stopped being invisible: the two runs would keep different lines.

Both raise rather than guess, the same choice `_resolves` makes by refusing to
default its `roots` parameter.

**The invariant, now asserted directly:** repair rewrites a line **if and only
if** the linter reads that line. `FENCE_SHAPES` states it as a table of ten
fence shapes. It is a regression guard on the derivation, not a probe of
`strip_fenced_blocks` — it holds trivially while the dropped set is derived from
the linter, and `opener_carries_the_citation` is the row that fails against the
closed-fence mirror it replaced.

## Info-string fences had no coverage at all

Every fence opener in the rewrite tests was bare. ` ```python ` closes against a
bare ` ``` ` only because `strip_fenced_blocks` truncates both sides to three
characters, and the mirror carried its own copy of that truncation: mutating
**the mirror's** `stripped[:3]` to `stripped` left the whole suite green while
making the fenced illustration rewritable. Reconstructed pre-fix, on
`` See `refs/x.md`.\n\n```python\ncite it as `refs/x.md`\n```\n ``: the mirror
reports `[2, 3, 4]` truncated and `[]` untruncated, so the fenced line 3 becomes
rewritable while the linter cannot read it.

The mirror's copy is gone with the mirror. `test_rewrite_skips_a_closed_info_string_fence`
and its `~~~yaml` sibling now discriminate on the LINTER's truncation. Worth
recording precisely: `test_rung1_ignores_a_path_named_only_inside_a_fence`
already used a ` ```text ` fence and already discriminated on the linter's copy,
so "no test anywhere uses an info-string fence" was true of the rewrite path
only.

## `test_absolute_path_outside_repo_is_never_repaired` was the fifth vacuous test

It named `if rel is None: continue` but `/etc/nginx/nginx.conf` yields ZERO
suffix candidates — an absolute path's leading `/` makes `segments[0]` empty and
no `git ls-files` path has an empty first segment — so `len(candidates) != 1`
decided it first. Mutating the named guard to `rel = cited` left the suite green;
only total deletion turned it red, via an incidental `TypeError` from
`repo_root / None`. It proved "no crash", not "never repaired", and its docstring
claimed the opposite.

Rebuilt rather than deleted. The guard is load-bearing — deleting it crashes the
run — and the candidate-side sibling tests a different call site. Making it
DECIDE requires an injected candidate with an empty path segment
(`vendor//etc/__cr_absent__/thing.conf`), which git cannot emit; the docstring
says so and rests the test on the same parameter-contract framing the
candidate-side sibling already uses, since `files` is a parameter of
`repair_text` rather than git's output. Every earlier guard is asserted inline.
The cited path must also be guaranteed ABSENT from the test machine, because
`repo_root / "/abs/path"` is `/abs/path` and `_resolves`'s on-disk arm would
otherwise answer True on some runners and not others — re-vacuuming the test
non-deterministically.

## The `.strip()` in `_sub`'s equality test

`extract_citations` strips each inline-code token before matching, so
`` ` references/checklist.md ` `` IS a citation it extracts and `repair_text`
repairs. Mutating `_SUFFIX_RE.sub("", token.strip())` to
`_SUFFIX_RE.sub("", token)` left the suite green while producing the forbidden
divergence directly: `repairs` non-empty, page untouched.
`test_a_padded_inline_span_is_both_reported_and_applied` asserts the applied
text, not only the report, and checks that the padding survives and a second
pass is a no-op.

## There are EIGHT splitlines()-only characters, not six

`\x1d` (GS) and `\x1e` (RS) were omitted from correction 3's list, from both
docstrings, from the `SPLITLINES_ONLY` test constant and from the `CLAUDE.md`
bullet. Re-derived rather than copied: every codepoint below U+3000 was written
to a file as UTF-8, read back with `Path.read_text()`, and kept when it BOTH
survived that round trip AND split `"a<ch>b"` in two under `splitlines()`. The
survivors are U+2028, U+2029, `\x85`, `\x0b`, `\x0c`, `\x1c`, `\x1d`, `\x1e`
(plus `\n` itself; `\r` is normalised away by `read_text`).

The shipped code was always correct — `splitlines()` handles all eight
uniformly — so this was a documentation and test-completeness gap, not a defect.
It is still worth closing: a character absent from the fixtures is a character a
lossy rejoin could normalise with nothing to catch it. Measured by normalising
ONLY `\x1d` and `\x1e` on the way out: red against the eight-character fixtures,
green against the six-character ones.

## Coverage added this round

All mutation-checked (delete or invert the guard the test names, confirm FAIL,
restore, confirm PASS):

- `test_rewrite_never_touches_the_dropped_opener_of_an_unterminated_fence` — the
  ghost repair; fails against the closed-fence mirror.
- `test_rewrite_applies_inside_the_body_of_an_unterminated_fence` — the other
  half, rebuilt from a test whose docstring asserted the false claim; fails
  against a mirror that over-drops to EOF.
- `test_rewrite_skips_a_closed_info_string_fence` and its `~~~yaml` sibling —
  the `stripped[:3]` truncation.
- `test_rewrite_touches_a_line_iff_the_linter_reads_it` — ten fence shapes.
- `test_a_broken_strip_fenced_blocks_contract_fails_loudly` and
  `test_a_marker_that_perturbs_the_linter_fails_loudly` — the two self-checks.
- `test_absolute_path_outside_repo_is_never_repaired` — rebuilt.
- `test_a_padded_inline_span_is_both_reported_and_applied` — the `.strip()`.

---

# Post-implementation correction 5 — rung 2's provenance, and what rung 1's narrowing cost (2026-08-21)

**Status:** correction, applied in `scripts/citation_repair.py`'s docstring, in
this spec and in `CLAUDE.md`
**Reason:** a fourth adversarial review, plus two reviewers who contradicted each
other about the same call site.

The two sections above are both numbered **4**. They are left exactly as they
are — renumbering the record to tidy it is the one edit this file never makes.

## Rung 2 is not "orchestrator-authoritative". It is a DIFFERENT AGENT.

`build_corroborators` documented rung 2 as **orchestrator-authoritative** while
the module's doctrine is that a candidate must be vouched for by *a source the
authoring agent did not write* — the doctrine that explicitly rejects
`evidence.files_read` because "an author that confabulates a citation can equally
confabulate a files_read entry." Traced end to end, the label is wrong:

| step | where |
| ---- | ----- |
| `source_paths` is `grounding` | `orchestrator_runner.py:2466` → `:1608` |
| `grounding = _pr_changed_files(batch_prs)` | `orchestrator_runner.py:2372` |
| `_pr_changed_files` reads `pr["files"]` verbatim | `orchestrator_runner.py:1680-1683` |
| `batch_prs` ⊆ `prs` from `dispatch_validated("source-collector", …)` | `orchestrator_runner.py:2048-2050` |
| source-collector is an LLM subagent | `agents/source-collector.md` (`model: sonnet`, tools `Bash`/`Read`/`WebFetch`) |
| its schema types `files` as a bare untyped array | `agents/schemas/source_collector.schema.json:22` — `"files": { "type": "array" }`, no `items` |

Grepping `scripts/` for any git-side validation of `pr["files"]` finds none. The
one orchestrator-side git safety net on source-collector output,
`_clip_prs_to_window` (`orchestrator_runner.py:974`), validates `merge_sha`
against `git rev-list` and never reads `files`. `GhClient.pr_view_files`
(`scripts/gh_client.py:23-27`) does ask `gh` for a PR's real file list, but its
only caller is `scripts/verify_runner.py:40` — a different stage, off this path.

**What is and is not true.** The doctrine holds *literally*: source-collector is
not the **authoring** agent, so a `page-author` that confabulates a citation
cannot also mint the corroborator that would rescue it. That is the whole
property rung 2 was designed for, and it survives.

**The residual, stated so it can be acted on.** A confabulating — or simply
sloppy — source-collector *can* mint one. An invented entry in `pr["files"]`
flows unchecked into `grounding` and becomes a corroborator.

**The bound, and where it is enforced.** A corroborator must be a **tracked**
file, and that bound is in code twice, not merely in the design:

- `scripts/citation_repair.py`, `build_corroborators`: `p in files`.
- `scripts/citation_repair.py`, `suffix_candidates`: it iterates `files`, so
  every candidate is a tracked path before corroboration is even consulted.

`files` is `git ls-files` — `citation_exists.tracked_files`
(`scripts/lint/citation_exists.py:183-189`), called at
`orchestrator_runner.py:1607` and passed to both. So an injected path can only
repoint a citation at some **other file that really is in the repo**; it can
never introduce an untracked or nonexistent one, and set-invariance against
*nonexistent* files is intact. What it loses is the narrowing: rung 2 widens
from a batch's honest 5–15 files to any of this host's **887** tracked files.
That is a widening of the confabulation surface, not a hole in the invariant,
and it is the number to quote when someone asks how much rung 2 actually buys.

The false label is removed from the docstring, which now names the chain, the
residual and the bound.

## Two reviewers contradicted each other. Reviewer A was right.

One reviewer reported that `_enforce_agent_frontmatter` **never runs** on a host
whose config has no `site:` block. Another reported that it **does** run and
overwrites the agent's `source_files` with the orchestrator's values. Settled by
execution, not by reading:

- **The guard.** `_enforce_agent_frontmatter` is called under
  `if agent_fields is not None and target_path.exists()`
  (`orchestrator_runner.py:2454`). `agent_fields` is `None` unless
  `action == "create"` **and**
  `fmc.section_generator_for(rel, config) == "agent-authored"`
  (`orchestrator_runner.py:2383-2386`).
- **The reference host.** `.engineering-docs-agent/config.yml` on
  `claude-code-self-assessment` has top-level keys
  `docs, lint, notifications, publishing, run, sources, voice` — **no `site:`
  key**. `section_generator_for` returns `None` on its first branch (`site` is
  not a dict, `frontmatter_contract.py:44-46`). Executed against the real file
  for three real page paths: `None` every time.
- **The other half.** Given a config that *does* carry
  `site.docs_dir` + a section with `generator: agent-authored`,
  `section_generator_for` returns `'agent-authored'`, and
  `_enforce_agent_frontmatter` executed on a page whose frontmatter listed
  `AGENT_INVENTED.py` returned frontmatter listing only the orchestrator's
  `source_files` — the agent's value gone.

So reviewer B described the function correctly and reviewer A described the
**reference host** correctly, and it is A's fact that decides the spec: on this
host the call never fires, so it cannot be what closes circularity. Reviewer B's
mechanism is real but conditional on a `site:` block that the host does not have.

**The spec's conclusion survives anyway, by a different route**, which is why
this is a corrected argument rather than a withdrawn feature: on a create,
corroboration comes from `source_paths=grounding` being passed to
`build_corroborators` directly (`orchestrator_runner.py:1608`). Nothing ever
reads the written page's frontmatter back. And it could not: executed on the
enforced page above plus one inline prose citation, `extract_citations` returned
**only** the prose path — frontmatter `source_files` are not backticked spans, so
they are invisible to rung 1 on every host. The "Circularity is closed" paragraph
in Revision 2 now carries an in-place note saying so.

## What the rung-1 narrowing cost, measured

Rung 1 was narrowed from a raw substring scan of the prior page to
`set(extract_citations(prior_text)["paths"]) & files`. Re-derived on this repo at
this branch — **887** tracked files (`git ls-files`), **108** pages under
`docs/site-src/` — by scoring each page both ways and differencing:

| quantity | value |
| -------- | ----- |
| raw substring scan (old rung 1), page/path mentions | **673** |
| `extract_citations & files` (new rung 1) | **369** |
| dropped | **304** — **45.2%** of 673 |
| pages affected | **45 of 108** |

Location of the 304 dropped mentions. One bucket per occurrence, precedence
`frontmatter` → linter-dropped fence line (`_linter_dropped_lines`) → markdown
link destination → inline code span → bare prose; a mention counted once per
*distinct* bucket it occurs in, which is why the column sums above 304:

| location | dropped | of those, consequential |
| -------- | ------- | ----------------------- |
| `markdown_link_target` | 149 | 149 |
| `bare_prose` | 84 | 59 |
| `inline_code_span` | 32 | 0 |
| `frontmatter` | 29 | 16 |
| `fenced_block` | 19 | 3 |
| **sum** | **313** (9 mentions occur in two regions) | **227** |

**Consequential** means: a 2- or 3-segment shortening of that path is a unique
suffix candidate, so an edit that shortened it *now declines where it previously
repaired*. Counted over **distinct tracked paths** that is **180** of the 215
distinct dropped paths; counted over **mentions** it is **226** of 304. Those are
different questions with different answers — name which one you mean, the same
hazard the probe-count and Boris-tip-count rules already flag.

That is the real price, and it is coverage, not correctness: on an edit, 180
distinct tracked paths lost their rung-1 corroborator, so a shortening of any of
them now emits a non-`info_only` `citation_repair_declined` partial and the page
does not ship. Rung 2 has to carry them, and on `claude-extensions` rung 2 is
already the whole gate.

### The `internal_links` defence does not survive on this corpus

The narrowing is usually defended by observing that markdown link targets are
validated by a **different** rule, `internal_links`, so excluding them from rung 1
is a real price rather than a free win. On this corpus that is **false**, and it
is false in the direction that makes the narrowing look *better*, not worse:

**149 of 149** dropped `markdown_link_target` mentions sit inside an **external**
`https://github.com/theoju/engineering-docs-agent/blob/main/…` URL. Measured by
importing `LINK_RE` and `is_external` from the rule itself:
`internal_links.is_external` returns True for `http://`, `https://`, `mailto:`
and `tel:`, and `check_path` `continue`s on it
(`scripts/lint/internal_links.py:54-55, 62-65`). **Zero** of the 149 are relative
internal links; zero would be checked by `internal_links` even after
`strip_code`. Nothing validates them at all.

So the single largest bucket of dropped corroborators is not a debt owed to
another rule — it is precisely the module docstring's own category *"inside URL
bodies"*, and losing it is the strongest part of the narrowing rather than its
cost. `internal_links` does validate *relative* link targets, and on a corpus
that used them the original defence would hold; it does not hold here, and the
sentence should not be repeated without re-running the measurement.

### Figures that did not reproduce

Recorded rather than silently replaced, in keeping with this file's convention:

- **`markdown_link_target` 140 / `inline_code_span` 41** was the split circulated
  into this round. Mine is **149 / 32** — same total (313), same other three
  buckets, 9 mentions classified differently. Swapping the link-target /
  code-span precedence does not move it, and neither does dropping
  reference-definition and autolink destinations from the link region, so the
  difference is a region classifier I could not reconstruct. Mine is stated with
  its rules above so it can be re-run and disagreed with.
- **"180 of the dropped are consequential"** reproduces only as a count of
  distinct **paths**. At mention level the same rule gives **226**. The
  accompanying split (`markdown_link_target` 138, `frontmatter` 15,
  `bare_prose` 15, `inline_code_span` 9, `fenced_block` 2 — which sums to 179,
  not 180) does not reproduce at either level; mine is the table above.
- **887 tracked / 108 pages / 673 → 369 / 304 / 45.2% / 45 of 108** all
  reproduced exactly, so the headline result is not in doubt — only the
  breakdowns are.

### How to re-run it

Reproduce with `scripts/lint/citation_exists.py` and `scripts/citation_repair.py`
on the import path:

```python
files = set(subprocess.run(["git", "-C", ROOT, "ls-files"],
                           capture_output=True, text=True).stdout.splitlines())
for page in sorted((ROOT / "docs" / "site-src").rglob("*.md")):
    text = page.read_text()
    raw  = {f for f in files if f in text}            # old rung 1
    lint = set(extract_citations(text)["paths"]) & files  # new rung 1
    dropped = raw - lint
```

Locations come from `citation_repair._linter_dropped_lines(text)` for the fence
region and from `citation_exists._INLINE_CODE_RE` for spans — the linter's own
functions, never a local copy. "Consequential" is
`len(citation_repair.suffix_candidates("/".join(p.split("/")[-n:]), files)) == 1`
for `n` in `(2, 3)` where `p` has more than `n` segments; adding
`_REPO_PATH_RE`-shape, non-resolution and full `_candidate_rejection` filters on
top changes the count by **zero**, so the simple form is the one recorded.

---

# Revision 3 — detection only (2026-08-21)

**Status:** design, supersedes Revision 2's mechanism and every candidate-side
correction below it
**Reason:** four adversarial rounds produced four Criticals and all four were the
same defect class in a new disguise. The class is a property of rewriting a page,
not of any one guard, so the rewrite is deleted.

**Everything above stays exactly as written.** Revisions 1 and 2 and corrections
3, 4 and 5 record three successive wrong answers, and that record is the most
useful thing in this file — it is the evidence for the lesson at the end of this
section. Nothing here softens them.

## What shipped

**Diagnosis, never mutation. The page is never rewritten.**

`scripts/citation_repair.py` now REPORTS the tracked file a blocked citation was
most likely shortened from, and stops. There is no `Path.write_text` in the
module, no `repair_text`, no `rewrite_token`, and there must never be one again.
`diagnose(text, repo_root, config, files, corroborators)` takes text and returns
`[(cited, candidate, confidence)]`; it does not return a modified string and it
does not accept a path to write to. The orchestrator entry point is renamed to
match — `_diagnose_citation_paths` (`scripts/orchestrator_runner.py:1586`), still
`info_only` in the digest, still called unconditionally after authoring.

The page still blocks, exactly as `citation_exists` decided. Post-CCE-140 the
deferral skip still abandons that PR. What changes is that a human reading the
run digest is now told which file the author probably meant, instead of being
told only that a path does not exist.

Corroboration survives, demoted: it was the **entry condition for acting**, and
it is now a **confidence label on a suggestion**. `build_corroborators` is
unchanged in behaviour — rung 1 is still the linter's own view of the prior
committed page, rung 2 is still the batch's source set with globs excluded, and
both still require `source_paths` and `corroborators` to be passed explicitly
with no default. Only its role changed: nothing acts, so there is nothing to
gate.

Nothing in this module is correct, let alone **provably** so. That claim was
retired in Revision 2 and stays retired; the last surviving assertion of it, in
the embedded `CLAUDE.md` draft at
`docs/superpowers/plans/2026-08-21-cce141-citation-path-repair.md:838`, was
retired in place on 2026-08-21 so that a future reader cannot copy it back.

## Why: four rounds, four Criticals, one class

Read this as a sequence, not as four unrelated bugs. Every row is the same
sentence with a different mechanism in the middle: **repair moved a citation into
a region `citation_exists` does not verify, so a BLOCK became a silent PASS** —
and the pointer stopped being checked even after the file it named was deleted.
In rounds 2, 3 and 4 the flip was reproduced end to end; in three of them the
target file was then `git rm`-ed and `check_path` still answered `(True, 'ok')`.

| round | the guard that was supposed to make rewriting safe | the Critical |
| ----- | -------------------------------------------------- | ------------ |
| 1 | uniqueness of the suffix match | Uniqueness never established that the cited token **was a shortening** of the candidate. A path is a suffix of itself, but that argument is conditional on an antecedent the code never checks; `repair_text`'s only entry condition was "does not resolve," which is precisely the confabulation population `citation_exists` exists to block. Measured: **2086** distinct non-resolving proper-tail tokens have a unique match against **887** tracked files — the set of invented strings that flip block into pass was larger than the repository. |
| 2 | rung 1 — corroboration from the prior committed page | The corroborator used a **raw substring scan** of the prior text, which sees path mentions inside fenced blocks, URL bodies, HTML comments and as substrings of longer paths. Those are invisible to `extract_citations` **because the linter never validates them**, so they evidence nothing about acceptance. A prior page naming a fixture only inside a ```` ```text ```` fence corroborated it; a new page citing an invented `.github/workflows/ci.yml` was repointed at the fixture, and `check_path` went `(False, "cites nonexistent path …")` → `(True, 'ok')`. |
| 3 | the candidate-side exclusion **blacklist** | A blacklist enumerates only what someone thought of, and it missed two rows. **(a)** A candidate the linter cannot PARSE: `_REPO_PATH_RE` admits only `[\w.\-/]`, so a tracked `app/(marketing)/guides/setup.md` was written into the page and then not SEEN by `extract_citations` at all. **(b)** A candidate under the mkdocs build dir: `_resolves`'s first arm returns True for ANY path under `site_dir` with **no existence check whatsoever**, structurally identical to `example/`. |
| 4 | the positive verifiability **gate** that replaced the blacklist | The gate's own probe was blind. `_resolves_absent` asked "would `_resolves` still say yes if this file were gone?" by running `_resolves` against an **empty temporary repo root** — which does not delete one file, it deletes every file. All three existence arms of `_resolves` are `X in files or (repo_root / X).exists()` (`scripts/lint/citation_exists.py:456-468`), so emptying the root killed the on-disk half of all three at once. The disk fallback exists for a documented reason — "same-run siblings not yet added to git" — and the probe could not see it. |

Round 4's blinding is reproducible in the current tree with `citation_exists`
alone, no withdrawn code required:

```python
# docs_dir-rebased sibling present on disk but untracked
(root / "docs/site-src/refs/notes.md").write_text("x")
files = {"refs/notes.md"}
_resolves("refs/notes.md", root, files - {"refs/notes.md"}, "docs/site-src", "", ())
#   -> True   the real linter: resolution never depended on the candidate existing
_resolves("refs/notes.md", Path(empty), files - {"refs/notes.md"}, "docs/site-src", "", ())
#   -> False  the probe: "safe, verified by existence" — and the gate ADMITS it
```

A False from the probe was read as "this candidate will be verified by its own
existence." The truth was the opposite: the candidate resolves through a file
that is not it, so once written, deleting the named file leaves the page `ok`.
Round 4's guard reproduced round 3's defect from inside the fix for round 3.

## The two measurements that decided it

Both re-derived on 2026-08-21 against `feat/CCE-141-corroborated-repair` at
`85d5cdc`; both reproduced the figures they were quoted as.

**1. The feature fired zero times across the whole archived production record.**
`.engineering-docs-agent/stale-prs-archive/` holds 41 archived PRs, of which
**19** carry a `cites nonexistent path` block, covering **15 distinct blocked
citations**. Run against today's tracked set (887 files, `docs_dir:
docs/site-src`), those 15 split:

| outcome | count | why repair could not fire |
| ------- | ----- | ------------------------- |
| resolves now | 5 | the `docs_dir` branch from CCE-139/145 already rescues them, so repair is never reached |
| no candidate at all | 10 | no tracked file ends with the cited tail |
| **unique suffix match** | **0** | — |
| ambiguous | 0 | — |

Zero unique matches means the count is zero **before** the corroboration gate is
consulted — the entry condition of Revision 2 never even gets a chance to
decline. Revision 2's "the four genuine `architecture/*.md` shortenings already
resolve" under-counts slightly: it is five, `.engineering-docs-agent/current_run.json`
included. Re-run with:

```
grep -roh "cites nonexistent path '[^']*'" .engineering-docs-agent/stale-prs-archive/ \
  | sed "s/.*path '//;s/'$//" | sort -u
```

then `citation_repair.suffix_candidates(rel, files)` for each.

**2. Disabling the feature entirely left the suite green.** With the production
call site replaced by `if False:` in a detached worktree at `85d5cdc`, the full
suite was **1531 passed, 4 skipped** — byte-identical to the same worktree's
baseline before the edit (1531 passed, 4 skipped). Not one test exercises the
feature through the path production uses. Every test that covers it calls
`repair_text` or `_repair_citation_paths` directly.

Together these say the same thing twice: the rewrite delivered nothing that was
measured, and nothing measured would have noticed its absence.

## The general lesson

**Escalating mechanism against a defect class that keeps reappearing is the
signal to question the architecture, not to add a fifth mechanism.**

Watch the mechanism grow across the four rounds:

1. a suffix match;
2. plus corroboration from an independent source;
3. plus corroboration narrowed to what the linter itself validated, and a
   candidate-side exclusion blacklist;
4. plus a four-mechanism positive gate — named branch classes, an extractor
   round-trip, an absence probe, and a catch-all that **fabricated an
   impossible-filename twin** in order to ask the linter a hypothetical
   question about a file that does not and cannot exist.

Each step was a locally reasonable response to the previous Critical. Each was
more elaborate than the last. And each one reproduced the same defect from
inside the fix for the one before it — round 3's blacklist missed a class,
round 4's gate replaced the blacklist and then went blind in a new place.

`superpowers:systematic-debugging` names this exactly: after three fixes,
**"each fix reveals new shared state/coupling/problem in different place"** and
**"this is NOT a failed hypothesis — this is a wrong architecture."** The rule
says stop and question fundamentals rather than attempt fix #4. Fix #4 was
attempted. It produced Critical #4.

The fundamental here is not any guard. It is the decision to **mutate a page the
linter has already blocked**. Every guard was an attempt to prove that a
particular mutation would stay under the lint; the class of "regions the lint
does not verify" is open, discovered incrementally, and cannot be enumerated in
advance from inside the module doing the mutating. A page that is never
rewritten cannot be corrupted this way. Deleting the rewrite deleted the entire
class — not the current four instances of it, the class — and kept the one thing
four rounds actually produced: the diagnosis.

The transferable form: when the Nth fix for a defect is structurally more
complex than the (N-1)th and the defect keeps returning in a new location, the
complexity is not buying safety. It is the cost of holding a wrong architecture
in place. Delete the capability that hosts the class.

## What is given up

**The automatic rescue.** A page blocked on a shortened-but-recoverable citation
is no longer repaired and re-checked; it blocks, the deferral skip abandons the
PR, and the page is not written that night. A human has to read the digest and
either fix the source or re-run. That is a real regression against the CCE-141
ticket as written, and it is stated plainly rather than reframed.

Honestly costed: **it costs nothing that was ever measured.** Against the
complete archived production record the rescue fired zero times (above), and
removing it moved no test. The loss is entirely prospective — a rescue that
might have fired on some future page — weighed against four demonstrated
BLOCK→PASS corruptions, each of which permanently un-verifies a citation on a
page that then ships.

The asymmetry is what decides it. A missed rescue leaves a page unwritten and
loudly reported. A wrong repair writes a page that points at the wrong file,
passes the lint, and keeps passing it after the file it names is deleted — and
the downstream-owner audit above establishes that **no layer below repair
catches it**.

## What replaces it

An honest, consistent digest line — `info_only`, one per blocked citation:

```
citation_shortening_suspected: <page>: '<cited>' -> '<candidate>' (<confidence>)
```

Four labels, and **every** non-resolving citation gets exactly one of them:

| confidence | candidate field | means |
| ---------- | --------------- | ----- |
| `candidate_in_run_inputs` | the one candidate | one strict suffix match, and an input to this run other than the authoring agent already named that file |
| `suffix_match_only` | the one candidate | one strict suffix match, resting on the match alone |
| `ambiguous` | the candidates, capped at `_AMBIGUITY_CAP` = 5, then `(+N more)` | several tracked files end with this tail |
| `no_candidate` | `""` | no tracked file ends with this tail at all |

> The first two labels were `corroborated` / `uncorroborated` as originally
> shipped. Correction 6 renamed them; see that section for why, and for why
> `no_candidate` no longer reaches the digest at all.

The last two rows are the change that matters most for an operator. Under the
repair design, `ambiguous`, `no_candidate` and `uncorroborated` all `continue`d
**silently** — declining to act was implemented as declining to speak. A page
that blocked because two candidates matched produced no digest line at all,
while the single-candidate case was loud. That inconsistency is why the digest
could not be read as a census of blocked citations. It can be now: every
non-excluded, non-resolving citation appears, labelled.

`_excluded_reason` still suppresses the classes `check_path` declines to CHECK —
exempt tokens, the reserved `example/` namespace, gitignored paths. Those are
unresolvable **by design**, so a finding there would be noise, not signal. What
is gone is the candidate side of that machinery: the exclusion table, the gate,
the extractor round-trip, the absence probe and the twin all existed to make a
mutation safe, and they went with the mutation.

A `corroborated` label is not a claim of correctness. It bounds the surface —
the candidate is a tracked file some other source already pointed at — and
nothing more. The residual from correction 5 survives unchanged and is now
cheap: a confabulating `source-collector` can widen the `corroborated` label
from a batch's true 5–15 files to any tracked file on the host. That residual
used to cost a wrong page rewrite. It now costs an operator one over-confident
line in a digest.

---

# Post-implementation correction 6 — the diagnostic's own honesty (2026-08-22)

Revision 3 deleted the page rewrite and left one thing behind: a digest line.
That makes **the digest's trustworthiness the feature's entire remaining
value** — a line that is wrong, misleading or missing is now the only harm
this code can do, and an operator will act on it. A sixth adversarial round
judged every part of the diagnostic against exactly that, and found six
defects. None of the fixes adds mechanism: each is a relocation, a rename, a
deletion or a cap.

## 1 (Critical) — the digest reported citations that are not blocked

`_diagnose_citation_paths` was called **inside** the per-page authoring loop,
so it evaluated `_resolves` against a tree that was **still being built**. A
page citing a sibling docs page that the SAME RUN authors later — the ordinary
shape of a docs page — was diagnosed before that sibling existed.

Reproduced by driving the real `runner.run(...)` with two `doc_targets` where
the first cites the second:

```
HITS = ["citation_shortening_suspected: docs/site-src/core/connectors/foo.md:
         'docs/site-src/core/connectors/bar.md' -> '' (no_candidate)"]
LINT  ok=True
```

A digest that flags citations the linter accepts is not a census; it is noise
that trains an operator to ignore it.

**The seam chosen:** after the whole authoring loop, **before** the
content-validator dispatch. That is where the two views agree — every page the
run authored is on disk, so `_resolves` sees the same tree `citation_exists` is
about to see inside content-validator.

Three ordering constraints were checked against that seam:

- **Still sees the pages the run authored.** It iterates `authored`, the list
  the loop appends to on `out["ok"]`, filtered by `Path.exists()`.
- **Rung 2 grounding still in scope.** `grounding` is computed per batch inside
  the loop, so it is now recorded per page in `grounding_by_path` and read back
  by page. Passing the last batch's grounding to every page would have
  mislabelled findings silently.
- **Must not run for pages reverted by the lint-block revert.** This is why the
  seam is ABOVE the revert, not below it. A reverted *edit* is restored from
  HEAD and **still exists on disk**, so a diagnosis below the revert would
  report the previous commit's citations as if this run had written them.
  Below the revert is also where the feature would have nothing to say: a
  lint-blocked page is precisely the population this diagnostic exists to
  explain.

Pinned by `test_a_citation_to_a_sibling_the_same_run_authors_is_not_reported`,
which asserts BOTH halves — `citation_exists.check_path` accepts the page, and
the digest says nothing about it. Its fixture seeds a tracked decoy whose tail
is the sibling's path, so a mid-loop diagnosis produces a LOUD line rather than
a `no_candidate` the digest now drops anyway; without the decoy the test would
pass with the call back inside the loop and pin nothing.

## 2 (Important) — `corroborated` was not earned

The label was granted by **batch membership alone**. Rung 2 admits the whole
`_pr_changed_files(batch_prs)` set, so any tracked file the batch happened to
touch — a vendored dependency, a lockfile, an unrelated module — took the top
confidence label the moment it was the unique strict suffix match. Reproduced:
a repo tracking only `vendor/third_party/oauthlib/auth/session.py`, a page
citing an invented `auth/session.py`, reported as `(corroborated)`.

**Renamed, not re-earned.** Adding a further check to try to deserve the old
name is the mechanism escalation this feature was already cut down for.

| was | is |
| --- | -- |
| `corroborated` | `candidate_in_run_inputs` |
| `uncorroborated` | `suffix_match_only` |
| `build_corroborators` | `build_run_inputs` |

Both names now state an **observation**, never a verdict. The module docstring
carries a per-label "ESTABLISHES / DOES NOT ESTABLISH" block, so what the top
label does *not* prove is written down beside what it does.

## 3 (Important) — `no_candidate` was filed under a key contradicting it

`no_candidate` means the module looked for a tracked file ending with that tail
and found none — **its own evidence says the token is not a shortening**. Those
findings were nonetheless emitted under `citation_shortening_suspected`, and it
is the most common shape, so the dominant population sat under a key asserting
the opposite of what was measured.

Measured amplification: one page with 40 confabulated citations produces **1**
`lint_block` line — which already names all 40 paths, with severity — and **40**
diagnosis lines.

**Decision: dropped from the digest, not renamed.** Justification is entirely
about the operator: a renamed key would still carry *zero added information*
over the `lint_block` line that already names those paths, while keeping 40
lines in front of the reader and burying the handful of findings that do name
a file. The findings still cross `diagnose`'s return boundary, so the census is
available to any caller that wants it — the digest is the one place it earns
nothing. Pinned in both directions by
`test_a_no_candidate_citation_is_kept_out_of_the_digest`.

## 4 (Important) — unbounded LLM-authored text in state

Both `add_partial` reason strings embedded `cited`, `candidate` and `str(exc)`
with no truncation, against this file's own convention: `orchestrator_runner`
defines `_STDERR_TRUNCATE = 300` and applies it to every other embedded
untrusted string. Measured: a 40,000-char citation token produced a single
40,198-byte `partial_reasons` entry; 40 pages x 40 blocked citations produced a
167,005-byte PR body against GitHub's 65,536 limit.

The **existing** convention is applied — the page `label` too, since an
agent-chosen `page_hint` is the same class of text. Findings per page are
additionally capped at `_CITATION_FINDINGS_CAP = 10`, and the count withheld is
**reported** as `citation_diagnosis_truncated`. A silent cap is the failure mode
this whole ticket exists to fight; the cap without that line would *be* it.

## 5 (Important) — report completeness was unpinned, four ways

All four of these mutations to the reporting loop SURVIVED the full suite:

```
for cited, candidate, confidence in findings:   ->  ... in findings[:1]:    GREEN
                                                    ... in findings[-1:]:   GREEN
                                                    ... in findings[:2]:    GREEN
insert  if confidence == "ambiguous": continue  as the loop's first line     GREEN
```

The test file's own words are "the digest is a census of blocked citations or
it is nothing", and nothing pinned it at the seam that writes the digest.
`test_the_digest_reports_every_finding_on_a_page_not_a_slice_of_them` asserts
three findings as an exact ordered list (killing all three slices) and
`test_an_ambiguous_finding_reaches_the_digest` kills the fourth.

## 6 (Important) — `diagnose` did not assert it inherits fence-stripping

`extract_citations` calls `strip_fenced_blocks` on purpose ("fenced examples
are legitimately hypothetical"), so a citation appearing only inside a fence
never blocks. Nothing asserted `diagnose` inherits that, and this mutation
survived the full suite: extracting from the text joined across triple-backtick
splits, i.e. removing the fence markers before extraction.

Worth recording for future mutation work in this module: the naive
`text.replace("```", "")` form of that mutation fails **only** via the AST
write-guard, because `replace` is in `_WRITE_ATTRS`. That is an artifact, not a
behavioural catch, and it must not be allowed to stand in for real coverage.

## Also closed this round

- `_excluded_reason` returned a classification string no caller read (its only
  use was `is not None`). Now `_is_excluded`, returning `bool`.
- Two of three line-pinned cross-references in the `build_run_inputs` docstring
  had already rotted by one revision (`:2372` and `:2048-2050` against real
  lines 2395 and 2072). Cross-references there name **symbols** now, so they
  cannot rot.
- `test_citation_repair_wiring.py` asserted `"corroborated" in r`, which the
  substring inside `"uncorroborated"` satisfies — it could not distinguish the
  two labels, the one thing its name claimed. Every label assertion is now
  parenthesised and exact.
- The census test in `test_citation_repair.py` overclaimed: its docstring said
  four citations produce four findings, it asserted three, and its fourth line
  `README.md` is not a citation at all (`_REPO_PATH_RE` requires a slash), so
  the `_resolves` arm it credited was never reached. Name, docstring and
  assertions agree now, and the resolving citation is a real slashed path.
- The failure line used a bare `path.name` while the finding line used the
  repo-relative label, so `citation_diagnosis_failed: index.md: …` did not say
  which page — and `add_partial` dedupes identical strings, collapsing many
  pages into one line. Both lines use `label`.

## Coverage added this round

Eight tests. Every one was mutation-checked against the FULL suite: the guard
it names was deleted or inverted, the suite was confirmed to FAIL, and the
source was restored byte-identically. Twelve mutations, twelve kills — the four
from defect 5, the seam move of defect 1, the `no_candidate` re-emission, the
truncation and the cap of defect 4, the fence-marker strip of defect 6, the
bare-basename failure line, the `_resolves` guard, and a label swap that the
old substring assertion would have passed.

---

# Post-implementation correction 7 — round 6, and where the ratchet stops (2026-08-22)

Two independent verifiers re-reviewed correction 6 and both returned
DO_NOT_MERGE — one Critical, seven Importants, six Minors between them. Every
finding was reproduced here before it was acted on, because reviewers on this
branch have twice reported a real defect with the wrong stated cause.

The finding *category* has changed, and that is the signal worth recording.
Rounds 1–4 each found **a repair corrupting a page**. Rounds 5 and 6 find
**a digest that might mislead an operator**. The architectural reversal did
what it was supposed to do: the remaining defects are advisory-quality
defects, none of which can turn a BLOCK into a PASS.

## Fixed

**1 — one pathological token destroyed the whole page's census.** `_resolves`
reaches `(repo_root / rel).exists()`, and pathlib **re-raises** OSError for
errno values outside its ignored set; ENAMETOOLONG is not in that set. A
single 3000-char citation token propagated out of `diagnose` and discarded the
local `findings` list wholesale, so every good finding that appeared **earlier
in document order** was lost and the page produced one vague
`citation_diagnosis_failed` line instead. The per-citation body is now wrapped;
the token is skipped and its neighbours survive. Skipping is safe for the same
reason the caller drops `no_candidate` — the token does not resolve, so
`citation_exists` blocks the page and `lint_block` names that exact path.
Pinned by `test_one_pathological_token_costs_only_itself`.

**2 — the digest was bounded per page and unbounded per run.** Correction 6
capped one page at `_CITATION_FINDINGS_CAP` and called the digest BOUNDED.
`_format_partial_digest` joins every reason unconditionally, so N pages × 10
findings × ~950 bytes — `label`, `cited` and `candidate` are each truncated at
`_STDERR_TRUNCATE` **separately** — clears GitHub's 65,536-byte PR-body limit
at roughly seven pages. That is the same defect correction 6 opened for,
half-fixed. `_CITATION_RUN_FINDINGS_CAP` now bounds the sum, and the line that
announces it names **no page**, so `add_partial`'s string-dedupe collapses
every page past the cap into one line.

**3 — both caps were pinned relatively, never absolutely.** Each cap test
derived its fixture size *from the constant it was testing*, so raising either
to an ineffective value scaled the fixture with it and the suite stayed green:
`_CITATION_FINDINGS_CAP = 10 → 10000` and `_AMBIGUITY_CAP = 5 → 5000` both
passed the full suite. Lowering was caught; raising was not — which leaves
exactly the harm each constant exists to prevent unguarded. Each now carries
one absolute assertion, with the reason for the bound in the test.

**4 — the orchestrator's write-guard guarded less than it claimed to.** Its
docstring called it "matching the module-level one"; it listed five attributes
against the module guard's nine. `path.touch()` and `path.open("w").write(...)`
inside `_diagnose_citation_paths` both passed the full suite while the same two
calls inside `citation_repair` were caught. It now imports the module test's
`_WRITE_ATTRS` rather than re-listing them. A guard that guards less than the
one it names is worse than no guard: it reads as coverage.

**5 — the classification rationale was factually wrong for one lens.** The
docstring argued info_only from "the page blocks because `citation_exists`
blocks it, and that block is already reported." Under a section whose
generator is `archive-index`, CCE-124 downgrades `citation_exists` to `warn`
and `run`'s revert fires only on `block` — so an archive page keeps its
shortened citation, **ships**, and produces no `lint_block` line at all. For
those pages this advisory is the only signal the operator gets. That argues
for keeping the line, not for promoting it: the run judged nothing and
rejected nothing, and `degraded=True` would cost auto-merge for a page the
host deliberately chose not to gate.

**6 — the durable record described a digest that does not ship.** `CLAUDE.md`
was two commits stale: it named `corroborated`/`uncorroborated`,
`_excluded_reason` and `build_corroborators`, all renamed in `998ad5c`, and
listed `no_candidate` as reaching the digest when it is dropped. Both
checkbox-driven plans under `docs/superpowers/plans/` were 100% unchecked, with
no superseded banner, and each opens by instructing an agentic worker to build
the capability that was deleted. Both now carry a stop banner.

## Accepted, not fixed — the same-run untracked sibling

The candidate search and the resolution test use different universes.
`_resolves` accepts `rel in files or (repo_root / rel).exists()`, and the disk
arm exists — by its own comment — to cover same-run siblings not yet added to
git. `suffix_candidates` iterates `files` alone, which is `git ls-files`. Pages
this run just **created** are not staged until `_stage_docs_run_changes`, far
below the diagnosis seam.

Reproduced, both shapes:

- with no tracked decoy → `no_candidate` → dropped from the digest → silence;
  `lint_block` still names the path, so the operator loses the hint, not the
  block.
- with a tracked decoy elsewhere in the tree → the digest suggests **the
  decoy** while the real target is the untracked sibling. This is the sharp
  edge: a wrong suggestion, not a missing one.

**Ruling: document and pin, do not fix.** Widening the candidate universe to
untracked on-disk state is precisely the region-the-linter-does-not-verify
class that produced a Critical in four consecutive rounds — it is the same
move that killed the repair, re-entering through the diagnostic. The cost is
bounded and asymmetric: the label is `suffix_match_only`, the weakest of the
four, whose documented meaning is "resting on the match alone," and **nothing
acts on it**. A wrong hint an operator can check against the tree is not in
the same class as a BLOCK silently becoming a PASS. Pinned by
`test_a_same_run_untracked_sibling_is_a_known_blind_spot`, whose docstring
says plainly that it records behaviour we accept rather than behaviour we
want.

## Parked, with reasons

- **`scripts/citation_repair.py` repairs nothing and is still named
  `citation_repair`.** Every `repair`/`rewrite` string inside it is correctly
  framed as history. A rename touches 8 files for no behavioural gain; it
  belongs in its own commit, not at the end of a six-round branch.
- **Reason strings dedupe within `_STDERR_TRUNCATE`.** Two distinct blocked
  citations whose reason strings agree within the first 300 characters
  collapse into one digest line with no truncation notice. Requires a
  ~300-character shared path stem to trigger.
- **`cited` vs `rel` at the two use sites, and the label's truncation upper
  bound**, are each unpinned by a test. Both argument choices are correct
  today and diverge only for an absolute in-repo citation.

## Verification

Six mutations, each run against the two citation test files, restored
byte-identically after each:

| # | mutation | result |
| - | -------- | ------ |
| M-A | `except OSError` → `except ZeroDivisionError` | 1 failed |
| M-B | delete the `return` after the run-cap line | **survived — see below** |
| M-C | `_CITATION_RUN_FINDINGS_CAP` 40 → 10000 | 2 failed |
| M-D | `_AMBIGUITY_CAP` 5 → 5000 | 1 failed |
| M-E | insert `path.touch()` into `_diagnose_citation_paths` | 1 failed |
| M-B′ | M-B again, against the strengthened test | 1 failed |

**M-B is this round's own vacuous test, caught by mutating it.** The run-cap
test asserted only on the `citation_shortening_suspected` lines, and deleting
the `return` still passed — because `[:room]` already empties `shown`. What
the `return` actually prevents is each page past the cap emitting its **own**
`citation_diagnosis_truncated: <page>: reported 0 of 10` line, which names a
page, so dedupe cannot collapse them and the growth the cap exists to stop
resumes at one line per page. The test now counts **every** line the feature
contributes, not the subset it happened to be about. That makes seven vacuous
tests found on this branch, all the same shape: an assertion that cannot
observe the thing its name claims.
