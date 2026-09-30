# Task 4 report — retire two false justifications

## Re-measurement (run before editing, independently of the brief's numbers)

```
$ cd /Users/theo/Projects/eda-cce181
$ grep -c "time_budget_seconds" tests/orchestrator/test_deferral_skip.py
10
$ grep -n "time_budget" tests/orchestrator/test_deferral_skip.py
294:        time_budget_seconds=100,
354:        time_budget_seconds=100,
416:        time_budget_seconds=100,
465:        time_budget_seconds=100,
479:    rc = orun.run(tmp_path, dry_run_dir=FAKES_MULTI, no_pr=True, time_budget_seconds=0)
537:        time_budget_seconds=100,
589:    rc = orun.run(repo, dry_run_dir=fakes, no_pr=True, time_budget_seconds=0)
636:        time_budget_seconds=100,
715:        time_budget_seconds=100,
776:        time_budget_seconds=100,
```

All 10 matches are the `time_budget_seconds=` config kwarg. Zero matches assert
a `time_budget_*` reason string.

```
$ grep -rl "time_budget" docs/runbooks/ || echo "confirmed: no runbook mentions it"
confirmed: no runbook mentions it
```

```
$ grep -rn '"time_budget_[a-z_]*:[^"]*" in' tests/ | wc -l
       5
$ grep -rn '"time_budget_[a-z_]*:[^"]*" in' tests/
tests/orchestrator/test_time_budget.py:140:        "time_budget_exceeded: admitted 2/3" in r for r in cr["partial_reasons"]
tests/orchestrator/test_time_budget.py:161:        "time_budget_exceeded: admitted 1/3" in r for r in cr["partial_reasons"]
tests/orchestrator/test_time_budget_authoring.py:67:        "time_budget_exceeded: authored 1/3 page batches" in r
tests/orchestrator/test_time_budget_authoring.py:96:        "time_budget_exceeded: fact-checked 0/3 pages" in r
tests/orchestrator/test_time_budget_authoring.py:124:        "time_budget_exceeded: gap-checked 0/3 PRs" in r for r in cr["partial_reasons"]
```

```
$ grep -rln "time_budget_no_advance\|time_budget_exceeded" docs/site-src/ | wc -l
       5
$ grep -rln "time_budget_no_advance\|time_budget_exceeded" docs/site-src/
docs/site-src/whats-new.md
docs/site-src/archive/2026-08-14-cce144-blind-run-detection.md
docs/site-src/archive/2026-08-17-cce152-pr-boundary-authoring-cut.md
docs/site-src/archive/2026-06-10-cce114-time-budget-fanout-fix.md
docs/site-src/architecture/orchestrator.md
```

