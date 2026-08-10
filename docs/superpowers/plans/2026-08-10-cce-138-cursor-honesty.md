# Track A — Cursor Honesty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An authoring-truncated docs-agent run must advance the baseline to the CCE-109 per-PR cursor, never to the full window HEAD.

**Architecture:** The PR-admission loop already sets a local `time_truncated` flag when it trips the soft deadline, and the state-promotion block keys the entire CCE-109 safe-advance path off that flag. The page-authoring loop truncates for the same reason but sets nothing, so the promotion block takes its `else` branch and writes `state["current_run"]["head_sha"]` — the full window HEAD — as the new baseline. This track sets the existing flag from the authoring break. No new state, no new config key, no new refusal logic. The three CCE-109 refusal branches are not modified; they become **reachable** from a code path that previously bypassed them entirely.

**Tech Stack:** Python 3.11/3.12, stdlib-only runtime, pytest, fixture-driven dry-run dispatch (`dry_run_dir`), git-backed test repos in `tmp_path`.

---

## Global Constraints

Copied verbatim from `/Users/theo/Projects/advanced-data-importer/docs/superpowers/specs/2026-08-10-docs-agent-self-sustaining-design.md` (§"Track A — cursor honesty", §"Ordering constraint", §"Testing", §"Risks"). Every task's requirements implicitly include this section.

- **Repo:** plugin. **Files:** `scripts/orchestrator_runner.py`.
- "The authoring-loop break at `:1566-1572` records a partial reason and breaks without setting `time_truncated`. Set it, so an authoring-truncated run routes into the existing safe-advance block instead of falling through to full HEAD."
- "The advance block already handles everything else correctly; this track adds no new refusal logic and no new state."
- **Acceptance:** "a run truncated during authoring writes `advance_sha` equal to the last processed PR's merge sha, and not equal to `current_run.head_sha`. A run truncated during admission keeps its existing behaviour unchanged."
- **Ordering constraint:** "**A must precede B.** B enables merging; A makes the advance honest. Landing B first would merge every run while `advance_sha` still resolves to full HEAD — automating the silent-loss bug and running it nightly. A is safe to land first for the same reason the bug stayed invisible: `advance_sha` reaches `main` only through a merge, and nothing merges until B."
- **Testing:** "**Track A** — assert `advance_sha != head_sha` explicitly, not merely that it equals the cursor. The bug being fixed is a fall-through to HEAD, so the negative assertion is the one that would have caught it."
- **Risk 3 (binding on how this lands):** "**The plugin is consumed at `ref: main` by every host, including its own dogfood** — currently the only working reference that the agent can succeed at all. Plugin changes take effect on the next fire with no release step, which makes both iteration and breakage immediate."
- **Risk 2 (binding on every number below):** "**Measurement conflict.** Prior analyses produced three different counts of affected pages (66 / 52 / 48) and two irreconcilable citation figures (33 to 17, and 47 of 79). Every number in the plans is to be re-measured from scratch; none is inherited."

Additional binding constraints from the plugin repo's own `CLAUDE.md` (`/Users/theo/Projects/engineering-docs-agent/CLAUDE.md`):

- "All work happens on a feature branch off `main`. Direct commits to `main` are not allowed."
- "Branch naming: `<type>/CCE-<number>-<short-slug>`"; "Commit messages: include `CCE-<number>` in the subject line or trailer"; "PR titles: prefix or include `CCE-<number>`".
- "Tests: pytest. TDD for new behavior (failing test → implementation → green). All tests use the fixture-driven dry-run path."
- "Python: stdlib-first. New runtime deps require explicit justification in the spec."
- "Tests use fixtures that represent arbitrary hosts, not this repo's tree."

---

## Environment

There is **no bare `python`** on this machine. Every Python invocation in this plan uses the plugin's venv interpreter:

```
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python
```

`ruff` is **not** installed in that venv; it is on `PATH` at `/usr/local/bin/ruff` (version 0.15.7). CI (`.github/workflows/test.yml`) runs `python -m pytest -q` only — there is no ruff gate in CI, but the repo has a formatter hook, so new files must be `ruff format` clean.

Plugin repo root: `/Users/theo/Projects/engineering-docs-agent`
Host repo root: `/Users/theo/Projects/advanced-data-importer` (**not touched by this track**)

---

## Ground truth measured for this plan

Every figure below was produced by running the command shown, in this session, against the pristine repo. Nothing is inherited from a prior analysis.

