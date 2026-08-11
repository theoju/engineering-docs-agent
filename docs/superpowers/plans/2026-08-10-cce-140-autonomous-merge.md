# Track B — Autonomous Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a time-truncated partial docs-agent run merge itself when — and only when — its baseline advance is backed by the CCE-109 cursor, so the pipeline stops depending on a daily human merge that already failed as a policy.

**Architecture:** Three coupled changes inside the plugin repo, landing as one PR. (1) The advance cursor stops at the first PR whose work this run did not finish, and `run()` reports whether the advance came from that cursor; `_maybe_auto_merge` blocks a partial run only when its advance was _not_ cursor-backed. (2) `fact_check_warnings` stops gating the merge and becomes a PR-body / notification warning only, matching the fact-checker's own documented warn-layer contract. (3) A PR deferred on `run.deferral_skip_threshold` (default 3) consecutive runs is forgiven on the next run: the cursor walks past it, a record lands in a durable `state.json` `skipped_prs` array, and a non-informational partial reason names the PR and its pages so it reaches notifications.

**Tech Stack:** Python 3.11+, pytest (`--import-mode=importlib`), jsonschema draft-07, `pyyaml`. No ruff/mypy in this repo — pytest is the whole gate. Interpreter is `/Users/theo/Projects/engineering-docs-agent/.venv/bin/python` (there is **no** bare `python` on this machine).

**Repo:** `/Users/theo/Projects/engineering-docs-agent` (the PLUGIN). Every path in this plan is relative to that repo unless it starts with `/`.

---

## Global Constraints

Binding requirements copied verbatim from the spec `docs/superpowers/specs/2026-08-10-docs-agent-self-sustaining-design.md` (host repo). Every task's requirements implicitly include this section.

