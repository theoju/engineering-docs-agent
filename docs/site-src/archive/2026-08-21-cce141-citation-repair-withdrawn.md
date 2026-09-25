---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/241
synthesized_into: []
doc_kind: decision
---

# CCE-141: automatic citation repair was built, then withdrawn

## The problem it was built to fix

`page-author` sometimes shortens an already-resolvable citation. The
canonical case: a committed page correctly cited
`.claude/skills/connector-builder/references/checklist.md`, and a later
rewrite shortened the same citation to `references/checklist.md`.
`citation_exists` (Tier-1, block) correctly finds nothing at the repo root
and blocks the page — every run, forever, because nothing corrects the
citation and nothing removes the block.

Post-CCE-140, a repeatedly-blocked PR is abandoned by the deferral-skip
hatch and the baseline moves past it. That turns the failure from "loud and
stuck" into something worse: the page is silently never written, the run
reports success, and the baseline advances. Nothing is red anywhere.

## What was built

A deterministic repair pass: for each citation token that failed to
resolve, suffix-match it against the tracked-file set, and if the match was
unique (and later, corroborated by an independent source), rewrite the
token in the page text to the full path. The mechanism went through four
adversarial review rounds, documented in
`docs/superpowers/specs/2026-08-21-cce141-citation-path-repair-design.md`.

Every round found the same defect in a new place: **the repair moved the
citation into a region `citation_exists` does not verify, turning a correct
BLOCK into a silent PASS — one that stayed a silent pass even after the
cited file was deleted.**

- **Round 1.** Uniqueness of a suffix match never established that the
  cited token was actually a shortening of the matched file. It only
  established that no *other* tracked file shared the tail. Measured
  against this repo's own tree: 2,086 distinct non-resolving tokens have a
  unique suffix match — a confabulation surface larger than the repository
  itself (887 tracked files).
- **Round 2.** The corroboration check meant to fix round 1 used a raw
  substring scan of the prior page text, which counted mentions inside
  fenced code blocks, URL bodies, and HTML comments — sites
  `citation_exists` itself never validates. A token the linter never
  checked cannot evidence that the pipeline accepted a reference to that
  file.
- **Round 3.** The candidate-side exclusion list was a blacklist, and a
  blacklist only enumerates what someone thought of. It missed a candidate
  the linter's extractor could not parse (a route segment like
  `app/(marketing)/guides/setup.md`) and a candidate living under the
  mkdocs build directory — both classes where `citation_exists` reports
  `ok` without checking existence at all.
- **Round 4.** The gate built to close round 3 asked whether a file would
  still resolve if it were absent by re-running the linter's resolution
  logic against an *empty* temporary repo root. That answer is correct for
  the candidate under test and wrong for every other file, because deleting
  the whole repo root blinded the on-disk half of every resolution arm at
  once, not just the one being probed.

## The decision: withdraw the repair, keep detection

Repair was deleted. What ships instead is `scripts/citation_repair.py`,
which never calls `Path.write_text` and never will — the module's own
docstring states outright that there must never be one. Its single function,
`diagnose`, reports the tracked file a blocked citation was most likely
shortened from, and stops.

`diagnose` returns one of four confidence labels per non-resolving citation:

- `candidate_in_run_inputs` — exactly one tracked file matches the suffix,
  and something other than the authoring agent already named that file this
  run (either the prior committed page, via a citation `citation_exists`
  actually validated, or the batch's source-collector output).
- `suffix_match_only` — exactly one tracked file matches, resting on the
  string match alone.
- `ambiguous` — more than one tracked file matches, listed up to a cap.
  `no_candidate` — no tracked file ends with the cited tail at all.

None of these labels establish that the citation was actually a
shortening, only what the module observed. `no_candidate` findings are
computed but dropped before they reach the digest: `lint_block` already
names that exact path, with severity, so surfacing it again would be pure
duplication.

Detection is wired as `_diagnose_citation_paths` in
`scripts/orchestrator_runner.py`, dispatched after the whole page-authoring
loop finishes and before the lint-block revert runs — so it inspects the
same finished tree `citation_exists` is about to check, not an
intermediate one. It is `info_only`: it adds a digest line, never flips
`partial`, and never blocks a merge. Findings are bounded both per-page and
per-run so that a pathological page cannot blow out the PR body.

## Why the measurements, not just the incidents, decided it

Two numbers closed the argument, independent of the four rounds of
corruption:

1. **Zero real-world firings.** Measured against the complete archived
   production record — 19 PRs, 15 distinct blocked citations in
   `.engineering-docs-agent/stale-prs-archive/` — the repair would have
   fired zero times. The genuine shortenings in that record already
   resolved through an unrelated `docs_dir` resolution branch added later
   (CCE-139/145), so repair never even reached them.
2. **The test suite was unchanged with the feature disabled.** Disabling
   the production call site entirely left the suite green and
   byte-identical to baseline — no test in the repository exercised the
   feature through the path production actually used.

Given a capability with demonstrated zero production value and four
successive corruption findings, the corruption findings are the reason to
stop building it, and the measurements are the reason not to try a fifth
time.

## The general lesson

`superpowers:systematic-debugging` names the shape directly: three or more
fixes, each revealing a new problem in a different place, is not a failed
hypothesis — it is a wrong architecture. Each round here made the guard
more elaborate (a suffix check, then corroboration, then a linter-validated
corroboration check, then a four-mechanism gate that fabricated a twin
filename to ask the linter a hypothetical about a file that cannot exist),
and the defect kept reappearing somewhere new inside the elaboration.

The actual fundamental was never any individual guard. It was the decision
to mutate a page the linter had already blocked. The set of regions a
linter does not verify is open and gets discovered incrementally — it
cannot be enumerated from inside the module doing the mutating. A page
that is never rewritten cannot be corrupted that way: deleting the rewrite
deleted the whole defect class, not four instances of it.

If a future change proposes automatically rewriting a page that
`citation_exists` has already blocked, the right question is not "which
guard is missing" — it is "which region of the lint have we not found
yet," and that question has no bounded answer.

## What's left

`scripts/citation_repair.py` (detection only), wired through
`_diagnose_citation_paths` in `scripts/orchestrator_runner.py`. Test
coverage lives in `tests/orchestrator/test_citation_repair.py` and
`tests/orchestrator/test_citation_repair_wiring.py`; the advisory
classification (`info_only`, never flips `partial`) is asserted in
`tests/orchestrator/test_classification_coverage.py`.

Full design history, including each round's reproduction steps, is in
`docs/superpowers/specs/2026-08-21-cce141-citation-path-repair-design.md`.
Reference: CCE-141 (2026-08-21).
