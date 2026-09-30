## Task 2: The cut, the `held_back` union, and the reason

The core of the change. Closes spec test-plan items **1**, **2**, **3**, **4** and **5**.

**Files:**

- Modify: `scripts/orchestrator_runner.py` — the cut (after `:2447`), the window-snapshot comment (`:2470-2471`), `held_back` (`:3278-3280`), the `emit_log` cursor line (`:3300-3313`), the `next_deferral_counts` docstring (`:864-868`)
- Modify: `tests/orchestrator/test_classification_coverage.py` (`:151-152` plus the docstring)
- Modify: `tests/orchestrator/test_window_cap.py` (append the second half)

**Interfaces:**

- Consumes: `resolve_window_cap(config) -> int` from Task 1.
- Produces: a local `window_capped: list[dict]` inside `run`, live from the cut site down to the `held_back` assignment. Task 3 relies on the reason string and on capped PRs reaching `held_back`.

### The cut goes immediately after `_order_prs_oldest_first`, and the position is load-bearing

Insert between line 2447 (the closing `)` of the `_order_prs_oldest_first` call) and line 2448 (`        jira_issues = sources.get("jira_issues", []) or []`). The surrounding code today:

```python
        prs = sources.get("prs", [])
        prs = _order_prs_oldest_first(
            prs,
            last_sha=sc_inputs["last_sha"],
            head_sha=head_sha,
            repo_root=repo_root,
        )
        jira_issues = sources.get("jira_issues", []) or []
```

Three constraints fix that position, and violating any one of them produces a change that looks correct in every sub-cap test:

- **After the ordering call.** The CCE-109/140/151 cursor is a **prefix** boundary (`advance_cursor_list` docstring, `:699-708`), so `prs[:cap]` is only meaningful once `prs` is oldest-first.
- **Before `window_prs = list(prs)` (`:2472`).** `window_prs` is the only value passed to `next_deferral_counts(window_pr_numbers=...)` (`:3494-3496`). Read `next_deferral_counts` (`:850-877`): in-window **and** still-deferred → `+1`; in-window and **not** still-deferred → **`out.pop(k, None)`, the entry is DELETED**; not in window → carried forward unchanged. A capped PR can never reach `still_deferred_numbers` (its two writers are `admission_deferred`, written only at the time-budget break, and `deferred_pages_by_pr`, written only by the CCE-140 complement writer over `per_target`, which is built from `summaries` — and a capped PR is never summarized). So a capped PR left inside `window_prs` takes the **else** branch every night it waits, **erasing** any genuine deferral history it had accrued and permanently disarming the CCE-140 skip hatch for it.
- **Before the summarize loop (`:2493`).** That loop dispatches `pr-summarizer` per PR against the run's single shared `deadline` (`:2293`). Capping after it — on `summaries` or `per_target` — looks identical in every sub-cap test and throws away most of the benefit, because the held PRs still spend their dispatches. This is the spec's named implementer error; it is why the cut's position is called out here rather than left implicit.

**Not a trap here, but check before moving anything:** the CCE-127 `add_partial`-stub hazard (a reason added before the `state["current_run"] = {...}` literal is silently overwritten by it) does not apply — that literal is at `:2325`, well above the cut site. Do not move the cut above it.

- [ ] **Step 1: Write the failing end-to-end tests**

Append to `tests/orchestrator/test_window_cap.py`. The real-git helper is modelled on `tests/orchestrator/test_cursor_backed_merge.py:_seed_merge_host`; it differs in that it does **not** append merge config (Task 3 does that) and it takes the cap as a parameter.

