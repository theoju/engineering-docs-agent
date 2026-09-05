---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/241
synthesized_into: []
doc_kind: decision
---

# CCE-141: shortened-citation repair ships as diagnosis only

## Context

`page-author` sometimes emits a citation as a bare relative path instead of
its full tracked path. The originating incident: a page cited
`.claude/skills/connector-builder/references/checklist.md` at three sites, and
a rewrite shortened all three to `references/checklist.md`. `citation_exists`
correctly found nothing at the repo root and blocked the page. Post-CCE-140,
a blocked page is not a stall — the deferral-skip path abandons the PR, so
the page is silently never written. Nobody was told which file the citation
had probably come from.

An automated repair for this defect was built, reviewed, and withdrawn. Four
adversarial review rounds each produced a Critical, and every one was the
same class in a new disguise: the repair moved a citation into a region
`citation_exists` does not verify, so a correct BLOCK became a silent PASS —
including a case where the repaired citation kept resolving as "valid" after
the file it named was deleted. Per this project's systematic-debugging
practice, three-plus fixes that each reveal a new problem in a different
place is not a failed hypothesis, it's a wrong architecture. Round 4 was the
one that made this legible: the fix for round 3 asked `citation_exists`
whether a repaired citation would still resolve by running the check against
an **empty temp repo root** — which blinds every on-disk existence check at
once, not just the one it meant to probe, so the gate ended up admitting the
very failure mode it was built to catch.

Two measurements closed the question. First, across the archived production
record — 41 stale PRs, 19 of them carrying a `cites nonexistent path` block
over 15 distinct blocked citations — zero of those citations had a unique
suffix match among tracked files. The corroboration-and-repair machinery had
never once fired in production. Second, disabling the repair path entirely
left the test suite green: not one test exercised the feature through the
path production actually used. Given zero measured production value and four
demonstrated correctness regressions, the repair capability was withdrawn.

## Decision

Ship detection, not repair. `scripts/citation_repair.py` reports the tracked
file a blocked citation was most likely shortened from, and stops there. The
module has no `Path.write_text` call, and two source-level AST guards enforce
that it never grows one — a page that is never rewritten can't be corrupted
by a rewrite.

`diagnose()` walks a page's citations and returns `(cited, candidate,
confidence)` tuples in document order, one per citation that doesn't resolve
and isn't in a class `citation_exists` already declines to check (exempt
tokens, `example/`-prefixed paths, gitignored paths). Confidence is one of
four labels:

- `candidate_in_run_inputs` — exactly one tracked file is a strict
  segment-suffix match for the cited tail, and some input to this run other
  than the authoring agent already named that file (either the batch's
  source-collector output, or a path the page's own prior committed version
  already cited and the linter validated).
- `suffix_match_only` — exactly one tracked file matches the suffix, resting
  on the string match alone.
- `ambiguous` — several tracked files end with the cited tail (candidates are
  capped and the count withheld is reported).
- `no_candidate` — no tracked file ends with the cited tail at all.

These are confidence labels on a suggestion, not a gate on an action —
nothing acts on them, so there is nothing left to gate. `candidate_in_run_
inputs` in particular is weaker than its name might suggest: the
source-collector half of its evidence is itself an LLM subagent's output, not
orchestrator-verified state, so the label bounds a coincidence rather than
confirming a rewrite.

Wiring lives in `orchestrator_runner.py` as `_diagnose_citation_paths`,
called once per authored page after the whole authoring loop finishes and
before the lint-block revert — so it reads the same finished tree
`citation_exists` is about to evaluate. Findings become one `info_only`
digest line per blocked citation, bounded per page and again across the
whole run so a pathological page can't blow out the PR body. `no_candidate`
findings are computed but deliberately dropped from the digest: `lint_block`
already names those exact paths with severity, and a `no_candidate` result's
own evidence is that the token isn't a shortening of anything in the repo —
surfacing it a second time would say nothing new.

Classification stays `info_only`, not `degraded`. The page still blocks
because `citation_exists` blocks it, and that failure is already reported and
already classified. A second degraded reason for the same underlying failure
would double-count it and would cost the run auto-merge for a line that is
pure advice. The one exception: under an archive-index section, `citation_
exists` runs at `warn` severity rather than `block`, so a shortened citation
there ships without producing any `lint_block` line at all — there, the
diagnosis line is the only signal an operator gets, which argues for keeping
it advisory rather than promoting it, since the run itself judged nothing and
rejected nothing.

## Consequences

A page whose citation was shortened is still abandoned by the deferral-skip
path — that part of the behavior is unchanged. What changes is what a human
sees afterward: instead of a page vanishing with no explanation, the PR
digest names the tracked file the citation most likely came from, so a
reviewer can fix the source page's citation and let it re-run cleanly.

The regression against the original ticket is real and accepted: a
recoverable shortened citation is no longer fixed automatically. That cost is
weighed against four demonstrated BLOCK-to-PASS correctness regressions that
no downstream layer would have caught, and against a measured zero
production firings for the capability being given up. If a future change
proposes rewriting a blocked page again, the question to ask first isn't
which guard is missing — it's which region of `citation_exists` hasn't been
found yet that the rewrite could move a citation into.

## References

- Spec: `docs/superpowers/specs/2026-08-21-cce141-citation-path-repair-design.md`
- `scripts/citation_repair.py`
- `scripts/orchestrator_runner.py:_diagnose_citation_paths`
- CCE-141 (2026-08-21)