| What                                                                                                | Value                                                                                                                                                                                                                                                                                                                                      | Command                                                                                                                 |
| --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| Plugin test baseline (pristine `main`)                                                              | `1203 passed, 5 skipped in 47.01s`                                                                                                                                                                                                                                                                                                         | `cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/ -q`                                |
| Plugin HEAD at measurement                                                                          | `d7e559c docs(agent): run 2026-08-10T19:17:56.705395+00:00 (#210)`                                                                                                                                                                                                                                                                         | `git -C /Users/theo/Projects/engineering-docs-agent log --oneline -1`                                                   |
| Pre-existing dirty working-tree entries (not created by this work, do not commit)                   | ` M .gitignore` and `?? uv.lock`                                                                                                                                                                                                                                                                                                           | `git -C /Users/theo/Projects/engineering-docs-agent status --short`                                                     |
| Expected suite total after this track                                                               | `1208 passed, 5 skipped` (1203 + 5 new tests)                                                                                                                                                                                                                                                                                              | measured with the fix and the new test file applied, then reverted                                                      |
| Per-task intermediate suite totals (1204 / 1205 / 1206 / 1207)                                      | **arithmetic, not measured** — only the 1203 and 1208 endpoints were run. Treat a mismatch as a signal to re-measure, not as a failure.                                                                                                                                                                                                    | —                                                                                                                       |
| Existing CCE-109 + CCE-114 suites (must not change)                                                 | `19 passed` in `test_time_budget.py`, `4 passed` in `test_time_budget_authoring.py`, `23 passed` together                                                                                                                                                                                                                                  | `.venv/bin/python -m pytest tests/orchestrator/test_time_budget.py tests/orchestrator/test_time_budget_authoring.py -q` |
| Host baseline drift (context only; host is untouched)                                               | **42** commits (`029dce87..HEAD`, re-measured at reconciliation time, host HEAD `03b1937f`). The spec says 38; an earlier measurement this session said 41. All three are correct at their own moment — this figure grows with every host commit and is load-bearing for nothing. Do not treat a mismatch as a defect; re-run the command. | `git -C /Users/theo/Projects/advanced-data-importer rev-list --count 029dce87..HEAD`                                    |
| Admission loop sets the flag at                                                                     | `scripts/orchestrator_runner.py:1491` (`time_truncated = True`, immediately after `prs = prs[:i]`)                                                                                                                                                                                                                                         | `sed -n '1487,1492p' scripts/orchestrator_runner.py`                                                                    |
| Authoring loop break at                                                                             | `scripts/orchestrator_runner.py:1566-1572` (`add_partial(...)` then a bare `break`)                                                                                                                                                                                                                                                        | `sed -n '1566,1573p' scripts/orchestrator_runner.py`                                                                    |
| Fall-through to full HEAD at                                                                        | `scripts/orchestrator_runner.py:2017` (`advance_sha = state["current_run"]["head_sha"]`)                                                                                                                                                                                                                                                   | `sed -n '2015,2018p' scripts/orchestrator_runner.py`                                                                    |
| All readers of `time_truncated`                                                                     | exactly two — `:1973` (the CCE-109 advance block) and `:2023` (the `window_head_sha` re-run marker). Nothing else branches on it.                                                                                                                                                                                                          | `grep -n "time_truncated" scripts/orchestrator_runner.py`                                                               |
| Observed bug, pre-fix (authoring truncation, 3 PR merges `c1..c3` + one non-PR commit `c4` at HEAD) | persisted baseline = `c4` (**HEAD**), `window_head_sha` **absent**, only 1 of 3 page batches written                                                                                                                                                                                                                                       | probe run, `runner.run(..., time_budget_seconds=100, now_monotonic=_fake_clock([0,10,20,150]))`                         |
| Observed behaviour, post-fix, same fixture                                                          | persisted baseline = `c3` (**cursor**), `window_head_sha` = `c4`                                                                                                                                                                                                                                                                           | same probe with `time_truncated = True` added                                                                           |
| Observed behaviour, post-fix, no admitted PR carries a `merge_sha`                                  | persisted baseline = the prior baseline (unchanged), reason `time_budget_no_advance_no_cursor: …`                                                                                                                                                                                                                                          | probe run                                                                                                               |
| Observed behaviour, post-fix, unresolvable cursor                                                   | persisted baseline = `old_sha_000` (unchanged), reason `time_budget_advance_out_of_window: cursor c unresolvable in repo (old_sha_..bd1c4894); baseline unchanged`                                                                                                                                                                         | probe run                                                                                                               |
| Admission-only truncation (1 doc target so the authoring loop never gates)                          | baseline = `c2`, `window_head_sha` = `c4`, **identical with and without the fix**                                                                                                                                                                                                                                                          | probe run, both revisions                                                                                               |

### Why the fixtures use four commits

`_last_processed_merge_sha(prs)` returns the newest admitted PR's `merge_sha`. Under an **authoring** truncation every PR was admitted, so the cursor is the **last** PR's merge sha. If a fixture's newest PR merge is also `HEAD`, then `advance_sha == cursor` and `advance_sha == head_sha` are the same statement and the test passes vacuously on the buggy code.

Every fixture in this plan therefore appends a fourth commit `c4` — a direct, non-PR commit — on top of `c3`, the newest PR merge. `HEAD == c4 != c3 == cursor` by construction. This mirrors production: the host's current `HEAD` (`b854a2a5`) is a direct commit, not a PR merge.

---

## File structure

- **Create:** `/Users/theo/Projects/engineering-docs-agent/tests/orchestrator/test_authoring_truncation_advance.py` — all five tests for this track. One file, because all five exercise the same seam (`runner.run` → the promotion block) and share four helpers. It uses the shared `init_host` / `read_current_run` fixtures from `tests/orchestrator/conftest.py`; it defines its own `_git` / `_fake_clock` / `_seed_window` / `_pr` / `_fakes` helpers rather than importing them from `tests/orchestrator/test_time_budget.py`, because cross-importing sibling test modules is fragile under pytest's prepend import mode and `_seed_window` here takes an `n` that the sibling's helper hardcodes differently.
- **Modify:** `/Users/theo/Projects/engineering-docs-agent/scripts/orchestrator_runner.py:1566-1572` — five added lines (one statement, four comment lines).
- **Modify:** `/Users/theo/Projects/engineering-docs-agent/CHANGELOG.md` — one entry under `## [Unreleased]` → `### Fixed`.

Not touched: `scripts/state_io.py`, `templates/config.schema.json`, any host file, any agent contract, any schema.

---

## Task 0 — Branch and ticket

**Files:** none (git and Jira only).

**Interfaces:**

- Consumes: nothing.
- Produces: the branch name and the `CCE-<number>` key that every commit subject and the PR title in Tasks 1-5 must carry.

- [ ] **Step 1: Confirm the working tree is at the measured baseline**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git checkout main && git pull --ff-only
git status --short
```

Expected: exactly two lines, ` M .gitignore` and `?? uv.lock`. These are pre-existing and are **not** part of this work — never `git add` either one. If anything else is listed, stop and resolve it before continuing.

- [ ] **Step 2: Confirm the test baseline**

```bash
cd /Users/theo/Projects/engineering-docs-agent
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -2
```

Expected: `1203 passed, 5 skipped` (the wall-clock figure varies; the counts must match). Re-confirmed at reconciliation on a clean tree at `d7e559c`.

Track A lands **first** of the four, so 1203 is both the measured and the expected figure — nothing else in this design has touched the suite yet. If the counts differ, `main` has moved for an unrelated reason: re-measure, record the new numbers in the PR body, and add 5 to whatever you measured for every later expectation in this plan. Do not assume this plan's absolute figures; the **delta of +5** is Track A's contract.

- [ ] **Step 3: File the Jira issue**

Create a Bug in the Claude-Code-Extensions project (`https://designitright.atlassian.net`, key prefix `CCE`) with:

- **Summary:** `Authoring-loop time truncation does not set time_truncated, so the baseline advances to full HEAD`
- **Description:** `scripts/orchestrator_runner.py:1566-1572 records a time_budget_exceeded partial reason and breaks without setting time_truncated. The admission loop at :1491 sets it. With the flag false, the promotion block takes its else branch at :2017 and writes state["current_run"]["head_sha"] — the full window HEAD — as the new baseline, so a run that authored 1 of N page batches persists a baseline claiming coverage of every PR in the window. Fix: set the existing flag from the authoring break, routing the run into the CCE-109 safe-advance block. Design: ADIS-490 "Docs-agent self-sustaining pipeline", Track A.`

