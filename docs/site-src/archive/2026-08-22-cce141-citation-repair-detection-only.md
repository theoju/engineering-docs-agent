---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/241
synthesized_into: []
doc_kind: decision
---

# CCE-141: citation-shortening detection ships; automatic repair does not

## The problem

`page-author` occasionally shortens an already-resolvable citation. In the
originating incident it cited
`.claude/skills/connector-builder/references/checklist.md`, then rewrote the
page and shortened the same citation to `references/checklist.md`. That
token resolves against nothing at the repo root, so `citation_exists`
correctly blocks it.

Blocking used to be recoverable — a blocked page just stalled until a later
run got it right. Once the watermark advance became cursor-backed, that
stopped being true. The deferral skip now abandons a PR that keeps
tripping the same block, and the page is silently never written. Nothing
about that shows up as red: the run reports success, the baseline advances
past it, and a documentation gap opens with no signal pointing at it.

## What ships: diagnosis, not repair

`scripts/citation_repair.py` inspects every citation on a freshly authored
page that `citation_exists` is about to block. When a shortened form of a
tracked file is the likely cause, it reports the best-match candidate and a
confidence label in the run digest. It changes nothing about whether the
page ships.

You'll see one of four labels per non-resolving citation:

- **`candidate_in_run_inputs`** — exactly one tracked file matches the
  cited tail on a strict segment boundary, and that file was already named
  by something other than the authoring agent: either the prior committed
  version of the page (a citation `citation_exists` had already validated
  there), or the batch's own source set.
- **`suffix_match_only`** — exactly one tracked file matches, but nothing
  else points at it. The suggestion rests on the string match alone.
- **`ambiguous`** — more than one tracked file ends with the cited tail
  (listed up to a cap, with a count of how many were withheld).
- **`no_candidate`** — no tracked file ends with the cited tail at all.
  This label is computed but deliberately dropped before it reaches the
  digest: it names nothing `lint_block` hasn't already named, and it's the
  dominant population, so including it would bury the handful of findings
  that actually point at a file.

None of these labels means "confirmed." Read them literally: they describe
what the module observed, not a verdict on what the author meant. Even
`candidate_in_run_inputs` only means some input to this run — not the
authoring agent — already named that file; the run's own source set comes
from `source-collector`, itself an LLM subagent, so a confabulated entry
there can widen this label without either doctrine actually being violated.

The pass is wired in as `_diagnose_citation_paths`
(`scripts/orchestrator_runner.py:_diagnose_citation_paths`), called once per
authored page after the whole authoring loop finishes and before the
lint-block revert runs — the same finished tree `citation_exists` is about
to check, and before a reverted edit gets restored from HEAD. Findings are
capped both per page and per run so the digest stays inside GitHub's PR-body
size limit, and a single pathological citation token (one that raises
`OSError` on resolution) costs only itself rather than discarding every
finding already collected for that page.

## Why automatic repair was withdrawn

A deterministic rewrite was built for this exact defect and reviewed across
four adversarial rounds. Every round produced a Critical, and every
Critical was the same class of defect wearing a different disguise: the
repair moved a citation into a region `citation_exists` does not verify, so
a correct BLOCK silently became a PASS — and stayed a pass even after the
target file was deleted.

- **Round 1**: uniqueness of a suffix match never established that the
  cited token was a shortening of anything. An invented path is also a path
  that fails to resolve — that's precisely the population `citation_exists`
  exists to catch, and a unique match alone can't distinguish the two.
- **Round 2**: the corroboration check that was added to gate round 1
  used a raw substring scan of the page's prior text, which counted
  fenced-block, URL, and HTML-comment mentions the linter itself never
  validates. A path named only inside a code fence corroborated a rewrite
  that pointed a real citation at an unrelated test fixture.
- **Round 3**: the candidate-side exclusion list was a blacklist, and it
  missed two more classes with the same failure shape — a candidate the
  linter's extractor can't parse (parentheses or brackets in the path), and
  a candidate that resolves only because it sits under the mkdocs build
  directory, which `citation_exists` accepts unconditionally.
- **Round 4**: the gate built to close round 3 tested "would this still
  resolve if the file were gone?" by re-running resolution against an empty
  temporary repo root — which made every file disappear at once, not just
  the one candidate under test, blinding the on-disk half of every
  resolution arm and admitting the exact class it was meant to reject.

Two measurements decided the withdrawal rather than the fourth Critical
alone. Across the whole archived production record — 41 stale PRs, 19 of
them carrying a `citation_exists` block over 15 distinct blocked
citations — a working repair would have fired **zero** times: every
resolvable case already resolves through an unrelated fix (the `docs_dir`
source-root branch), and none of the rest had a unique suffix match.
Separately, disabling the repair call site entirely left the test suite
byte-for-byte unchanged, meaning nothing in the suite exercised the feature
through the path production actually uses.

The transferable lesson isn't "the guard was wrong four times." It's that
three-plus fixes, each surfacing a new problem in a new place, is a signal
to question the architecture rather than write fix five. The fundamental
mistake was mutating a page the linter had already blocked at all — the set
of regions a lint rule doesn't verify is open-ended and gets discovered
incrementally, so it can never be fully enumerated from inside the module
doing the mutating. A page that is never rewritten can't be corrupted that
way. Deleting the rewrite deleted the whole defect class, not four
instances of it.

## What this costs, honestly

The automatic rescue is gone. A recoverable shortened citation is no longer
fixed and re-checked in place — the page blocks, the PR is abandoned by the
deferral skip, and a human has to read the digest and act on it. That's a
real regression against the original ask, and it's accepted because the
measured cost of *not* having repair was zero observed cases in the entire
archived record, weighed against four demonstrated BLOCK-to-PASS
corruptions that nothing downstream of repair would have caught.

There's one path where the info-only framing gets stretched thin: an
`archive-index` section downgrades `citation_exists` to `warn` (CCE-124),
and the lint-block revert only fires on `block` severity — so a page in
that kind of section can ship with an unrepaired shortened citation and
produce no `lint_block` line at all. There the diagnosis is the only signal
an operator gets, which is an argument for keeping the digest line, not for
promoting the finding to something that blocks the run.

If a future contributor is tempted to bring the rewrite back, the question
to ask first isn't "which guard is missing" — it's "which region of the
lint have we not found yet." That question doesn't have a bounded answer,
which is exactly why detection-only is where this stopped.

## Related

- `scripts/citation_repair.py` — the diagnosis module.
- `scripts/lint/citation_exists.py` — the Tier-1 block rule this diagnoses
  around; imported from, never reimplemented.
- CCE-140 (cursor-backed watermark advance) — the change that turned a
  blocked page from "stalled" into "silently abandoned."
- CCE-124 (archive-index severity downgrade) — the one case where this
  diagnostic is the only signal on a shipped page.
