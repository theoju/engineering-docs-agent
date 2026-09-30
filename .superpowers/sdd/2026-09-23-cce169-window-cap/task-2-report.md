# Task 2 report — the cut, the `held_back` union, and the reason (CCE-169)

**Status:** DONE_WITH_CONCERNS (one brief error found and corrected; see §4)
**Branch:** `feat/CCE-169-window-cap` in `/Users/theo/Projects/eda-cce181`
**Base:** `97c84ae` (Task 1)
**Commit:** see §6

---

## 1. Edits and where they landed

All anchors were found by quoted content, as instructed. The brief's line
numbers were stale by roughly +25 (Task 1's insertions); actual landing sites
below.

### `scripts/orchestrator_runner.py`

| #   | Brief step                                | Brief line    | Actual                        | Anchor line quoted next to the insertion                                                                                                   |
| --- | ----------------------------------------- | ------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Step 3 — the cut                          | after `:2447` | `:2477-2493`                  | inserted between the `_order_prs_oldest_first` call's closing `        )` and `        jira_issues = sources.get("jira_issues", []) or []` |
| 2   | Step 4 — the reason                       | after the cut | `:2494-2507`                  | immediately after `            prs = prs[:_window_cap]`, still above `jira_issues = ...`                                                   |
| 3   | Step 5 — window-snapshot comment          | `:2470-2471`  | `:2530-2535`                  | replaced the two comment lines sitting directly above `        window_prs = list(prs)`                                                     |
| 4   | Step 6 — `held_back` union                | `:3278-3280`  | `:3344-3353`                  | the `held_back = (` statement directly above `        still_deferred = _still_deferred`                                                    |
| 5   | Step 7 — cursor log line                  | `:3300-3313`  | fmt `:3383-3384`, arg `:3388` | the `emit_log(` whose format string begins `"cursor: admitted=[%s] ..."`                                                                   |
| 6   | Step 8 — `next_deferral_counts` docstring | `:864-868`    | `:889-897`                    | the `- not in this window at all → carried forward unchanged.` bullet                                                                      |

Diffstat: `scripts/orchestrator_runner.py | +56 -8`.

Every inserted block is byte-for-byte the brief's text. The only judgement call
was placement, and all six anchors were unambiguous.

**Position verification for the cut** (the brief's three constraints, each
checked against the tree rather than assumed):

- _After the ordering call_ — the insertion is textually below
  `prs = _order_prs_oldest_first(...)`'s closing paren. ✓
- _Before `window_prs = list(prs)`_ — that assignment is at `:2536`, 44 lines
  below the cut. ✓
- _Before the summarize loop_ — `for i, pr in enumerate(prs):` is at `:2557`,
  64 lines below the cut. ✓
- _Below the `state["current_run"] = {...}` literal_ (the CCE-127 stub hazard) —
  that literal's `"head_sha": head_sha,` is at `:2356`, 121 lines **above** the
  cut, so `add_partial`'s stub cannot be overwritten. ✓

`window_capped` is bound by straight-line code between the cut and both of its
consumers (`held_back` at `:3344`, `emit_log` at `:3388`); there is no branch
that reaches either without passing through the cut, and no `finally` referencing
it. Checked by reading the enclosing block structure (`try:` at `:2408`,
`if sources is None: / else:` at `:2438/:2444`, `if isinstance(...)` at `:2459`)
— the cut sits at the same 8-space level as its consumers with no intervening
conditional.

### `tests/orchestrator/test_window_cap.py`

Appended the second half (the brief's Step-1 block) after
`test_window_cap_tolerates_a_malformed_run_block`. The file was **appended to**,
not recreated: the module header, imports, `FAKES_MULTI` and all four Task-1
resolver tests are untouched. +202 lines.

Two assertions inside that block were corrected — see §4.

### `tests/orchestrator/test_classification_coverage.py`

Both inline literals in the one statement bumped `46 -> 47` (`:151-152` in the
brief's numbering; actually `:165-168` after the docstring grew), and the audit
paragraph appended to the test's docstring, newest-last, after the `45 -> 46`
CCE-181 entry. +20 -11 (the `-11` is the re-flow of the two-line assert message).

---

## 2. TDD steps, commands, and counts

All pytest invocations were prefixed with `rtk proxy` (the shell proxy rewrites
bare `pytest`; the caller flagged this).

### Step 2 — RED

```
cd /Users/theo/Projects/eda-cce181 && rtk proxy python3 -m pytest tests/orchestrator/test_window_cap.py -v
```

**4 failed, 5 passed in 5.48s.**

The brief predicted the key test would fail and the two no-op tests would
already pass. The key test failed exactly as predicted; the two no-op tests
**also** failed, for an unrelated reason that turned out to be a brief error
(§4).

Actual red-step failure text for the load-bearing test
(`test_a_capped_run_advances_to_the_cap_boundary_and_says_so`), quoted verbatim:

```
        rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
        assert rc == 0
        written = json.loads(state_path.read_text())
        advance = written["last_successful_run"]["head_sha"]
>       assert advance == c2, written["last_successful_run"]
E       AssertionError: {'completed_at': '2026-09-23T22:00:23.389218+00:00', 'head_sha': '27dc94d7b33d37539472ec809026e10815f0ca09'}
E       assert '27dc94d7b33d...6e10815f0ca09' == '7d299e9e44a1...30e0865333d91'
E
E         - 7d299e9e44a190f63a3244c4abc30e0865333d91
E         + 27dc94d7b33d37539472ec809026e10815f0ca09

tests/orchestrator/test_window_cap.py:148: AssertionError
----------------------------- Captured stderr call -----------------------------
cursor: admitted=[1, 2, 3] deferred=[none] held_back=[none] skipped=[none] baseline_age=unknown stall_window=4d
```

**This is the non-vacuous red the brief's ambiguity #3 demanded.** The captured
log line `admitted=[1, 2, 3]` proves the fixture produced a 3-PR window against
a cap of 2 — the cut was genuinely absent, not the window genuinely sub-cap.
`held_back=[none]` is the CCE-151 defect the test exists to guard: the walk was
never entered and the `else` branch advanced to full window HEAD.

And for `test_a_capped_pr_does_not_accrue_a_deferral_count`, the erasure the
brief describes, observed directly:

```
>       assert written.get("deferral_counts", {}).get("unknown/unknown#3") == 2, (
            written.get("deferral_counts")
        )
E       AssertionError: None
E       assert None == 2
E        +  where None = <built-in method get of dict object at 0x7fdf786b9480>('unknown/unknown#3')
E        +    where <built-in method get of dict object at 0x7fdf786b9480> = {}.get
```

The seeded count of 2 was **deleted**, not incremented — `next_deferral_counts`
took the pop branch, exactly as the brief's Step-3 reasoning predicted. The
`unknown/unknown#3` key was correct as written (conftest's autouse
`_pin_repo_slug`); no adjustment needed.

`test_a_capped_pr_at_threshold_is_not_abandoned` passed vacuously at red, which
the brief allowed for.

### Step 9 — GREEN (window-cap file)

```
cd /Users/theo/Projects/eda-cce181 && rtk proxy python3 -m pytest tests/orchestrator/test_window_cap.py -v
```

**9 passed in 6.35s.** Matches the brief's expectation.

The green run's captured log now reads
`cursor: admitted=[1, 2] deferred=[none] capped=[3] held_back=[3] skipped=[none] ...`
on the capped test — the Step-7 `capped=[…]` column doing its job, and PR 3
appearing in `held_back` without appearing in `deferred`.

### Step 11 — full suite

```
cd /Users/theo/Projects/eda-cce181 && rtk proxy python3 -m pytest
```

**1638 passed, 4 skipped in 261.00s.**

|         | baseline (`97c84ae`) | after | delta  |
| ------- | -------------------- | ----- | ------ |
| passed  | 1633                 | 1638  | **+5** |
| skipped | 4                    | 4     | **0**  |
| failed  | 0                    | 0     | 0      |

+5 is exactly the five tests appended in Step 1. **The skip count did not move**,
so nothing regressed into an `importorskip` and no previously-running test
stopped running.

---

## 3. Global constraints — discharged

- **Reason string** is the plain literal
  `held_back_window_capped: {held} of {total} PRs held for a later run (cap {cap})`,
  with `{total}` reconstructed as `len(prs) + len(window_capped)` post-slice.
  Asserted as a fully rendered string by list membership:
  `"held_back_window_capped: 1 of 3 PRs held for a later run (cap 2)"`. Not
  routed through `_rsn`. `degraded=True`. ✓
- **`_MERGE_VETO_REASON_PREFIXES` untouched** — still `("app_token_unavailable",)`.
  Verified: it appears in the diff zero times. ✓
- **Routing, all three rows:**
  - into `held_back` — pinned by the `advance == c2` assertion (the cursor could
    not stop at the cap boundary otherwise) and visible in the log line;
  - out of `window_prs` — pinned by the deferral-count test, which is the
    erasure guard;
  - out of `_deferred_all` — pinned by the at-threshold test (count 3 against a
    default threshold of 3, not skipped). ✓
- **stdlib only.** The test helper's `subprocess` import is the only addition
  and matches `test_cursor_backed_merge.py`. ✓
- **TDD** — red observed and quoted above before any implementation line was
  written. ✓
- **Branch** — all work on `feat/CCE-169-window-cap`; `main` untouched. ✓

---

## 4. What the brief got wrong

**One substantive error, in the Step-1 test block: both no-op tests assert the
wrong advance SHA.**

The brief writes, in `test_window_pr_cap_zero_is_a_true_no_op` and
`test_a_sub_cap_window_is_untouched`:

```python
    assert written["last_successful_run"]["head_sha"] == c3, written[
        "last_successful_run"
    ]
```

with the docstring "the advance reaches the newest PR merge exactly as an
uncapped run would."

That is false, and it is false about _today's_ code, not about anything this
task changes. When nothing is held back, CCE-151's walk is not entered and
control reaches

```python
        else:
            advance_sha = state["current_run"]["head_sha"]
```

(`scripts/orchestrator_runner.py`, the `else` of `if time_truncated or held_back:`),
where `current_run["head_sha"]` is assigned from `git rev-parse HEAD` at
`:2337-2344`. The fixture — copied from `test_cursor_backed_merge._seed_merge_host`
— deliberately creates **four** commits and maps only `shas[:3]` onto PRs, so
HEAD is `c4`, a trailing non-PR commit. An uncapped clean run therefore advances
to `c4`, never to `c3`.

Both tests failed at the red step on this, and would have failed at the green
step too; the implementation has nothing to do with it. Confirmed by reading the
`else` branch and the `head_sha` assignment rather than by guessing from the
diff.

**Correction applied:** both assertions now compare against
`_git(tmp_path, "rev-parse", "HEAD")`, with an added `!= c2` guard so the test
still distinguishes "the cap did nothing" from "something stopped the cursor at
a boundary", and a docstring paragraph recording why `c3` is wrong. This is
strictly stronger than the brief's intent — asserting full window HEAD is the
real statement of "untouched", whereas `== c3` would have been asserting a
cursor-backed advance on a run that never took one.

Nothing else in the brief was wrong. The `unknown/unknown#3` key, the config
`replace`-not-append warning, the `len(prs) + len(window_capped)` note, the
CCE-127 stub-hazard clearance, and all six anchor descriptions were accurate.

Minor, not an error: the brief's line numbers were stale by +25 as the caller
said; every anchor was located by content without difficulty.

---

## 5. Concerns

1. **(Low, for the reviewer's awareness) The corrected no-op assertions are
   mine, not the brief's.** They are the two assertions in this task that were
   not written by the plan author. If the plan intended the fixture to have no
   `c4` — i.e. to assert a _cursor-backed_ advance to the newest PR merge — then
   the helper itself is what needs changing, not the assertion. I judged not: the
   helper's docstring explicitly explains why `c4` exists ("so the newest PR
   merge is never HEAD"), so removing it would break the capped test's
   `advance != HEAD` independence, which is the more valuable property.

2. **(Low) Digest/PR-body PR counts now report the admitted count, not the
   window count.** Anything downstream that says "N PRs" is counting `prs` after
   the slice. The held PRs are named only in the `held_back_window_capped`
   reason and the `capped=[…]` log column. That is the intended design (the
   reason is the run's only signal), but it means an operator reading only the
   PR-body headline sees a smaller number than the window contained. Task 3 may
   want to surface this; flagging rather than acting, since it is out of scope.

3. **(Low, inherited from Task 1, not introduced here) `resolve_window_cap`
   ends in a bare `int(val)`.** A host writing `window_pr_cap: "ten"` raises
   `ValueError` out of `run` rather than degrading. Its siblings in the file have
   the same shape, so this is consistent rather than novel.

   > **CORRECTED in review round 1 — the rest of this paragraph as originally
   > written was FALSE.** It read: "and the cut itself is safe (`if _window_cap
and len(prs) > _window_cap` handles 0, and a negative cap would slice to
   > empty admitted + everything capped, which is loud)." A negative cap did
   > the **opposite**: `_window_cap` is truthy and `len(prs) > -1` is always
   > true, so `prs[-1:]` capped only the **newest** PR and `prs[:-1]` admitted
   > every other one, reporting `(cap -1)` — quiet, and on the wrong end of the
   > window. I asserted the slice semantics instead of evaluating them. Fixed
   > in the same round by changing the condition to `if _window_cap > 0 and
len(prs) > _window_cap:`; see Finding 2 in the fix report below. The
   > `int(val)` concern about non-integer strings stands and remains out of
   > scope for Task 2.

4. **(Informational) No test pins the `capped=[…]` log column.** Step 7's change
   is observable only as captured stderr in the tests that happen to print it.
   The CCE-175 log line has no assertions today either, so this matches the
   existing convention — but it does mean a future refactor could drop the column
   silently.

---

## 6. Commit

Subject contains `CCE-169`; body is the brief's Step-12 message verbatim, with a
short added paragraph recording the two corrected test assertions so the
divergence from the brief is in the permanent record and not only in this file.
Trailer: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

Files: `scripts/orchestrator_runner.py`,
`tests/orchestrator/test_window_cap.py`,
`tests/orchestrator/test_classification_coverage.py`.

**Commit SHA:** `db62723`. Tree clean, branch `feat/CCE-169-window-cap`.

Note: `.superpowers/sdd/` is gitignored in this repo, so this report is **not**
in the commit — it exists only at the path the task specified. If it is evidence
for the review decision it needs a home in a tracked location before this
worktree goes away (CLAUDE.md, "Capture throwaway analysis the day you produce
it").

---

# Fix report — review round 1 of max 5

Both findings accepted as correct and fixed. No pushback on either.

## Finding 1 (Important) — `test_a_capped_pr_at_threshold_is_not_abandoned` did not discriminate

**Accepted in full.** The reviewer's trace is right and I verified it empirically
rather than by reading (below). The test asserted the _absence of a skip record_,
and in the counterfactual world no skip record is ever written — so the assertion
passed on an empty list while the baseline advanced past PR 3 and stranded it.

**Fix** — `tests/orchestrator/test_window_cap.py`, in that test:

```python
    # The assertion that discriminates.
    assert written["last_successful_run"]["head_sha"] == c2, written[
        "last_successful_run"
    ]
```

The existing `skipped_prs` assertion is kept, as instructed, and is now ordered
**first** with a comment saying why — so that running the test against the
counterfactual demonstrates the weak assertion passing while the strong one
fails, in a single run. A docstring paragraph records the full trace
(`held_back == {3} - {3} == set()` → `else` branch → c4 → `_crossed == {1, 2}`
filters PR 3 out of the `if _skipped_prs:` loop → `merge_skipped_pr_records`
returns early → the `skipped_prs` key is never created).

### Discrimination proof (the counterfactual, run for real)

I temporarily injected the reviewer's hypothetical into the live tree —
`_deferred_all = list(admission_deferred) + list(window_capped) + [...]` — and
ran the single test:

```
cd /Users/theo/Projects/eda-cce181 && rtk proxy python3 -m pytest "tests/orchestrator/test_window_cap.py::test_a_capped_pr_at_threshold_is_not_abandoned"
```

```
        assert rc == 0
        skipped = written.get("skipped_prs", [])
        assert not [s for s in skipped if "#3" in json.dumps(s)], skipped
>       assert written["last_successful_run"]["head_sha"] == c2, written[
E       AssertionError: {'completed_at': '2026-09-23T22:20:11.268113+00:00', 'head_sha': '9c34c649d2baa1894d19d427200ac2295160e8e4'}
E       assert '9c34c649d2ba...ac2295160e8e4' == 'b45f3b24db04...8ab2f77e17374'
E
E         - b45f3b24db045d689542d629ef58ab2f77e17374
E         + 9c34c649d2baa1894d19d427200ac2295160e8e4
tests/orchestrator/test_window_cap.py:223: AssertionError
cursor: admitted=[1, 2] deferred=[3] capped=[3] held_back=[none] skipped=[3] baseline_age=unknown stall_window=4d
============================== 1 failed in 1.16s ===============================
```

Both halves of the reviewer's claim are confirmed by this one run:

- **The record assertion is non-discriminating.** Execution reached the line
  _after_ it, so `skipped_prs` contained no `#3` record even though
  `skipped=[3]` — the state key was never written, exactly as traced.
- **The advance assertion discriminates.** It failed, on full window HEAD (c4)
  instead of c2.
- The captured log is the trace made visible: `capped=[3]` **and**
  `deferred=[3]` **and** `skipped=[3]`, with `held_back=[none]` — the
  subtraction that my cut's comment calls "a no-op for them" had stopped being
  one.

The counterfactual was then **fully reverted**; `git diff` on
`scripts/orchestrator_runner.py` shows only the Finding-2 change (+8 −1),
confirmed before the covering runs below.

## Finding 2 (Minor) — a negative `window_pr_cap` inverted the cut

**Accepted in full, including the criticism of my report.** My concern #3 in the
original report claimed a negative cap "would slice to empty admitted +
everything capped, which is loud." That is **false**. `prs[-1:]` is the last
element and `prs[:-1]` is everything but the last, so `window_pr_cap: -1`
admitted every PR _except the newest_ and held the newest back, reporting
`(cap -1)`. Quiet, and on the wrong end of the window. The original paragraph is
corrected in place above (§5, concern 3), since a measured-false claim left
standing is the CCE-127 failure mode this repo already paid for.

**Fix** — `scripts/orchestrator_runner.py`, the cut's condition:

```python
        if _window_cap > 0 and len(prs) > _window_cap:
```

with a comment recording why it is `> 0` and not truthiness, so the next reader
does not "simplify" it back. A negative cap now behaves as the documented
unlimited opt-out, identically to 0. `resolve_window_cap` itself is untouched —
clamping belongs to Task 1's resolver if anyone wants it there, and the cut is
the site that was actually unsafe.

## Deferred items — not touched, as instructed

The `!= c2` guard, the no-op tests reading HEAD post-run, and the unpinned
`capped=[…]` log column were all left exactly as they are.

## Tests

**Covering tests for the amended code**, per the review instruction — the
window-cap file for Finding 1, plus the three CCE-144/151 classification guards
for Finding 2 since it changes the cut's condition:

```
cd /Users/theo/Projects/eda-cce181 && rtk proxy python3 -m pytest tests/orchestrator/test_window_cap.py tests/orchestrator/test_time_budget.py tests/orchestrator/test_deferral_skip.py tests/orchestrator/test_cursor_backed_merge.py
```

```
tests/orchestrator/test_window_cap.py .........                          [ 13%]
tests/orchestrator/test_time_budget.py ...................               [ 42%]
tests/orchestrator/test_deferral_skip.py ............................... [ 89%]
.                                                                        [ 90%]
tests/orchestrator/test_cursor_backed_merge.py ......                    [100%]

============================= 66 passed in 32.94s ==============================
```

**Full suite:**

```
cd /Users/theo/Projects/eda-cce181 && rtk proxy python3 -m pytest
```

```
================= 1638 passed, 4 skipped in 257.98s (0:04:17) ==================
```

|         | round-1 baseline | after fixes | delta |
| ------- | ---------------- | ----------- | ----- |
| passed  | 1638             | 1638        | 0     |
| skipped | 4                | 4           | **0** |
| failed  | 0                | 0           | 0     |

Pass count unchanged (no tests added — Finding 1 strengthened an existing test
rather than adding one) and **the skip count did not move**, so nothing
regressed into an `importorskip`.

## Concerns after this round

None on the two findings. One standing note, unchanged from round 1 and still
out of scope: `resolve_window_cap` (Task 1) still ends in a bare `int(val)`, so
`window_pr_cap: "ten"` raises `ValueError` out of `run` rather than degrading.
The cut is now safe against every _integer_ value including negatives; a
non-integer string is a separate, loud failure in Task 1's resolver.