- **Decision 1 — Fully autonomous.** "No routine human action. A daily human merge already failed as a policy — not through negligence, but because a 500–1700 line prose diff at 06:00 is not a thing anyone sustains."
- **Decision 2 — Generalize the CCE-109 cursor.** "Partial runs merge; the baseline advances only to the last PR whose pages all landed. Reverted pages stay in-window and are re-authored next run."
- **Decision 3 — Skip after 3 consecutive deferrals**, "record every skip durably, and enable notifications. A loud, recorded loss beats an indefinite silent stall."
- **Decision 4 — `fact_check_warnings` warns, never gates.** "The fact-checker is documented as a warn layer at `:1755-1760`; `skip("fact_check_warnings")` at `:2859` contradicts its own contract."
- **Ordering constraint — A must precede B.** "B enables merging; A makes the advance honest. Landing B first would merge every run while `advance_sha` still resolves to full HEAD — automating the silent-loss bug and running it nightly."
- **Track B scope (verbatim).** "1. Allow a partial run to auto-merge **when its advance is cursor-backed**. A partial run whose `advance_sha` came from the cursor has, by construction, advanced only past PRs whose pages all landed. A partial run that would advance to full HEAD must still be blocked. 2. Demote `fact_check_warnings` from a merge gate to a PR-body and notification warning. 3. Add per-PR deferral counting. A PR deferred on three consecutive runs is skipped on the fourth: the cursor moves past it, an entry is appended to a durable `skipped_prs` list in `state.json`, and a non-informational partial reason names the PR and the page so it reaches notifications."
- **New-state precedent (verbatim).** "No per-PR deferral tracking exists today — `deferred_unanchored` is a within-run boolean, never persisted. This is the only genuinely new state in the design; the `dismissed_gap_flags` key is the precedent for its shape. The threshold is a config key with a default of 3, so it is tunable without a code change."
- **Track B acceptance (verbatim).** "a partial run with a cursor-backed advance auto-merges, and the baseline moves by exactly the clean PRs. A partial run that would advance to full HEAD does not merge. A page failing three consecutive runs is skipped on the fourth with a `skipped_prs` entry and a notification."
- **Testing (verbatim, Track A clause — it binds B's shared assertions too).** "assert `advance_sha != head_sha` explicitly, not merely that it equals the cursor. The bug being fixed is a fall-through to HEAD, so the negative assertion is the one that would have caught it."
- **Risk 1 (verbatim).** "**No green baseline for track B.** The auto-merge path has never once succeeded on this host. First success is the test; there is nothing to regress against."
- **Risk 3 (verbatim).** "**The plugin is consumed at `ref: main` by every host, including its own dogfood** — currently the only working reference that the agent can succeed at all. Plugin changes take effect on the next fire with no release step, which makes both iteration and breakage immediate."
- **Risk 2 (verbatim).** "**Measurement conflict.** Prior analyses produced three different counts of affected pages (66 / 52 / 48) and two irreconcilable citation figures (33 to 17, and 47 of 79). Every number in the plans is to be re-measured from scratch; none is inherited."
- **Out of scope (verbatim).** "Grandfathering the legacy corpus; narrowing the agent's editable paths; adopting the `archive-index` generator for the archive lens; the verification-phase budget reserve […]. Restoring the nightly `schedule:` trigger is the final step after all four tracks verify, not part of any track."

### Non-negotiable execution rules for this plan

- **This track lands LAST.** Do not open Track B's PR until Track A, C and D are merged. B is the switch; A is what makes throwing it safe.
- **Ticket key.** Commit subjects in this plan use `CCE-140`. The highest CCE key referenced anywhere in the plugin repo today is **CCE-137** (`git log --oneline -60 | grep -o "CCE-[0-9]\+" | sort -t- -k2 -n | tail -3` → `CCE-135 / CCE-136 / CCE-137`).

  **Cross-track key assignment (reconciled 2026-08-10 — do not re-derive).** Track D is a HOST-repo track filed under `ADIS-490`; it consumes no CCE number. The plugin tracks therefore take three consecutive keys, not four:

  | Track | Repo   | Key                                |
  | ----- | ------ | ---------------------------------- |
  | A     | plugin | **CCE-138**                        |
  | C     | plugin | **CCE-139**                        |
  | D     | host   | **ADIS-490** (consumes no CCE key) |
  | B     | plugin | **CCE-140** ← this plan            |

  If the real key differs, substitute it everywhere — it appears only in commit subjects, docstrings and test docstrings, never in code that executes.

- **The plugin repo has no lint/format/typecheck gate.** `pyproject.toml` declares only `pytest`/`pytest-cov`. The full-suite run is the whole gate.

---

## Measurements taken for this plan

Every number below was measured in this session against plugin commit `d7e559c`. No figure is inherited.

| What                                          | Value                                                                                                                                                                                                                                                                                                                                                                        | Command                                                                                                                                |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Plugin test baseline                          | **`1203 passed, 5 skipped`** (re-measured at reconciliation time on a clean tree at `d7e559c`; the `1206` first recorded here was the DIRTY tree — a concurrent agent's `tests/orchestrator/test_zz_tmp_probe.py` contributed +3. That probe file no longer exists; `git status --short` is back to ` M .gitignore` / `?? uv.lock`. **1203 is the figure to plan against.**) | `cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/ -q`                                               |
| Plugin HEAD at planning time                  | `d7e559c`                                                                                                                                                                                                                                                                                                                                                                    | `git rev-parse --short HEAD`                                                                                                           |
| `tests/orchestrator/test_auto_merge.py` size  | 26 tests, 0.30s                                                                                                                                                                                                                                                                                                                                                              | `.venv/bin/python -m pytest tests/orchestrator/test_auto_merge.py -q`                                                                  |
| Highest CCE key in the repo                   | `CCE-137`                                                                                                                                                                                                                                                                                                                                                                    | `git log --oneline -60 \| grep -o "CCE-[0-9]\+" \| sort -t- -k2 -n \| tail -3`                                                         |
| `partial` gate line at HEAD                   | `2857: return skip("partial_run")`                                                                                                                                                                                                                                                                                                                                           | `git show HEAD:scripts/orchestrator_runner.py > /tmp/orun_head.py; grep -n 'return skip("partial_run")' /tmp/orun_head.py`             |
| `fact_check_warnings` gate line at HEAD       | `2859: return skip("fact_check_warnings", …)`                                                                                                                                                                                                                                                                                                                                | same file, `grep -n 'return skip("fact_check_warnings"'`                                                                               |
| Advance fall-through line at HEAD             | `2017: advance_sha = state["current_run"]["head_sha"]`                                                                                                                                                                                                                                                                                                                       | same file, `grep -n 'advance_sha = state\["current_run"\]\["head_sha"\]'`                                                              |
| Cursor computation line at HEAD               | `1979: cursor = _last_processed_merge_sha(prs)`                                                                                                                                                                                                                                                                                                                              | same file, `grep -n 'cursor = _last_processed_merge_sha'`                                                                              |
| Authoring-loop truncation reason line at HEAD | `1569`                                                                                                                                                                                                                                                                                                                                                                       | same file, `grep -n 'f"time_budget_exceeded: authored'`                                                                                |
| `time_truncated` init / admission set         | `1474` / `1491`                                                                                                                                                                                                                                                                                                                                                              | same file, `grep -n 'time_truncated = '`                                                                                               |
| `config.schema.json` `run` block              | has `"additionalProperties": false`                                                                                                                                                                                                                                                                                                                                          | `.venv/bin/python -c "import json;print(json.load(open('templates/config.schema.json'))['properties']['run'])"`                        |
| `state.schema.json` root                      | **no** `additionalProperties: false`, `required` is `["version"]` only                                                                                                                                                                                                                                                                                                       | `.venv/bin/python -c "import json;s=json.load(open('templates/state.schema.json'));print(s['required'], 'additionalProperties' in s)"` |
| `dismissed_gap_flags` shape (the precedent)   | `{"type":"object","additionalProperties":{"type":"string"}}`, keys `{owner}/{name}#{pr}`                                                                                                                                                                                                                                                                                     | `templates/state.schema.json:20-24`                                                                                                    |
| Live `pr_id` key format in the runner         | `f"{repo['owner']}/{repo['name']}#{pr['number']}"`                                                                                                                                                                                                                                                                                                                           | `scripts/orchestrator_runner.py:1901`                                                                                                  |

### Working-tree caveat — RESOLVED, kept for the line-number rule it implies

At planning time `git status --short` in the plugin repo showed, besides the two pre-existing entries (` M .gitignore`, `?? uv.lock`), a concurrent agent's uncommitted probe (` M scripts/orchestrator_runner.py` with `time_truncated = True` inserted, and `?? tests/orchestrator/test_zz_tmp_probe.py`). **Both are gone as of reconciliation.** Re-measured: the tree carries only ` M .gitignore` and `?? uv.lock`, and the suite is `1203 passed, 5 skipped`. Nothing to delete.

The rule that episode produced still stands and is why this plan is written the way it is: **every line number below is measured against committed `HEAD` (`d7e559c`), i.e. BEFORE Track A.** After Track A lands, every line at or below 1572 shifts by **+1**; after Track C lands, the fact-checker region shifts again. All edits in this plan are anchored on exact source text, not line numbers, so both shifts are harmless — the line numbers are navigation aids only. Never anchor an edit on a number in this file.

---

## File Structure

| File                                               | Change | Responsibility after the change                                                                                                                                                                                       |
| -------------------------------------------------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/orchestrator_runner.py`                   | Modify | Owns the merge gate, the advance block, and the new pure deferral helpers. All four helpers are module-level and pure so they are unit-testable without a git repo or a fake gh client.                               |
| `templates/config.schema.json`                     | Modify | Declares `run.deferral_skip_threshold`. **Required**, not cosmetic: the `run` block sets `additionalProperties: false`, so an undeclared key makes `load_config_validated` raise `ConfigError` and the runner exit 2. |
| `templates/state.schema.json`                      | Modify | Declares `skipped_prs` and `deferral_counts`. Cosmetic for validation (the root has no `additionalProperties: false`) but load-bearing for discoverability and for the operator who reads state.json.                 |
| `scripts/state_io.py`                              | Modify | Gains `merge_skipped_pr_records()` — the single writer of `skipped_prs`, next to `add_partial` which is the single writer of `partial_reasons`.                                                                       |
| `tests/orchestrator/test_auto_merge.py`            | Modify | Gate unit tests. One existing test (`test_fact_warnings_demote_to_manual_review`) is **rewritten**, not deleted — it inverts.                                                                                         |
| `tests/orchestrator/test_deferral_skip.py`         | Create | Pure-helper unit tests + the end-to-end skip integration test.                                                                                                                                                        |
| `tests/orchestrator/test_cursor_backed_merge.py`   | Create | The dangerous-case tests: partial-to-full-HEAD must not merge; partial-cursor-backed must.                                                                                                                            |
| `tests/orchestrator/test_time_budget_authoring.py` | Modify | Cursor-narrowing integration test lives with the other authoring-truncation tests.                                                                                                                                    |
| `tests/schemas/test_state_schema.py`               | Modify | Schema acceptance + pre-`skipped_prs` back-compat.                                                                                                                                                                    |
| `tests/schemas/test_config_schema.py`              | Modify | `run.deferral_skip_threshold` accepted; an unknown `run` key still rejected.                                                                                                                                          |
| `CHANGELOG.md`                                     | Modify | `## [Unreleased] / ### Fixed` entry, matching the existing `**CCE-NNN** — …` prose style.                                                                                                                             |
| `README.md`                                        | Modify | The merge paragraph currently says a partial run "disables auto-merge"; that becomes false.                                                                                                                           |

---

## Interfaces — track-level summary

**Consumes from Track A (hard dependency).** Track A sets `time_truncated = True` immediately before the `break` in the authoring-truncation branch of `run()` (`scripts/orchestrator_runner.py`, the `if deadline is not None and i > 0 and clock() > deadline:` guard that emits `f"time_budget_exceeded: authored {i}/{len(per_target)} page batches …"`, HEAD line 1566-1572). Without it an authoring-truncated run falls through to `advance_sha = state["current_run"]["head_sha"]` at HEAD line 2017 and this track's whole gate is dead: `advance_cursor_backed` would be `False` on every authoring-truncated run, and `partial → skip("partial_run")` would fire exactly as it does today. **Verify Track A landed before starting Task 1:** `grep -n -A 8 'time_budget_exceeded: authored' scripts/orchestrator_runner.py` must show `time_truncated = True` between the `add_partial(...)` call and the `break`. If it does not, stop and land Track A first.

**Produces for other tracks.** Nothing. Track B is terminal — no other track consumes its symbols. Everything it exports is internal to `scripts/orchestrator_runner.py` and `scripts/state_io.py`.

**Produces for the host repo (operator-facing surface).** One new host config key, `run.deferral_skip_threshold` (integer, default 3, `0` disables skipping). Track D does **not** need to set it; the default is the spec's value. Two new `state.json` keys that appear only once a skip happens.

---

## Design notes you need before Task 1

Read these once. They are the reasoning the tasks assume; without them several edits look arbitrary.

### The cursor is a prefix boundary

`_last_processed_merge_sha(admitted_prs)` (`scripts/orchestrator_runner.py:406`) scans the oldest-first admitted list from the end and returns the newest non-empty `merge_sha`. `_order_prs_oldest_first` guarantees the list is in window order. The baseline advance is therefore a **prefix boundary**: advancing to PR _k_'s merge sha declares every PR at index ≤ _k_ done. If PR 2 is unprocessed and PR 3 is processed, advancing to PR 3 strands PR 2 outside every future window forever — there is no mechanism that ever re-collects it.

Today the admitted list is the only input, and admission truncation is the only way a PR leaves it. After Track A, an **authoring**-truncated run also takes the cursor path — but `prs` still holds every admitted PR, including ones whose page batches were never authored. So `_last_processed_merge_sha(prs)` on that path names a PR whose pages did not land. That is precisely what Decision 2 forbids ("the baseline advances only to the last PR whose pages all landed"), and it is what Track B's own acceptance requires ("the baseline moves by exactly the clean PRs"). Task 1 closes it. This is not scope creep bolted onto change #1 — it is the precondition that makes "cursor-backed" mean anything, and it shares all its machinery with change #3.

### Why `app_token_unavailable` needs an explicit veto

`README.md:47` and `scripts/orchestrator_runner.py:1377-1386` document a deliberate coupling: when the GitHub App token cannot be minted, the run records a **blocking** `app_token_unavailable` reason _for the express purpose of flipping `partial` so auto-merge skips_. The stated reason — "a PR built on the fallback `GITHUB_TOKEN` never triggers host CI, so its check list would be empty rather than green" — is exactly the `if not items: … break` zero-checks path in `_maybe_auto_merge` (HEAD 2904-2906), which merges after the grace window.

Relaxing `partial` from an unconditional block to a cursor-conditional one therefore re-opens that hole: a nightly that is _both_ app-token-degraded _and_ time-truncated with a valid cursor would merge an unvalidated PR. Task 3 adds an explicit veto list so the coupling survives the relaxation as a named rule rather than as a side effect of a gate that is going away.

`deferral_skip:` reasons are deliberately **not** on the veto list. A skip only ever happens on a truncated run, its whole purpose is to let the cursor advance past a stuck PR, and that advance only reaches `main` if the run merges. Vetoing it would make the skip a no-op that re-fires forever.

### The human-edit guard — does it interact? (asked explicitly; answered here)

There are two guards, and they are the same authority applied at two seams:

- `_auto_close_superseded_prs`, HEAD **2765-2796** — before closing a superseded `docs-agent/*` PR, `gh.pr_view_commits(prior_num)` is fetched and any non-bot author aborts the close with an `info_only` `auto_close_skipped:{n}:human_edited` reason.
- `_maybe_auto_merge`, HEAD **2864-2870** — the identical lookup on the PR about to be merged; any non-bot author returns `skip("human_edited")`.

**Verdict: Track B changes neither guard, and must not. But the interaction is real and it changes character in three ways, so the plan pins all three with tests rather than leaving them to inference.**

1. **Ordering.** The guard sits _after_ the `partial` gate in `_maybe_auto_merge`. Today, on this host, that means it is unreachable for merge purposes — every run is partial, so `skip("partial_run")` returns at HEAD 2857 and `gh.pr_view_commits` is never called on the merge path. Track B makes the guard reachable **every night**. It goes from dead code to the primary human override. Task 3 keeps it strictly after the new gate (a human-edited PR must not merge even with a perfect cursor) and Task 3 Step 1 pins that with a test that would pass vacuously today.
2. **Failure mode.** `commits_lookup_failed` (HEAD 2865-2866) is a conservative skip. It also goes from unreachable to load-bearing: a flaky `gh` now costs a night's merge instead of nothing. That is the correct trade and no change is needed, but it is why the existing `test_commits_lookup_failure_skips_conservatively` must keep passing untouched.
3. **Composition with auto-close.** A human who pushes a commit onto tonight's docs-agent PR blocks tonight's merge (`human_edited`); the PR stays open; tomorrow's `_auto_close_superseded_prs` _also_ refuses to close it (`auto_close_skipped:…:human_edited`) and opens a fresh branch alongside. That composition is already correct and already tested in `tests/orchestrator/test_auto_close_superseded.py` — Track B neither improves nor degrades it. **No change; no new test for the auto-close side.**

### Back-compat for a `state.json` that predates `skipped_prs`

`load_state_validated` (`scripts/state_io.py:191-200`) validates against `templates/state.schema.json`, whose root declares `"required": ["version"]` and — measured — sets **no** `additionalProperties: false`. Consequences, all of which the tasks below assert rather than assume:

- A pre-existing `state.json` (e.g. the host's, or `tests/fixtures/e2e_host/.engineering-docs-agent/state.json`, literally `{ "version": "1", "dismissed_gap_flags": {}, "cursors": {} }`) validates unchanged. **There is no migration step and no version bump.** Absent keys are read with `state.get("skipped_prs", [])` / `state.get("deferral_counts", {})`.
- The reverse also holds: a state.json written by the _new_ runner validates against the _old_ schema, so a rollback of the plugin to a pre-Track-B commit does not brick the host. This matters because the plugin is consumed at `ref: main` with no release step (Global Constraints, Risk 3).
- Neither key is ever seeded empty. A host that never skips keeps a `state.json` byte-identical to today's. `save_persistent_state` (`scripts/state_io.py:206-213`) serialises whatever keys the dict has, so "don't create it empty" is enforced by the writer, and Task 8 Step 1 pins it.

---

## Task 1 — Hold unfinished PRs out of the advance cursor

**Files:**

- Modify: `scripts/orchestrator_runner.py` (add `advance_cursor_list` near `_last_processed_merge_sha` at :406; record deferrals in the admission loop :1476-1492 and the authoring loop :1559-1572; consume them in the advance block :1972-2017)
- Test: `tests/orchestrator/test_deferral_skip.py` (create), `tests/orchestrator/test_time_budget_authoring.py` (modify), **`tests/orchestrator/test_authoring_truncation_advance.py` (modify — Track A's file; three of its five tests invert here, see Step 9)**

**Interfaces:**

- Consumes: Track A's `time_truncated = True` in the authoring-truncation branch (see the track-level Interfaces block; verify with the `grep` given there before starting).
- Consumes, from the existing `run()` body — all measured in scope at the advance block, none introduced by this plan:
  - `pr_by_number: dict[int, dict]`, built at `scripts/orchestrator_runner.py:1548` as `{pr.get("number"): pr for pr in prs}` **after** admission truncation, so it holds only ADMITTED PRs. That is exactly right for `deferred_pages_by_pr` (whose keys are all admitted) and is why Task 8's `_deferred_all` guards the lookup with `if n in pr_by_number`.
  - `repo: dict` with `owner`/`name`, assigned once at `:1340` (`detect_repo(repo_root)`).
  - `now: str`, the ISO timestamp assigned once at `:1347`.
  - `config: dict`, assigned once at `:1316`.
- Produces: `advance_cursor_list(admitted: list[dict], deferred_tail: list[dict], *, held_back: set) -> list[dict]` — consumed by Task 2 (`advance_cursor_backed`) and Task 8 (skip forgiveness). Also produces the run-local names `window_prs: list[dict]`, `admission_deferred: list[dict]`, `deferred_pages_by_pr: dict[int, list[str]]`, all read by Task 8.
- **Retires** Track A's `advance == cursor` acceptance for the authoring path, replacing it with spec Decision 2's stricter `advance == the last PR whose pages all landed`. Step 9 carries the exact rewrites. Nothing outside `tests/orchestrator/test_authoring_truncation_advance.py` is affected.

- [ ] **Step 1: Write the failing unit test for the new helper**

Create `tests/orchestrator/test_deferral_skip.py` with exactly this content:

```python
# tests/orchestrator/test_deferral_skip.py
"""CCE-140: per-PR deferral counting, cursor narrowing, and the skip hatch.

The CCE-109 advance cursor is a PREFIX boundary: advancing the baseline to
PR k's merge sha declares every PR at index <= k done. So a PR this run did
not finish must stop the walk, and a PR the operator has decided to abandon
must not stop it. These tests pin both directions.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as orun  # noqa: E402


def _pr(n: int, sha: str | None = None) -> dict:
    d = {"number": n, "title": f"PR {n}", "url": f"https://github.com/o/r/pull/{n}"}
    if sha:
        d["merge_sha"] = sha
    return d


# ---------------------------------------------------------------------------
# advance_cursor_list
# ---------------------------------------------------------------------------


def test_cursor_list_is_whole_admitted_list_when_nothing_held_back():
    """Today's behaviour, pinned: no deferrals -> the cursor sees every
    admitted PR, exactly as _last_processed_merge_sha(prs) does now."""
    admitted = [_pr(1, "a"), _pr(2, "b"), _pr(3, "c")]
    out = orun.advance_cursor_list(admitted, [], held_back=set())
    assert [p["number"] for p in out] == [1, 2, 3]


def test_cursor_list_stops_at_first_held_back_pr():
    """PR 2 unfinished -> the cursor may only anchor on PR 1. Advancing to
    PR 3 would strand PR 2 outside every future window."""
    admitted = [_pr(1, "a"), _pr(2, "b"), _pr(3, "c")]
    out = orun.advance_cursor_list(admitted, [], held_back={2})
    assert [p["number"] for p in out] == [1]


def test_cursor_list_stops_at_the_first_held_back_pr_not_the_last():
    """Two held-back PRs: the boundary is the OLDEST, never the newest."""
    admitted = [_pr(1, "a"), _pr(2, "b"), _pr(3, "c"), _pr(4, "d")]
    out = orun.advance_cursor_list(admitted, [], held_back={2, 4})
    assert [p["number"] for p in out] == [1]


def test_cursor_list_refuses_everything_when_the_oldest_is_held_back():
    admitted = [_pr(1, "a"), _pr(2, "b")]
    assert orun.advance_cursor_list(admitted, [], held_back={1}) == []


def test_cursor_list_walks_into_the_deferred_tail_when_it_is_forgiven():
    """A PR the admission gate never reached is normally held back. When it
    has been forgiven (skipped), the walk continues into the tail so the
    baseline can finally move past it."""
    admitted = [_pr(1, "a"), _pr(2, "b")]
    tail = [_pr(3, "c"), _pr(4, "d")]
    out = orun.advance_cursor_list(admitted, tail, held_back={4})
    assert [p["number"] for p in out] == [1, 2, 3]


def test_cursor_list_does_not_walk_the_tail_when_an_admitted_pr_is_held_back():
    """Forgiveness of a tail PR must not leap over an unfinished admitted
    one — the boundary is still the oldest unfinished PR."""
    admitted = [_pr(1, "a"), _pr(2, "b")]
    tail = [_pr(3, "c")]
    out = orun.advance_cursor_list(admitted, tail, held_back={2})
    assert [p["number"] for p in out] == [1]


def test_cursor_list_empty_inputs():
    assert orun.advance_cursor_list([], [], held_back=set()) == []
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_deferral_skip.py -q
```

Expected: 7 errors/failures, each `AttributeError: module 'orchestrator_runner' has no attribute 'advance_cursor_list'`.

- [ ] **Step 3: Add the helper**

In `scripts/orchestrator_runner.py`, insert this immediately **after** the `_last_processed_merge_sha` function (which ends with `    return None` at HEAD line 418) and before `def _git_is_ancestor(`:

```python
def advance_cursor_list(
    admitted: list[dict],
    deferred_tail: list[dict],
    *,
    held_back: set,
) -> list[dict]:
    """Return the PR list whose newest merge_sha may anchor the advance.

    CCE-140. ``admitted`` is the oldest-first prefix this run processed;
    ``deferred_tail`` is the oldest-first remainder the admission gate never
    reached. Walk both in window order and stop at the first PR number in
    ``held_back``.

    The CCE-109 cursor is a PREFIX boundary: advancing the baseline to PR k's
    merge sha declares every PR at index <= k done. So the walk must stop at
    the OLDEST unfinished PR, never merely exclude it — advancing past it
    would strand it outside every future window, and nothing ever
    re-collects it.

    ``held_back`` carries PRs this run did not finish (admission-deferred or
    authoring-deferred) MINUS the ones forgiven by the CCE-140 deferral-skip
    hatch. Forgiveness is what lets the walk continue into ``deferred_tail``.

    With ``held_back`` empty and an empty tail this is the identity on
    ``admitted`` — the pre-CCE-140 behaviour.
    """
    out: list[dict] = []
    for pr in list(admitted) + list(deferred_tail):
        if pr.get("number") in held_back:
            break
        out.append(pr)
    return out
```

- [ ] **Step 4: Run the unit tests and watch them pass**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_deferral_skip.py -q
```

Expected: `7 passed`.

- [ ] **Step 5: Write the failing integration test for authoring-deferral narrowing**

Append to `tests/orchestrator/test_time_budget_authoring.py`:

```python
def test_authoring_truncation_does_not_advance_past_unauthored_prs(
    tmp_path, init_host, read_current_run
):
    """CCE-140 / spec Decision 2: 'the baseline advances only to the last PR
    whose pages all landed.'

    The dry-run summarizer fixture is a single static file replayed for every
    PR (scripts/orchestrator_runner.py:617), so all three PRs route to all
    three page batches. Cutting the authoring loop after batch 0 therefore
    leaves work outstanding for PR 1, 2 AND 3 — the oldest unfinished PR is
    the oldest PR, so NOTHING may anchor the cursor and the baseline must not
    move at all.

    Before CCE-140 this run advanced to PR 3's merge sha (the last ADMITTED
    PR) while two thirds of its pages had never been written.
    """
    repo = tmp_path
    fakes = _write_fakes_multi_targets(
        tmp_path.parent / f"fakes_cce140_{tmp_path.name}"
    )
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "seed"}})
    base = _seed_window(repo, state_path)
    # admission gates at 10,20 (all 3 admitted); authoring batch-1 gate at 150.
    clock = _fake_clock([0, 10, 20, 150])
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    head_sha = _git(repo, "rev-parse", "HEAD")
    advance = written["last_successful_run"]["head_sha"]
    # The negative assertion is the one that would have caught the bug.
    assert advance != head_sha, (
        "an authoring-truncated run must never advance to full HEAD; "
        f"advance={advance} head={head_sha}"
    )
    assert advance == base, written["last_successful_run"]
    cr = read_current_run(state_path)
    assert any(
        "time_budget_no_advance_no_cursor" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
```

That test needs two helpers this file does not have. Add them just below the existing `_write_fakes_multi_targets` function:

```python
def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _seed_window(repo: Path, state_path: Path, n: int = 3) -> str:
    """Add n commits on top of the host's init commit and pin the baseline at
    that init commit, so last_sha..HEAD is a real n-commit window. Returns the
    base sha (mirrors test_time_budget._seed_real_window, which returns the
    per-commit shas this test does not need)."""
    base = _git(repo, "rev-parse", "HEAD")
    for i in range(1, n + 1):
        (repo / "f.txt").write_text(f"c{i}")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"c{i}")
    state_path.write_text(
        json.dumps({"version": "1", "last_successful_run": {"head_sha": base}})
    )
    return base
```

and add `import subprocess` to that file's import block (it currently imports only `json`, `sys`, `Path`), so the header reads:

```python
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
```

- [ ] **Step 6: Run it and watch it fail**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest "tests/orchestrator/test_time_budget_authoring.py::test_authoring_truncation_does_not_advance_past_unauthored_prs" -q
```

Expected: FAIL on the `advance != head_sha` assertion — the message shows `advance` equal to the third seeded commit (the last admitted PR's merge sha), not `base`. If instead it fails with `assert advance != head_sha` where the two are literally equal, Track A has **not** landed; stop and land Track A.

- [ ] **Step 7: Record the deferrals and consume them in the advance block**

Four edits in `scripts/orchestrator_runner.py`.

**7a.** Capture the full window and replace the `deferred_unanchored` bookkeeping. Find (HEAD 1474-1475):

```python
        time_truncated = False
        deferred_unanchored = False
```

Replace with:

```python
        time_truncated = False
        # CCE-140: the full window, oldest-first, before admission truncation.
        # Deferral counting is keyed to the window a run actually saw.
        window_prs = list(prs)
        # PRs the admission gate never reached (oldest-first), and the pages
        # an admitted PR still owes because the authoring loop was cut.
        admission_deferred: list[dict] = []
        deferred_pages_by_pr: dict[int, list[str]] = {}
```

**7b.** Find the admission-truncation body (HEAD 1484-1491):

```python
                # A deferred PR without a merge_sha can't be re-anchored by the
                # next window — advancing past it would lose it forever, so the
                # advance block below must refuse when any exist.
                deferred_unanchored = any(
                    not (p.get("merge_sha") or "").strip() for p in prs[i:]
                )
                prs = prs[:i]
                time_truncated = True
```

Replace with:

```python
                # A deferred PR without a merge_sha can't be re-anchored by the
                # next window — advancing past it would lose it forever, so the
                # advance block below must refuse when any exist. CCE-140 moves
                # that test into the advance block so it can be evaluated over
                # the STILL-deferred set (a PR forgiven by the deferral-skip
                # hatch is deliberately being lost and must not block).
                admission_deferred = prs[i:]
                prs = prs[:i]
                time_truncated = True
```

**7c.** Find the authoring-truncation body. **After Track A has landed** it reads (HEAD 1566-1572 plus Track A's inserted line):

```python
            if deadline is not None and i > 0 and clock() > deadline:
                add_partial(
                    state,
                    f"time_budget_exceeded: authored {i}/{len(per_target)} "
                    f"page batches (budget {budget}s); deferring the rest",
                )
                time_truncated = True
                break
```

Replace with:

```python
            if deadline is not None and i > 0 and clock() > deadline:
                add_partial(
                    state,
                    f"time_budget_exceeded: authored {i}/{len(per_target)} "
                    f"page batches (budget {budget}s); deferring the rest",
                )
                # CCE-140: an admitted PR whose page batch was never written
                # is NOT done. Record which pages it still owes so the advance
                # block can hold it out of the cursor prefix (spec Decision 2:
                # "the baseline advances only to the last PR whose pages all
                # landed") and so a skip record can name the page.
                for _dkey, _dbatch in list(per_target.items())[i:]:
                    for _ds in _dbatch:
                        _dn = _ds.get("pr_number")
                        if _dn is None:
                            continue
                        deferred_pages_by_pr.setdefault(_dn, []).append(
                            f"{_dkey[0]}/{_dkey[1]}"
                        )
                time_truncated = True
                break
```

**7d.** Rewire the advance block. Find (HEAD 1978-1994):

```python
            advance_sha = prior_baseline_sha
            cursor = _last_processed_merge_sha(prs)
            window = f"{(prior_baseline_sha or '(root)')[:8]}..{head_sha[:8]}"
            full_cursor = _rev_parse_commit(repo_root, cursor) if cursor else None
            if cursor is None:
                add_partial(
                    state,
                    "time_budget_no_advance_no_cursor: truncated run had no "
                    "admitted PR with a usable merge_sha; baseline unchanged",
                )
            elif deferred_unanchored:
```

Replace with:

```python
            advance_sha = prior_baseline_sha
            # CCE-140: hold every PR this run did not finish out of the cursor
            # prefix. `skipped_numbers` is populated in the deferral-skip block
            # below; on a run with no skips it is empty and `held_back` is
            # exactly "everything unfinished".
            held_back = (
                set(deferred_pages_by_pr)
                | {p.get("number") for p in admission_deferred}
            ) - skipped_numbers
            still_deferred = [
                p
                for p in list(admission_deferred)
                + [
                    pr_by_number[n]
                    for n in sorted(deferred_pages_by_pr)
                    if n in pr_by_number
                ]
                if p.get("number") in held_back
            ]
            cursor_prs = advance_cursor_list(
                prs, admission_deferred, held_back=held_back
            )
            cursor = _last_processed_merge_sha(cursor_prs)
            window = f"{(prior_baseline_sha or '(root)')[:8]}..{head_sha[:8]}"
            full_cursor = _rev_parse_commit(repo_root, cursor) if cursor else None
            if cursor is None:
                add_partial(
                    state,
                    "time_budget_no_advance_no_cursor: truncated run had no "
                    "admitted PR with a usable merge_sha; baseline unchanged",
                )
            elif any(not (p.get("merge_sha") or "").strip() for p in still_deferred):
```

> `skipped_numbers` does not exist yet — Task 8 introduces it. To keep this task's tests green on their own, also add the following line immediately **before** `advance_sha = prior_baseline_sha` in the same block; Task 8 replaces it with the real computation:
>
> ```python
>             skipped_numbers: set = set()
> ```

- [ ] **Step 8: Run the integration test and watch it pass**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest "tests/orchestrator/test_time_budget_authoring.py::test_authoring_truncation_does_not_advance_past_unauthored_prs" -q
```

Expected: `1 passed`.

- [ ] **Step 9: Reconcile Track A's acceptance tests — THREE OF THEM INVERT HERE**

**This step is not optional and it is not cleanup.** Track A (CCE-138) shipped `tests/orchestrator/test_authoring_truncation_advance.py` with five tests. Task 1's cursor narrowing changes what three of them must assert, because Track A's acceptance ("an authoring-truncated run advances to the last processed PR's merge sha") is exactly what spec Decision 2 supersedes ("the baseline advances only to the last PR whose pages all landed"). Reconciled by measurement against the real fixtures, not by inference:

| Track A test                                                        | Fixture                                   | Behaviour after Track A                                         | Behaviour after Task 1                                                                                                                                                                          | Action      |
| ------------------------------------------------------------------- | ----------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| `test_authoring_truncation_advances_to_cursor_not_head`             | 3 PRs (`c1..c3`), 3 doc_targets, cut at 1 | `advance == c3`                                                 | all three PRs owe pages in the deferred batches, so `held_back == {1,2,3}`, `advance_cursor_list` returns `[]`, `cursor is None` → `advance == base`, reason `time_budget_no_advance_no_cursor` | **REWRITE** |
| `test_authoring_truncation_without_cursor_holds_baseline`           | 3 PRs, no `merge_sha`                     | `advance == base`, `time_budget_no_advance_no_cursor`           | identical                                                                                                                                                                                       | unchanged   |
| `test_authoring_truncation_with_unresolvable_cursor_holds_baseline` | stock `fakes_multi` shas `a`/`b`/`c`      | `advance == "old_sha_000"`, `time_budget_advance_out_of_window` | `advance == "old_sha_000"` still, but the **reason** becomes `time_budget_no_advance_no_cursor` (the walk empties before rev-parse is ever reached)                                             | **REWRITE** |
| `test_authoring_truncation_never_reports_unanchored_deferred`       | PRs `c1`/none/`c3`, 3 doc_targets         | `advance == c3`                                                 | `advance == base`; the absence assertion still holds                                                                                                                                            | **REWRITE** |
| `test_admission_truncation_advance_unchanged_by_track_a`            | 1 doc_target, admission cut at 2/3        | `advance == c2`, `window_head_sha == c4`                        | identical — `deferred_pages_by_pr` is empty, `held_back == {3}`, walk yields `[pr1, pr2]`                                                                                                       | unchanged   |

Why the first row holds back all three PRs: `dispatch_subagent` replays one static fixture per agent (`scripts/orchestrator_runner.py:617-618`), and the runner then stamps the real number onto each summary (`summary_with_pr = {**summary, "pr_number": pr["number"]}`, `scripts/orchestrator_runner.py:1518`). Every PR therefore contributes a summary to every `(lens, page_hint)` batch, so cutting the authoring loop after batch 0 leaves all three PRs owing pages.

Confirm the damage first, so the rewrite is driven by an observed failure and not by this table:

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_authoring_truncation_advance.py -q 2>&1 | tail -6
```

Expected: `3 failed, 2 passed`, naming `test_authoring_truncation_advances_to_cursor_not_head`, `test_authoring_truncation_with_unresolvable_cursor_holds_baseline` and `test_authoring_truncation_never_reports_unanchored_deferred`.

Now apply the three rewrites.

**9a.** In `tests/orchestrator/test_authoring_truncation_advance.py`, rename `test_authoring_truncation_advances_to_cursor_not_head` to `test_authoring_truncation_holds_baseline_when_every_pr_owes_pages` and replace its three trailing state assertions. Change:

```python
    assert head == c4
    # THE assertion: the bug was a fall-through to head, so the negative is
    # what discriminates. Keep it even though the positive below implies it.
    assert advance != head, written["last_successful_run"]
    assert advance == c3, written["last_successful_run"]
    # A truncated run also stamps the window it covered for the CCE-43 guard.
    assert written["last_successful_run"].get("window_head_sha") == c4, written[
        "last_successful_run"
    ]
```

to:

```python
    assert head == c4
    # THE assertion, unchanged and still the discriminating one: the bug
    # Track A fixed was a fall-through to head.
    assert advance != head, written["last_successful_run"]
    # CCE-140 narrowed the cursor. The summarizer fixture is replayed per PR
    # (orchestrator_runner.py:617) and the runner stamps the real number onto
    # each summary (:1518), so every PR contributes to every page batch —
    # cutting after batch 0 leaves ALL THREE PRs owing pages, the walk stops
    # at the oldest one, and nothing may anchor the advance. Before CCE-140
    # this asserted `advance == c3`, i.e. an advance past two PRs whose pages
    # were never written; spec Decision 2 forbids exactly that.
    assert advance == base, written["last_successful_run"]
    # A truncated run still stamps the window it covered for the CCE-43 guard.
    assert written["last_successful_run"].get("window_head_sha") == c4, written[
        "last_successful_run"
    ]
    cr = read_current_run(state_path)
    assert any(
        "time_budget_no_advance_no_cursor" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
```

and add `read_current_run` to that test's parameter list, so its signature reads:

```python
def test_authoring_truncation_holds_baseline_when_every_pr_owes_pages(
    tmp_path, init_host, read_current_run
):
```

**9b.** In `test_authoring_truncation_with_unresolvable_cursor_holds_baseline`, the advance assertions are unchanged; only the reason changes. Replace:

```python
    cr = read_current_run(state_path)
    assert any(
        "time_budget_advance_out_of_window" in r and "unresolvable" in r
        for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
```

with:

```python
    # CCE-140: the cursor walk now empties before any sha is rev-parsed (all
    # three PRs owe pages), so the run refuses at the no_cursor branch rather
    # than at out_of_window. The baseline outcome — held, not advanced — is
    # identical, which is what this test exists to pin. The out_of_window
    # branch stays covered from the ADMISSION path by
    # tests/orchestrator/test_time_budget.py.
    cr = read_current_run(state_path)
    assert any(
        "time_budget_no_advance_no_cursor" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
```

**9c.** In `test_authoring_truncation_never_reports_unanchored_deferred`, replace:

```python
    assert advance != c4, written["last_successful_run"]
    assert advance == c3, written["last_successful_run"]
```

with:

```python
    assert advance != c4, written["last_successful_run"]
    # CCE-140: all three PRs owe pages, so the walk stops at PR #1 and the
    # baseline holds. The point of the test is unchanged and is the assertion
    # below: `unanchored_deferred` must stay silent on the authoring path,
    # because `admission_deferred` is empty when the admission gate completed.
    assert advance == base, written["last_successful_run"]
```

- [ ] **Step 10: Run every test that touches the advance block**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_time_budget.py tests/orchestrator/test_time_budget_authoring.py tests/orchestrator/test_authoring_truncation_advance.py tests/orchestrator/test_state_advancement_invariant.py tests/orchestrator/test_deferral_skip.py -q
```

Expected: all pass, `test_authoring_truncation_advance.py` contributing 5. `test_truncation_refuses_advance_when_deferred_pr_unanchored` in particular must still pass — PR 2 has no `merge_sha`, is admission-deferred, is not skipped (no counts yet), so it lands in `still_deferred` and the `elif` fires exactly as before.

- [ ] **Step 11: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent && git add scripts/orchestrator_runner.py tests/orchestrator/test_deferral_skip.py tests/orchestrator/test_time_budget_authoring.py tests/orchestrator/test_authoring_truncation_advance.py && git commit -m "fix(CCE-140): hold unfinished PRs out of the advance cursor

The CCE-109 cursor is a prefix boundary, but it was computed over the whole
admitted list. After the authoring loop learned to truncate, that meant a
run could advance past PRs whose page batches were never written. The walk
now stops at the oldest unfinished PR, per spec Decision 2."
```

---

## Task 2 — Report whether the advance was cursor-backed

**Files:**

- Modify: `scripts/orchestrator_runner.py` (advance block :1972-2017)
- Test: `tests/orchestrator/test_cursor_backed_merge.py` (create)

**Interfaces:**

- Consumes: `advance_cursor_list` from Task 1; Track A's `time_truncated`.
- Produces: the run-local boolean `advance_cursor_backed`, read by Task 3's `_maybe_auto_merge` call site. Semantics: `True` **iff** `advance_sha` was assigned from `full_cursor` after passing `_sha_in_window`. It is `False` for a non-truncated run (which advances to full HEAD), and `False` for a truncated run that refused to advance (baseline unchanged).

- [ ] **Step 1: Write the failing test**

Create `tests/orchestrator/test_cursor_backed_merge.py`:

```python
# tests/orchestrator/test_cursor_backed_merge.py
"""CCE-140: a partial run may merge only when its advance is cursor-backed.

The dangerous case first. A run that is partial for a reason UNRELATED to the
time budget (a lint block, a failed dispatch) is not time-truncated, so its
advance falls through to full HEAD. Merging that run promotes a baseline past
work whose pages were reverted -- the silent-loss bug, automated nightly. It
must stay blocked.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as runner  # noqa: E402

FAKES_BLOCK = Path(__file__).parent / "fakes_block"
FAKES_MULTI = Path(__file__).parent / "fakes_multi"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_lint_block_partial_run_advances_to_head_and_is_not_cursor_backed(
    tmp_path, init_host, read_current_run
):
    """THE DANGEROUS CASE. A lint-block partial run is not time-truncated, so
    it advances to full HEAD (pinned by test_state_advancement_invariant).
    This test pins the OTHER half: that advance is not cursor-backed, so the
    Task-3 gate will refuse to merge it."""
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "old_sha_000"}}
    )
    head_sha = _git(tmp_path, "rev-parse", "HEAD")
    captured: dict = {}
    real = runner._maybe_auto_merge

    def spy(gh, **kw):
        captured.update(kw)
        return real(gh, **kw)

    runner._maybe_auto_merge = spy
    try:
        rc = runner.run(tmp_path, dry_run_dir=FAKES_BLOCK, no_pr=True)
    finally:
        runner._maybe_auto_merge = real
    assert rc == 0
    cr = read_current_run(state_path)
    assert cr["partial"] is True
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == head_sha
    assert runner._LAST_ADVANCE_CURSOR_BACKED is False, (
        "a run that advanced to full HEAD must never report a cursor-backed "
        "advance -- that flag is the only thing standing between a lint-block "
        "partial and an automatic merge"
    )


def test_truncated_run_with_a_real_cursor_reports_cursor_backed(
    tmp_path, init_host
):
    """The permitted case: admission truncation with a verified in-window
    cursor. advance_sha comes from the cursor, so the flag is True and the
    advance is strictly less than HEAD."""
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "seed"}})
    base = _git(repo, "rev-parse", "HEAD")
    shas = []
    for i in range(1, 4):
        (repo / "f.txt").write_text(f"c{i}")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    state_path.write_text(
        json.dumps({"version": "1", "last_successful_run": {"head_sha": base}})
    )
    c1, c2, c3 = shas
    fakes = tmp_path.parent / f"fakes_cce140_cb_{tmp_path.name}"
    fakes.mkdir(parents=True, exist_ok=True)
    for f in FAKES_MULTI.iterdir():
        (fakes / f.name).write_text(f.read_text())
    sc = json.loads((FAKES_MULTI / "fake_source_collector.json").read_text())
    for pr, sha in zip(sc["prs"], [c1, c2, c3]):
        pr["merge_sha"] = sha
    (fakes / "fake_source_collector.json").write_text(json.dumps(sc))

    it = iter([0, 50, 150])
    clock = lambda: next(it, 150)  # noqa: E731
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=clock,
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    assert advance == c2, written["last_successful_run"]
    assert advance != c3, "cursor-backed advance must not reach full HEAD"
    assert runner._LAST_ADVANCE_CURSOR_BACKED is True
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_cursor_backed_merge.py -q
```

Expected: 2 failures, both `AttributeError: module 'orchestrator_runner' has no attribute '_LAST_ADVANCE_CURSOR_BACKED'`.

- [ ] **Step 3: Compute the flag**

Three edits in `scripts/orchestrator_runner.py`.

**3a.** Add the test-observable module global. Insert immediately after `_CHECKS_POLL_INTERVAL_SECONDS = 15.0` (HEAD line 316):

```python

# CCE-140 test seam: the last run's `advance_cursor_backed` decision. run()
# stamps it on every pass so an integration test can assert the gate input
# without threading a return value through run()'s int contract. Never read
# by production code — _maybe_auto_merge takes the value as an argument.
_LAST_ADVANCE_CURSOR_BACKED = False
```

**3b.** Initialise and set the flag in the advance block. Find the two lines added in Task 1 Step 7d plus their neighbour:

```python
            skipped_numbers: set = set()
            advance_sha = prior_baseline_sha
```

Replace with:

```python
            skipped_numbers: set = set()
            advance_sha = prior_baseline_sha
            advance_cursor_backed = False
```

Then find (HEAD 2008-2009, unchanged by Task 1):

```python
                if ok:
                    advance_sha = full_cursor
```

Replace with:

```python
                if ok:
                    advance_sha = full_cursor
                    advance_cursor_backed = True
```

**3c.** Set it to `False` on the non-truncated path and publish it. Find (HEAD 2016-2021):

```python
        else:
            advance_sha = state["current_run"]["head_sha"]
        state["last_successful_run"] = {
            "head_sha": advance_sha,
            "completed_at": now,
        }
```

Replace with:

```python
        else:
            advance_sha = state["current_run"]["head_sha"]
            # A non-truncated run advances to the full window HEAD. That is
            # correct when the run is clean, and it is exactly the advance the
            # CCE-140 merge gate must refuse to merge when the run is partial.
            advance_cursor_backed = False
        global _LAST_ADVANCE_CURSOR_BACKED
        _LAST_ADVANCE_CURSOR_BACKED = advance_cursor_backed
        state["last_successful_run"] = {
            "head_sha": advance_sha,
            "completed_at": now,
        }
```

> `global _LAST_ADVANCE_CURSOR_BACKED` must appear before any other use of the name inside `run()`. It does — this is the only reference.

- [ ] **Step 4: Run the test and watch it pass**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_cursor_backed_merge.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent && git add scripts/orchestrator_runner.py tests/orchestrator/test_cursor_backed_merge.py && git commit -m "feat(CCE-140): report whether a run's baseline advance came from the cursor

advance_cursor_backed is True only when advance_sha was assigned from a
cursor that passed the CCE-109 in-window guard. A non-truncated run (full
HEAD) and a truncated run that refused to advance both report False."
```

---

## Task 3 — Gate auto-merge on cursor-backing, with an explicit veto list

**Files:**

- Modify: `scripts/orchestrator_runner.py` (`_maybe_auto_merge` :2817-2870; its call site :2077-2087)
- Test: `tests/orchestrator/test_auto_merge.py`, `tests/orchestrator/test_cursor_backed_merge.py`

**Interfaces:**

- Consumes: `advance_cursor_backed` from Task 2.
- Produces: `_maybe_auto_merge(..., advance_cursor_backed: bool = False, partial_reasons: tuple[str, ...] = ())` — both new keyword-only parameters carry defaults so every existing call and every existing test keeps working. Also produces `merge_veto_reason(partial_reasons) -> str | None` and the module constant `_MERGE_VETO_REASON_PREFIXES: tuple[str, ...]`.

- [ ] **Step 1: Write the failing gate tests**

Append to `tests/orchestrator/test_auto_merge.py`:

```python
# ---------------------------------------------------------------------------
# CCE-140: partial runs merge when — and only when — cursor-backed
# ---------------------------------------------------------------------------


def test_partial_run_with_full_head_advance_still_never_merges():
    """THE DANGEROUS CASE, at the gate. Relaxing `partial` must not relax it
    for a run whose advance_sha is the full window HEAD: merging that promotes
    a baseline past pages that were reverted."""
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green()]))
    outcome, reasons = _run(gh, partial=True, advance_cursor_backed=False)
    assert outcome == {"merged": False, "reason": "partial_run"}
    assert reasons == [("auto_merge_skipped: partial_run", True)]
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_partial_run_with_cursor_backed_advance_merges():
    """Spec Decision 2: a partial run whose advance came from the cursor has,
    by construction, advanced only past PRs whose pages all landed."""
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green()]))
    outcome, reasons = _run(gh, partial=True, advance_cursor_backed=True)
    assert outcome == {"merged": True, "reason": None}
    assert ("pr_merge", (7,)) in gh.calls
    assert ("auto_merge_succeeded: pr=7", True) in reasons