**Conclusion: my measurement agrees with the brief's on every count** — 10
kwarg-only matches (no reason-string assertion), zero runbook hits, exactly
5 pinned prefixes in `test_time_budget.py`/`test_time_budget_authoring.py`,
exactly 5 published `docs/site-src/` pages. Both original claims
("`test_deferral_skip.py` asserts those exact strings" and "the CCE-109/
CCE-140 runbooks tell operators to grep for them") are false. Proceeded to
edit using the brief's exact replacement text (no numbers had drifted).

## Site 1 — `scripts/orchestrator_runner.py` (`_rsn` comment)

Found by content at line 3424 (not 3344-3351 as the brief's stale line
numbers suggested — the file has grown since the brief was drafted; located
via `grep -n "CCE-151: the walk now runs" scripts/orchestrator_runner.py`).

**Before:**

```python
            # CCE-151: the walk now runs for two different causes, so the
            # reason has to name the one that actually applies. A run that was
            # never truncated reporting `time_budget_no_advance_*` would be a
            # false statement in the operator digest — and the digest is the
            # only place most of these are ever read. The `time_budget_` family
            # is preserved verbatim on the truncated path: those exact strings
            # are asserted by test_time_budget.py and test_deferral_skip.py,
            # and are what the CCE-109/CCE-140 runbooks tell operators to grep.
```

**After:**

```python
            # CCE-151: the walk now runs for two different causes, so the
            # reason has to name the one that actually applies. A run that was
            # never truncated reporting `time_budget_no_advance_*` would be a
            # false statement in the operator digest — and the digest is the
            # only place most of these are ever read. The `time_budget_` family
            # is preserved verbatim on the truncated path.
            #
            # CCE-169 retired the two reasons this comment used to give, both
            # measurably false: `test_deferral_skip.py` asserts no
            # `time_budget_*` reason string at all (its only matches are the
            # `time_budget_seconds=` kwarg), and no runbook mentions
            # `time_budget` — `grep -rl time_budget docs/runbooks/` is empty.
            # The real reasons: `test_time_budget.py` and
            # `test_time_budget_authoring.py` pin five distinct
            # `time_budget_exceeded:` prefixes including their counts, and the
            # family is quoted verbatim in five PUBLISHED pages
            # (docs/site-src/architecture/orchestrator.md, whats-new.md, and
            # three archive pages). A rename silently falsifies the published
            # docs, which `citation_exists` cannot catch — these are prose
            # strings, not paths.
```

## Site 2 — `CLAUDE.md` (CCE-151 entry, trap 4)

Located by `grep -n "CCE-151" CLAUDE.md` → line 77 (single bullet). Edited
surgically with the Edit tool — `git diff --stat` confirms exactly one line
changed in `CLAUDE.md` (no reflow of surrounding text).

**Before (substring):**

> The `time_budget_*` family must stay byte-identical — `test_time_budget.py` / `test_deferral_skip.py` assert those exact strings and the CCE-109/CCE-140 runbooks tell operators to grep for them.

**After:**

> The `time_budget_*` family must stay byte-identical — but **not for the reason this entry gave until CCE-169**: `test_deferral_skip.py` asserts no `time_budget_*` reason string at all (only the `time_budget_seconds=` kwarg), and no runbook mentions `time_budget` (`grep -rl time_budget docs/runbooks/` is empty). The real reasons are that `test_time_budget.py` / `test_time_budget_authoring.py` pin five distinct `time_budget_exceeded:` prefixes **including their counts**, and that the family is quoted verbatim in five **published** pages (`docs/site-src/architecture/orchestrator.md`, `whats-new.md`, three archive pages) — a rename silently falsifies the published docs, and `citation_exists` cannot catch it because these are prose strings, not paths.

## Substituted justification

The false claims (test_deferral_skip.py assertion; runbook grep instruction)
were replaced with the true, measured ones: (1) `test_time_budget.py` and
`test_time_budget_authoring.py` pin 5 distinct `time_budget_exceeded:`
prefixes including their exact counts (e.g. `admitted 2/3`, `authored 1/3
page batches`), so a rename breaks those 5 assertions; and (2) the
`time_budget_*` strings are quoted verbatim in 5 published `docs/site-src/`
pages, and `citation_exists` cannot catch a silent rename there because these
are prose strings, not file-path citations.

## Suite verification

```
$ cd /Users/theo/Projects/eda-cce181 && python3 -m pytest -q
...
1639 passed, 4 skipped in 265.32s (0:04:25)
```

Matches the stated baseline exactly (1639 passed, 4 skipped) — no change in
pass or skip counts, as expected for a prose-only change.

## Diff scope

`git diff --stat` after both edits, before commit:

```
CLAUDE.md                      |  2 +-
scripts/orchestrator_runner.py | 18 +++++++++++++++---
```

Only the two intended files touched; no other `.py` files, no test files, no
reason strings changed.

## Commit

`564189e32946dbb2139252a692caad77f5e28b16` on branch
`feat/CCE-169-window-cap` — subject: `docs: retire two false justifications
for the time_budget_* strings — CCE-169`. Working tree clean after commit.