```python
# ---------------------------------------------------------------------------
# the cut: third-category routing
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _seed_capped_host(tmp_path, init_host, base_config_yaml, *, cap, state_extra=None):
    """Real git window of three PR merges plus a trailing non-PR commit.

    Returns (state_path, base, [c1, c2, c3], fakes).

    c4 exists so the newest PR merge is never HEAD: without it `advance == c2`
    and `advance != head` stop being independent statements. Copied from
    test_cursor_backed_merge._seed_merge_host for that reason.

    The cap is set by REPLACING a line of the shared config, never by appending
    a second `run:` block -- CONFIG_YAML already carries `run:` with
    `time_budget_seconds: 2100`, and PyYAML keeps only the LAST duplicate key,
    so an append would silently delete the budget and change what the test
    measures.
    """
    cfg = base_config_yaml.replace(
        "  time_budget_seconds: 2100",
        f"  time_budget_seconds: 2100\n  window_pr_cap: {cap}",
    )
    assert "window_pr_cap" in cfg, "config replacement anchor drifted"
    seeded = {"version": "1", "last_successful_run": {"head_sha": "seed"}}
    seeded.update(state_extra or {})
    state_path = init_host(seeded, config_yaml=cfg)
    repo = tmp_path
    base = _git(repo, "rev-parse", "HEAD")
    shas = []
    for i in range(1, 5):
        (repo / "f.txt").write_text(f"c{i}")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    seeded["last_successful_run"] = {"head_sha": base}
    state_path.write_text(json.dumps(seeded))
    fakes = tmp_path / "fakes_cap"
    fakes.mkdir(parents=True, exist_ok=True)
    for f in FAKES_MULTI.iterdir():
        (fakes / f.name).write_text(f.read_text())
    sc = json.loads((FAKES_MULTI / "fake_source_collector.json").read_text())
    for pr, sha in zip(sc["prs"], shas[:3]):
        pr["merge_sha"] = sha
    (fakes / "fake_source_collector.json").write_text(json.dumps(sc))
    return state_path, base, shas[:3], fakes


def test_a_capped_run_advances_to_the_cap_boundary_and_says_so(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """THE CCE-151 REGRESSION GUARD, and the most important test in this file.

    A bare `prs = prs[:cap]` puts capped PRs in neither `deferred_pages_by_pr`
    nor `admission_deferred`, so `held_back` is empty, `time_truncated` is
    False, CCE-151's walk is never entered, and control reaches the `else`
    branch where `advance_sha = current_run.head_sha` -- FULL WINDOW HEAD. The
    run would document 2 PRs and advance past all 3, losing the third
    permanently and silently.

    The reason must be asserted PRESENT, by list membership on the fully
    rendered line. Nothing else here distinguishes the right label from a wrong
    one or from NO label at all, and emitting nothing is the dangerous variant
    because it passes everything else: on a healthy capped run CCE-151's walk
    takes its `if ok:` branch, which sets `advance_sha` and
    `advance_cursor_backed` WITHOUT calling `add_partial`, so this site is the
    run's only signal that any PR was held.
    """
    state_path, base, (c1, c2, c3), fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=2
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    assert advance == c2, written["last_successful_run"]
    assert advance != _git(tmp_path, "rev-parse", "HEAD")
    cr = read_current_run(state_path)
    assert (
        "held_back_window_capped: 1 of 3 PRs held for a later run (cap 2)"
        in cr["partial_reasons"]
    ), cr["partial_reasons"]


def test_a_capped_pr_does_not_accrue_a_deferral_count(
    tmp_path, init_host, base_config_yaml
):
    """Row 2 of the routing table. The danger is ERASURE, not over-counting.

    `next_deferral_counts` pops the entry for any in-window PR that is not in
    `still_deferred_numbers`, and a capped PR can never be in that set. So a
    capped PR left inside `window_prs` has its genuine history DELETED every
    night it waits, permanently disarming the CCE-140 skip hatch for it.
    """
    state_path, base, (c1, c2, c3), fakes = _seed_capped_host(
        tmp_path,
        init_host,
        base_config_yaml,
        cap=2,
        state_extra={"deferral_counts": {"unknown/unknown#3": 2}},
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    written = json.loads(state_path.read_text())
    assert written.get("deferral_counts", {}).get("unknown/unknown#3") == 2, written.get(
        "deferral_counts"
    )


def test_a_capped_pr_at_threshold_is_not_abandoned(
    tmp_path, init_host, base_config_yaml
):
    """Row 3. The skip hatch must never abandon a PR the run did not attempt.

    Threshold is 3 by default, so a count of 3 is exactly at it. The PR is only
    safe because it never reaches `_deferred_all` -- `partition_deferrals` is
    order-independent and would skip it on sight.
    """
    state_path, base, (c1, c2, c3), fakes = _seed_capped_host(
        tmp_path,
        init_host,
        base_config_yaml,
        cap=2,
        state_extra={"deferral_counts": {"unknown/unknown#3": 3}},
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    written = json.loads(state_path.read_text())
    skipped = written.get("skipped_prs", [])
    assert not [s for s in skipped if "#3" in json.dumps(s)], skipped


def test_window_pr_cap_zero_is_a_true_no_op(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """The advertised opt-out. No reason, and the advance reaches the newest PR
    merge exactly as an uncapped run would."""
    state_path, base, (c1, c2, c3), fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=0
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    cr = read_current_run(state_path)
    assert not [
        r for r in cr["partial_reasons"] if "window_capped" in r
    ], cr["partial_reasons"]
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == c3, written[
        "last_successful_run"
    ]


def test_a_sub_cap_window_is_untouched(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """Three PRs against a cap of 10 -- `window_capped` stays empty, nothing is
    added to `held_back`, and the code path is today's."""
    state_path, base, (c1, c2, c3), fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=10
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    cr = read_current_run(state_path)
    assert not [
        r for r in cr["partial_reasons"] if "window_capped" in r
    ], cr["partial_reasons"]
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == c3, written[
        "last_successful_run"
    ]
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd ~/Projects/eda-cce181 && python3 -m pytest tests/orchestrator/test_window_cap.py -v
```

