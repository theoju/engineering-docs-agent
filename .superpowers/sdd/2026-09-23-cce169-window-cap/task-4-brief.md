## Task 4: Correct the two stale justifications

Pre-existing falsehoods, not caused by this change, but in the exact code region this change touches and in the `CLAUDE.md` entry an implementer reads first. Separate task because a reviewer could approve the cap and reject this, and because it carries no test.

**Files:**

- Modify: `scripts/orchestrator_runner.py:3344-3351` (the `_rsn` comment)
- Modify: `CLAUDE.md` (the CCE-151 entry's trap 4)

**Interfaces:** none — prose only. No code behaviour changes.

### The measurement

The comment above `_rsn` makes two supporting claims. Both are false:

```bash
cd ~/Projects/eda-cce181
grep -n "time_budget" tests/orchestrator/test_deferral_skip.py   # only `time_budget_seconds=` kwargs
grep -rl "time_budget" docs/runbooks/                            # no output at all
```

The conclusion — keep the `time_budget_*` strings byte-identical — is still right, for two reasons the false ones displaced:

```bash
grep -rn '"time_budget_[a-z_]*:[^"]*" in' tests/   # 5 pinned prefixes incl. counts
grep -rln "time_budget_no_advance\|time_budget_exceeded" docs/site-src/   # 5 published pages
```

- [ ] **Step 1: Re-run the measurements before editing**

```bash
cd ~/Projects/eda-cce181
grep -c "time_budget_seconds" tests/orchestrator/test_deferral_skip.py
grep -rl "time_budget" docs/runbooks/ || echo "confirmed: no runbook mentions it"
grep -rn '"time_budget_[a-z_]*:[^"]*" in' tests/ | wc -l                          # expect 5
grep -rln "time_budget_no_advance\|time_budget_exceeded" docs/site-src/ | wc -l   # expect 5
```

If any count has drifted from what the replacement text below asserts, update that text to the measured number. Shipping a second false justification in the act of retiring the first is the exact failure this task exists to close.

- [ ] **Step 2: Correct the `_rsn` comment**

At `scripts/orchestrator_runner.py:3344-3351`, replace:

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

with:

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

- [ ] **Step 3: Correct the same sentence in `CLAUDE.md`**

The CCE-151 entry's trap 4 carries the identical false claim — it is where the draft of the CCE-169 spec copied it from. Find this exact substring:

```
The `time_budget_*` family must stay byte-identical — `test_time_budget.py` / `test_deferral_skip.py` assert those exact strings and the CCE-109/CCE-140 runbooks tell operators to grep for them.
```

Replace with:

```
The `time_budget_*` family must stay byte-identical — but **not for the reason this entry gave until CCE-169**: `test_deferral_skip.py` asserts no `time_budget_*` reason string at all (only the `time_budget_seconds=` kwarg), and no runbook mentions `time_budget` (`grep -rl time_budget docs/runbooks/` is empty). The real reasons are that `test_time_budget.py` / `test_time_budget_authoring.py` pin five distinct `time_budget_exceeded:` prefixes **including their counts**, and that the family is quoted verbatim in five **published** pages (`docs/site-src/architecture/orchestrator.md`, `whats-new.md`, three archive pages) — a rename silently falsifies the published docs, and `citation_exists` cannot catch it because these are prose strings, not paths.
```

- [ ] **Step 4: Run the full suite**

```bash
cd ~/Projects/eda-cce181 && python3 -m pytest
```

Expected: all pass. This task changes no behaviour, so any failure means a comment edit broke syntax or indentation.

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/eda-cce181
git add scripts/orchestrator_runner.py CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: retire two false justifications for the time_budget_* strings — CCE-169

The comment above `_rsn` and the identical sentence in CLAUDE.md's CCE-151
entry both claimed test_deferral_skip.py asserts those exact strings and that
the CCE-109/CCE-140 runbooks tell operators to grep for them. Neither is true:
test_deferral_skip.py's only time_budget matches are the time_budget_seconds=
kwarg, and `grep -rl time_budget docs/runbooks/` returns nothing.

The conclusion is right for two reasons the false ones displaced, now recorded
in both places: test_time_budget.py / test_time_budget_authoring.py pin five
distinct time_budget_exceeded: prefixes including their counts, and the family
is quoted verbatim in five PUBLISHED pages -- a rename silently falsifies the
docs, and citation_exists cannot catch it because these are prose strings, not
paths.

Found while drafting the CCE-169 spec, which had copied the CLAUDE.md sentence
and repeated it. Measuring a justification false in a spec while leaving it in
the code is CCE-127's _TEMPLATE_ONLY_DIVERGENCES lesson by a shorter route: the
next person weighing a reason-string rename reads the comment, not the spec.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**1. Spec coverage.** Every spec section maps to a task:

| Spec section                                                | Task |
| ----------------------------------------------------------- | ---- |
| Decisions (PR count, default 10, on-by-default, err low)    | 1    |
| Config (`run.window_pr_cap`, schema, `resolve_window_cap`)  | 1    |
| The cut / The third category is the design (3 routing rows) | 2    |
| Why this converges                                          | 3    |
| Reporting (the literal, not `_rsn`, not veto, count bump)   | 2    |
| Stale justifications — `next_deferral_counts` docstring     | 2    |
| Stale justifications — `_rsn` comment + `CLAUDE.md`         | 4    |
| Guards and degradation (`0` no-op, sub-cap untouched)       | 2    |
| Test plan 1, 2, 3, 4, 5                                     | 2    |
| Test plan 6                                                 | 3    |
| Test plan 7, 8                                              | 1    |

No gaps. The Accepted-risks and Rejected sections are rationale, not requirements.

**2. Placeholder scan.** No `TBD`, no "add appropriate error handling", no "similar to Task N". Every code step carries the literal code. The one deliberate judgement call is Task 3 Step 1's import fallback, which names both forms rather than leaving the choice open.

**3. Type consistency.** `resolve_window_cap(config: dict) -> int` is defined in Task 1 and called in Task 2 under that exact name. `DEFAULT_WINDOW_PR_CAP` likewise. `window_capped: list[dict]` is declared at the cut (Task 2 Step 3) and consumed in Steps 4, 6 and 7 of the same task and in Task 3's assertions. `_window_cap` is the local int, distinct from `window_capped` the list — an implementer must not conflate them; the reason string uses both.

**Three things an implementer will hit that the spec does not say:**

- **`CONFIG_YAML` already has a `run:` block** (`tests/orchestrator/conftest.py:28`, `time_budget_seconds: 2100`). Appending a second `run:` silently deletes the budget, because PyYAML keeps only the last duplicate key. Task 2's helper sets the cap by string replacement and asserts the anchor matched. Appending `merge:` in Task 3 is safe because no `merge:` block exists.
- **Line numbers shift after Task 2 Step 3.** Every later step in Task 2 gives a line number for orientation and says to find the anchor by content. Use the quoted code, not the number.
- **`len(prs)` inside the admission loop's `time_budget_exceeded` message (`:2497`) becomes the post-cut count.** That reads correctly — the run admitted N of the M it intended to process — and no existing test is affected, because the default cap of 10 never fires against 3-PR fixtures. Do not "fix" it to `len(window_prs)`: `tests/orchestrator/test_authoring_truncation_advance.py:324-327` pins `admitted 2/3` by exact list membership, and `window_prs` is the pre-cut list only until Task 2's cut moves above it.

---

## Execution Handoff

Plan complete. Two execution options:

**1. Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session with checkpoints for review.
