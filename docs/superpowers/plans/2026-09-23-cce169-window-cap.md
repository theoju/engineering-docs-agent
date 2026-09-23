# CCE-169 Window Cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound the docs-agent review window by PR count before admission, so a stalled baseline drains at a fixed rate instead of compounding into an unrecoverable backlog.

**Architecture:** A new `resolve_window_cap(config)` reads `run.window_pr_cap` (default 10, `0` = unlimited). `orchestrator_runner.run` slices the oldest-first PR list immediately after `_order_prs_oldest_first`, putting the overflow into a **third category** `window_capped` — distinct from `admission_deferred`. Capped PR numbers are unioned into `held_back`, so CCE-151's existing cursor walk stops the baseline at the cap boundary; they are deliberately kept out of `window_prs` and `_deferred_all`, so they accrue no deferral counts and the CCE-140 skip hatch cannot abandon a PR the run never attempted.

**Tech Stack:** Python 3 stdlib only, `jsonschema` (already a dep), pytest. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-23-cce169-window-cap-design.md` (revisions `8c59430` → `7a53af3` → `c2b3cd0`). Read it before Task 2 — the routing table and its three rationales are the design, and this plan does not repeat all of them.

## Global Constraints

Exact values, copied from the spec. Every task's requirements implicitly include this section.

- **Config key:** `run.window_pr_cap`, `"type": "integer"`, `"minimum": 0`. **Default 10.** `0` = unlimited (restores pre-CCE-169 behaviour).
- **Reason string:** `held_back_window_capped: {held} of {total} PRs held for a later run (cap {cap})` — a **plain literal**, `degraded=True`. Never routed through `_rsn` (that helper only discriminates truncated-vs-degraded and would render `time_budget_window_capped`).
- **Counts are `held` of the **pre-cut** PR total**, never of raw commits.
- **NOT added to `_MERGE_VETO_REASON_PREFIXES`** (`scripts/orchestrator_runner.py:4343`, currently `("app_token_unavailable",)`). A capped run is the healthy case and must merge, or the cap accomplishes nothing.
- **Routing table — all three rows are load-bearing:**

  | Consumer                                | `admission_deferred` | `window_capped` |
  | --------------------------------------- | -------------------- | --------------- |
  | `held_back`                             | yes                  | **yes**         |
  | `window_prs` → `next_deferral_counts`   | yes                  | **no**          |
  | `_deferred_all` → `partition_deferrals` | yes                  | **no**          |

- **Python:** stdlib-first. No new runtime deps.
- **Tests:** pytest, TDD (failing test → implementation → green). All orchestrator tests use the fixture-driven dry-run path.
- **Branch:** `feat/CCE-169-window-cap` in worktree `~/Projects/eda-cce181`. Direct commits to `main` are not allowed.
- **Commit trailer:** every commit ends with
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- **Jira:** include `CCE-169` in commit subjects.

---

## File Structure

| File                                                 | Responsibility                                                                  | Task    |
| ---------------------------------------------------- | ------------------------------------------------------------------------------- | ------- |
| `scripts/orchestrator_runner.py`                     | `DEFAULT_WINDOW_PR_CAP`, `resolve_window_cap`                                   | 1       |
| `templates/config.schema.json`                       | `run.window_pr_cap` property                                                    | 1       |
| `tests/orchestrator/test_window_cap.py` (new)        | resolver unit tests + the cut's end-to-end tests                                | 1, 2, 3 |
| `tests/schemas/test_config_schema.py`                | schema round-trip for the new key                                               | 1       |
| `scripts/orchestrator_runner.py`                     | the cut, `held_back` union, the reason, the log line, the invalidated docstring | 2       |
| `tests/orchestrator/test_classification_coverage.py` | expected-count bump 46 → 47 + audit paragraph                                   | 2       |
| `scripts/orchestrator_runner.py`                     | the `_rsn` comment's two false claims                                           | 4       |
| `CLAUDE.md`                                          | the same false sentence in the CCE-151 entry                                    | 4       |

---

## Task 1: `resolve_window_cap`, the schema key, and their tests

Closes spec test-plan items **7** (schema round-trip) and **8** (the default is 10). Nothing is wired to the runner yet — this task's deliverable is a resolver and a schema property that a host can set without the config load failing.

**Files:**

- Modify: `scripts/orchestrator_runner.py` (add constant near `:320`, add function after `resolve_deferral_stall_days` which ends at `:466`)
- Modify: `templates/config.schema.json` (the `run` block, `:205-229`)
- Create: `tests/orchestrator/test_window_cap.py`
- Modify: `tests/schemas/test_config_schema.py`

**Interfaces:**

- Consumes: `_run_cfg(config) -> dict` (`scripts/orchestrator_runner.py:398`) — the shared `run:` block accessor.
- Produces: `DEFAULT_WINDOW_PR_CAP: int = 10` and `resolve_window_cap(config: dict) -> int`. Task 2 calls `resolve_window_cap(config)` exactly once, inside `run`.

### Why the schema edit is not bookkeeping

`templates/config.schema.json`'s `run` block is `"additionalProperties": false` (`:207`). A key absent from the schema is a **hard config-load failure with exit 2**, not an ignored field: `jsonschema.validate` inside `load_config_validated` (`scripts/state_io.py:202`) raises `ConfigError`, and `run` turns that into `return 2` (`scripts/orchestrator_runner.py:2274`). A host that writes the advertised opt-out `window_pr_cap: 0` would get a config file that stops loading.

This is a live hazard, not a hypothetical: `run.deferral_stall_days` is documented as a host override and is **already** missing from this schema (filed as **CCE-184**). Do not fix CCE-184 here — this task adds `window_pr_cap` only.

- [ ] **Step 1: Write the failing resolver tests**

Create `tests/orchestrator/test_window_cap.py` with exactly this header and these four tests. The import shape is copied from `tests/orchestrator/test_deferral_skip.py:1-22`.

```python
# tests/orchestrator/test_window_cap.py
"""CCE-169: the pre-admission PR-count window cap.

The review window had no upper bound, so a stalled baseline widened by a day
every night and each run finished a smaller fraction of it. These tests pin the
cap itself (this file's first half) and the third-category routing that keeps a
capped PR out of the deferral machinery while still stopping the cursor at the
cap boundary (second half, added in Task 2).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as orun  # noqa: E402

FAKES_MULTI = Path(__file__).parent / "fakes_multi"


# ---------------------------------------------------------------------------
# resolve_window_cap
# ---------------------------------------------------------------------------


def test_window_cap_defaults_to_ten():
    """The default is the whole point of CCE-169 and NOTHING else can catch it.

    Every `fake_source_collector.json` in the tree tops out at 3 PRs, and each
    helper that rewrites them keeps 3 — so `len(prs) > cap` is False for any
    default >= 3 and no end-to-end test can observe the value. An implementer
    who writes `int(run_cfg.get("window_pr_cap") or 0)` ships the rejected
    off-by-default alternative with every other test green.
    """
    assert orun.DEFAULT_WINDOW_PR_CAP == 10
    assert orun.resolve_window_cap({}) == 10
    assert orun.resolve_window_cap({"run": {}}) == 10


def test_window_cap_reads_the_config_key():
    assert orun.resolve_window_cap({"run": {"window_pr_cap": 25}}) == 25


def test_window_cap_zero_is_unlimited():
    """`0` is the advertised opt-out, so it must survive as 0.

    This is why the resolver tests `val is None` and not truthiness: `or
    DEFAULT` would silently rewrite an explicit 0 back to 10.
    """
    assert orun.resolve_window_cap({"run": {"window_pr_cap": 0}}) == 0


def test_window_cap_tolerates_a_malformed_run_block():
    """`_run_cfg` exists because `config.get("run") or {}` raises
    AttributeError on `run: "nonsense"`. Mirror its siblings, do not reinvent.
    """
    assert orun.resolve_window_cap({"run": "nonsense"}) == 10
    assert orun.resolve_window_cap({"run": None}) == 10
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd ~/Projects/eda-cce181 && python3 -m pytest tests/orchestrator/test_window_cap.py -v
```

Expected: 4 FAILED with `AttributeError: module 'orchestrator_runner' has no attribute 'DEFAULT_WINDOW_PR_CAP'` (and `resolve_window_cap`).

> If `pytest` produces mangled output, the `rtk` shell proxy is interfering. Prefix the command with `rtk proxy` to run it unfiltered.

- [ ] **Step 3: Add the constant**

In `scripts/orchestrator_runner.py`, immediately after line 320 (`DEFAULT_DEFERRAL_SKIP_THRESHOLD = 3`), with a blank line either side and no comment — matching the shape of its neighbours:

```python
DEFAULT_DEFERRAL_SKIP_THRESHOLD = 3

DEFAULT_WINDOW_PR_CAP = 10
```

- [ ] **Step 4: Add the resolver**

In `scripts/orchestrator_runner.py`, after `resolve_deferral_stall_days` (which ends at `:466` with `    return int(val)`) and before `def resolve_authoring_hard_cap(` — two blank lines between defs, matching house style:

```python
def resolve_window_cap(config: dict) -> int:
    """Resolve `run.window_pr_cap` (CCE-169). 0 = unlimited.

    The maximum number of merged PRs a single run admits, oldest-first. PRs
    beyond the cap are held for a later run: they enter `held_back`, so the
    CCE-151 cursor stops at the cap boundary, but they do NOT accrue deferral
    counts and are not exposed to the CCE-140 skip hatch, because the run never
    attempted them.

    Default-ON, unlike `citation_source_roots` and `lint.external_repos`. That
    is deliberate: every CCE-169 incident happened on a host that had configured
    nothing, and an opt-in guard against an unrecoverable failure is discovered
    by having the failure. A cap set too tight is a visible nightly reason an
    operator raises in one edit; a cap set too loose is a silent stall that cost
    113 PRs of documentation on ADIS.
    """
    run_cfg = _run_cfg(config)
    val = run_cfg.get("window_pr_cap")
    if val is None:
        return DEFAULT_WINDOW_PR_CAP
    return int(val)
```

**Mirror this idiom exactly; do not invent one.** `_run_cfg(config)`, never `config.get("run") or {}`. `if val is None:`, never a truthiness test and never `or DEFAULT` — that is what lets an explicit `0` survive. `int(val)` unguarded — the JSON-schema layer is what rejects wrong types for real hosts, and only raw-dict unit tests reach here otherwise.

- [ ] **Step 5: Run the resolver tests to verify they pass**

```bash
cd ~/Projects/eda-cce181 && python3 -m pytest tests/orchestrator/test_window_cap.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Write the failing schema round-trip test**

Append to `tests/schemas/test_config_schema.py`. The file already imports `json`, `yaml`, `Path`, `validate`, `ValidationError`, `pytest` and binds `SCHEMA` at module level — use them; do not add imports.

```python
def test_run_window_pr_cap_accepted():
    """CCE-169. `run` is additionalProperties: false, so a key missing from the
    schema is a hard load failure with exit 2, not an ignored field — and the
    bare host is the one case that omission spares, which is what would keep the
    gap invisible until the night an operator reaches for the opt-out.

    Assert on a SUCCESSFUL load. A test that counts ValidationErrors passes
    whether or not the property exists.
    """
    run = SCHEMA["properties"]["run"]
    validate({"window_pr_cap": 10}, run)
    validate({"window_pr_cap": 0}, run)


def test_run_window_pr_cap_rejects_negative():
    run = SCHEMA["properties"]["run"]
    with pytest.raises(ValidationError):
        validate({"window_pr_cap": -1}, run)
```

- [ ] **Step 7: Run it to verify it fails**

```bash
cd ~/Projects/eda-cce181 && python3 -m pytest tests/schemas/test_config_schema.py -k window_pr_cap -v
```

Expected: `test_run_window_pr_cap_accepted` FAILS with `ValidationError: Additional properties are not allowed ('window_pr_cap' was unexpected)`. (`test_run_window_pr_cap_rejects_negative` passes vacuously — for the wrong reason, which is exactly why the accepted-case test is the one that matters.)

- [ ] **Step 8: Add the schema property**

In `templates/config.schema.json`, inside `properties.run.properties`, after the `authoring_hard_cap_seconds` entry (which ends at `:226`), adding a comma to the preceding entry's closing brace:

```json
        "window_pr_cap": {
          "type": "integer",
          "minimum": 0,
          "description": "CCE-169: maximum merged PRs a single run admits, oldest-first. PRs beyond the cap are held for a later run: they are excluded from the advance cursor so the baseline stops at the cap boundary, and they do NOT accrue deferral counts, because they were never attempted. Default 10. 0 = unlimited, restoring the pre-CCE-169 unbounded window."
        }
```

- [ ] **Step 9: Run both test files to verify green**

```bash
cd ~/Projects/eda-cce181 && python3 -m pytest tests/schemas/test_config_schema.py tests/orchestrator/test_window_cap.py -v
```

Expected: all pass, including the two new schema cases.

- [ ] **Step 10: Commit**

```bash
cd ~/Projects/eda-cce181
git add scripts/orchestrator_runner.py templates/config.schema.json \
        tests/orchestrator/test_window_cap.py tests/schemas/test_config_schema.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): resolve_window_cap + run.window_pr_cap schema key — CCE-169

The resolver and its config key, not yet wired to the admission path.

The default (10) gets its own direct unit assertion because nothing else can
catch it: every fake_source_collector.json in the tree tops out at 3 PRs, so
`len(prs) > cap` is False for any default >= 3 and no end-to-end test can
observe the value. An implementer writing `or 0` would ship the rejected
off-by-default alternative with every other test green.

The schema edit is load-bearing, not bookkeeping. `run` is
additionalProperties: false, so omitting the key makes `window_pr_cap: 0` --
the advertised opt-out -- hard-fail config load with exit 2. The bare host is
the one case that omission spares, which is what would keep the gap invisible
until an operator reached for the opt-out. Asserts on a successful load, never
on a ValidationError count.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

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

## Task 3: The auto-merge end-to-end test

Closes spec test-plan item **6**. Separate from Task 2 because it needs the fake-`gh` harness and asserts a different property: that the cap does not accidentally make a run ineligible to merge. A reviewer could reasonably approve Task 2 and reject this.

**Files:**

- Modify: `tests/orchestrator/test_window_cap.py`

**Interfaces:**

- Consumes: `_seed_capped_host` from Task 2, and `_install_fake_gh` from `tests/orchestrator/test_cursor_backed_merge.py` (import it, do not copy).

### Why "did not return `partial_run`" is not enough

`_maybe_auto_merge` returns `skip("merge_vetoed", veto)` and then `skip("blind_run")` **before** it ever reaches `skip("partial_run")` (`scripts/orchestrator_runner.py:4426-4436`). So "did not return `partial_run`" is equally true of a run vetoed by a `held_back_window_capped` entry mistakenly added to `_MERGE_VETO_REASON_PREFIXES`, and of one misclassified `blind`. Neither merges, and both leave the cap inert. `pr_merge` in the fake call log is the assertion.

- [ ] **Step 1: Write the test**

Append to `tests/orchestrator/test_window_cap.py`. Add the import beside the existing ones at the top of the file. `tests/orchestrator/` is on `sys.path` under pytest's prepend import mode because `tests/` has no `__init__.py`; if the bare import fails, add the explicit path insert shown second.

```python
from test_cursor_backed_merge import _install_fake_gh  # noqa: E402
```

Fallback if that raises `ModuleNotFoundError`:

```python
sys.path.insert(0, str(Path(__file__).parent))
from test_cursor_backed_merge import _install_fake_gh  # noqa: E402
```

Do **not** copy the helper into this file — duplicating it means a future change to the fake `gh` client silently stops applying here.

```python
def test_a_capped_run_still_auto_merges(
    tmp_path, monkeypatch, init_host, base_config_yaml, read_current_run
):
    """If a capped run cannot merge, the cap accomplishes nothing.

    The whole convergence argument is: capped PRs enter `held_back` -> CCE-151's
    walk runs -> `advance_cursor_backed=True` -> CCE-140's carve-out
    (`if partial and not advance_cursor_backed`) permits the auto-merge ->
    state.json is promoted to the default branch -> the baseline advances -> the
    next run takes the next `cap` PRs. Break the merge and the baseline never
    moves, so the cap turns a compounding stall into a permanent one.

    `pr_merge` in the call log is the assertion. Nothing weaker distinguishes
    "the gate opened" from "the gate opened and something downstream closed it":
    _maybe_auto_merge returns skip("merge_vetoed") and skip("blind_run") BEFORE
    skip("partial_run"), so asserting the absence of the last one passes for a
    run vetoed by the wrong list or misclassified blind.
    """
    state_path, base, (c1, c2, c3), fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=2
    )
    # Safe to APPEND: unlike `run:`, the shared CONFIG_YAML has no `merge:`
    # block, so there is no duplicate key for PyYAML to silently drop. Same
    # append test_cursor_backed_merge._seed_merge_host performs.
    config_path = tmp_path / ".engineering-docs-agent" / "config.yml"
    config_path.write_text(
        config_path.read_text()
        + "\nmerge:\n  policy: auto\n  checks_grace_seconds: 0\n"
        + "  checks_timeout_seconds: 0\n"
    )
    gh = _install_fake_gh(monkeypatch)
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=False)
    assert rc == 0
    cr = read_current_run(state_path)
    # Preconditions -- without these the merge assertion could pass for the
    # wrong reason (a run that is not partial at all reaches the merge path
    # under today's rules too).
    assert cr["partial"] is True, cr
    assert [
        r for r in cr["partial_reasons"] if r.startswith("held_back_window_capped:")
    ], cr["partial_reasons"]
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == c2, written[
        "last_successful_run"
    ]
    fake = gh["gh"]
    assert [c for c in fake.calls if c[0] == "pr_merge"], (
        "a capped run is cursor-backed and must auto-merge; if it does not, the "
        "baseline never advances and the cap converts a compounding stall into "
        f"a permanent one. reasons={cr['partial_reasons']} calls={fake.calls}"
    )
```

- [ ] **Step 2: Run it, then prove it is falsifiable**

```bash
cd ~/Projects/eda-cce181 && python3 -m pytest tests/orchestrator/test_window_cap.py::test_a_capped_run_still_auto_merges -v
```

Expected: **PASS**, because Task 2 already wired the mechanism. That is correct — this test is a regression guard on Task 2's work, not red/green for new code. **A test that cannot be made to fail is not a test**, so prove it: temporarily change `scripts/orchestrator_runner.py:4343` to

```python
_MERGE_VETO_REASON_PREFIXES: tuple[str, ...] = ("app_token_unavailable", "held_back_window_capped")
```

re-run, and confirm it FAILS on the `pr_merge` assertion. Then revert:

```bash
cd ~/Projects/eda-cce181 && git checkout -- scripts/orchestrator_runner.py
```

`git checkout --` is safe here only because Task 2 is already committed. If you have uncommitted work in that file, undo the edit by hand instead.

- [ ] **Step 3: Confirm the revert and run the full suite**

```bash
cd ~/Projects/eda-cce181
git diff --stat scripts/orchestrator_runner.py   # expect: no output
python3 -m pytest
```

Expected: `git diff --stat` prints nothing, and the suite is green.

- [ ] **Step 4: Commit**

```bash
cd ~/Projects/eda-cce181
git add tests/orchestrator/test_window_cap.py
git commit -m "$(cat <<'EOF'
test(orchestrator): a capped run must actually reach gh pr merge — CCE-169

The convergence argument depends on it: capped PRs enter held_back ->
CCE-151's walk runs -> advance_cursor_backed=True -> CCE-140's carve-out
permits the merge -> state.json reaches main -> the baseline advances. Break
the merge and the cap converts a compounding stall into a permanent one.

Asserts pr_merge in the fake gh call log, not the absence of
skip("partial_run"). _maybe_auto_merge returns skip("merge_vetoed") and
skip("blind_run") ahead of skip("partial_run"), so the weaker assertion passes
for a run vetoed by the wrong prefix list or misclassified blind -- neither of
which merges. Preconditions (partial, carries the reason, advance stops at the
cap boundary) are pinned beside it so the merge cannot pass for the wrong
reason either.

Verified falsifiable: adding held_back_window_capped to
_MERGE_VETO_REASON_PREFIXES makes it fail.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

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