def test_cursor_backed_partial_still_loses_to_the_human_edit_guard():
    """The human-edit guard sits AFTER the new gate and must stay decisive.
    Before CCE-140 this assertion was vacuous on every real host: no partial
    run ever reached the guard, because skip('partial_run') returned first."""
    gh = _eligible_gh(
        pr_view_commits=GhResult(
            ok=True,
            value=[
                {"authors": [_bot_author()]},
                {"authors": [{"name": "Theo", "login": "theoju", "email": "t@x.com"}]},
            ],
        ),
        pr_checks=GhResult(ok=True, value=[_green()]),
    )
    outcome, _ = _run(gh, partial=True, advance_cursor_backed=True)
    assert outcome["reason"] == "human_edited"
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_app_token_unavailable_vetoes_even_a_cursor_backed_partial():
    """README:47 / orchestrator_runner.py:1377 record app_token_unavailable as
    a BLOCKING reason expressly so auto-merge skips: a PR built on the fallback
    GITHUB_TOKEN never fires host CI, so `pr_checks` returns [] and the
    zero-checks path would read that as 'nothing failed'. The cursor proves
    the BASELINE is honest; it says nothing about whether the PR is safe to
    land."""
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[]))
    outcome, reasons = _run(
        gh,
        partial=True,
        advance_cursor_backed=True,
        partial_reasons=(
            "app_token_unavailable: GitHub App installation token could not "
            "be minted; run degraded to GITHUB_TOKEN, so host CI will not "
            "fire on this PR. Verify the App is installed on this repo.",
        ),
    )
    assert outcome["reason"] == "merge_vetoed"
    assert reasons[0][0].startswith(
        "auto_merge_skipped: merge_vetoed: app_token_unavailable"
    )
    assert reasons[0][1] is True
    assert not [c for c in gh.calls if c[0] == "pr_merge"]


