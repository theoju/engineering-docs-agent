---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/241
synthesized_into: []
doc_kind: decision
---

# CCE-141: citation shortening is detected, not repaired

`page-author` sometimes shortens a citation that already resolves. The
committed page for the connector-builder skill cited
`.claude/skills/connector-builder/references/checklist.md` correctly at three
sites; the author's rewrite shortened one of them to a bare
`references/checklist.md`. `citation_exists` found nothing at the repo root
and blocked the page — correctly.

That block should have been a one-page problem. It wasn't, because of what
happens next.

## Why a correct block was silently making pages disappear

Under CCE-140's deferral-skip semantics, a PR that keeps getting blocked on
the same page is eventually abandoned and the baseline advances past it. So a
shortened citation didn't stall the run — it made the run report success
while the page was never written at all. Nothing was red anywhere. The gap
was invisible until someone went looking for a page that should exist and
didn't.

You can't fix this by exempting the path. The obvious host-side workaround —
adding the shortened token to `lint.citation_exempt_tokens` — is wrong on its
own terms: the path is genuinely resolvable, and exemptions exist for paths
that are *not* verifiable, never for ones with merely the wrong prefix.
Converting a blocking gate into a silent one just relocates the same failure
mode one layer down.

## What was tried: deterministic repair

The first response was a deterministic repair pass — on any citation that
failed to resolve, suffix-match it against the tracked-file set and, on a
unique match, rewrite the token in the page to the full path. That module
went through four adversarial review rounds, and every round produced a
Critical in the same class, in a different disguise: **the repair moved a
citation into a region `citation_exists` does not re-verify, so a BLOCK
silently became a PASS — and stayed a PASS even after the file the repaired
citation pointed at was deleted.**

- **Round 1.** Uniqueness of a suffix match was treated as proof the token had
  been shortened from that file. It isn't — "does not resolve" is exactly the
  confabulation population `citation_exists` exists to block, and an invented
  path can be just as unique a suffix match as a genuine shortening.
- **Round 2.** The corroboration check added in response to round 1 scanned
  raw text for prior mentions of a candidate path, which counted mentions
  inside fenced code blocks, URLs, and comments — regions `citation_exists`
  deliberately never validates. A path named only inside a fenced example was
  accepted as corroboration for repointing a real citation at it.
- **Round 3.** The exclusion list meant to keep repair off of paths
  `citation_exists` declines to check (exempt tokens, the reserved `example/`
  namespace, gitignored paths) missed two more classes: a candidate the
  extractor's own path grammar can't parse (parens, brackets, spaces), and a
  candidate that lives under the mkdocs build directory.
- **Round 4.** The fix for round 3 — a gate that asked `citation_exists`
  whether a candidate would still resolve if the target file were absent —
  implemented "absent" by resolving the candidate against an **empty temp
  repo root**. That deletes every file, not the one file under test, so the
  probe answered yes for candidates that resolve through unrelated on-disk
  state and admitted them as verified.

Three of the four rounds are the identical shape: repair extends its own
notion of "safe" by asking a question whose answer it computes itself,
instead of asking the one component whose answer actually matters —
`citation_exists`. `superpowers:systematic-debugging` names this pattern:
three or more fixes, each surfacing a new problem in a different place, is
not a sequence of failed hypotheses to keep patching. It's a wrong
architecture.

## The measurement that decided it

Two numbers, both re-derived against the plugin's own tree, ended the
question of whether a fifth round was worth attempting:

- **Zero historical firings.** Across the whole archived production record —
  41 PRs, 19 of them carrying a `cites nonexistent path` block over 15
  distinct blocked citations — not one would have triggered repair. The
  citations that did block already resolve today through the CCE-139/145
  `docs_dir` fallback branch in `citation_exists`; repair never reached them.
- **A green suite with repair disabled.** Turning the repair call site off
  entirely (`if False:` at the production call site) left the test suite
  passing byte-identical to the baseline. Not one test exercised the feature
  through the path production actually uses.