Record the returned key. CCE-137 is the newest key landed on `main` (commit `0c88411`, PR #209), so the created issue is expected to be **CCE-138**. Every command below writes `CCE-138`; if the tracker returns a different key, substitute the returned key everywhere.

**Cross-track key assignment (reconciled 2026-08-10 — do not re-derive per track).** Track A and Track C independently both claimed CCE-138. The collision is resolved as follows, and all four plans now carry the assigned key throughout. **Track A files first**, because it lands first:

| Track | Repo   | Key                                |
| ----- | ------ | ---------------------------------- |
| A     | plugin | **CCE-138** ← this plan            |
| C     | plugin | **CCE-139**                        |
| D     | host   | **ADIS-490** (consumes no CCE key) |
| B     | plugin | **CCE-140**                        |

If the tracker allocates something other than 138 here, every later plugin key shifts by the same amount — tell whoever is executing Tracks C and B before they file.

- [ ] **Step 4: Create the branch**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git checkout -b fix/CCE-138-authoring-truncation-cursor
git branch --show-current
```

Expected output: `fix/CCE-138-authoring-truncation-cursor`

---

## Task 1 — Pin the authoring-truncation advance to the CCE-109 cursor

The core of the track. One failing test that asserts the negative (`advance != head`) first and the positive (`advance == cursor`) second, then the five-line implementation.

**Files:**

- Create: `/Users/theo/Projects/engineering-docs-agent/tests/orchestrator/test_authoring_truncation_advance.py`
- Modify: `/Users/theo/Projects/engineering-docs-agent/scripts/orchestrator_runner.py:1566-1572`

**Interfaces:**

- Consumes from earlier tasks: nothing. From the existing codebase it consumes, unchanged and unmodified:
  - `orchestrator_runner.run(repo_root, *, dry_run_dir, no_pr, time_budget_seconds, now_monotonic) -> int`
  - `orchestrator_runner._last_processed_merge_sha(admitted_prs: list[dict]) -> str | None`
  - `orchestrator_runner._rev_parse_commit(repo_root, rev) -> str | None`
  - `orchestrator_runner._sha_in_window(sha, *, last_sha, head_sha, repo_root) -> tuple[bool, str]`
  - pytest fixtures `init_host(seeded_state: dict, config_yaml: str = CONFIG_YAML, seed_files: dict[str,str] | None = None) -> Path` and `read_current_run(state_path: Path) -> dict`, both from `tests/orchestrator/conftest.py`.
- Produces, for **Track B** (`_maybe_auto_merge` and the cursor-backed merge gate) to rely on:
  - After an **authoring** truncation, the local `time_truncated` in `orchestrator_runner.run` is `True`, so control reaches the CCE-109 block at `:1973` and `advance_sha` is either the normalized cursor or the held prior baseline — **never** `state["current_run"]["head_sha"]`.
  - The persisted contract Track B reads: `state["last_successful_run"]["head_sha"]` is the advance; `state["last_successful_run"]["window_head_sha"]` is present **iff** the run truncated (admission or authoring) and equals `state["current_run"]["head_sha"]`. It is absent on a non-truncated run — pinned by the pre-existing `tests/orchestrator/test_time_budget.py::test_unlimited_budget_processes_all_prs`.
  - The predicate Track B needs for "this advance is cursor-backed, not full HEAD" is derivable with **no new state**: `advance_sha != state["current_run"]["head_sha"]`. Track A deliberately adds no boolean for it.
  - Note for Track B: `window_head_sha` present means _truncated_, which includes the refusal cases where the baseline did **not** move. Presence of that key is therefore not by itself proof that the baseline advanced.
- Produces nothing consumed by Tracks C or D.

**Forward notice — Track B (CCE-140) supersedes three of this track's five tests.** Recorded here so nobody executing Track B reads the inversion as a regression, and so nobody executing Track A writes the tests more rigidly than they need to be.

Track A's acceptance is the spec's Track A acceptance verbatim: an authoring-truncated run advances to _the last processed PR's merge sha_. Spec **Decision 2** is stricter — "the baseline advances only to the last PR whose pages all landed" — and Track B implements it by narrowing the cursor walk (`advance_cursor_list`). Under that narrowing, an authoring-truncated run in which every admitted PR still owes a page batch advances **nowhere**, not to `c3`. Both statements are correct at their own point in the sequence; A is a strict improvement on the fall-through-to-HEAD bug, and B is a strict improvement on A.

Concretely, after Track B lands:

| Test in this file                                                   | Under Track A          | Under Track B                                                     |
| ------------------------------------------------------------------- | ---------------------- | ----------------------------------------------------------------- |
| `test_authoring_truncation_advances_to_cursor_not_head`             | `advance == c3`        | `advance == base` — **Track B Task 1 Step 9a rewrites + renames** |
| `test_authoring_truncation_without_cursor_holds_baseline`           | `advance == base`      | unchanged                                                         |
| `test_authoring_truncation_with_unresolvable_cursor_holds_baseline` | reason `out_of_window` | reason `no_cursor` — **Track B Task 1 Step 9b rewrites**          |
| `test_authoring_truncation_never_reports_unanchored_deferred`       | `advance == c3`        | `advance == base` — **Track B Task 1 Step 9c rewrites**           |
| `test_admission_truncation_advance_unchanged_by_track_a`            | `advance == c2`        | unchanged                                                         |

`assert advance != head` — the spec's Testing directive and the assertion that would have caught the original bug — survives in every one of them. Do not weaken it in anticipation of Track B; Track B keeps it.

- [ ] **Step 1: Write the failing test**

Create `/Users/theo/Projects/engineering-docs-agent/tests/orchestrator/test_authoring_truncation_advance.py` with exactly this content:

```python
# tests/orchestrator/test_authoring_truncation_advance.py
"""Track A: an authoring-truncated run advances to the CCE-109 cursor, never
to the full window HEAD.

The PR-admission loop sets ``time_truncated`` when it hits the soft deadline
(orchestrator_runner.py:1491). The authoring loop truncates for the same reason
and historically set nothing, so ``advance_sha`` fell through to
``state["current_run"]["head_sha"]`` — the full window HEAD — and the run
persisted a baseline covering PRs whose pages it never authored.

Every fixture here places a NON-PR commit (``c4``) on top of the newest PR
merge commit (``c3``), so the cursor and HEAD are provably different shas.
Asserting ``advance == cursor`` alone would pass vacuously on a fixture whose
newest PR merge happens to BE head; the discriminating assertion — and the one
that would have caught the original fall-through — is ``advance != head``.
"""

from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import orchestrator_runner as runner  # noqa: E402

FAKES_MULTI = Path(__file__).parent / "fakes_multi"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _fake_clock(values):
    """Monotonic values in order, then repeating the last. The first value is
    consumed by the deadline calc (same helper as test_time_budget.py)."""
    it = iter(values)
    last = values[-1]
    return lambda: next(it, last)


def _seed_window(repo: Path, state_path: Path, n: int) -> tuple[str, list[str]]:
    """Add n commits on top of the host's init commit and pin the baseline at
    that init commit, so last_sha..HEAD is a real n-commit window.
    Returns (base_sha, [c1..cn] oldest-first)."""
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


def _pr(n: int, sha: str | None = None) -> dict:
    d = {"number": n, "title": f"PR {n}", "url": f"https://github.com/o/r/pull/{n}"}
    if sha:
        d["merge_sha"] = sha
    return d


def _fakes(dst: Path, prs: list[dict] | None, hints: list[str] | None) -> Path:
    """Copy fakes_multi, optionally overriding the collector's PRs and the
    summarizer's doc_targets (one batch per hint drives the authoring loop)."""
    dst.mkdir(parents=True, exist_ok=True)
    for f in FAKES_MULTI.iterdir():
        (dst / f.name).write_text(f.read_text())
    if prs is not None:
        sc = json.loads((FAKES_MULTI / "fake_source_collector.json").read_text())
        sc["prs"] = prs
        (dst / "fake_source_collector.json").write_text(json.dumps(sc))
    if hints is not None:
        summ = json.loads((FAKES_MULTI / "fake_pr_summarizer.json").read_text())
        summ["doc_targets"] = [
            {"lens": "core", "action": "create", "page_hint": h} for h in hints
        ]
        (dst / "fake_pr_summarizer.json").write_text(json.dumps(summ))
    return dst


THREE_HINTS = ["connectors/alpha.md", "connectors/beta.md", "connectors/gamma.md"]
# deadline=100; admission gates at 10 and 20 admit all 3 PRs; authoring batch 0
# is unconditional, batch 1's gate sees 150 → the authoring loop truncates.
AUTHORING_TRUNCATION_CLOCK = [0, 10, 20, 150]


def test_authoring_truncation_advances_to_cursor_not_head(tmp_path, init_host):
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (c1, c2, c3, c4) = _seed_window(repo, state_path, 4)
    # c4 is a direct (non-PR) commit, so HEAD is strictly ahead of the newest
    # PR merge — cursor and head can never coincide in this fixture.
    fakes = _fakes(
        tmp_path.parent / f"trackA_cursor_{tmp_path.name}",
        [_pr(1, c1), _pr(2, c2), _pr(3, c3)],
        THREE_HINTS,
    )
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock(AUTHORING_TRUNCATION_CLOCK),
    )
    assert rc == 0
    core = repo / "docs" / "site-src" / "core" / "connectors"
    # Precondition: the run really was cut inside the authoring loop.
    assert (core / "alpha.md").exists()
    assert not (core / "beta.md").exists()
    assert not (core / "gamma.md").exists()
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    head = _git(repo, "rev-parse", "HEAD")
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

