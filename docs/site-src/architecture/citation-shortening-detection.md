---
description: 'Documents architecture citation shortening detection: The docs-agent now detects citations that page-author shortened into an unresolvable form (e.g. dropping a directory prefix) and reports them as an info-only digest line, instead of attempting to repair them. A prior repair capability (scripts/citation_repair.py rewriting the page text) was built, reviewed across four rounds, and withdrawn: each round moved the shortened citation into a region citation_exists does not verify, turning a correct BLOCK into a silent PASS even after the cited file was deleted. Detection now runs via _diagnose_citation_paths in orchestrator_runner.py, after the authoring loop and before the lint-block revert, so it inspects the same finished tree citation_exists checks. Findings are bounded per-page and per-run and classified into four confidence labels (candidate_in_run_inputs, suffix_match_only, ambiguous, no_candidate), with only the first three surfaced in the digest.'
source_files:
  - .engineering-docs-agent/config.yml
  - CLAUDE.md
  - docs/superpowers/plans/2026-08-21-cce141-citation-path-repair.md
  - docs/superpowers/plans/2026-08-21-cce141-corroborated-repair.md
  - docs/superpowers/specs/2026-08-21-cce141-citation-path-repair-design.md
  - scripts/citation_repair.py
  - scripts/orchestrator_runner.py
last_reviewed: '2026-09-30'
status: draft
---
# Citation shortening detection

`page-author` sometimes shortens a citation that already resolves. A committed page cited `.claude/skills/connector-builder/references/checklist.md` at three sites. The rewrite emitted bare `references/checklist.md`. `citation_exists` resolves from the repo root, finds nothing, and blocks the page.

That block is correct. The problem is what follows it. After the deferral skip abandons a repeatedly blocked PR, the page is never written and nothing is red. The run reports success and the baseline moves on.

The orchestrator does not fix these citations. It reports them.

## What runs

`citation_repair.diagnose()` in `scripts/citation_repair.py` takes page text and returns `[(cited, candidate, confidence)]`. It never writes to a page, and the module has no write call. Do not add one.

For each citation in the text, it skips the citation when any of these hold:

- The citation resolves.
- It is an absolute path outside the repo.
- `check_path` would decline to check it: an exempt token, a reserved `example/` prefix, or a gitignored path.

Everything else is matched against tracked files. A tracked file is a candidate when the cited path is a strict, segment-boundary suffix of it. `references/checklist.md` matches the full `.claude/skills/...` path. `erences/checklist.md` matches nothing.

The module imports its resolution helpers from `scripts/lint/citation_exists.py` rather than reimplementing them. Detection has to agree with the linter on what a citation is and what resolves.

## Where it sits in the pipeline

`_diagnose_citation_paths` in `scripts/orchestrator_runner.py` calls `diagnose`. It runs after the whole authoring loop and above the lint-block revert. It reads the same finished tree `citation_exists` is about to read. Run it earlier or later and the two disagree about which citations exist.

## Confidence labels

`diagnose` returns four labels. Each describes an observation, not a verdict.

| Label | Meaning | In digest |
| --- | --- | --- |
| `candidate_in_run_inputs` | Exactly one suffix match, and an input to this run other than the authoring agent already named that file. | Yes |
| `suffix_match_only` | Exactly one suffix match, resting on the string match alone. | Yes |
| `ambiguous` | Several tracked files end with the tail. Candidates are listed up to a cap, then `(+N more)`. | Yes |
| `no_candidate` | No tracked file ends with the tail. | No |

`candidate_in_run_inputs` is weaker than it sounds. Run inputs come from two places: paths the page's prior commit cited and the linter validated, and the batch's changed-file list. The second comes from the `source-collector` subagent, which is an LLM. It is not orchestrator-authoritative. The only hard bound is that the candidate must be a tracked file.

The label was called `corroborated` until it was renamed. That name read as confirmed while the status came from batch membership alone.

`no_candidate` is dropped from the digest. Its own evidence says the token is not a shortening of anything in the repo, and `lint_block` already names those paths with severity.

## Digest behavior

The findings are `info_only`. They never flip `partial` and do not gate auto-merge.

The digest is bounded twice, per page and per run. Each cap reports what it withheld. Without the run-level cap, the digest joins every reason unconditionally. A handful of pages with many findings each would pass GitHub's 65,536-byte PR-body limit.

One malformed token costs only itself. `diagnose` catches `OSError` per citation, because pathlib re-raises errors such as ENAMETOOLONG from an existence check. Without the catch, one long token would discard every earlier finding on the page.

## Known blind spot

The resolution check accepts an untracked on-disk sibling from the same run. Candidate search iterates tracked files only. A citation shortened to a page this run just wrote will therefore name a tracked decoy elsewhere in the tree. Nothing acts on the label, so the cost is one misleading suggestion. A test pins this behavior as known.

Under an `archive-index` section, `citation_exists` is downgraded to `warn` and the revert never fires. The page ships with its shortened citation, and the digest line is the only signal.

## Why this page's example paths are exempt

This page has to name the evidence. The full `.claude/skills/connector-builder/references/checklist.md` path belongs to another repository. `references/checklist.md` is the shortened form, and its non-resolution is the whole finding. `erences/checklist.md` is the over-shortened form that the boundary rule must reject. None of the three resolves in this repo, and that is the point of the page.

`citation_exists` would block them like any other unresolvable citation. That happened on nightly 36245832365. The page was the last one owed by PR #241, the oldest admitted PR. Its block kept the cursor prefix empty, the run partial and auto-merge skipped, so 13 authored pages were discarded.

The host config now lists the three tokens under `lint.citation_exempt_tokens` in `.engineering-docs-agent/config.yml`. The match is on the exact token, so a nearby path that is also unresolvable still blocks. The plugin's own defaults in `scripts/lint/citation_exists.py` separately exempt a few generic example tokens that pages about citation linting quote.

If you add an example path to this page, use a placeholder form such as `scripts/<name>.py`. A concrete unresolvable path needs its own exemption entry, and the prose that explains the entry can mint the next blocked token.

## Why there is no repair

A deterministic repair was built and withdrawn. Four review rounds produced four critical findings, all of one class. The repair moved a citation into a region `citation_exists` does not verify. A BLOCK became a silent PASS, and the pointer stayed unchecked even after the target file was deleted.

Two measurements settled it:

- Across the archived record, 19 PRs carried 15 distinct blocked citations. None had a unique suffix match, so the repair would have fired zero times.
- Disabling the feature at its production call site left the test suite unchanged.

The lesson is about mutation. The set of regions the linter does not verify is open and found one at a time, so it cannot be enumerated from inside the module doing the rewriting. A page that is never rewritten cannot be corrupted that way.

What was given up is the automatic rescue. A recoverable shortened citation now blocks the page, and a human reads the digest. That cost nothing that was measured.

See `docs/superpowers/specs/2026-08-21-cce141-citation-path-repair-design.md` for the design history.