def test_deferral_skip_reason_does_not_veto_the_merge():
    """A skip only ever happens on a truncated run, and it only takes effect
    if the run merges. Vetoing it would make the hatch a no-op that re-fires
    forever."""
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green()]))
    outcome, _ = _run(
        gh,
        partial=True,
        advance_cursor_backed=True,
        partial_reasons=(
            "deferral_skip: o/r#5 skipped after 3 consecutive deferrals; "
            "pages=core/connectors/beta.md",
        ),
    )
    assert outcome["merged"] is True


def test_non_partial_run_still_merges_with_no_cursor():
    """Back-compat: the clean path is untouched. A non-partial run advances to
    full HEAD (cursor_backed False) and must still merge."""
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green()]))
    outcome, _ = _run(gh, partial=False, advance_cursor_backed=False)
    assert outcome["merged"] is True
```

Those tests need the shared `_run` helper to forward the new kwargs. Replace the existing `_run` (lines 83-106 of that file) with:

```python
def _run(
    gh,
    *,
    partial=False,
    fact_warnings=None,
    settings=None,
    build_workflow="docs-agent-pages.yml",
    deadline=None,
    clock=None,
    ci_provider=None,
    advance_cursor_backed=False,
    partial_reasons=(),
):
    clock = clock or FakeClock()
    return orun._maybe_auto_merge(
        gh,
        pr_number=7,
        partial=partial,
        fact_warnings=fact_warnings or [],
        merge_settings=settings or _settings(),
        build_workflow=build_workflow,
        deadline=deadline,
        clock=clock,
        sleep=clock.sleep,
        ci_provider=ci_provider,
        advance_cursor_backed=advance_cursor_backed,
        partial_reasons=partial_reasons,
    )
```

- [ ] **Step 2: Run and watch it fail**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_auto_merge.py -q
```

Expected: every test in the file errors with `TypeError: _maybe_auto_merge() got an unexpected keyword argument 'advance_cursor_backed'` (the shared `_run` helper now passes it unconditionally).

- [ ] **Step 3: Add the veto helper**

In `scripts/orchestrator_runner.py`, insert immediately **before** `def _maybe_auto_merge(` (HEAD 2817):

```python
# CCE-140: partial reasons that veto auto-merge even on a cursor-backed
# advance. The cursor proves the BASELINE is honest; it says nothing about
# whether this PR is safe to land. `app_token_unavailable` is recorded as a
# blocking reason at :1377 for exactly this purpose (README §nightly): a PR
# built on the fallback GITHUB_TOKEN never fires host CI, so `gh pr checks`
# returns [] and the zero-checks branch below would read that as green.
# Match is by prefix, against the reason string as stored in state.
#
# `deferral_skip:` is deliberately NOT here — a skip only happens on a
# truncated run and only takes effect if that run merges.
_MERGE_VETO_REASON_PREFIXES: tuple[str, ...] = ("app_token_unavailable",)


def merge_veto_reason(partial_reasons) -> str | None:
    """Return the first veto prefix present in ``partial_reasons``, else None."""
    for reason in partial_reasons or ():
        for prefix in _MERGE_VETO_REASON_PREFIXES:
            if reason.startswith(prefix):
                return prefix
    return None
```

- [ ] **Step 4: Widen the signature and the gate**

Find (HEAD 2822-2831):

```python
    fact_warnings: list[str],
    merge_settings: dict,
    build_workflow: str | None,
    ci_provider: str | None = None,
    deadline: float | None,
    clock: Callable[[], float],
    sleep: Callable[[float], None] = time.sleep,
    bot_author_names: tuple[str, ...] = _DOCS_AGENT_BOT_AUTHOR_NAMES,
    bot_author_emails: tuple[str, ...] = _DOCS_AGENT_BOT_AUTHOR_EMAILS,
) -> tuple[dict, list[tuple[str, bool]]]:
```

Replace with:

```python
    fact_warnings: list[str],
    merge_settings: dict,
    build_workflow: str | None,
    ci_provider: str | None = None,
    deadline: float | None,
    clock: Callable[[], float],
    sleep: Callable[[float], None] = time.sleep,
    bot_author_names: tuple[str, ...] = _DOCS_AGENT_BOT_AUTHOR_NAMES,
    bot_author_emails: tuple[str, ...] = _DOCS_AGENT_BOT_AUTHOR_EMAILS,
    advance_cursor_backed: bool = False,
    partial_reasons: tuple[str, ...] = (),
) -> tuple[dict, list[tuple[str, bool]]]:
```

Find (HEAD 2852-2859):

```python
    if merge_settings.get("policy") != "auto":
        # The configured normal path for a manual host — no reason entry,
        # the digest's merge_outcome line carries it.
        return {"merged": False, "reason": "policy_manual"}, []
    if partial:
        return skip("partial_run")
    if fact_warnings:
        return skip("fact_check_warnings", f"{len(fact_warnings)} warning(s)")
```

Replace with:

```python
    if merge_settings.get("policy") != "auto":
        # The configured normal path for a manual host — no reason entry,
        # the digest's merge_outcome line carries it.
        return {"merged": False, "reason": "policy_manual"}, []
    veto = merge_veto_reason(partial_reasons)
    if veto:
        return skip("merge_vetoed", veto)
    if partial and not advance_cursor_backed:
        # CCE-140 / spec Decision 2. A partial run whose advance came from the
        # CCE-109 cursor has, by construction, advanced only past PRs whose
        # pages all landed; its reverted pages stay in-window and are
        # re-authored next run. A partial run that would advance to FULL HEAD
        # has not — merging it promotes the baseline past work that was never
        # authored, which is the silent-loss bug, automated nightly.
        return skip("partial_run")
```

(The `fact_warnings` gate is deleted here. Task 4 completes that change — it is removed now because leaving it would make Task 3's `test_partial_run_with_cursor_backed_advance_merges` pass for the wrong reason on a host that has warnings.)

- [ ] **Step 5: Update the docstring's eligibility sentence**

Find (HEAD 2834-2838):

```python
    Eligibility (cheapest first): policy auto → non-partial → zero
    fact-checker warnings → no human commits on the PR → enough CCE-109
    budget left to wait out the check-grace window. Then a bounded poll
    of `gh pr checks`; zero registered checks after the grace window
    means a no-App-token host (the in-run validation is the gate there).
```

Replace with:

```python
    Eligibility (cheapest first): policy auto → no vetoing partial reason →
    non-partial OR a cursor-backed advance → no human commits on the PR →
    enough CCE-109 budget left to wait out the check-grace window. Then a
    bounded poll of `gh pr checks`; zero registered checks after the grace
    window means a no-App-token host (the in-run validation is the gate
    there).

    CCE-140: `partial` alone no longer blocks. Every run this pipeline has
    ever produced is partial, so the unconditional block meant the auto-merge
    path never once fired on the flagship host and ten PRs were merged by
    hand until the human stopped. `advance_cursor_backed` is the replacement
    invariant: True only when advance_sha was assigned from a cursor that
    passed `_sha_in_window`, i.e. the baseline moves by exactly the PRs whose
    pages all landed.

    Fact-checker warnings are NOT an eligibility input (CCE-140 / spec
    Decision 4). They ride the PR body, the digest, and the notification.
    `fact_warnings` is retained in the signature only so the caller's kwargs
    and the digest composition need no change.
```

- [ ] **Step 6: Thread the two new arguments at the call site**

Find (HEAD 2077-2087):

```python
        merge_outcome, merge_reasons = _maybe_auto_merge(
            gh,
            pr_number=pr_number,
            partial=state["current_run"]["partial"],
            fact_warnings=state["current_run"].get("fact_check_warnings") or [],
            merge_settings=merge_settings,
            build_workflow=config.get("publishing", {}).get("build_workflow"),
            ci_provider=config.get("publishing", {}).get("ci_provider"),
            deadline=deadline,
            clock=clock,
        )
```

Replace with:

```python
        merge_outcome, merge_reasons = _maybe_auto_merge(
            gh,
            pr_number=pr_number,
            partial=state["current_run"]["partial"],
            fact_warnings=state["current_run"].get("fact_check_warnings") or [],
            merge_settings=merge_settings,
            build_workflow=config.get("publishing", {}).get("build_workflow"),
            ci_provider=config.get("publishing", {}).get("ci_provider"),
            deadline=deadline,
            clock=clock,
            advance_cursor_backed=advance_cursor_backed,
            partial_reasons=tuple(state["current_run"]["partial_reasons"]),
        )
```

- [ ] **Step 7: Run the auto-merge suite and confirm the ONE intended inversion**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_auto_merge.py -q
```

Expected: **31 passed, 1 failed**. The single failure is `test_fact_warnings_demote_to_manual_review`, with `AssertionError` on `outcome["reason"] == "fact_check_warnings"` (the outcome is now `{"merged": True, "reason": None}`). That inversion is the intended consequence of deleting the `fact_warnings` gate in Step 4, and it must be resolved **inside this task, before the commit** — see Step 7b. Do not "fix" it by restoring the gate and do not delete the test.

If any OTHER test in the file fails, stop: Step 4 or Step 6 is wrong.

- [ ] **Step 7b: Rewrite the inverted test now, so nothing is committed red**

The plan's own TDD rule is "run it, see it pass → commit". Task 4 owns the _demotion's_ proof surfaces (PR body, digest), but the inverted assertion belongs to the commit that inverts it. Perform Task 4 Step 1 here — the verbatim edit is reproduced so this step is executable on its own.

In `tests/orchestrator/test_auto_merge.py`, find:

```python
def test_fact_warnings_demote_to_manual_review():
    """CCE-110 guard: under auto-merge nobody reads the PR, so a
    contradiction warning must withhold the merge (not the content)."""
    gh = FakeGhClient()
    outcome, reasons = _run(gh, fact_warnings=["page.md: contradicts source"])
    assert outcome["reason"] == "fact_check_warnings"
    assert reasons[0][0].startswith("auto_merge_skipped: fact_check_warnings")
    assert reasons[0][1] is True
    assert not [c for c in gh.calls if c[0] == "pr_merge"]
```

Replace with:

```python
def test_fact_warnings_never_gate_the_merge():
    """CCE-140 / spec Decision 4. This test is the exact inverse of the
    CCE-110 behaviour it replaces, and the inversion is the point.

    The fact-checker documents itself as a warn layer at
    scripts/orchestrator_runner.py:1755-1760 -- 'Findings are operator-facing
    warnings only: info_only reasons, a PR-body section, and the run record
    -- never a partial flag, never a dropped page.' skip('fact_check_warnings')
    contradicted that contract. Under a fully autonomous policy the choice is
    not 'merge vs. a human reads it', it is 'merge vs. the pipeline stalls
    forever', so the warning rides the PR body and the notification instead.
    """
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green()]))
    outcome, reasons = _run(gh, fact_warnings=["page.md: contradicts source"])
    assert outcome == {"merged": True, "reason": None}
    assert ("pr_merge", (7,)) in gh.calls
    assert not any("fact_check_warnings" in r for r, _ in reasons)
```

Then re-run:

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_auto_merge.py -q
```

Expected: `32 passed`, `0 failed`. Task 4 Step 1 is now already done; Task 4 opens at its Step 1b.

- [ ] **Step 8: Add the end-to-end refusal test**

Append to `tests/orchestrator/test_cursor_backed_merge.py`:

```python
def test_lint_block_partial_run_does_not_auto_merge_end_to_end(
    tmp_path, monkeypatch, init_host
):
    """Wired, not mocked at the gate: a lint-block partial run opens its PR
    and leaves it open. The FakeGhClient call log is the assertion -- no
    pr_merge, ever."""
    from gh_client import FakeGhClient, GhResult

    init_host({"version": "1", "dismissed_gap_flags": {}, "cursors": {}})
    config_path = tmp_path / ".engineering-docs-agent" / "config.yml"
    config_path.write_text(
        config_path.read_text()
        + "\nmerge:\n  policy: auto\n  checks_grace_seconds: 0\n"
        + "  checks_timeout_seconds: 0\n"
    )
    fake = None

    def _fake_factory(repo_root):
        nonlocal fake
        fake = FakeGhClient(
            pr_create=GhResult(ok=True, value=12),
            pr_view_commits=GhResult(
                ok=True,
                value=[
                    {
                        "authors": [
                            {
                                "name": "engineering-docs-agent[bot]",
                                "login": "engineering-docs-agent-bot",
                                "email": (
                                    "engineering-docs-agent@users.noreply."
                                    "github.com"
                                ),
                            }
                        ]
                    }
                ],
            ),
            pr_checks=GhResult(ok=True, value=[]),
        )
        return fake

    monkeypatch.setattr(runner, "GhClient", _fake_factory)
    real_run = runner.subprocess.run

    def selective(cmd, *a, **kw):
        if isinstance(cmd, list) and cmd[:2] == ["git", "-C"] and "push" in cmd:
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(runner.subprocess, "run", selective)

    rc = runner.run(tmp_path, dry_run_dir=FAKES_BLOCK, no_pr=False)
    assert rc == 0
    assert not [c for c in fake.calls if c[0] == "pr_merge"], fake.calls
```