Expected: the four resolver tests from Task 1 pass; `test_a_capped_run_advances_to_the_cap_boundary_and_says_so` FAILS on the `advance == c2` assertion (it will be `c3`, full window HEAD) and the two routing tests FAIL or pass vacuously. The two no-op tests pass already. **If `test_a_capped_run_...` passes at this step, stop — the fixture is not producing a >cap window and the whole task is untested.**

- [ ] **Step 3: Add the cut**

In `scripts/orchestrator_runner.py`, insert between line 2447 and line 2448 (between the `_order_prs_oldest_first` call's closing `)` and `jira_issues = ...`), at 8-space indentation:

```python
        # CCE-169: bound the window BEFORE admission. The only pre-existing
        # truncation is the time-based cut inside the admission loop below,
        # which fires after the run has already begun failing to keep up — so a
        # stalled baseline widened by a day every night and each run finished a
        # smaller fraction of it. `window_capped` is a THIRD category, not a
        # reuse of `admission_deferred`: those two have the same shape and
        # different causes (`admission_deferred` means the run TRIED and ran out
        # of time; `window_capped` means the run deliberately DID NOT TRY), and
        # per CCE-144 classification follows the call site, never the
        # resemblance. It enters `held_back` so the cursor stops at the cap
        # boundary, and stays out of `window_prs` and `_deferred_all` so it
        # accrues no deferral count and the skip hatch cannot abandon it.
        _window_cap = resolve_window_cap(config)
        window_capped: list[dict] = []
        if _window_cap and len(prs) > _window_cap:
            window_capped = prs[_window_cap:]
            prs = prs[:_window_cap]
```

- [ ] **Step 4: Emit the reason**

Immediately after the cut block added in Step 3, still before `jira_issues = ...`:

```python
        if window_capped:
            # A plain literal, deliberately NOT routed through `_rsn` below:
            # that helper only discriminates truncated-vs-degraded, so a cap
            # reason passed through it renders as `time_budget_window_capped` on
            # a truncated run — factually wrong, since the cap fires before any
            # clock is consulted. degraded=True (CCE-144): the run HELD BACK
            # what it did not process; it did not consume and lose it.
            add_partial(
                state,
                f"held_back_window_capped: {len(window_capped)} of "
                f"{len(prs) + len(window_capped)} PRs held for a later run "
                f"(cap {_window_cap})",
                degraded=True,
            )
```

Note `len(prs) + len(window_capped)` — `prs` has already been sliced, so the pre-cut total must be reconstructed. Writing `len(prs)` alone would report `1 of 2`.

- [ ] **Step 5: Amend the window-snapshot comment**

`window_prs` is no longer "the full window". At `:2470-2471` (numbering before Step 3's insertion; find it by content), replace:

```python
        # CCE-140: the full window, oldest-first, before admission truncation.
        # Deferral counting is keyed to the window a run actually saw.
```

with:

```python
        # CCE-140: the admitted window, oldest-first, before admission
        # truncation. Deferral counting is keyed to the window a run actually
        # saw — which since CCE-169 EXCLUDES PRs the cap held back, because
        # `next_deferral_counts` pops the entry for any in-window PR that is not
        # still deferred, and a capped PR can never be in that set. Leaving them
        # here would erase their genuine history every night they wait.
```

- [ ] **Step 6: Union the capped numbers into `held_back`**

At `:3278-3280` (find by content), replace:

```python
        held_back = (
            set(deferred_pages_by_pr) | {p.get("number") for p in admission_deferred}
        ) - skipped_numbers
```

with:

```python
        held_back = (
            set(deferred_pages_by_pr)
            | {p.get("number") for p in admission_deferred}
            # CCE-169: capped PRs stop the cursor exactly like unfinished ones.
            # They cannot intersect `skipped_numbers` — that set comes from
            # `partition_deferrals(_deferred_all, ...)` and a capped PR is in
            # neither of `_deferred_all`'s two writers — so the subtraction
            # below is a no-op for them, which is row 3 of the routing table
            # holding by construction rather than by a guard.
            | {p.get("number") for p in window_capped}
        ) - skipped_numbers
```

- [ ] **Step 7: Name the capped PRs in the cursor log line**

`held_back` now mixes three causes. The CCE-175 log line exists so an operator can answer "which PR is blocking the cursor?"; without this, capped PRs appear in `held_back` and read as failures. At `:3300-3313` (find by content), extend the format string and its arguments:

```python
        emit_log(
            "cursor: admitted=[%s] deferred=[%s] capped=[%s] held_back=[%s] "
            "skipped=[%s] baseline_age=%s stall_window=%sd"
            % (
                ", ".join(str(p.get("number")) for p in prs) or "none",
                ", ".join(str(p.get("number")) for p in _deferred_all) or "none",
                ", ".join(str(p.get("number")) for p in window_capped) or "none",
                ", ".join(str(n) for n in sorted(held_back, key=str)) or "none",
                ", ".join(str(n) for n in sorted(skipped_numbers, key=str)) or "none",
                "unknown" if _baseline_age is None else f"{_baseline_age:.1f}d",
                _stall_days,
            )
        )
```

- [ ] **Step 8: Correct the `next_deferral_counts` docstring**

Its carry-forward branch is justified by a claim the cap falsifies. At `:864-868`, replace:

```python
    - not in this window at all → carried forward unchanged. A window can
      shrink transiently when the source-collector degrades, and absence is
      not evidence a PR was processed. Growth is bounded because a PR leaves
      the window only once the baseline passes it, which requires it to be in
      the cursor prefix, which requires it not to be deferred.
```

with:

```python
    - not in this window at all → carried forward unchanged. A window can
      shrink transiently when the source-collector degrades, and absence is
      not evidence a PR was processed. CCE-169: growth used to be justified by
      "a PR leaves the window only once the baseline passes it, which requires
      it to be in the cursor prefix, which requires it not to be deferred" —
      false under a window cap, which removes a PR from the window without the
      baseline passing it. The BEHAVIOUR is unchanged and still correct (carry
      forward is exactly right for a PR that was never attempted); growth is now
      bounded by `run.window_pr_cap` instead.
```

The behaviour is correct as written — only the stated reason was false. Do not change the code.

- [ ] **Step 9: Run the window-cap tests to verify they pass**

```bash
cd ~/Projects/eda-cce181 && python3 -m pytest tests/orchestrator/test_window_cap.py -v
```

Expected: 9 passed.

- [ ] **Step 10: Bump the classification-coverage count and write its audit paragraph**

`tests/orchestrator/test_classification_coverage.py` pins the exact population of `add_partial` call sites. This change adds one. The number is an **inline literal written twice in one statement** (`:151-152`), not a named constant — edit both.

```python
    calls = list(_add_partial_calls(REPO_ROOT / "scripts/orchestrator_runner.py"))
    assert len(calls) == 47, (
        f"expected 47 add_partial calls, found {len(calls)}; re-audit and "
        "update this count deliberately"
    )
```

The file's convention requires an audit paragraph appended to that test's docstring (newest last, after the `45 -> 46` entry), in the form `<old> -> <new>, <TICKET>: \`<reason_token>\` in \`<enclosing_function>\`. Audited <classification>. <why>`:

```
    46 -> 47, CCE-169: `held_back_window_capped` in `run`. Audited
    degraded=True. The run HELD BACK the PRs beyond the cap — it did not
    consume and lose them, which is the blind shape. They enter `held_back`, so
    CCE-151's cursor stops at the cap boundary and their content is documented
    by a later run; nothing is stranded outside every future window. Explicitly
    NOT info_only: the reason must flip `partial` so the count is visible in the
    digest, and it is the run's ONLY signal that any PR was held — on a healthy
    capped run CCE-151's walk takes its `if ok:` branch, which sets
    `advance_sha` and `advance_cursor_backed` without calling `add_partial` at
    all. Also explicitly NOT left bare, which would default to blind and turn
    every draining nightly red; and NOT added to `_MERGE_VETO_REASON_PREFIXES`,
    because a capped run is the healthy case and must merge or the cap
    accomplishes nothing.
```

- [ ] **Step 11: Run the full suite**

```bash
cd ~/Projects/eda-cce181 && python3 -m pytest
```

Expected: all pass. Compare the **skip count** against the pre-change baseline as well as the pass count — a test that `importorskip`s reports green, so "pytest passed" is not the same as "the test ran."

- [ ] **Step 12: Commit**

```bash
cd ~/Projects/eda-cce181
git add scripts/orchestrator_runner.py tests/orchestrator/test_window_cap.py \
        tests/orchestrator/test_classification_coverage.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): bound the review window before admission — CCE-169

The cut lands immediately after _order_prs_oldest_first and before
`window_prs = list(prs)`. All three positions are load-bearing:

- after the ordering call, because the cursor is a PREFIX boundary and
  prs[:cap] is only meaningful on an oldest-first list;
- before window_prs, because next_deferral_counts POPS the entry for any
  in-window PR not in still_deferred_numbers, and a capped PR can never be in
  that set -- so leaving it in window_prs ERASES its genuine deferral history
  every night it waits and permanently disarms the CCE-140 skip hatch;
- before the summarize loop, because that loop spends a pr-summarizer dispatch
  per PR against the run's single shared deadline. Capping later looks
  identical in every sub-cap test and returns none of the benefit.

window_capped is a THIRD category, not a reuse of admission_deferred: same
shape, different cause, and per CCE-144 classification follows the call site.
It is unioned into held_back so CCE-151's walk stops the baseline at the cap
boundary; it stays out of window_prs and _deferred_all so it accrues no count
and partition_deferrals cannot abandon a PR the run never attempted.

Also corrects the next_deferral_counts docstring, whose bounded-growth
justification ("a PR leaves the window only once the baseline passes it") the
cap falsifies. The behaviour is unchanged and still right; only the stated
reason was false. Per CCE-127's _TEMPLATE_ONLY_DIVERGENCES lesson, a
justification nobody re-examines is worse than none.

Classification audit 46 -> 47 in test_classification_coverage.py.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