A mechanism that never fired in production and that no test could distinguish
from absent was costing four rounds of adversarial review to keep patching a
recurring class of BLOCK→PASS corruption. The repair was withdrawn.

## Decision: report the likely source, never touch the page

`scripts/citation_repair.py` now does diagnosis only. Its `diagnose()`
function takes the authored page text and returns findings — it has no
parameter to write to and returns nothing but a list of tuples. It never
calls anything that would mutate a file.

For every citation that doesn't resolve and isn't in a class `citation_exists`
already declines to check, `diagnose()` reports the tracked file it was most
likely shortened from, labeled with one of four confidence levels:

| label | what it means |
| --- | --- |
| `candidate_in_run_inputs` | exactly one tracked file is a strict suffix match, and something other than the authoring agent already named it — either the batch's own source files, or a path the page's prior committed version cited and the linter validated |
| `suffix_match_only` | exactly one tracked file is a strict suffix match, with nothing else pointing at it |
| `ambiguous` | several tracked files end with the cited tail (candidates listed up to a cap, then `(+N more)`) |
| `no_candidate` | no tracked file ends with the cited tail at all |

Every label is a description of what was observed, not a verdict — even
`candidate_in_run_inputs` only means "this run was already looking at that
file," not "the page-author meant to cite it." A batch-touched vendored
dependency can earn the top label the moment it's the unique suffix match;
the name was chosen deliberately not to overstate that as corroboration.

`no_candidate` findings are dropped before they reach the run digest.
`citation_exists` already names every one of those paths, with severity, in
its own `lint_block` reason — repeating them under a different key adds
nothing and (since `no_candidate` is the dominant population on a typical
page) would drown the findings that do point at a real file.

## Wiring

`_diagnose_citation_paths` in `scripts/orchestrator_runner.py` runs once per
authored page, after the full authoring loop completes and before the
content-validator dispatch — reading the same finished tree `citation_exists`
is about to check, and reading it before any lint-block revert restores an
edited page to its prior committed version. Findings are appended to the run
digest as `citation_shortening_suspected` lines, always `info_only`: the
page's block is already reported by `lint_block`, so a second, degraded
reason for the same failure would double-count it and cost the run
auto-merge eligibility for a line that's pure advice.

Both the per-page and per-run finding counts are capped, and each cap reports
what it withheld — a `citation_diagnosis_truncated` or
`citation_diagnosis_run_cap` line — because a digest that silently drops
findings past its limit reads as complete when it isn't.

## What stops repair from coming back

Two source-level guards, both AST walks rather than string checks so the
prose warning them off doesn't trip its own alarm, assert that neither module
ever calls a mutating method:

- `test_the_module_never_writes_anything` (`tests/orchestrator/test_citation_repair.py`)
  parses `scripts/citation_repair.py` itself and fails if any call to
  `write_text`, `write_bytes`, `rename`, `unlink`, or similar appears anywhere
  in it.
- `test_the_diagnostic_never_writes_a_page`
  (`tests/orchestrator/test_citation_repair_wiring.py`) does the same over the
  source of `orchestrator_runner._diagnose_citation_paths`.

A future contributor reaching for `Path.write_text` in either module to
"finish the job" trips one of these before the change lands.

## What this costs

A recoverable shortened citation is no longer fixed and re-checked in the
same run. The page still blocks, the PR is still abandoned by the CCE-140
deferral skip, and a human now has to read the digest and either fix the
citation or the prompt guidance that produced it. That's a real regression
against automatic recovery — and it costs nothing that was ever measured in
production, against four demonstrated cases of a block silently becoming an
unverified pass.

## Related

- `scripts/citation_repair.py`
- `scripts/orchestrator_runner.py:_diagnose_citation_paths`
- `tests/orchestrator/test_citation_repair.py`
- `tests/orchestrator/test_citation_repair_wiring.py`
- `docs/superpowers/specs/2026-08-21-cce141-citation-path-repair-design.md`