- [ ] **Step 2: Run the test and watch it fail**

```bash
cd /Users/theo/Projects/engineering-docs-agent
.venv/bin/python -m pytest tests/orchestrator/test_authoring_truncation_advance.py -q
```

Expected: `1 failed`. The failure is on the negative assertion, and both sides of the inequality are the same 40-hex sha (the run's `HEAD`, i.e. `c4`):

```
>       assert advance != head, written["last_successful_run"]
E       AssertionError: {'head_sha': '1f9211fc2ca6e72f7d56876249f52dc0b460426d', 'completed_at': '...'}
E       assert '1f9211fc2ca6e72f7d56876249f52dc0b460426d' != '1f9211fc2ca6e72f7d56876249f52dc0b460426d'
tests/orchestrator/test_authoring_truncation_advance.py:124: AssertionError
```

The sha value differs on every run (the fixture repo is created fresh in `tmp_path`); what must match is the shape — one failure, on `assert advance != head`, with two identical shas. If instead the failure is on `assert (core / "alpha.md").exists()` or on `assert head == c4`, the fixture is not truncating where it should — fix the fixture before touching the runner.

- [ ] **Step 3: Write the minimal implementation**

In `/Users/theo/Projects/engineering-docs-agent/scripts/orchestrator_runner.py`, find the authoring-loop break at line 1566-1572:

```python
            if deadline is not None and i > 0 and clock() > deadline:
                add_partial(
                    state,
                    f"time_budget_exceeded: authored {i}/{len(per_target)} "
                    f"page batches (budget {budget}s); deferring the rest",
                )
                break
```

Replace it with:

```python
            if deadline is not None and i > 0 and clock() > deadline:
                add_partial(
                    state,
                    f"time_budget_exceeded: authored {i}/{len(per_target)} "
                    f"page batches (budget {budget}s); deferring the rest",
                )
                # Track A: an authoring truncation is a truncation. Without
                # this the advance block below falls through to
                # current_run.head_sha and the run persists a baseline
                # covering PRs whose pages it never wrote.
                time_truncated = True
                break
```

That is the entire implementation. Do not add a `deferred_unanchored` assignment here — see Task 3 for why that would be wrong.

- [ ] **Step 4: Run the test and watch it pass**

```bash
cd /Users/theo/Projects/engineering-docs-agent
.venv/bin/python -m pytest tests/orchestrator/test_authoring_truncation_advance.py -q
```

Expected: `1 passed`

- [ ] **Step 5: Run the full suite**

```bash
cd /Users/theo/Projects/engineering-docs-agent
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -2
```

Expected: `1204 passed, 5 skipped` (baseline 1203 + this one new test). No pre-existing test may fail — this was verified against the whole suite while measuring this plan.

- [ ] **Step 6: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add tests/orchestrator/test_authoring_truncation_advance.py scripts/orchestrator_runner.py
git commit -m "fix(CCE-138): authoring truncation sets time_truncated so the baseline advances to the cursor

The admission loop sets time_truncated at :1491; the authoring loop broke
without it, so the promotion block fell through to current_run.head_sha and
a run that wrote 1 of N page batches persisted a baseline claiming the whole
window. The new test asserts the negative (advance != head) as well as the
positive (advance == cursor); the fixture puts a non-PR commit on top of the
newest PR merge so the two can never coincide.

Design: ADIS-490 Track A."
```

---

## Task 2 — Make the CCE-109 refusal branches reachable from the authoring loop

The CCE-109 block at `:1982-2015` has three refusal branches. Before Task 1 they were dead code for any authoring-truncated run — the run bypassed the whole block. This task proves each one now behaves correctly on that path. These tests are also the mutation guard for Task 1: they must fail if the `time_truncated = True` line is ever removed.

**Files:**

- Modify: `/Users/theo/Projects/engineering-docs-agent/tests/orchestrator/test_authoring_truncation_advance.py` (append two tests)

**Interfaces:**

- Consumes from Task 1: the module-level helpers `_git`, `_fake_clock`, `_seed_window`, `_pr`, `_fakes`, and the constants `THREE_HINTS` and `AUTHORING_TRUNCATION_CLOCK` in the same test file; the `time_truncated = True` statement in `orchestrator_runner.run`.
- Produces: nothing other tracks import. It pins two persisted-state facts Track B relies on — on a refused advance, `state["last_successful_run"]["head_sha"]` equals the **prior** baseline and `state["current_run"]["partial_reasons"]` contains `time_budget_no_advance_no_cursor` or `time_budget_advance_out_of_window`.

- [ ] **Step 1: Append the two refusal-branch tests**

Append to `/Users/theo/Projects/engineering-docs-agent/tests/orchestrator/test_authoring_truncation_advance.py`:

```python
def test_authoring_truncation_without_cursor_holds_baseline(
    tmp_path, init_host, read_current_run
):
    # CCE-109 refusal branch 1 (no_cursor), now reachable from the authoring
    # loop: no admitted PR carries a merge_sha, so there is nothing to anchor
    # the advance to and the baseline must not move.
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (_c1, _c2, _c3, c4) = _seed_window(repo, state_path, 4)
    fakes = _fakes(
        tmp_path.parent / f"trackA_nocursor_{tmp_path.name}",
        [_pr(1), _pr(2), _pr(3)],
        THREE_HINTS,
    )
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock(AUTHORING_TRUNCATION_CLOCK),
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    assert advance != c4, written["last_successful_run"]
    assert advance == base, written["last_successful_run"]
    cr = read_current_run(state_path)
    assert any(
        "time_budget_no_advance_no_cursor" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]


def test_authoring_truncation_with_unresolvable_cursor_holds_baseline(
    tmp_path, init_host, read_current_run
):
    # CCE-109 refusal branch 3 (out_of_window), now reachable from the authoring
    # loop: fakes_multi's merge_shas are the literals "a"/"b"/"c", which no
    # rev-parse can resolve, so the advance is refused and the baseline holds.
    repo = tmp_path
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": "old_sha_000"}}
    )
    fakes = _fakes(
        tmp_path.parent / f"trackA_unresolvable_{tmp_path.name}", None, THREE_HINTS
    )
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock(AUTHORING_TRUNCATION_CLOCK),
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    head = _git(repo, "rev-parse", "HEAD")
    advance = written["last_successful_run"]["head_sha"]
    assert advance != head, written["last_successful_run"]
    assert advance == "old_sha_000", written["last_successful_run"]
    cr = read_current_run(state_path)
    assert any(
        "time_budget_advance_out_of_window" in r and "unresolvable" in r
        for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
```

- [ ] **Step 2: Run the file and confirm the new tests pass**

```bash
cd /Users/theo/Projects/engineering-docs-agent
.venv/bin/python -m pytest tests/orchestrator/test_authoring_truncation_advance.py -q
```

Expected: `3 passed`. They pass immediately because Task 1's implementation is already in the tree — that is expected, and Step 3 is what proves they are not vacuous.

- [ ] **Step 3: Mutation-verify — temporarily remove the fix and confirm all three fail**

Delete the single line `                time_truncated = True` from the authoring-loop break in `scripts/orchestrator_runner.py` (leave the four comment lines in place so the edit is easy to see), then run:

```bash
cd /Users/theo/Projects/engineering-docs-agent
.venv/bin/python -m pytest tests/orchestrator/test_authoring_truncation_advance.py -q 2>&1 | tail -5
```

Expected: `3 failed`, naming exactly:

```
FAILED tests/orchestrator/test_authoring_truncation_advance.py::test_authoring_truncation_advances_to_cursor_not_head
FAILED tests/orchestrator/test_authoring_truncation_advance.py::test_authoring_truncation_without_cursor_holds_baseline
FAILED tests/orchestrator/test_authoring_truncation_advance.py::test_authoring_truncation_with_unresolvable_cursor_holds_baseline
```

If any of the three still passes with the line removed, it is not exercising the fixed path — fix that test before continuing.

- [ ] **Step 4: Restore the fix and confirm green**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git checkout scripts/orchestrator_runner.py
.venv/bin/python -m pytest tests/orchestrator/test_authoring_truncation_advance.py -q
```

Expected: `3 passed`. `git checkout` restores the file from the Task 1 commit, so the fix and its comment come back exactly as committed.

- [ ] **Step 5: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add tests/orchestrator/test_authoring_truncation_advance.py
git commit -m "test(CCE-138): cover the CCE-109 no-cursor and unresolvable-cursor refusals from the authoring path

Both branches were unreachable for an authoring-truncated run before the
flag was set. Each test was mutation-verified: removing time_truncated = True
fails all three tests in this file."
```

---

## Task 3 — Pin the unanchored-deferred branch as correctly unreachable

The second refusal branch — `time_budget_no_advance_unanchored_deferred` — must **not** fire on a pure authoring truncation, and the reason is structural: `deferred_unanchored` is computed only inside the admission break, from `prs[i:]`, the PRs that were **deferred**. An authoring-truncated run deferred no PR at all; every PR was admitted. Adding a `deferred_unanchored` assignment to the authoring break would be new refusal logic, which the spec forbids, and would be wrong on the merits: it would refuse an advance because of a PR that was in fact processed.

This task pins that as intended behaviour so a later reader does not "fix" the asymmetry.

**Files:**

- Modify: `/Users/theo/Projects/engineering-docs-agent/tests/orchestrator/test_authoring_truncation_advance.py` (append one test)

**Interfaces:**

- Consumes from Tasks 1-2: the same module-level helpers and constants in the test file.
- Produces: the pinned fact for Track B that an authoring-truncated run never emits `time_budget_no_advance_unanchored_deferred`, so Track B's deferral counter must not expect that reason from this path.

- [ ] **Step 1: Append the test**

Append to `/Users/theo/Projects/engineering-docs-agent/tests/orchestrator/test_authoring_truncation_advance.py`:

```python
def test_authoring_truncation_never_reports_unanchored_deferred(
    tmp_path, init_host, read_current_run
):
    # CCE-109 refusal branch 2 (unanchored_deferred) stays unreachable from a
    # pure authoring truncation, and must: `deferred_unanchored` is computed
    # only in the admission break, and an authoring-truncated run deferred no
    # PR at all. PR #2 has no merge_sha, so ordering sinks it last → the cursor
    # is PR #3's c3, and no unanchored-deferred refusal fires.
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (c1, _c2, c3, c4) = _seed_window(repo, state_path, 4)
    fakes = _fakes(
        tmp_path.parent / f"trackA_unanchored_{tmp_path.name}",
        [_pr(1, c1), _pr(2), _pr(3, c3)],
        THREE_HINTS,
    )
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock(AUTHORING_TRUNCATION_CLOCK),
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    assert advance != c4, written["last_successful_run"]
    assert advance == c3, written["last_successful_run"]
    cr = read_current_run(state_path)
    assert not any(
        "time_budget_no_advance_unanchored_deferred" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
```

- [ ] **Step 2: Run the file**

```bash
cd /Users/theo/Projects/engineering-docs-agent
.venv/bin/python -m pytest tests/orchestrator/test_authoring_truncation_advance.py -q
```

Expected: `4 passed`

- [ ] **Step 3: Mutation-verify**

Delete the line `                time_truncated = True` from the authoring-loop break again, then:

```bash
cd /Users/theo/Projects/engineering-docs-agent
.venv/bin/python -m pytest tests/orchestrator/test_authoring_truncation_advance.py -q 2>&1 | tail -6
```

Expected: `4 failed` — the new test fails on `assert advance != c4`, confirming it exercises the fixed path rather than merely asserting the absence of a string that was never going to appear.

- [ ] **Step 4: Restore and confirm green**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git checkout scripts/orchestrator_runner.py
.venv/bin/python -m pytest tests/orchestrator/test_authoring_truncation_advance.py -q
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add tests/orchestrator/test_authoring_truncation_advance.py
git commit -m "test(CCE-138): pin unanchored-deferred as correctly unreachable from the authoring break

deferred_unanchored is derived from prs[i:] — the PRs the admission loop
deferred. An authoring-truncated run deferred none, so the branch must stay
silent. Mirroring the admission assignment into the authoring break would be
new refusal logic and would refuse an advance over a PR that was processed."
```

---

## Task 4 — Lock admission truncation as unchanged

The spec's second acceptance clause: "A run truncated during admission keeps its existing behaviour unchanged." This test is deliberately constructed so that it passes **identically** with and without the Track A line — that equality is the assertion. It uses `fakes_multi`'s stock summarizer, whose single `doc_targets` entry makes `len(per_target) == 1`, so the authoring loop's `i > 0` gate never fires and admission truncation is the only truncation in play.

**Files:**

- Modify: `/Users/theo/Projects/engineering-docs-agent/tests/orchestrator/test_authoring_truncation_advance.py` (append one test)

**Interfaces:**

- Consumes from Tasks 1-3: the same module-level helpers in the test file.
- Produces: the pinned admission contract — `advance == cursor` (`c2`), `window_head_sha == HEAD` (`c4`), the exact partial reason string `time_budget_exceeded: admitted 2/3 PRs (budget 100s); deferring PR #3 to next run`, and no authoring-truncation reason. Track B's gate reads the same two state keys on this path.

- [ ] **Step 1: Append the regression test**

Append to `/Users/theo/Projects/engineering-docs-agent/tests/orchestrator/test_authoring_truncation_advance.py`:

```python
def test_admission_truncation_advance_unchanged_by_track_a(
    tmp_path, init_host, read_current_run
):
    # Regression guard: Track A must not touch the admission path. One
    # doc_target keeps len(per_target) == 1, so the authoring loop's `i > 0`
    # gate never fires and admission truncation is the only truncation in play.
    # This test passes identically with and without the Track A line.
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (c1, c2, c3, c4) = _seed_window(repo, state_path, 4)
    fakes = _fakes(
        tmp_path.parent / f"trackA_admission_{tmp_path.name}",
        [_pr(1, c1), _pr(2, c2), _pr(3, c3)],
        None,
    )
    # deadline=100; admission gate at i=1 sees 50 (admit PR #2), at i=2 sees
    # 150 → truncate after 2 of 3 PRs. Cursor = c2.
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock([0, 50, 150]),
    )
    assert rc == 0
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    assert advance != c4, written["last_successful_run"]
    assert advance == c2, written["last_successful_run"]
    assert written["last_successful_run"].get("window_head_sha") == c4, written[
        "last_successful_run"
    ]
    cr = read_current_run(state_path)
    assert (
        "time_budget_exceeded: admitted 2/3 PRs (budget 100s); "
        "deferring PR #3 to next run" in cr["partial_reasons"]
    ), cr["partial_reasons"]
    # The authoring loop never truncated, so no authoring reason is present.
    assert not any("page batches" in r for r in cr["partial_reasons"]), cr[
        "partial_reasons"
    ]
    core = repo / "docs" / "site-src" / "core" / "connectors"
    assert (core / "multi.md").exists()
```

- [ ] **Step 2: Run the file with the fix in place**

```bash
cd /Users/theo/Projects/engineering-docs-agent
.venv/bin/python -m pytest tests/orchestrator/test_authoring_truncation_advance.py -q
```

Expected: `5 passed`

- [ ] **Step 3: Verify it passes without the fix too — that is the point of this test**

Delete the line `                time_truncated = True` from the authoring-loop break, then:

```bash
cd /Users/theo/Projects/engineering-docs-agent
.venv/bin/python -m pytest tests/orchestrator/test_authoring_truncation_advance.py -q 2>&1 | tail -6
```

Expected: `4 failed, 1 passed`, with the one pass being `test_admission_truncation_advance_unchanged_by_track_a`. That is the spec's "admission keeps its existing behaviour unchanged" demonstrated directly: the same assertions hold on both revisions of the runner.

- [ ] **Step 4: Restore and confirm green**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git checkout scripts/orchestrator_runner.py
.venv/bin/python -m pytest tests/orchestrator/test_authoring_truncation_advance.py -q
```

Expected: `5 passed`

- [ ] **Step 5: Run the pre-existing admission suite untouched**

```bash
cd /Users/theo/Projects/engineering-docs-agent
.venv/bin/python -m pytest tests/orchestrator/test_time_budget.py tests/orchestrator/test_time_budget_authoring.py -q 2>&1 | tail -2
```

Expected: `23 passed` (19 in `test_time_budget.py`, 4 in `test_time_budget_authoring.py` — both counts measured). These are the CCE-109 and CCE-114 suites; not one of them may change.

- [ ] **Step 6: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add tests/orchestrator/test_authoring_truncation_advance.py
git commit -m "test(CCE-138): lock admission-truncation advance as unchanged by Track A

Stock fakes_multi summarizer (one doc_target) keeps len(per_target) == 1, so
the authoring gate never fires and admission truncation is isolated. Verified
to pass identically with and without the Track A line."
```

---

## Task 5 — Changelog, format gate, and PR

**Files:**

- Modify: `/Users/theo/Projects/engineering-docs-agent/CHANGELOG.md`

**Interfaces:**

- Consumes from Tasks 1-4: the committed implementation and tests, and the `CCE-138` key from Task 0.
- Produces: the merged plugin `main` that Track B branches from. Track B must not start until this is merged, per the spec's ordering constraint.

- [ ] **Step 1: Add the changelog entry**

In `/Users/theo/Projects/engineering-docs-agent/CHANGELOG.md`, insert this as the **first** bullet under `## [Unreleased]` → `### Fixed` (immediately above the existing `- **CCE-134** — …` bullet):

```markdown
- **CCE-138** — an authoring-truncated run no longer advances the baseline to the full window HEAD. The PR-admission loop sets `time_truncated` when it trips the CCE-109 soft deadline (`scripts/orchestrator_runner.py:1491`); the page-authoring loop, added by CCE-114 for the same reason, recorded its `time_budget_exceeded` partial reason and broke without setting anything. With the flag false, the state-promotion block took its `else` branch and wrote `state["current_run"]["head_sha"]` as the new baseline — so a run that wrote one of N page batches persisted a baseline claiming coverage of every PR in the window, and the PR body reported that window as covered. The consequence only materialises on merge, in a different function from the omission, which is why it produced no error for months. The fix is the one missing assignment: an authoring truncation now routes into the same CCE-109 safe-advance block as an admission truncation, so the baseline moves to the normalized cursor (`_last_processed_merge_sha` → `_rev_parse_commit` → `_sha_in_window`) or, on any of the three refusals, does not move at all. Two of those three refusal branches — no usable cursor, and an unresolvable/out-of-window cursor — were dead code for this path before now and gain direct coverage; the third, `unanchored_deferred`, stays correctly silent, because `deferred_unanchored` is derived from the PRs the admission loop deferred and an authoring-truncated run deferred none. Admission-truncation behaviour is unchanged and is pinned by a test that passes identically on both revisions. No new state and no new config key.
```

- [ ] **Step 2: Verify formatting and lint on the changed Python**

```bash
cd /Users/theo/Projects/engineering-docs-agent
ruff format --check tests/orchestrator/test_authoring_truncation_advance.py scripts/orchestrator_runner.py
ruff check tests/orchestrator/test_authoring_truncation_advance.py
```

Expected: `2 files already formatted` and `All checks passed!`.

Do **not** run `ruff check` on `scripts/orchestrator_runner.py` expecting a clean result — it reports one pre-existing `E401 Multiple imports on one line` at `scripts/orchestrator_runner.py:9`, which predates this work and is out of scope. Do not fix it here.

- [ ] **Step 3: Run the full suite one final time**

```bash
cd /Users/theo/Projects/engineering-docs-agent
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -2
```

Expected: `1208 passed, 5 skipped` — the measured baseline of 1203 plus the five new tests, with zero pre-existing failures.

- [ ] **Step 4: Confirm the diff is exactly what this track claims**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git diff main...HEAD --stat
```

Expected: three files — `CHANGELOG.md`, `scripts/orchestrator_runner.py` (5 insertions, 0 deletions), `tests/orchestrator/test_authoring_truncation_advance.py` (new file). If `.gitignore` or `uv.lock` appears, they were staged by mistake — unstage them (`git restore --staged .gitignore uv.lock`) and amend.

- [ ] **Step 5: Commit the changelog and push**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git add CHANGELOG.md
git commit -m "docs(CCE-138): changelog entry for the authoring-truncation cursor fix"
git push -u origin fix/CCE-138-authoring-truncation-cursor
```

- [ ] **Step 6: Open the PR**

```bash
cd /Users/theo/Projects/engineering-docs-agent
gh pr create \
  --title "[CCE-138] authoring truncation advances to the CCE-109 cursor, not full HEAD" \
  --body "$(cat <<'EOF'
## What

The page-authoring loop's time-budget break (`scripts/orchestrator_runner.py:1566-1572`) recorded a partial reason and broke without setting `time_truncated`. The PR-admission loop sets it (`:1491`). With the flag false, the state-promotion block fell through to `advance_sha = state["current_run"]["head_sha"]` (`:2017`) and persisted the full window HEAD as the new baseline — a run that authored one of N page batches claimed the whole window.

One statement fixes it. The three CCE-109 refusal branches (`:1982-2015`) are unchanged; they were simply unreachable from this path.

## Tests

Five new tests in `tests/orchestrator/test_authoring_truncation_advance.py`:

1. `test_authoring_truncation_advances_to_cursor_not_head` — the critical one. Asserts `advance != head` **and** `advance == cursor`. Every fixture appends a non-PR commit `c4` on top of the newest PR merge `c3`, so cursor and HEAD are provably different shas and `advance == cursor` cannot pass vacuously.
2. `test_authoring_truncation_without_cursor_holds_baseline` — CCE-109 no-cursor refusal, now reachable.
3. `test_authoring_truncation_with_unresolvable_cursor_holds_baseline` — CCE-109 out-of-window refusal, now reachable.
4. `test_authoring_truncation_never_reports_unanchored_deferred` — pins the third branch as correctly silent on this path.
5. `test_admission_truncation_advance_unchanged_by_track_a` — the regression guard; passes identically with and without the fix.

Tests 1-4 were mutation-verified: removing the added line fails all four.

Suite: `1203 passed, 5 skipped` before, `1208 passed, 5 skipped` after.

## Known limitation, deliberately not addressed here

Under an authoring truncation every PR was admitted, so the cursor is the newest admitted PR's merge sha — even though some page batches were never written, and a batch may carry summaries from an older PR. The advance is therefore honest about *PRs admitted*, not about *pages written*. That is strictly better than the previous fall-through to HEAD, and narrowing it further would be new refusal logic, which ADIS-490 Track A explicitly excludes. Track B's per-PR deferral counting is where that residual belongs. See the plan's "Residual" section.

## Design

ADIS-490, "Docs-agent self-sustaining pipeline", Track A. Track A must land before Track B: B enables auto-merge, and merging while `advance_sha` still resolved to full HEAD would automate the silent-loss bug nightly.
EOF
)"
```

- [ ] **Step 7: Merge on a green integrated suite**

Per the plugin's `CLAUDE.md`: merge on a green _integrated_ suite, never on GitHub's mergeable flag.

```bash
cd /Users/theo/Projects/engineering-docs-agent
git fetch origin
git merge origin/main
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -2
```

Expected: `1208 passed, 5 skipped` (higher totals are fine if `main` moved and added tests; zero failures is the gate). Then merge the PR.

**Remember Global Constraints risk 3:** the plugin is consumed at `ref: main`, so this is live on the next nightly fire with no release step. Nothing merges docs PRs yet (Track B is not landed), so the newly honest `advance_sha` still reaches the host's `main` only through a human merge.

---

## Residual — what this track does not make honest

Recorded here rather than fixed, because fixing it is new refusal logic and the spec excludes that from Track A.

Under an **authoring** truncation, the admission loop completed, so `prs` is the full admitted list and `_last_processed_merge_sha(prs)` returns the **newest** PR's merge sha. But page batches are keyed by `(lens, page_hint)`, not by PR, and a batch cut off by the deadline can carry summaries from any admitted PR — including the oldest. So the advance can move past a PR whose only page batch was never written, and the next window will not re-collect it.

This is strictly better than the pre-fix behaviour (which advanced past _every_ PR in the window plus any non-PR commits), and it is the behaviour the spec asks for. Three notes for whoever picks it up:

1. It cannot be reproduced with the current test harness. `dispatch_subagent` reads one static fixture per agent name (`<dry_run_dir>/fake_pr_summarizer.json`), so every PR in a dry run gets the same summary and therefore the same `doc_targets` — every batch contains every PR. Demonstrating the residual needs per-PR summarizer fixtures, which is new harness machinery.
2. The honest cursor for an authoring truncation would be the newest PR all of whose `(lens, page_hint)` batches were authored — computable from `per_target` and `authored` without any new persisted state, but it is a new refusal and belongs to a track that is allowed to add one.
3. **This is closed by Track B (CCE-140) Task 1**, not left open. Track B adds `advance_cursor_list(admitted, deferred_tail, *, held_back)`, records `deferred_pages_by_pr` at this very break, and stops the cursor walk at the oldest PR that still owes a page batch. Track B's charter permits the new refusal logic that Track A's forbids. Do not attempt it here; the two tracks would collide on the same seven lines. Track A's job is to make the run take the safe-advance path at all — Track B's is to make that path exact.

---

## Self-review

**Spec coverage.** Track A's spec section has two sentences of requirement and two acceptance clauses. Requirement "Set it, so an authoring-truncated run routes into the existing safe-advance block" → Task 1 Step 3. Requirement "adds no new refusal logic and no new state" → Task 1 Step 3 adds one assignment to an existing local; Task 3 explicitly declines to add the one piece of new refusal logic a careless reading would invite. Acceptance "writes `advance_sha` equal to the last processed PR's merge sha, and not equal to `current_run.head_sha`" → both assertions in the Task 1 test, negative first. Acceptance "A run truncated during admission keeps its existing behaviour unchanged" → Task 4, verified on both revisions. Testing directive "assert `advance_sha != head_sha` explicitly" → present in four of the five tests. Ordering constraint → Task 5 Step 7 note.

**Placeholder scan.** No TBD, no "similar to Task N", no "add appropriate error handling". Every code step carries the literal code; every command carries its expected output. The one substitution in the plan is the Jira key, which Task 0 Step 3 creates and names concretely (`CCE-138`, with the rule for what to do if the tracker returns something else).

**Reconciliation changes to this plan (2026-08-10).** Four tracks were planned independently; this is what changed here when they were reconciled against each other:

1. **Ticket key confirmed as CCE-138, and the collision with Track C resolved.** Track C independently claimed the same number. The assignment table in Task 0 Step 3 is now the shared source of truth: A = CCE-138, C = CCE-139, D = ADIS-490 (host, no CCE key), B = CCE-140. **Track A files first**, so if the tracker allocates something other than 138 here, every later plugin key shifts and Tracks C and B must be told before they file.
2. **A forward notice added to Task 1's Interfaces block.** Track B (CCE-140) narrows the advance cursor further, to satisfy spec Decision 2, and in doing so inverts three of this track's five tests. The table there names exactly which, and Track B Task 1 Step 9 carries the rewrites. This is not a defect in either track — A implements the spec's Track A acceptance, B implements the spec's stricter Decision 2, and B is a strict improvement on A exactly as A is on the original bug. The `assert advance != head` directive survives in every one of them.
3. **The Residual section's item 3 rewritten.** It previously flagged the "advance can move past a PR whose page batch was never written" gap as an open question for whoever picks it up. Track B Task 1 closes it, with `advance_cursor_list` and `deferred_pages_by_pr` recorded at this very break. The item now says so, and says plainly not to attempt it here — the two tracks would collide on the same seven lines.
4. **Host baseline drift re-measured, 41 → 42**, and reframed. The spec says 38, an earlier measurement said 41, this one says 42; all three were correct at their own moment. The figure grows with every host commit, this track touches no host file, and nothing in it depends on the number. A mismatch is not a finding — re-run the command.
5. **The full-suite expectation reframed around the delta.** Track A lands first, so 1203 is both measured and expected. But the plan now states that `+5` is the contract and the absolute is a property of whatever else is on `main` — which is what Tracks C and B key their own arithmetic off.

**Type consistency.** `runner.run` is called with the same keyword set in all five tests (`dry_run_dir`, `no_pr`, `time_budget_seconds`, `now_monotonic`). `_seed_window(repo, state_path, n) -> (base, [c1..cn])` is unpacked as `base, (c1, c2, c3, c4)` with `n=4` everywhere. `_fakes(dst, prs, hints)` takes positional `None` for "leave the stock fixture alone" in exactly two places (Task 2's unresolvable-cursor test passes `None` for `prs`; Task 4 passes `None` for `hints`). `THREE_HINTS` and `AUTHORING_TRUNCATION_CLOCK` are defined once in Task 1 and referenced by name in Tasks 2 and 3.