- [ ] **Step 9: Run it and watch it pass**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_cursor_backed_merge.py -q
```

Expected: `3 passed`.

- [ ] **Step 10: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent && git add scripts/orchestrator_runner.py tests/orchestrator/test_auto_merge.py tests/orchestrator/test_cursor_backed_merge.py && git commit -m "feat(CCE-140): a partial run merges only when its advance is cursor-backed

skip('partial_run') was the first condition in _maybe_auto_merge and every
run this pipeline produces is partial, so the auto-merge path never fired.
It now blocks only a partial run that would advance to full HEAD. An explicit
veto list keeps app_token_unavailable decisive: the cursor proves the
baseline is honest, not that host CI ran.

The fact_warnings gate is deleted in the same commit, and the one test it
inverts (test_fact_warnings_demote_to_manual_review) is rewritten here rather
than left red across a commit boundary."
```

The suite is green at this commit. Verify before running `git commit`:

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_auto_merge.py tests/orchestrator/test_cursor_backed_merge.py -q 2>&1 | tail -2
```

Expected: `0 failed`.

---

## Task 4 — Demote `fact_check_warnings` to a warning

**Files:**

- Modify: `scripts/orchestrator_runner.py` (already edited in Task 3 Step 4; this task adds the PR-body/notification guarantee tests)
- Test: `tests/orchestrator/test_auto_merge.py`, `tests/orchestrator/test_fact_checker.py`

**Interfaces:**

- Consumes: nothing new.
- Produces: nothing new. `_maybe_auto_merge`'s `fact_warnings` parameter is retained (still required, still passed) so the caller and the digest need no change; it simply no longer influences the outcome.

> **The inverted test was already rewritten in Task 3 Step 7b**, so nothing was committed red. This task opens at Step 1b. If `test_fact_warnings_demote_to_manual_review` still exists in `tests/orchestrator/test_auto_merge.py`, Task 3 Step 7b was skipped — go back and do it, then return here.

- [ ] **Step 1b: Add the composition test**

Append to `tests/orchestrator/test_auto_merge.py`, immediately after `test_fact_warnings_never_gate_the_merge`:

```python
def test_fact_warnings_do_not_gate_a_cursor_backed_partial_either():
    """The two relaxations compose: warnings + partial + a cursor still
    merges."""
    gh = _eligible_gh(pr_checks=GhResult(ok=True, value=[_green()]))
    outcome, _ = _run(
        gh,
        partial=True,
        advance_cursor_backed=True,
        fact_warnings=["a.md: contradicts source", "b.md: contradicts source"],
    )
    assert outcome["merged"] is True
```

- [ ] **Step 2: Run and watch it pass**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_auto_merge.py -q
```

Expected: `33 passed` — the 26 the file started with, plus 6 from Task 3 Step 1, plus this one. (Task 3 Step 7b rewrote one test in place; it did not add or remove one.)

- [ ] **Step 3: Write the surfacing test — the warning must not vanish**

The whole risk of a demotion is that the signal disappears. `_compose_pr_body` already renders a `**Factual-accuracy warnings:**` section (HEAD 2508-2511) and the digest already carries `fact_check_warnings` (HEAD 2110-2111). Pin both so a later cleanup cannot drop them now that nothing else depends on the list. Append to `tests/orchestrator/test_fact_checker.py`:

```python
def test_fact_warnings_still_reach_the_pr_body_after_the_gate_demotion():
    """CCE-140: with the merge gate gone, the PR body is one of the two
    places a contradiction warning survives. Pin it."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import orchestrator_runner as orun

    body = orun._compose_pr_body(
        changed_files=["docs/site-src/core/a.md"],
        lens_paths={"core": "docs/site-src/core"},
        partial=True,
        partial_reasons=["time_budget_exceeded: authored 1/3 page batches"],
        baseline_sha="a" * 40,
        current_sha="b" * 40,
        fact_warnings=["`core/a.md`: contradicts source"],
    )
    assert "**Factual-accuracy warnings:**" in body
    assert "`core/a.md`: contradicts source" in body


def test_fact_warnings_still_reach_the_notifier_digest(
    tmp_path, monkeypatch, init_host
):
    """CCE-140: the notification is the other surviving surface. Capture the
    digest handed to the notifier dispatch and assert the key is populated."""
    import json as _json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import orchestrator_runner as orun

    init_host({"version": "1", "dismissed_gap_flags": {}, "cursors": {}})
    seen: dict = {}
    real_dispatch = orun.dispatch_validated

    def spy(name, inputs, **kw):
        if name == "notifier":
            seen["digest"] = _json.loads(_json.dumps(inputs["digest"]))
        return real_dispatch(name, inputs, **kw)

    monkeypatch.setattr(orun, "dispatch_validated", spy)
    monkeypatch.setattr(
        orun,
        "open_or_append_pr",
        lambda *a, **kw: (99, []),
    )

    class _NoopGh:
        def __init__(self, *a, **kw):
            pass

    monkeypatch.setattr(orun, "GhClient", _NoopGh)
    monkeypatch.setattr(
        orun,
        "_maybe_auto_merge",
        lambda *a, **kw: ({"merged": False, "reason": "policy_manual"}, []),
    )
    rc = orun.run(
        tmp_path,
        dry_run_dir=Path(__file__).parent / "fakes",
        no_pr=False,
    )
    assert rc == 0
    assert "fact_check_warnings" in seen["digest"]
```

- [ ] **Step 4: Run and watch them pass**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_fact_checker.py -q
```

Expected: all pass. If `test_fact_warnings_still_reach_the_notifier_digest` fails on an import or fixture name, the `init_host` fixture comes from `tests/orchestrator/conftest.py` and is available to every file in that directory — check the file is under `tests/orchestrator/`.

- [ ] **Step 5: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent && git add scripts/orchestrator_runner.py tests/orchestrator/test_auto_merge.py tests/orchestrator/test_fact_checker.py && git commit -m "fix(CCE-140): fact_check_warnings warns, it does not gate the merge

The fact-checker documents itself as a warn layer at :1755-1760 --
'never a partial flag, never a dropped page' -- and skip('fact_check_warnings')
contradicted its own contract. Warnings keep the PR-body section and the
notifier digest; both surfaces are now pinned by tests, because nothing else
depends on the list any more."
```

---

## Task 5 — `run.deferral_skip_threshold` config key

**Files:**

- Modify: `templates/config.schema.json` (the `run` block, lines 178-188)
- Modify: `scripts/orchestrator_runner.py` (next to `resolve_time_budget`, :340-353)
- Test: `tests/schemas/test_config_schema.py`, `tests/orchestrator/test_deferral_skip.py`

**Interfaces:**

- Consumes: nothing.
- Produces: `DEFAULT_DEFERRAL_SKIP_THRESHOLD: int = 3` and `resolve_deferral_threshold(config: dict) -> int`, consumed by Task 8.

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestrator/test_deferral_skip.py`:

```python
# ---------------------------------------------------------------------------
# resolve_deferral_threshold
# ---------------------------------------------------------------------------


def test_threshold_defaults_to_three():
    assert orun.DEFAULT_DEFERRAL_SKIP_THRESHOLD == 3
    assert orun.resolve_deferral_threshold({}) == 3
    assert orun.resolve_deferral_threshold({"run": {}}) == 3


def test_threshold_reads_the_config_key():
    assert orun.resolve_deferral_threshold({"run": {"deferral_skip_threshold": 5}}) == 5


def test_threshold_zero_disables_skipping():
    assert orun.resolve_deferral_threshold({"run": {"deferral_skip_threshold": 0}}) == 0


def test_threshold_tolerates_a_malformed_run_block():
    """Same posture as resolve_merge_settings: a non-dict block falls back to
    the default rather than raising inside run()."""
    assert orun.resolve_deferral_threshold({"run": "nope"}) == 3
```

Append to `tests/schemas/test_config_schema.py`:

```python
_CCE140_BASE_CFG = """
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/core }
sources: { git: { host: github } }
lint: { tier1: default, tier2: {}, tier3: {} }
publishing:
  base_url: https://x
  build_workflow: deploy.yml
  url_map_rule: standard
notifications: {}
"""


def test_run_block_accepts_deferral_skip_threshold():
    """CCE-140: the `run` block sets additionalProperties: false, so an
    undeclared key makes load_config_validated raise and the runner exit 2.
    The schema edit is a hard requirement, not documentation."""
    cfg = yaml.safe_load(_CCE140_BASE_CFG)
    cfg["run"] = {"time_budget_seconds": 2700, "deferral_skip_threshold": 3}
    validate(cfg, SCHEMA)


def test_run_block_still_rejects_an_unknown_key():
    cfg = yaml.safe_load(_CCE140_BASE_CFG)
    cfg["run"] = {"deferral_skip_threshhold": 3}  # typo, one 'h' too many
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


def test_deferral_skip_threshold_rejects_a_negative():
    cfg = yaml.safe_load(_CCE140_BASE_CFG)
    cfg["run"] = {"deferral_skip_threshold": -1}
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)
```

> `_CCE140_BASE_CFG` is the exact YAML that file's own `test_minimal_valid` already builds inline (verified against `tests/schemas/test_config_schema.py:15-30`). That file has **no** shared config constant — every test writes its own YAML — so hoisting one for these three matches the file's spirit without touching an existing test. `SCHEMA`, `yaml`, `validate`, `ValidationError` and `pytest` are all already imported at the top of that file (lines 1-12); add no imports.
>
> **Cross-track collision check (reconciled).** Track C (CCE-139) also appends to this file, and also hoists a module-level constant — named `_BASE_CFG`. The two names differ, so appending both is clean: no `NameError`, no shadowing. They are near-duplicates but not identical — Track C's omits the `lint` key (each of its tests supplies its own `lint:` line) while this one carries `lint: { tier1: default, tier2: {}, tier3: {} }`. **Do not merge them.** Collapsing the two would couple Track C's already-reviewed negative tests to Track B's `lint` block, and Track B lands last, so the merge would be a silent rewrite of someone else's landed test. Two eight-line YAML strings is the cheap side of that trade.
>
> Confirm before appending:
>
> ```bash
> cd /Users/theo/Projects/engineering-docs-agent && grep -n "^_BASE_CFG\|^_CCE140_BASE_CFG" tests/schemas/test_config_schema.py
> ```
>
> Expected: one hit, `_BASE_CFG` (Track C's). If `_CCE140_BASE_CFG` is already there, this step has been run.

- [ ] **Step 2: Run and watch them fail**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_deferral_skip.py tests/schemas/test_config_schema.py -q
```

Expected: 4 `AttributeError: module 'orchestrator_runner' has no attribute 'DEFAULT_DEFERRAL_SKIP_THRESHOLD'` / `'resolve_deferral_threshold'`, plus `test_run_block_accepts_deferral_skip_threshold` failing with a `ValidationError` naming `deferral_skip_threshold` as an additional property.

- [ ] **Step 3: Declare the key in the schema**

In `templates/config.schema.json`, find:

```json
    "run": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "time_budget_seconds": {
          "type": "integer",
          "minimum": 0,
          "description": "CCE-109: soft per-run time budget in seconds. 0 = unlimited. Default 2700."
        }
      }
    },
```

Replace with:

```json
    "run": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "time_budget_seconds": {
          "type": "integer",
          "minimum": 0,
          "description": "CCE-109: soft per-run time budget in seconds. 0 = unlimited. Default 2700."
        },
        "deferral_skip_threshold": {
          "type": "integer",
          "minimum": 0,
          "description": "CCE-140: number of CONSECUTIVE runs a PR may be deferred before the next run abandons it — the advance cursor walks past it, an entry is appended to state.json `skipped_prs`, and a non-informational partial reason names the PR and its pages. Default 3. 0 disables skipping entirely, which restores the pre-CCE-140 indefinite-stall behaviour."
        }
      }
    },
```

- [ ] **Step 4: Add the resolver**

In `scripts/orchestrator_runner.py`, find:

```python
DEFAULT_MERGE_POLICY = "auto"
```

Insert immediately **before** it:

```python
DEFAULT_DEFERRAL_SKIP_THRESHOLD = 3

```

Then insert the resolver immediately **after** the `resolve_time_budget` function (which ends with `    return int(val)` at HEAD line 353) and before `def _order_prs_oldest_first(`:

```python
def resolve_deferral_threshold(config: dict) -> int:
    """Resolve `run.deferral_skip_threshold` (CCE-140).

    Absent `run:` block, a malformed (non-dict) block, or an absent key all
    resolve to DEFAULT_DEFERRAL_SKIP_THRESHOLD (3) — same default-ON posture
    as `resolve_merge_settings`, so an existing host gains the skip hatch with
    no config edit. A value <= 0 disables skipping.
    """
    run_cfg = config.get("run")
    if not isinstance(run_cfg, dict):
        run_cfg = {}
    val = run_cfg.get("deferral_skip_threshold")
    if val is None:
        return DEFAULT_DEFERRAL_SKIP_THRESHOLD
    return int(val)
```

- [ ] **Step 5: Run and watch them pass**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_deferral_skip.py tests/schemas/test_config_schema.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent && git add templates/config.schema.json scripts/orchestrator_runner.py tests/orchestrator/test_deferral_skip.py tests/schemas/test_config_schema.py && git commit -m "feat(CCE-140): run.deferral_skip_threshold, default 3

The run block sets additionalProperties: false, so the schema declaration is
a hard requirement — an undeclared key makes load_config_validated raise and
the runner exit 2. 0 disables skipping."
```

---

## Task 6 — `skipped_prs` and `deferral_counts` in `state.schema.json`, with back-compat proof

**Files:**

- Modify: `templates/state.schema.json`
- Test: `tests/schemas/test_state_schema.py`, `tests/contracts/test_state_io.py`

**Interfaces:**

- Consumes: nothing.
- Produces: the on-disk contract Task 7 and Task 8 write. `skipped_prs` is an array of objects requiring `pr`, `deferrals`, `skipped_at`; `deferral_counts` is an object mapping `{owner}/{name}#{pr}` → non-negative integer.

- [ ] **Step 1: Write the failing tests**

Append to `tests/schemas/test_state_schema.py`:

```python
def test_skipped_prs_and_deferral_counts_validate():
    """CCE-140. Shape follows the dismissed_gap_flags precedent: PR identity
    is the `{owner}/{name}#{pr}` string the runner already builds at
    orchestrator_runner.py:1901."""
    state = {
        "version": "1",
        "last_successful_run": {"head_sha": "abc", "completed_at": "2026-08-11T03:00:00+00:00"},
        "deferral_counts": {"o/r#5": 2, "o/r#6": 0},
        "skipped_prs": [
            {
                "pr": "o/r#4",
                "url": "https://github.com/o/r/pull/4",
                "pages": ["core/connectors/beta.md"],
                "deferrals": 3,
                "skipped_at": "2026-08-11T03:00:00+00:00",
            }
        ],
    }
    validate(state, SCHEMA)


def test_skipped_pr_entry_requires_its_identity_fields():
    with pytest.raises(ValidationError):
        validate(
            {"version": "1", "skipped_prs": [{"pages": ["a.md"]}]},
            SCHEMA,
        )


def test_deferral_counts_rejects_a_negative():
    with pytest.raises(ValidationError):
        validate({"version": "1", "deferral_counts": {"o/r#1": -1}}, SCHEMA)


def test_deferral_counts_rejects_a_non_integer():
    with pytest.raises(ValidationError):
        validate({"version": "1", "deferral_counts": {"o/r#1": "two"}}, SCHEMA)


def test_pre_cce140_state_still_validates():
    """Back-compat, both directions. A state.json written before CCE-140 has
    neither key; the root declares required:['version'] and no
    additionalProperties:false, so nothing about the old file becomes invalid
    and there is no migration step. The reverse also holds — a new-format file
    validates against the OLD schema — which matters because the plugin is
    consumed at ref: main with no release step."""
    legacy = {"version": "1", "dismissed_gap_flags": {}, "cursors": {}}
    validate(legacy, SCHEMA)
    assert "skipped_prs" not in legacy
    assert "deferral_counts" not in legacy
```

Append to `tests/contracts/test_state_io.py`:

```python
def test_load_state_validated_accepts_a_pre_cce140_state_file(tmp_path):
    """CCE-140 back-compat at the real load path, not just the schema. This is
    the exact byte content of tests/fixtures/e2e_host/.engineering-docs-agent/
    state.json, which is what a host that predates CCE-140 has on disk."""
    import json

    from state_io import load_state_validated

    p = tmp_path / "state.json"
    p.write_text('{ "version": "1", "dismissed_gap_flags": {}, "cursors": {} }')
    loaded = load_state_validated(p)
    assert loaded == {"version": "1", "dismissed_gap_flags": {}, "cursors": {}}
    # The reader contract the runner relies on: absent means empty.
    assert loaded.get("skipped_prs", []) == []
    assert loaded.get("deferral_counts", {}) == {}
    assert json.loads(p.read_text()) == loaded, "load must not rewrite the file"


def test_save_persistent_state_round_trips_the_cce140_keys(tmp_path):
    import json

    from state_io import save_persistent_state

    state = {
        "version": "1",
        "last_successful_run": {"head_sha": "abc"},
        "deferral_counts": {"o/r#5": 2},
        "skipped_prs": [
            {
                "pr": "o/r#4",
                "url": "https://github.com/o/r/pull/4",
                "pages": ["core/a.md"],
                "deferrals": 3,
                "skipped_at": "2026-08-11T03:00:00+00:00",
            }
        ],
        "current_run": {"partial": True},
    }
    p = tmp_path / "state.json"
    save_persistent_state(p, state)
    written = json.loads(p.read_text())
    assert "current_run" not in written
    assert written["deferral_counts"] == {"o/r#5": 2}
    assert written["skipped_prs"][0]["pr"] == "o/r#4"
```

- [ ] **Step 2: Run and watch them fail**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/schemas/test_state_schema.py tests/contracts/test_state_io.py -q
```

Expected: `test_skipped_pr_entry_requires_its_identity_fields`, `test_deferral_counts_rejects_a_negative` and `test_deferral_counts_rejects_a_non_integer` all fail with `DID NOT RAISE ValidationError` (the root has no `additionalProperties: false`, so today the schema silently accepts anything under those keys). The other four pass already — that is the back-compat proof, and it is worth seeing green before the schema changes.

- [ ] **Step 3: Declare both keys**

In `templates/state.schema.json`, find:

```json
    "dismissed_gap_flags": {
      "type": "object",
      "description": "Operator-set dismissals. Keys are {owner}/{name}#{pr}. Values are dismissal notes (free text).",
      "additionalProperties": { "type": "string" }
    },
    "cursors": { "type": "object" }
```

Replace with:

```json
    "dismissed_gap_flags": {
      "type": "object",
      "description": "Operator-set dismissals. Keys are {owner}/{name}#{pr}. Values are dismissal notes (free text).",
      "additionalProperties": { "type": "string" }
    },
    "deferral_counts": {
      "type": "object",
      "description": "CCE-140: consecutive-deferral count per PR. Keys are {owner}/{name}#{pr}, the same shape as dismissed_gap_flags. Runner-owned, not operator-edited. An entry is dropped as soon as its PR is processed or skipped, so a quiescent pipeline carries no entries and the key is absent entirely.",
      "additionalProperties": { "type": "integer", "minimum": 0 }
    },
    "skipped_prs": {
      "type": "array",
      "description": "CCE-140: PRs abandoned after run.deferral_skip_threshold consecutive deferrals. Append-only — the runner never removes an entry. Absent means no PR has ever been skipped; the key is never seeded empty.",
      "items": {
        "type": "object",
        "required": ["pr", "deferrals", "skipped_at"],
        "properties": {
          "pr": {
            "type": "string",
            "description": "{owner}/{name}#{pr}, same key shape as dismissed_gap_flags."
          },
          "url": { "type": "string" },
          "pages": {
            "type": "array",
            "items": { "type": "string" },
            "description": "lens/page_hint targets this PR still owed when it was skipped. Empty when the admission gate never reached the PR, so no page was ever routed for it."
          },
          "deferrals": { "type": "integer", "minimum": 0 },
          "skipped_at": { "type": "string" }
        }
      }
    },
    "cursors": { "type": "object" }
```

- [ ] **Step 4: Run and watch them pass**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/schemas/test_state_schema.py tests/contracts/test_state_io.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent && git add templates/state.schema.json tests/schemas/test_state_schema.py tests/contracts/test_state_io.py && git commit -m "feat(CCE-140): declare skipped_prs and deferral_counts in state.schema.json

No migration and no version bump: the root declares required:['version'] and
no additionalProperties:false, so a pre-CCE-140 state.json validates unchanged
and a post-CCE-140 one validates against the old schema. Both directions are
now pinned by tests, because the plugin is consumed at ref: main with no
release step."
```

---

## Task 7 — Pure deferral bookkeeping helpers

**Files:**

- Modify: `scripts/orchestrator_runner.py` (next to `advance_cursor_list`)
- Modify: `scripts/state_io.py` (the single writer of `skipped_prs`)
- Test: `tests/orchestrator/test_deferral_skip.py`, `tests/contracts/test_state_io.py`

**Interfaces:**

- Consumes: `DEFAULT_DEFERRAL_SKIP_THRESHOLD` / `resolve_deferral_threshold` (Task 5).
- Produces, all consumed by Task 8:
  - `deferral_key(repo: dict, pr_number) -> str`
  - `partition_deferrals(deferred: list[dict], *, counts: dict, repo: dict, threshold: int) -> tuple[list[dict], list[dict]]` → `(skipped_now, still_deferred)`
  - `next_deferral_counts(counts: dict, *, repo: dict, window_pr_numbers: set, still_deferred_numbers: set) -> dict`
  - `state_io.merge_skipped_pr_records(state: dict, records: list[dict]) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestrator/test_deferral_skip.py`:

```python
# ---------------------------------------------------------------------------
# deferral_key / partition_deferrals / next_deferral_counts
# ---------------------------------------------------------------------------

_REPO = {"owner": "o", "name": "r"}


def test_deferral_key_matches_the_dismissed_gap_flags_shape():
    """One key shape across the whole state file. The runner already builds
    this string for gap-detector pr_ids at orchestrator_runner.py:1901."""
    assert orun.deferral_key(_REPO, 5) == "o/r#5"


def test_partition_leaves_an_under_threshold_pr_deferred():
    skipped, still = orun.partition_deferrals(
        [_pr(5, "e")], counts={"o/r#5": 2}, repo=_REPO, threshold=3
    )
    assert skipped == []
    assert [p["number"] for p in still] == [5]


def test_partition_skips_a_pr_that_has_already_hit_the_threshold():
    """'3 consecutive deferrals -> skipped on the 4th': the count reaching 3
    is what the THIS run reads, so this run is the fourth."""
    skipped, still = orun.partition_deferrals(
        [_pr(5, "e")], counts={"o/r#5": 3}, repo=_REPO, threshold=3
    )
    assert [p["number"] for p in skipped] == [5]
    assert still == []


def test_partition_skips_above_the_threshold_too():
    skipped, _ = orun.partition_deferrals(
        [_pr(5, "e")], counts={"o/r#5": 9}, repo=_REPO, threshold=3
    )
    assert [p["number"] for p in skipped] == [5]


def test_partition_treats_an_unseen_pr_as_count_zero():
    skipped, still = orun.partition_deferrals(
        [_pr(5, "e")], counts={}, repo=_REPO, threshold=3
    )
    assert skipped == []
    assert [p["number"] for p in still] == [5]


def test_threshold_zero_never_skips():
    skipped, still = orun.partition_deferrals(
        [_pr(5, "e")], counts={"o/r#5": 99}, repo=_REPO, threshold=0
    )
    assert skipped == []
    assert [p["number"] for p in still] == [5]


def test_counts_increment_for_a_still_deferred_pr():
    out = orun.next_deferral_counts(
        {"o/r#5": 1},
        repo=_REPO,
        window_pr_numbers={5, 6},
        still_deferred_numbers={5},
    )
    assert out["o/r#5"] == 2


def test_counts_reset_when_a_pr_is_processed():
    """'Consecutive' means consecutive: a PR that got processed this run
    loses its history, so an intermittently-slow PR is never skipped."""
    out = orun.next_deferral_counts(
        {"o/r#5": 2},
        repo=_REPO,
        window_pr_numbers={5},
        still_deferred_numbers=set(),
    )
    assert "o/r#5" not in out


def test_counts_drop_a_skipped_pr():
    """A skipped PR is in the window and not still-deferred, so the same
    reset rule drops it — and it never returns to any window."""
    out = orun.next_deferral_counts(
        {"o/r#4": 3},
        repo=_REPO,
        window_pr_numbers={4},
        still_deferred_numbers=set(),
    )
    assert "o/r#4" not in out


def test_counts_carry_forward_a_pr_absent_from_this_window():
    """A window can shrink transiently when the source-collector degrades.
    Absence is not evidence the PR was processed, so its history survives."""
    out = orun.next_deferral_counts(
        {"o/r#9": 2},
        repo=_REPO,
        window_pr_numbers={5},
        still_deferred_numbers=set(),
    )
    assert out["o/r#9"] == 2


def test_counts_do_not_mutate_the_input():
    counts = {"o/r#5": 1}
    orun.next_deferral_counts(
        counts, repo=_REPO, window_pr_numbers={5}, still_deferred_numbers={5}
    )
    assert counts == {"o/r#5": 1}
```

Append to `tests/contracts/test_state_io.py`:

```python
def test_merge_skipped_pr_records_creates_the_key_only_when_there_is_a_record():
    from state_io import merge_skipped_pr_records

    state = {"version": "1"}
    merge_skipped_pr_records(state, [])
    assert "skipped_prs" not in state, (
        "an empty append must leave a quiescent host's state.json byte-"
        "identical to today's"
    )
    merge_skipped_pr_records(
        state,
        [
            {
                "pr": "o/r#4",
                "url": "https://github.com/o/r/pull/4",
                "pages": ["core/a.md"],
                "deferrals": 3,
                "skipped_at": "2026-08-11T03:00:00+00:00",
            }
        ],
    )
    assert [e["pr"] for e in state["skipped_prs"]] == ["o/r#4"]


def test_merge_skipped_pr_records_appends_and_never_rewrites_history():
    from state_io import merge_skipped_pr_records

    state = {
        "version": "1",
        "skipped_prs": [
            {"pr": "o/r#1", "deferrals": 3, "skipped_at": "2026-08-01T00:00:00+00:00"}
        ],
    }
    merge_skipped_pr_records(
        state,
        [{"pr": "o/r#4", "deferrals": 3, "skipped_at": "2026-08-11T03:00:00+00:00"}],
    )
    assert [e["pr"] for e in state["skipped_prs"]] == ["o/r#1", "o/r#4"]


def test_merge_skipped_pr_records_is_idempotent_per_pr():
    """A retry inside one run must not double-record. Identity is the pr key."""
    from state_io import merge_skipped_pr_records

    state = {"version": "1"}
    rec = {"pr": "o/r#4", "deferrals": 3, "skipped_at": "2026-08-11T03:00:00+00:00"}
    merge_skipped_pr_records(state, [rec])
    merge_skipped_pr_records(state, [rec])
    assert len(state["skipped_prs"]) == 1
```

- [ ] **Step 2: Run and watch them fail**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_deferral_skip.py tests/contracts/test_state_io.py -q
```

Expected: 11 `AttributeError` on `orchestrator_runner` (`deferral_key`, `partition_deferrals`, `next_deferral_counts`) and 3 `ImportError: cannot import name 'merge_skipped_pr_records' from 'state_io'`.

- [ ] **Step 3: Add the runner helpers**

In `scripts/orchestrator_runner.py`, insert immediately **after** `advance_cursor_list` (added in Task 1 Step 3) and before `def _git_is_ancestor(`:

```python
def deferral_key(repo: dict, pr_number) -> str:
    """`{owner}/{name}#{pr}` — one PR-identity shape across state.json.

    Same string the gap-detector builds for `pr_id`, and the same key shape
    `dismissed_gap_flags` uses, so an operator reading state.json sees one
    vocabulary.
    """
    return f"{repo['owner']}/{repo['name']}#{pr_number}"


def partition_deferrals(
    deferred: list[dict],
    *,
    counts: dict,
    repo: dict,
    threshold: int,
) -> tuple[list[dict], list[dict]]:
    """Split this run's deferred PRs into ``(skipped_now, still_deferred)``.

    CCE-140 / spec Decision 3: "Skip after 3 consecutive deferrals, record
    every skip durably, and enable notifications. A loud, recorded loss beats
    an indefinite silent stall."

    ``counts`` is the PRIOR consecutive-deferral map, so a PR whose stored
    count already equals ``threshold`` has been deferred on that many runs and
    this run is the (threshold+1)-th — the one that abandons it. ``threshold``
    <= 0 disables skipping entirely and every deferred PR stays deferred.

    Order-independent: the prefix-boundary invariant is enforced structurally
    by ``advance_cursor_list``, not here.
    """
    if threshold <= 0:
        return [], list(deferred)
    skipped: list[dict] = []
    still: list[dict] = []
    for pr in deferred:
        if int(counts.get(deferral_key(repo, pr.get("number")), 0)) >= threshold:
            skipped.append(pr)
        else:
            still.append(pr)
    return skipped, still


def next_deferral_counts(
    counts: dict,
    *,
    repo: dict,
    window_pr_numbers: set,
    still_deferred_numbers: set,
) -> dict:
    """Return the next persistent consecutive-deferral map (never mutates
    ``counts``).

    - in this window AND still deferred → count + 1
    - in this window and NOT still deferred → entry dropped. Covers both the
      processed case and the skipped case; "consecutive" means consecutive, so
      an intermittently-slow PR never accumulates toward a skip.
    - not in this window at all → carried forward unchanged. A window can
      shrink transiently when the source-collector degrades, and absence is
      not evidence a PR was processed. Growth is bounded because a PR leaves
      the window only once the baseline passes it, which requires it to be in
      the cursor prefix, which requires it not to be deferred.
    """
    out = dict(counts)
    for n in window_pr_numbers:
        k = deferral_key(repo, n)
        if n in still_deferred_numbers:
            out[k] = int(out.get(k, 0)) + 1
        else:
            out.pop(k, None)
    return out
```

- [ ] **Step 4: Add the state writer**

In `scripts/state_io.py`, insert immediately **after** the `add_partial` function (which ends with `    emit_stderr(safe_reason, info_only=info_only)`) and before `def cleanup_empty_parents(`:

```python
def merge_skipped_pr_records(state: dict, records: list[dict]) -> None:
    """Append CCE-140 skip records to the durable ``skipped_prs`` list.

    The single writer of that key, mirroring ``add_partial``'s ownership of
    ``partial_reasons``. Contract:

    - Append-only. A record is never removed and never rewritten; the list is
      the pipeline's permanent account of content it chose to abandon.
    - Idempotent per PR. Identity is the ``pr`` field (``{owner}/{name}#{pr}``),
      so a retry inside one run cannot double-record.
    - Never seeds the key. An empty ``records`` leaves ``state`` untouched, so
      a host that has never skipped keeps a state.json byte-identical to its
      pre-CCE-140 content and the absent key reads as ``[]`` everywhere.
    """
    if not records:
        return
    existing = state.setdefault("skipped_prs", [])
    seen = {e.get("pr") for e in existing}
    for rec in records:
        if rec.get("pr") in seen:
            continue
        existing.append(rec)
        seen.add(rec.get("pr"))
```

- [ ] **Step 5: Run and watch them pass**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_deferral_skip.py tests/contracts/test_state_io.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent && git add scripts/orchestrator_runner.py scripts/state_io.py tests/orchestrator/test_deferral_skip.py tests/contracts/test_state_io.py && git commit -m "feat(CCE-140): pure deferral-counting helpers and the skipped_prs writer

deferral_key/partition_deferrals/next_deferral_counts are pure and take the
counts map as an argument, so the counting rules are unit-testable without a
git repo. merge_skipped_pr_records is the single writer of skipped_prs, and it
never seeds the key: a host that never skips keeps today's state.json."
```

---

## Task 8 — Wire deferral counting, skipping and the notification into `run()`

**Files:**

- Modify: `scripts/orchestrator_runner.py` (advance block; the `run()` import line for `state_io`)
- Test: `tests/orchestrator/test_deferral_skip.py`

**Interfaces:**

- Consumes: `advance_cursor_list`, `deferral_key`, `partition_deferrals`, `next_deferral_counts`, `resolve_deferral_threshold`, `state_io.merge_skipped_pr_records`, and the run-local `window_prs` / `admission_deferred` / `deferred_pages_by_pr` from Task 1.
- Produces: the finished behaviour. Nothing downstream consumes new symbols.

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/orchestrator/test_deferral_skip.py`:

```python
# ---------------------------------------------------------------------------
# End-to-end: counting, the skip on run 4, and the quiescent-host invariant
# ---------------------------------------------------------------------------

import json  # noqa: E402
import subprocess  # noqa: E402

FAKES_MULTI = Path(__file__).parent / "fakes_multi"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _fake_clock(values):
    it = iter(values)
    last = values[-1]
    return lambda: next(it, last)


def _fakes_with_prs(src: Path, dst: Path, prs: list[dict]) -> Path:
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        (dst / f.name).write_text(f.read_text())
    sc = json.loads((src / "fake_source_collector.json").read_text())
    sc["prs"] = prs
    (dst / "fake_source_collector.json").write_text(json.dumps(sc))
    return dst


def _seed_window(repo: Path, state_path: Path, n: int = 3) -> tuple[str, list[str]]:
    base = _git(repo, "rev-parse", "HEAD")
    shas = []
    for i in range(1, n + 1):
        (repo / "f.txt").write_text(f"c{i}")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    state_path.write_text(
        json.dumps({"version": "1", "last_successful_run": {"head_sha": base}})
    )
    return base, shas


def test_a_deferred_pr_accumulates_a_count(tmp_path, init_host):
    """One truncated run: PR 3 is deferred, so its count goes 0 -> 1 and it
    is NOT skipped."""
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    _base, (c1, c2, c3) = _seed_window(repo, state_path)
    fakes = _fakes_with_prs(
        FAKES_MULTI,
        tmp_path.parent / f"fakes_cce140_count_{tmp_path.name}",
        [
            {**_pr(1, c1), "files": [], "labels": [], "jira_keys": []},
            {**_pr(2, c2), "files": [], "labels": [], "jira_keys": []},
            {**_pr(3, c3), "files": [], "labels": [], "jira_keys": []},
        ],
    )
    rc = orun.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 50, 150]),  # admit 2 of 3
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    assert written["deferral_counts"] == {"unknown/unknown#3": 1}, written
    assert "skipped_prs" not in written
    assert written["last_successful_run"]["head_sha"] == c2


def test_a_pr_at_the_threshold_is_skipped_and_recorded(tmp_path, init_host):
    """Seed the count at 3, so THIS run is the fourth. The cursor walks past
    PR 3 to the window HEAD, a skipped_prs entry lands, and a NON-info_only
    partial reason names the PR."""
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    _base, (c1, c2, c3) = _seed_window(repo, state_path)
    state_path.write_text(
        json.dumps(
            {
                "version": "1",
                "last_successful_run": {"head_sha": _base},
                "deferral_counts": {"unknown/unknown#3": 3},
            }
        )
    )
    fakes = _fakes_with_prs(
        FAKES_MULTI,
        tmp_path.parent / f"fakes_cce140_skip_{tmp_path.name}",
        [
            {**_pr(1, c1), "files": [], "labels": [], "jira_keys": []},
            {**_pr(2, c2), "files": [], "labels": [], "jira_keys": []},
            {**_pr(3, c3), "files": [], "labels": [], "jira_keys": []},
        ],
    )
    rc = orun.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 50, 150]),  # admit 2 of 3, defer PR 3
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    # The cursor forgives PR 3 and walks into the deferred tail.
    assert written["last_successful_run"]["head_sha"] == c3, written
    entries = written["skipped_prs"]
    assert [e["pr"] for e in entries] == ["unknown/unknown#3"]
    assert entries[0]["deferrals"] == 3
    assert entries[0]["skipped_at"]
    # The count is cleared: a skipped PR never returns.
    assert "unknown/unknown#3" not in written.get("deferral_counts", {})
    cr = json.loads(
        (state_path.parent / "current_run.json").read_text()
    )["current_run"]
    reason = [r for r in cr["partial_reasons"] if r.startswith("deferral_skip:")]
    assert len(reason) == 1, cr["partial_reasons"]
    assert "unknown/unknown#3" in reason[0]
    assert cr["partial"] is True, (
        "the skip reason must NOT be info_only -- it is a recorded content "
        "loss and it has to reach the notifier digest"
    )


def test_a_skipped_pr_names_the_page_it_owed(tmp_path, init_host):
    """Authoring-truncation skip: the reason and the record name the pages.
    All three PRs share every page batch (the summarizer fixture is a single
    static file), so all three are over threshold and all three are skipped."""
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    _base, (c1, c2, c3) = _seed_window(repo, state_path)
    fakes = _fakes_with_prs(
        FAKES_MULTI,
        tmp_path.parent / f"fakes_cce140_pages_{tmp_path.name}",
        [
            {**_pr(1, c1), "files": [], "labels": [], "jira_keys": []},
            {**_pr(2, c2), "files": [], "labels": [], "jira_keys": []},
            {**_pr(3, c3), "files": [], "labels": [], "jira_keys": []},
        ],
    )
    summ = json.loads((fakes / "fake_pr_summarizer.json").read_text())
    summ["doc_targets"] = [
        {"lens": "core", "action": "create", "page_hint": f"connectors/{n}.md"}
        for n in ("alpha", "beta", "gamma")
    ]
    (fakes / "fake_pr_summarizer.json").write_text(json.dumps(summ))
    state_path.write_text(
        json.dumps(
            {
                "version": "1",
                "last_successful_run": {"head_sha": _base},
                "deferral_counts": {
                    "unknown/unknown#1": 3,
                    "unknown/unknown#2": 3,
                    "unknown/unknown#3": 3,
                },
            }
        )
    )
    rc = orun.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        # admission 10,20 (all 3 admitted); authoring batch-1 gate at 150.
        now_monotonic=_fake_clock([0, 10, 20, 150]),
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    entries = {e["pr"]: e for e in written["skipped_prs"]}
    assert set(entries) == {
        "unknown/unknown#1",
        "unknown/unknown#2",
        "unknown/unknown#3",
    }
    assert entries["unknown/unknown#1"]["pages"] == [
        "core/connectors/beta.md",
        "core/connectors/gamma.md",
    ]
    cr = json.loads(
        (state_path.parent / "current_run.json").read_text()
    )["current_run"]
    assert any(
        r.startswith("deferral_skip:") and "core/connectors/beta.md" in r
        for r in cr["partial_reasons"]
    ), cr["partial_reasons"]


def test_threshold_zero_never_skips_end_to_end(tmp_path, init_host):
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    config_path = tmp_path / ".engineering-docs-agent" / "config.yml"
    config_path.write_text(
        config_path.read_text() + "\nrun:\n  deferral_skip_threshold: 0\n"
    )
    _base, (c1, c2, c3) = _seed_window(repo, state_path)
    state_path.write_text(
        json.dumps(
            {
                "version": "1",
                "last_successful_run": {"head_sha": _base},
                "deferral_counts": {"unknown/unknown#3": 99},
            }
        )
    )
    fakes = _fakes_with_prs(
        FAKES_MULTI,
        tmp_path.parent / f"fakes_cce140_zero_{tmp_path.name}",
        [
            {**_pr(1, c1), "files": [], "labels": [], "jira_keys": []},
            {**_pr(2, c2), "files": [], "labels": [], "jira_keys": []},
            {**_pr(3, c3), "files": [], "labels": [], "jira_keys": []},
        ],
    )
    rc = orun.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 50, 150]),
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    assert "skipped_prs" not in written
    assert written["last_successful_run"]["head_sha"] == c2


def test_a_clean_run_writes_neither_new_key(tmp_path, init_host):
    """The quiescent-host invariant: nothing deferred, nothing skipped, so
    state.json gains neither key and a host that never truncates sees no
    change at all."""
    state_path = init_host({"version": "1", "last_successful_run": {}})
    rc = orun.run(
        tmp_path, dry_run_dir=FAKES_MULTI, no_pr=True, time_budget_seconds=0
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    assert "skipped_prs" not in written
    assert "deferral_counts" not in written
```

> The `unknown/unknown#N` keys are not a typo. `detect_repo` (`scripts/orchestrator_runner.py:37-50`) returns `{"owner": "unknown", "name": "unknown"}` when it cannot parse an `origin` remote, and the `init_host` fixture creates a bare `git init` with no remote. If a future conftest change adds a remote, these keys change — that is a correct, load-bearing coupling, not a fragile one. Run `.venv/bin/python -c "import sys;sys.path.insert(0,'scripts');import orchestrator_runner as o;from pathlib import Path;print(o.detect_repo(Path('/tmp')))"` to confirm the fallback if a key assertion fails.

- [ ] **Step 2: Run and watch them fail**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_deferral_skip.py -q
```

Expected: `test_a_deferred_pr_accumulates_a_count` fails with `KeyError: 'deferral_counts'`; `test_a_pr_at_the_threshold_is_skipped_and_recorded` and `test_a_skipped_pr_names_the_page_it_owed` fail with `KeyError: 'skipped_prs'`. The `threshold_zero` and `clean_run` tests already pass (nothing writes the keys yet) — that is fine; they are regression locks, not drivers.

- [ ] **Step 3: Import the new state writer**

Measured (reconciliation, plugin `d7e559c`): `scripts/orchestrator_runner.py:17-28` uses the single parenthesised, alphabetically-sorted form. There is no ambiguity and no branch to choose. Change:

```python
from state_io import (
    ConfigError,
    StateError,
    add_partial,
    cleanup_empty_parents,
    load_config_validated,
    load_state_validated,
    load_voice_samples,
    resolve_lens,
    save_current_run,
    save_persistent_state,
)
```

to:

```python
from state_io import (
    ConfigError,
    StateError,
    add_partial,
    cleanup_empty_parents,
    load_config_validated,
    load_state_validated,
    load_voice_samples,
    merge_skipped_pr_records,
    resolve_lens,
    save_current_run,
    save_persistent_state,
)
```

(`load_voice_samples` < `merge_skipped_pr_records` < `resolve_lens` — the sort order is preserved.) Confirm the block still matches before editing; Tracks A and C do not touch it, so it should be byte-identical:

```bash
cd /Users/theo/Projects/engineering-docs-agent && sed -n '17,28p' scripts/orchestrator_runner.py
```

- [ ] **Step 4: Compute the skip set and write the state**

In `scripts/orchestrator_runner.py`, find the block installed by Task 1 Step 7d and Task 2 Step 3b, which now reads:

```python
            skipped_numbers: set = set()
            advance_sha = prior_baseline_sha
            advance_cursor_backed = False
            # CCE-140: hold every PR this run did not finish out of the cursor
```

Replace those four lines (keeping the comment and everything after it) with:

```python
            # CCE-140: decide which deferred PRs this run abandons, BEFORE the
            # cursor walk — forgiveness is what lets the walk continue past
            # them. `counts` is the PRIOR map, so a stored count equal to the
            # threshold means this run is the (threshold+1)-th.
            _deferral_counts = state.get("deferral_counts", {}) or {}
            _threshold = resolve_deferral_threshold(config)
            _deferred_all = list(admission_deferred) + [
                pr_by_number[n]
                for n in sorted(deferred_pages_by_pr)
                if n in pr_by_number
            ]
            _skipped_prs, _still_deferred = partition_deferrals(
                _deferred_all,
                counts=_deferral_counts,
                repo=repo,
                threshold=_threshold,
            )
            skipped_numbers = {p.get("number") for p in _skipped_prs}
            advance_sha = prior_baseline_sha
            advance_cursor_backed = False
            # CCE-140: hold every PR this run did not finish out of the cursor
```

Then find the `still_deferred` list-comprehension installed by Task 1 Step 7d:

```python
            still_deferred = [
                p
                for p in list(admission_deferred)
                + [
                    pr_by_number[n]
                    for n in sorted(deferred_pages_by_pr)
                    if n in pr_by_number
                ]
                if p.get("number") in held_back
            ]
```

Replace with:

```python
            still_deferred = _still_deferred
```

- [ ] **Step 5: Persist the counts, the records and the reason**

Find (installed by Task 2 Step 3c):

```python
        global _LAST_ADVANCE_CURSOR_BACKED
        _LAST_ADVANCE_CURSOR_BACKED = advance_cursor_backed
        state["last_successful_run"] = {
            "head_sha": advance_sha,
            "completed_at": now,
        }
```

Replace with:

```python
        global _LAST_ADVANCE_CURSOR_BACKED
        _LAST_ADVANCE_CURSOR_BACKED = advance_cursor_backed
        if time_truncated:
            # CCE-140 / spec Decision 3. Record the loss loudly and durably.
            # The reason is deliberately NOT info_only: it is content the
            # pipeline chose to abandon, and `partial` is what routes it into
            # the notifier digest. It does not veto the merge — the skip only
            # takes effect if this run merges (see _MERGE_VETO_REASON_PREFIXES).
            _records = []
            for _pr_obj in _skipped_prs:
                _k = deferral_key(repo, _pr_obj.get("number"))
                _pages = sorted(set(deferred_pages_by_pr.get(_pr_obj.get("number"), [])))
                _records.append(
                    {
                        "pr": _k,
                        "url": _pr_obj.get("url", ""),
                        "pages": _pages,
                        "deferrals": int(_deferral_counts.get(_k, 0)),
                        "skipped_at": now,
                    }
                )
                add_partial(
                    state,
                    f"deferral_skip: {_k} skipped after "
                    f"{int(_deferral_counts.get(_k, 0))} consecutive deferrals "
                    f"(threshold {_threshold}); pages="
                    + (", ".join(_pages) if _pages else "(none authored)"),
                )
            merge_skipped_pr_records(state, _records)
            _next_counts = next_deferral_counts(
                _deferral_counts,
                repo=repo,
                window_pr_numbers={
                    p.get("number") for p in window_prs if p.get("number") is not None
                },
                still_deferred_numbers={
                    p.get("number") for p in still_deferred
                },
            )
            if _next_counts:
                state["deferral_counts"] = _next_counts
            else:
                state.pop("deferral_counts", None)
        state["last_successful_run"] = {
            "head_sha": advance_sha,
            "completed_at": now,
        }
```

- [ ] **Step 6: Run and watch them pass**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_deferral_skip.py -q
```

Expected: all pass.

- [ ] **Step 7: Re-run every advance-path test**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/orchestrator/test_time_budget.py tests/orchestrator/test_time_budget_authoring.py tests/orchestrator/test_state_advancement_invariant.py tests/orchestrator/test_cursor_backed_merge.py tests/orchestrator/test_auto_merge.py tests/orchestrator/test_deferral_skip.py -q
```

Expected: all pass. If `test_truncation_refuses_advance_when_deferred_pr_unanchored` fails, check that `still_deferred` is `_still_deferred` (Step 4) and not filtered by `held_back` — the unanchored guard must see the PR even though it is also held back.

- [ ] **Step 8: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent && git add scripts/orchestrator_runner.py tests/orchestrator/test_deferral_skip.py && git commit -m "feat(CCE-140): abandon a PR deferred on N consecutive runs, loudly

Three consecutive deferrals (run.deferral_skip_threshold, default 3) and the
next run forgives the PR: the cursor walks past it, a record lands in the
durable state.json skipped_prs list, and a NON-info_only partial reason names
the PR and the pages it owed so it reaches the notifier digest. A loud,
recorded loss beats an indefinite silent stall."
```

---

## Task 9 — Full-suite regression, CHANGELOG, README

**Files:**

- Modify: `CHANGELOG.md`, `README.md`
- Test: the whole suite

**Interfaces:**

- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Run the full suite**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -20
```

Expected: `0 failed` and `5 skipped`. If the skip count is not 5, something got skipped that should not have; investigate before proceeding.

The pass count is **not** `1203 + this plan's tests`. Track B lands **last**, after A (CCE-138) and C (CCE-139), and both add tests to the same suite:

| Contribution                                                                            | Tests    |
| --------------------------------------------------------------------------------------- | -------- |
| Clean-`main` baseline measured at `d7e559c`                                             | **1203** |
| Track A — `tests/orchestrator/test_authoring_truncation_advance.py`                     | +5       |
| Track C — 27 (4+8+4+4 lint, 1 sentinel, 3 config schema, 3 pr-summarizer schema)        | +27      |
| **Expected baseline when Track B starts**                                               | **1235** |
| Track B Task 1 (7 helper unit tests + 1 authoring integration; Step 9 rewrites, adds 0) | +8       |
| Track B Task 2                                                                          | +2       |
| Track B Task 3 (6 gate tests + 1 end-to-end; Step 7b rewrites in place, adds 0)         | +7       |
| Track B Task 4 (1 composition + 2 surfacing)                                            | +3       |
| Track B Task 5 (4 resolver + 3 config schema)                                           | +7       |
| Track B Task 6 (5 state schema + 2 state_io)                                            | +7       |
| Track B Task 7 (11 helper + 3 state_io)                                                 | +14      |
| Track B Task 8 (5 integration)                                                          | +5       |
| **Expected total after Track B**                                                        | **1288** |

**Do not treat a mismatch as a failure.** Run `git log --oneline main | head -20` and confirm A's and C's commits are ancestors; if `main` moved for any other reason, recompute from the actual collected total. `0 failed` is the gate; the arithmetic is a sanity check.

- [ ] **Step 2: Verify the dogfood config still validates**

The plugin dogfoods itself. Confirm its own config still loads under the amended schema:

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
from pathlib import Path
from state_io import load_config_validated, load_state_validated
c = load_config_validated(Path('.engineering-docs-agent/config.yml'))
s = load_state_validated(Path('.engineering-docs-agent/state.json'))
print('config ok; run block =', c.get('run'))
print('state ok; keys =', sorted(s))
"
```

Expected: `config ok; run block = …` and `state ok; keys = [...]` with no traceback. If `.engineering-docs-agent/config.yml` does not exist in the plugin repo, skip this step and note it.

- [ ] **Step 3: Verify the HOST config still validates under the amended schema**

Track B ships a schema change that the host's config must survive. The host does not set the new key, but confirm the load path is clean:

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
from pathlib import Path
from state_io import load_config_validated, load_state_validated
c = load_config_validated(Path('/Users/theo/Projects/advanced-data-importer/.engineering-docs-agent/config.yml'))
s = load_state_validated(Path('/Users/theo/Projects/advanced-data-importer/.engineering-docs-agent/state.json'))
print('host config ok; run block =', c.get('run'))
print('host state ok; keys =', sorted(s))
print('skipped_prs default =', s.get('skipped_prs', []))
print('deferral_counts default =', s.get('deferral_counts', {}))
"
```

Expected: both load; `skipped_prs default = []` and `deferral_counts default = {}`. **This is the back-compat proof against the real production state file**, not a synthetic one.

- [ ] **Step 4: Update the CHANGELOG**

In `CHANGELOG.md`, insert immediately after the `### Fixed` heading under `## [Unreleased]` (i.e. as the new first bullet, above the `**CCE-134**` entry):

```markdown
- **CCE-140** — the nightly merges itself. `_maybe_auto_merge`'s first condition was `if partial: return skip("partial_run")`, and every run this pipeline has ever produced is partial — so the auto-merge path never once fired on the flagship host. All ten docs-agent PRs that landed there were merged by hand, by one person, and the baseline froze on the day those manual merges stopped, unnoticed for sixteen days. `partial` now blocks only a run whose baseline advance would reach the full window HEAD; a run whose `advance_sha` came from the CCE-109 cursor has, by construction, advanced only past PRs whose pages all landed, and it merges. Making that guarantee true required narrowing the cursor itself: it was computed over the whole admitted PR list, so once CCE-140 taught the authoring loop to truncate, a run could advance past PRs whose page batches were never written. `advance_cursor_list` now stops the walk at the OLDEST unfinished PR, because the cursor is a prefix boundary — advancing past an unfinished PR strands it outside every future window and nothing re-collects it. `fact_check_warnings` stops gating: the fact-checker documents itself as a warn layer at `:1755-1760` ("never a partial flag, never a dropped page") and the gate contradicted its own contract; the warnings keep the PR-body section and the notifier digest, both now pinned by tests since nothing else depends on the list. An explicit `_MERGE_VETO_REASON_PREFIXES` list preserves the one coupling the old gate carried by accident: `app_token_unavailable` is recorded as blocking expressly so auto-merge skips, because a PR built on the fallback `GITHUB_TOKEN` never fires host CI and `gh pr checks` returning `[]` would read as green. And a PR deferred on `run.deferral_skip_threshold` consecutive runs (default 3, `0` disables) is abandoned on the next: the cursor walks past it, a record lands in a durable append-only `skipped_prs` array in `state.json`, and a non-informational partial reason names the PR and the pages it owed so it reaches notifications. Neither new state key is ever seeded empty, and `state.schema.json`'s root has no `additionalProperties: false` — so a pre-CCE-140 `state.json` validates unchanged, a post-CCE-140 one validates against the old schema, and there is no migration and no version bump. The human-edit guard is untouched but changes character: it sits after the new gate and was previously unreachable on the merge path (every run skipped first), so it goes from dead code to the primary human override, and a test now pins that a cursor-backed partial still loses to it.
```

- [ ] **Step 5: Correct the README's now-false claim**

In `README.md`, find this sentence inside the paragraph at line 47:

```
When that value is exactly `failure` — an App is configured but its installation token could not be minted, typically because the App was uninstalled or transferred to another account — the orchestrator records a blocking `app_token_unavailable` reason and marks the run partial, which disables auto-merge: a PR built on the fallback `GITHUB_TOKEN` never triggers host CI, so its check list would be empty rather than green.
```

Replace with:

```
When that value is exactly `failure` — an App is configured but its installation token could not be minted, typically because the App was uninstalled or transferred to another account — the orchestrator records a blocking `app_token_unavailable` reason and marks the run partial. Since CCE-140 a partial run is no longer barred from auto-merging outright (a cursor-backed advance merges), so `app_token_unavailable` carries its own explicit veto in `_MERGE_VETO_REASON_PREFIXES`: a PR built on the fallback `GITHUB_TOKEN` never triggers host CI, so its check list would be empty rather than green, and the cursor proves only that the baseline is honest — not that anything validated this PR.
```

Then append a new paragraph immediately after it:

```
Auto-merge eligibility (CCE-140): `merge.policy: auto` (the default when the block is absent), no vetoing partial reason, and either a non-partial run **or** a run whose baseline advance came from the CCE-109 cursor. Fact-checker warnings never gate the merge — they ride the PR body and the notification. A PR deferred on `run.deferral_skip_threshold` consecutive runs (default 3; set `0` to disable) is abandoned on the next run, recorded in `state.json`'s append-only `skipped_prs` array, and named in a partial reason so the notification carries it. A human commit on the docs-agent PR still blocks the merge unconditionally.
```

- [ ] **Step 6: Re-run the full suite one final time**

```bash
cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: `0 failed`, `5 skipped`.

- [ ] **Step 7: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent && git add CHANGELOG.md README.md && git commit -m "docs(CCE-140): changelog and README for autonomous merge

README:47 claimed a partial run 'disables auto-merge'. That is no longer
true, and the replacement names the explicit veto that preserves the
app-token coupling."
```

- [ ] **Step 8: Open the PR — LAST, after A, C and D have merged**

```bash
cd /Users/theo/Projects/engineering-docs-agent && git log --oneline origin/main..HEAD
```

Confirm Track A's commit is an ancestor (it must already be on `main`). Then:

```bash
cd /Users/theo/Projects/engineering-docs-agent && gh pr create --title "[CCE-140] Autonomous merge — cursor-backed partial merges, fact-check demotion, deferral skip hatch" --body "$(cat <<'EOF'
Track B of the docs-agent self-sustaining design (host spec ADIS-490).
Lands LAST: A makes the advance honest, B throws the switch.

- Partial runs merge only when `advance_sha` came from the CCE-109 cursor.
  A partial run that would advance to full HEAD is still blocked.
- The cursor walk stops at the oldest unfinished PR, so the baseline moves
  by exactly the PRs whose pages all landed (spec Decision 2).
- `fact_check_warnings` warns via the PR body and the notification; it no
  longer gates (spec Decision 4).
- `app_token_unavailable` gains an explicit merge veto — the coupling the
  old unconditional `partial` gate carried by accident.
- A PR deferred on `run.deferral_skip_threshold` consecutive runs (default 3)
  is abandoned on the next, recorded in `state.json` `skipped_prs`, and named
  in a non-info_only partial reason.

No state migration: `state.schema.json`'s root has no `additionalProperties:
false`, so a pre-CCE-140 `state.json` validates unchanged and neither new key
is ever seeded empty.

**This merges to a repo consumed at `ref: main`. It is live on the next fire.**
EOF
)"
```

---

## Self-Review

**Spec coverage.**

| Spec requirement (Track B)                                                 | Task                                                                                                                                                                                        |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| "Allow a partial run to auto-merge when its advance is cursor-backed"      | Task 2 (compute), Task 3 (gate)                                                                                                                                                             |
| "A partial run that would advance to full HEAD must still be blocked"      | Task 3 Step 1 `test_partial_run_with_full_head_advance_still_never_merges`; Task 2 Step 1 `test_lint_block_partial_run_advances_to_head_and_is_not_cursor_backed`; Task 3 Step 8 end-to-end |
| "the baseline moves by exactly the clean PRs" (acceptance)                 | Task 1 (`advance_cursor_list`)                                                                                                                                                              |
| "Demote `fact_check_warnings` … to a PR-body and notification warning"     | Task 3 Step 4 (removal), Task 4 (test inversion + surfacing pins)                                                                                                                           |
| "per-PR deferral counting … threshold is a config key with a default of 3" | Task 5, Task 7                                                                                                                                                                              |
| "skipped on the fourth: the cursor moves past it"                          | Task 7 `partition_deferrals` + Task 1 `advance_cursor_list` forgiveness path; Task 8 `test_a_pr_at_the_threshold_is_skipped_and_recorded`                                                   |
| "an entry is appended to a durable `skipped_prs` list in `state.json`"     | Task 6 (schema), Task 7 (`merge_skipped_pr_records`), Task 8 (wiring)                                                                                                                       |
| "a non-informational partial reason names the PR and the page"             | Task 8 Step 5; asserted in `test_a_skipped_pr_names_the_page_it_owed` and by `cr["partial"] is True`                                                                                        |
| "the `dismissed_gap_flags` key is the precedent for its shape"             | Task 6 schema mirrors it; Task 7 `deferral_key` produces the identical `{owner}/{name}#{pr}` string                                                                                         |
| Back-compat for a pre-`skipped_prs` `state.json`                           | Task 6 Steps 1/4, Task 9 Step 3 (against the real host file)                                                                                                                                |
| "Read the human-edit guard … say whether it interacts"                     | Design-notes section; Task 3 Step 1 `test_cursor_backed_partial_still_loses_to_the_human_edit_guard`                                                                                        |
| Testing clause: "assert `advance_sha != head_sha` explicitly"              | Task 1 Step 5, Task 2 Step 1 (both cases)                                                                                                                                                   |

**Placeholder scan.** No "TBD", no "similar to Task N", no "add appropriate error handling", no unfilled PR body. Task 8 Step 3's `state_io` import form was originally left as a two-branch conditional; it is now pinned to the single measured form (`scripts/orchestrator_runner.py:17-28`, parenthesised and alphabetically sorted) with the exact before/after block, so no branch remains.

**Reconciliation changes to this plan (2026-08-10).** Recorded here so the diff against the as-planned version is legible:

1. **Ticket key `CCE-141` → `CCE-140` throughout** (including the `_CCE141_BASE_CFG` constant and the `fakes_cce141_*` fixture directory names). Track D is a HOST track under `ADIS-490` and consumes no CCE number, so the plugin tracks take three consecutive keys, not four.
2. **Task 1 gained Step 9 — reconcile Track A's test file.** This is the reconciliation's highest-value finding. Task 1's cursor narrowing inverts three of the five tests Track A ships in `tests/orchestrator/test_authoring_truncation_advance.py`, a file that did not exist when this plan was written. Left unhandled, Track B's first full-suite run is red for a reason nothing in the plan explains. The three rewrites are given verbatim; the two unaffected tests are named so nobody touches them.
3. **Task 3 gained Step 7b, and Task 4's Step 1 moved into it.** The plan previously committed a knowingly-red suite ("Known failing until the next commit"), which contradicts its own TDD rule. The inverted test is now rewritten in the commit that inverts it.
4. **Baseline corrected 1206 → 1203.** The 1206 was the dirty tree (a concurrent agent's probe contributed +3). Re-measured on a clean tree at `d7e559c`: `1203 passed, 5 skipped`. The probe file no longer exists.
5. **Task 9 Step 1's pass-count arithmetic replaced with a per-track table.** Track B lands last; its starting baseline is 1235 (1203 + Track A's 5 + Track C's 27), not 1203.
6. **Task 1's Interfaces block now names the run-locals this plan consumes but never introduced** — `pr_by_number` (`:1548`, admitted-PRs-only, which is why Task 8 guards the lookup), `repo` (`:1340`), `now` (`:1347`), `config` (`:1316`). All four were verified in scope at the advance block.
7. **The `tests/schemas/test_config_schema.py` collision with Track C is documented and deliberately not resolved** — the two hoisted constants have different names and different contents; merging them would rewrite an already-landed Track C test.

**Type consistency.** `advance_cursor_list(admitted, deferred_tail, *, held_back)` — same signature in Task 1 Step 3, Task 1 Step 7d, Task 7 docstrings. `partition_deferrals(deferred, *, counts, repo, threshold) -> (skipped, still)` — same in Task 7 Step 3 and Task 8 Step 4. `next_deferral_counts(counts, *, repo, window_pr_numbers, still_deferred_numbers)` — same in Task 7 Step 3 and Task 8 Step 5. `merge_skipped_pr_records(state, records)` — same in Task 7 Step 4 and Task 8 Step 5. `_maybe_auto_merge(..., advance_cursor_backed=False, partial_reasons=())` — same in Task 3 Step 4 (signature), Task 3 Step 1 (`_run` helper), Task 3 Step 6 (call site). `_LAST_ADVANCE_CURSOR_BACKED` — declared Task 2 Step 3a, written Task 2 Step 3c / Task 8 Step 5, read Task 2 Step 1.

**One deliberate deviation from the prompt's three-change framing, stated plainly.** Task 1 (cursor narrowing) is not one of the three listed changes. It is included because change #1's gate is meaningless without it: after Track A, an authoring-truncated run's cursor names the last _admitted_ PR, not the last PR whose pages landed, so "cursor-backed" would certify an advance that spec Decision 2 forbids and Track B's own acceptance ("the baseline moves by exactly the clean PRs") rules out. It shares all its machinery with change #3. If a reviewer cuts it, cut Task 1 Steps 5-9 and Task 8's authoring-skip test, and accept that an authoring-truncated run auto-merges an advance past unwritten pages — the exact silent loss this design exists to end.

---

## Post-implementation amendments (2026-08-10)

Recorded after the four-way verification. Re-executing this plan without them
produces a feature that does nothing, so they are part of the plan, not notes
about it. Deliberately not renumbered into tasks — the task sequence as
executed is the historical record.

### A. The merge epilogue is exempt from the run's time budget

`scripts/orchestrator_runner.py::_maybe_auto_merge`. Opening the partial gate
was necessary and not sufficient. Three lines below it, CCE-101's
`if deadline is not None and clock() + grace > deadline: return skip("time_budget")`
refused every run the new gate had just admitted: the only run that can be
cursor-backed is a time-truncated one, and a time-truncated run is past its
deadline by construction. The feature was a complete no-op, and the suite was
green — the gate had a unit test, the `advance_cursor_backed` computation had
a unit test, and nothing joined them by driving `run()` to `gh pr merge`.

The deadline now governs authoring only. The epilogue is bounded by
`merge.checks_grace_seconds` / `checks_timeout_seconds` measured from the
merge attempt. Guarded by an end-to-end pair in
`tests/orchestrator/test_cursor_backed_merge.py` that asserts on the
`FakeGhClient` call log — a merge fires when eligible, and an
`app_token_unavailable` veto blocks an otherwise identical run.

### B. Hosts must be re-sized, and the two timeouts are not interchangeable

A consequence of A, and cross-repo. A run's worst case moves from
`time_budget_seconds` to `time_budget_seconds + checks_timeout_seconds +
post-deadline tail`. At the plugin defaults that is 2700 + 900 = exactly the
60-minute job timeout both the dogfood workflow and `templates/workflow-run.yml`
carried, before counting setup or the App-token mint.

- both hosts set `run.time_budget_seconds: 2100`
- dogfood workflow and the scaffolding template move `timeout-minutes` 60 → 90
  (the template matters more: every host inherits it, at `ref: main`, with no
  release step to warn them)
- `tests/templates/test_workflow_run_parity.py`'s locked literal moves with them
- the host adds `tests/test_docs_agent_time_budget.py`

The ordering is load-bearing. A token expiry mid-poll degrades honestly —
`auto_merge_skipped: checks_query_failed`, branch pushed, nothing lost,
notification still sent. A **job** timeout mid-poll kills the process before
`run()`'s notifier dispatch, so it is silent: no digest, no partial reasons,
no alarm. That is the one outcome strictly worse than forfeiting the merge, so
the job timeout must stay the slacker of the two bounds.

### C. Four defects closed after the verification passes

Each shipped with a regression test proven red against the pre-fix code,
because the suite passed on both sides of all four:

1. `held_back` enumerated only time-deferred work, so a lint-reverted page or
   a failed dispatch let the cursor walk past a PR whose page was never
   written. Replaced with the complement of what actually landed, which covers
   failure modes nobody has enumerated yet.
2. Deferral-count pruning ran only under `if time_truncated:`, so a clean run
   never reset a counter and a truncated/clean/truncated alternation
   accumulated toward skipping a PR the pipeline was handling correctly.
3. A skip was recorded for PRs behind an older still-deferred one, which the
   walk never crosses — an uncorrectable entry in an append-only array plus an
   alarm for a loss that did not happen.
4. Decision 2's mixed case (some PRs landed, some did not) had no end-to-end
   coverage, because one static summarizer fixture is replayed for every PR.
   A per-PR dry-run fixture (`fake_<agent>__pr<N>.json`) makes it expressible.

### D. The `unanchored_deferred` refusal branch is NOT redundant

Recorded because it looks redundant and a reviewer proposed deleting it.
`advance_cursor_list` stops at the oldest held-back PR, so no still-deferred PR
can sit behind the cursor — but that holds only while list order tracks commit
order, and `_order_prs_oldest_first` documents the exception: a PR with no
`merge_sha` "sorts last (cannot anchor the cursor)". Sunk to the tail it looks
newest to the walk while its true merge point may be older than the cursor.
Deleting the branch trades a held baseline for a permanently stranded PR.
