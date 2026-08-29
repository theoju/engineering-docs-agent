---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/241
synthesized_into: []
doc_kind: decision
---

# CCE-141: shortened citations are detected, never repaired

## The problem

`page-author` sometimes shortens an already-resolvable citation. One
committed page cited `.claude/skills/connector-builder/references/checklist.md`
at three sites; a subsequent rewrite emitted the bare
`references/checklist.md`. `citation_exists` correctly finds nothing at the
repo root and blocks the page — but post-CCE-140 that is not a stall. The
deferral skip abandons a repeatedly-blocked PR, so the page is silently never
written and nothing is red anywhere: the run reports success, the baseline
advances, and a documentation gap appears with no signal pointing at it.

## The decision

Detect the shortening and report it. Never rewrite the page to fix it.

`scripts/citation_repair.py` reports the tracked file a blocked citation was
most likely shortened from, via `diagnose()`, and stops. There is no
`Path.write_text` anywhere in the module, and per its own docstring there must
never be one.

`diagnose()` returns `[(cited, candidate, confidence)]` — one entry per
citation that fails to resolve and isn't in a class the linter declines to
check (an exempt token, the reserved `example/` namespace, a gitignored path).
Every non-resolving citation gets exactly one of four confidence labels:

- `candidate_in_run_inputs` — exactly one tracked file is a strict
  segment-suffix match for the cited tail, and some input to this run other
  than the authoring agent already named that file (either the linter's own
  validated view of the prior committed page, via `build_run_inputs`, or the
  batch's source set).
- `suffix_match_only` — exactly one suffix match, resting on the string match
  alone.
- `ambiguous` — several tracked files share the tail, listed up to a cap and
  then `(+N more)`.
- `no_candidate` — no tracked file ends with the cited tail at all.

`suffix_candidates()` requires a segment-boundary suffix, not a substring
match: `references/checklist.md` matches
`.claude/skills/connector-builder/references/checklist.md`, but
`erences/checklist.md` matches nothing.

The orchestrator wires this in as `_diagnose_citation_paths` in
`scripts/orchestrator_runner.py`, called once per authored page after the
whole authoring loop finishes and before the lint-block revert — so it reads
the same finished tree `citation_exists` is about to read, including sibling
pages the same run authored. Every line it produces is `info_only=True`: the
page's block is already reported by `citation_exists` (`lint_block`,
`degraded=True`), and a second degraded reason for the same failure would
double-count it and cost the run auto-merge for advice alone. Findings are
capped per page and per run so one wholesale-confabulated page can't blow out
the PR body: past a handful of lines, a digest stops being something an
operator reads. `no_candidate` findings are computed but dropped from the
digest — that population is the dominant one and `lint_block` already names
every one of those paths, with severity, so repeating them adds no
information.

## Why automatic repair was rejected

A deterministic repair implementation was built for this exact defect —
resolve the shortened token by suffix match, rewrite it in place — and went
through four adversarial review rounds. Each round produced a Critical
finding, and every one was the same class of defect wearing a different
disguise: **the repair moved a citation into a region `citation_exists` does
not verify, so a correct `block` became a silent `pass`, and the pointer
stopped being checked even after the file it named was deleted.**

- Round 1: uniqueness of a suffix match never established that the cited
  token was a shortening of anything — it only established that exactly one
  tracked file happened to end the same way. That's precisely the
  confabulation population `citation_exists` exists to block.
- Round 2: the corroboration step meant to gate repair used a raw substring
  scan that counted fenced, URL, and comment mentions the linter never
  validates in the first place.
- Round 3: the candidate exclusion list missed unparseable tokens and paths
  under the mkdocs build directory.
- Round 4: the gate built to catch round 3's gap asked whether a candidate
  would "still resolve" by emptying the repo root to simulate absence — which
  deleted every file, not just the one under test, blinding the on-disk half
  of every resolution check across the board.

Two measurements decided the withdrawal. Across the whole archived production
record — 19 PRs, 15 distinct blocked citations — the repair mechanism would
have fired zero times: the real shortenings already resolved through an
unrelated `docs_dir` fallback added for a different ticket. And disabling the
repair call site entirely, in a detached worktree, left the full test suite
green and byte-identical to that worktree's own baseline: no test anywhere
exercised the feature through the path production actually used.

The transferable lesson isn't about any one guard. Three-plus fixes, each
revealing a new problem in a different place, is not a failed hypothesis —
it's a wrong architecture. The fundamental mistake was mutating a page the
linter had already blocked; the set of regions the lint doesn't verify is
open-ended and gets discovered incrementally, so it can't be enumerated from
inside the module doing the mutating. A page that is never rewritten can't be
corrupted that way. Deleting the rewrite deleted the whole defect class, not
one more instance of it.

## What shipped instead

Diagnosis only, backed by two guards against reintroducing a write path. A
recoverable shortened citation is no longer fixed and re-checked
automatically — the page blocks, the PR is abandoned by the CCE-140 deferral
skip, and a human reads the digest to decide what to do. That's a real
regression against the original ticket, and it costs nothing that was ever
measured: see the zero-firings and green-suite-when-disabled results above,
weighed against four demonstrated block-to-pass corruption modes that no
lower layer catches.

If anyone proposes rewriting a blocked page again, the question isn't which
guard is still missing — it's which region of the lint hasn't been found yet.
That question has no bounded answer.

Spec: `docs/superpowers/specs/2026-08-21-cce141-citation-path-repair-design.md`.

Reference: CCE-141 (2026-08-21).
