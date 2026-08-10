# Track C — citation resolution (plugin) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the plugin's `citation_exists` Tier-1 rule that a host can be a nested monorepo, by adding an additive `lint.citation_source_roots` config key and threading it through **all four** path-resolution sites in `scripts/lint/citation_exists.py` plus the orchestrator call site that feeds the fact-checker — without ever letting an invented path resolve. Also permit `notes` on a `pr_summarizer` `doc_targets` item.

**Architecture:** One new accessor, `citation_exists.source_roots(config)`, reads the host's declared package roots and returns them as a tuple. Two resolvers consume it: `_resolves()` (bool, used by the paths loop) gains a **required** `roots` parameter so neither of its two call sites can silently keep the narrow behaviour, and a new `_resolve_target()` (Path-or-None, used by the symbol loop) replaces the bare `target = repo_root / rel`. A third, independent resolver — `resolve_cited_sources()` — gains an optional `roots` parameter and returns paths in **resolved** form, and the orchestrator's fact-checker admission gate passes `source_roots(config)` into it. Declared roots are tried **after** the repo root and `docs_dir`, never before, so a root can only widen resolution and can never redirect a path that already resolves.

**Tech Stack:** Python 3.11+, stdlib plus `pyyaml` and `jsonschema`. pytest with `--import-mode=importlib`. No new runtime dependencies. This repo has no ruff/mypy gate — CI (`.github/workflows/test.yml`) runs `python -m pytest -q` on 3.11 and 3.12, and `actionlint` on workflows only.

**Spec:** `/Users/theo/Projects/advanced-data-importer/docs/superpowers/specs/2026-08-10-docs-agent-self-sustaining-design.md` (§Track C)

**Repos:**

- PLUGIN (every edit in this plan): `/Users/theo/Projects/engineering-docs-agent`
- HOST (read-only here; Track D owns its config): `/Users/theo/Projects/advanced-data-importer`

**Python interpreter:** there is no bare `python` on this machine. Every command below uses `/Users/theo/Projects/engineering-docs-agent/.venv/bin/python`.

---

## Global Constraints

These are the spec's binding requirements for Track C, quoted verbatim. They are not negotiable and are not re-litigated by this plan.

- > Add an additive `lint.citation_source_roots`, defaulting to empty, and thread it through **every** path resolver in the file:
  >
  > 1. `_resolves()` — the reported failures
  > 2. both `check_path()` call sites
  > 3. the symbol loop's `target = repo_root / rel` (`~:362`) — this one reads `if not target.exists(): continue`, so omitting it produces a **silent skip**, not a phantom report: symbol confabulation would go unchecked
  > 4. `resolve_cited_sources()` (`:376`) and its orchestrator call site (`:1794`)

- > Item 4 is not optional. It is a second, independent resolver feeding the fact-checker's admission gate (`if not cited_sources: continue`). Widening only `_resolves()` would make the linter accept citations the fact-checker cannot see — the same weakening the constraint forbids, moved one layer down.

- > Roots must be **package roots** (`backend`, `frontend`), never a tail like `backend/storage`. A root list deep enough to catch tails is suffix-matching in disguise, and suffix-matching admits confabulated paths.

- > Also fix `pr_summarizer.schema.json`: run #699 rejected `notes` as an additional property. The root object already permits `notes`, so the rejection came from the `doc_targets` item object, which is `additionalProperties: false`.

- > **Acceptance:** the plugin's existing lint tests still pass. Two controls hold — invented paths under a declared root still block, and the four genuinely-bad host citations (`storage/_probe.py`, `.claude/rules/deploy-ci.md`, `db_engine_specs/mysql.py`, `.claude/skill-usage.log`) still block. `resolve_cited_sources` returns non-empty for pages that return empty today.

- > **Track C** — every widened resolver needs a control proving invented paths still block. Missing one converts a blocking gate into a silent one, and the round-1 analysis of this incident already missed `resolve_cited_sources` once.

- > **The plugin is consumed at `ref: main` by every host, including its own dogfood** — currently the only working reference that the agent can succeed at all. Plugin changes take effect on the next fire with no release step, which makes both iteration and breakage immediate.

- Ordering (spec §Architecture): the track order is **A → C → D → B**. > C and D land between them so that lint failures are near zero before autonomy turns on, making the track-B skip hatch a rare safety net rather than a routine content shredder.

Track C is inert on every host that declares no roots, so it is safe to land at any point after A.

### Constraints this plan adds — measured, not inherited

- **Track C ships no host change.** `.engineering-docs-agent/config.yml` in the host belongs to Track D. Task 9 verifies against a throwaway copy of that config placed inside the host repo and deleted in the same step; the host working tree must be byte-identical before and after (`git -C /Users/theo/Projects/advanced-data-importer status --short` empty).

- **The plugin clone is shared, and line numbers in it are not stable.** At plan time `git status --short` in `/Users/theo/Projects/engineering-docs-agent` showed ` M scripts/orchestrator_runner.py` (one inserted line at `+1572`, Track A's `time_truncated` assignment) and `?? tests/orchestrator/test_zz_tmp_probe.py` — a concurrent agent's uncommitted work, so `resolve_cited_sources` read `:1795` there against `:1794` in `HEAD`.

  **Re-checked at reconciliation: both are gone.** The tree carries only the two pre-existing entries (` M .gitignore`, `?? uv.lock`), the suite is `1203 passed, 5 skipped`, and `grep -n resolve_cited_sources scripts/orchestrator_runner.py` prints `1794` again.

  The rule survives the episode, and it is why this plan is written the way it is. When Track A **lands** (it must, before this track merges), every line at or below 1572 shifts by `+1` for real and permanently — `:1794` becomes `:1795`. **Anchor every edit on exact code text, never on a line number**, and do the work in a dedicated git worktree (Task 1) so no other track's work-in-progress can land inside a Track C commit.

- **Branch and keys.** Plugin convention (`CLAUDE.md` §Plugin conventions) is `<type>/CCE-<number>-<short-slug>`, with the key in the commit subject and the PR title. `CCE-137` is the highest key across all refs, verified by `git log --oneline --all | grep -o 'CCE-[0-9]*' | sort -t- -k2 -n | tail -1`.

  **Cross-track key assignment (reconciled 2026-08-10 — do not re-derive per track).** Track A and Track C independently both claimed CCE-138; the collision is resolved as follows and every plan now carries the assigned key throughout:

  | Track | Repo   | Key                                |
  | ----- | ------ | ---------------------------------- |
  | A     | plugin | **CCE-138**                        |
  | C     | plugin | **CCE-139** ← this plan            |
  | D     | host   | **ADIS-490** (consumes no CCE key) |
  | B     | plugin | **CCE-140**                        |

  File the CCE issues in ascending order (A, then C, then B) so the tracker's allocation matches. If the tracker returns a different number for this track, substitute it consistently across the branch name, every commit subject and the PR title (`jira-transition.yml` reads the key from the PR **title** only) — and tell whoever is executing the other plugin tracks, because the table above is the shared source of truth.

- **TDD is literal.** Every task is: write the test, run it, observe the _stated_ failure message, write the minimal implementation, run it, observe green, commit. A test that fails for a different reason than the one stated means an assumption in this plan is wrong — stop and re-read the code rather than editing until it goes green.

- **Never `sys.path.insert` the `scripts/lint` directory in a test.** Plugin `CLAUDE.md`: import via the dotted namespace path (`from scripts.lint import citation_exists`), which is what `tests/lint/test_citation_exists.py` already does. Tests under `tests/orchestrator/` may keep the existing `sys.path.insert(... / "scripts")` idiom their siblings use.

- **Do not seal the `lint` object.** Measured: `templates/config.schema.json` `properties.lint` sets no `additionalProperties`. Adding `additionalProperties: false` would break any host carrying an unknown lint key and is out of scope for this spec.

- **An agent-schema change is a three-file lockstep.** Plugin `CLAUDE.md`: edit `agents/schemas/<agent>.schema.json` and the `## Output schema (canonical)` fenced block in `agents/<agent>.md` together (`tests/agents/test_schema_md_sync.py` asserts `json.loads`-equality), then regenerate `docs/site-src/api/contracts/` with `scripts/contracts_doc.py`. Never hand-edit the generated markdown.

---

## Measurements — taken for this plan, 2026-08-10

Every number below was produced by the command shown, in this session, against the trees named. Nothing is inherited.

| #   | What                                                                         | Value                                                                                                                                                                                                                                                                                                                                                                                                                     | Command                                                                                                                         |
| --- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| M1  | Plugin test baseline                                                         | `1203 passed, 5 skipped in 33.68s`                                                                                                                                                                                                                                                                                                                                                                                        | `cd /Users/theo/Projects/engineering-docs-agent && .venv/bin/python -m pytest tests/ -q`                                        |
| M2  | Host pages under `docs/site-src`                                             | `152`                                                                                                                                                                                                                                                                                                                                                                                                                     | `cd /Users/theo/Projects/advanced-data-importer && find docs/site-src -name '*.md' -type f \| wc -l`                            |
| M3  | Host pages failing `citation_exists` today                                   | `33` of 152, all at `severity=block`                                                                                                                                                                                                                                                                                                                                                                                      | `citation_exists.py --config <host cfg> --paths <all 152> --json`, then count `not ok`                                          |
| M4  | Host pages failing with `[backend, frontend]` honoured                       | `17` — 16 fixed, **0** newly failing (the widened set is a strict subset of today's 33)                                                                                                                                                                                                                                                                                                                                   | `scratchpad/probe_trackC.py`                                                                                                    |
| M5  | `resolve_cited_sources` empty-result pages                                   | `29` today, `26` widened; only **3** pages flip empty to non-empty                                                                                                                                                                                                                                                                                                                                                        | `scratchpad/probe_trackC.py`                                                                                                    |
| M6  | `resolve_cited_sources` total resolved paths across corpus                   | `652` today, `706` widened                                                                                                                                                                                                                                                                                                                                                                                                | `scratchpad/probe_trackC.py`                                                                                                    |
| M7  | The spec's four named controls                                               | Only **two** are live citations at all. `db_engine_specs/mysql.py` is cited on 3 pages, does not exist, does not resolve widened — **valid control**. `.claude/skill-usage.log` is cited once and **exists on disk** at the host root (untracked, gitignored) — passes here, would block in CI, so **environment-dependent and unusable**. `storage/_probe.py` and `.claude/rules/deploy-ci.md` are cited **zero** times. | `scratchpad/probe_trackC.py` §control candidates                                                                                |
| M8  | Does an un-widened symbol loop silently skip once the paths loop is widened? | **Yes.** `app/core/real_module.py:ghost_fn`, with `backend/app/core/real_module.py` present and `ghost_fn` absent: sites 1+2 widened and site 3 narrow gives `ok=True, msg='ok'`. Site 3 widened gives `ok=False, "cites nonexistent symbol 'ghost_fn'"`.                                                                                                                                                                 | `scratchpad/probe_site3_isolation.py`                                                                                           |
| M9  | Does a **positive** symbol control discriminate site 3?                      | **No.** `app/core/real_module.py:real_fn` returns `ok=True` whether or not site 3 is widened. Only the **negative** control catches it.                                                                                                                                                                                                                                                                                   | `scratchpad/probe_site3_isolation.py`                                                                                           |
| M10 | Is `lint` sealed in `templates/config.schema.json`?                          | **No** — six declared keys, no `additionalProperties`. `lint.citation_source_roots: [backend, frontend]` therefore validates against the **unmodified** schema today.                                                                                                                                                                                                                                                     | `jsonschema.validate` of the host config plus the key, against the current schema                                               |
| M11 | Does `pr_summarizer.schema.json` reject `notes` in a `doc_targets` item?     | **Yes.** Root permits `notes: ["string","null"]`; `doc_targets.items` sets `additionalProperties: false` over `lens`/`action`/`page_hint`/`doc_kind` only.                                                                                                                                                                                                                                                                | `.venv/bin/python -c "import json;print(json.dumps(json.load(open('agents/schemas/pr_summarizer.schema.json')),indent=1))"`     |
| M12 | Does the generated contract page render nested item properties?              | **No** — `render_contract_page` iterates root `properties` only, so adding `notes` to `doc_targets.items` produces no diff in `docs/site-src/api/contracts/pr_summarizer.schema.md`.                                                                                                                                                                                                                                      | `sed -n '41,70p' scripts/contracts_doc.py`                                                                                      |
| M13 | Callers of `resolve_cited_sources` repo-wide                                 | Exactly one production caller (`scripts/orchestrator_runner.py`) plus two tests in `tests/lint/test_citation_exists.py`                                                                                                                                                                                                                                                                                                   | `grep -rn "resolve_cited_sources" --include='*.py' .`                                                                           |
| M14 | `config` inside `orchestrator_runner.run()`                                  | Assigned exactly once, at `:1316` (`load_config_validated(cfg_path)`), never reassigned before the fact-checker loop. In scope at the call site.                                                                                                                                                                                                                                                                          | `awk 'NR>=1301 && NR<=2140 && /^[ \t]*config[ \t]*=/ {print NR": "$0}' scripts/orchestrator_runner.py`                          |
| M15 | Line drift from the concurrent Track A edit                                  | `resolve_cited_sources` call site: `1794` in `HEAD`, `1795` in the working tree                                                                                                                                                                                                                                                                                                                                           | `git show HEAD:scripts/orchestrator_runner.py \| grep -n resolve_cited_sources` compared with the same grep on the working tree |

### The 17 surviving failures — why widening cannot fix them

Grouped by cause, so nobody later mistakes a surviving failure for an incomplete widening.

1. **Connector-tail citations** — `jira/enums.py`, `salesforce/catalog.py`, `jira/type_mapper.py`, `jira/connector.py`, `salesforce/type_mapper.py`. These live under `backend/connectors/jira/…`. Fixing them needs `backend/connectors` as a root, which the spec forbids by name.
2. **Skill-relative citations** — `references/checklist.md` on three pages, plus six siblings. These live under `.claude/skills/connector-builder/references/`, a third root that is neither `backend` nor `frontend`.
3. **Docs-site cross-links written without the `core/` segment** — `backend/api.md`, `frontend/index.md`, `backend/security.md`, `backend/data-model.md`, `frontend/role-gates.md`, all on `whats-new.md`. They need `docs/site-src/core/`, not a source root. Note they collide semantically with the new roots: widening changes their failure reason, not the outcome.
4. **Genuinely dead paths** — `db_engine_specs/mysql.py` (three pages, the M7 control), `services/superset_sync.py`, `backend/app/models/object_dependency.py`, `backend/app/services/datasets_service.py`, `docs/2026-04-27-dataset-feature.md`, `pipelines/page.tsx`, `new/page.tsx`, `drift/page.test.tsx`, plus the three invented `test_ensure_prefect_*` / `test_expected_name_*` identifiers on `archive/adrs/pipeline-execution.md` (test citations are root-independent by construction).
5. **One generator-owned page** — `archive/specs.md` cites `docs/superpowers/plans/2026-05-16-drift-wizard-ux-and-refresh.md`, which no longer exists. That page is rewritten by the host's `scripts/generate_archive_indexes.py`, so the fix belongs upstream of the generator, in Track D.

These 17 are Track D's problem, not Track C's. Track C's acceptance is **33 to 17 with zero newly-failing pages**.

---

## File Structure

| Path                                                        | Repo   | Change                                                                                                                                                                                                       |
| ----------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `scripts/lint/citation_exists.py`                           | plugin | Add `source_roots()`; widen `_resolves()` with a required `roots` param; add `_resolve_target()`; thread `roots` through both `check_path()` call sites and the symbol loop; widen `resolve_cited_sources()` |
| `scripts/orchestrator_runner.py`                            | plugin | One call: pass `_citation_exists.source_roots(config)` into `resolve_cited_sources`                                                                                                                          |
| `templates/config.schema.json`                              | plugin | Declare `lint.citation_source_roots` as an array of single-segment strings                                                                                                                                   |
| `agents/schemas/pr_summarizer.schema.json`                  | plugin | Add `notes` to the `doc_targets` **item** object                                                                                                                                                             |
| `agents/pr-summarizer.md`                                   | plugin | Mirror the schema change into the `## Output schema (canonical)` fenced block; extend the illustrative example                                                                                               |
| `tests/lint/test_citation_source_roots.py`                  | plugin | **New.** Per-site red/green tests and their controls (Tasks 2 to 5)                                                                                                                                          |
| `tests/orchestrator/test_citation_source_roots_sentinel.py` | plugin | **New.** The single four-site sentinel test (Task 6)                                                                                                                                                         |
| `tests/schemas/test_config_schema.py`                       | plugin | Three cases for the new config key                                                                                                                                                                           |
| `tests/schemas/test_pr_summarizer_schema.py`                | plugin | Three cases for `notes` on a `doc_targets` item                                                                                                                                                              |

Nothing under `/Users/theo/Projects/advanced-data-importer` is edited by this plan.

---

## Task 1 — Worktree, branch and a recorded baseline

**Interfaces**

- Consumes: nothing. Track A's landing is not a prerequisite for any code here; the only interaction is the shared clone's dirty tree (M15).
- Produces: the branch `feat/CCE-139-citation-source-roots`, the empty test module `tests/lint/test_citation_source_roots.py`, and a recorded baseline that Tasks 2 to 9 compare against.

- [ ] **Step 1: Create an isolated worktree so the concurrent Track A edits cannot leak into a Track C commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git worktree add -b feat/CCE-139-citation-source-roots \
  /Users/theo/Projects/engineering-docs-agent-trackC main
```

Expected: `Preparing worktree (new branch 'feat/CCE-139-citation-source-roots')` followed by `HEAD is now at d7e559c docs(agent): run …`. The sha differs if `main` has moved; that is fine.

**Every remaining command in this plan runs from `/Users/theo/Projects/engineering-docs-agent-trackC` unless it explicitly names another directory.** Never `cd` back to the primary clone to edit — Track A is working there.

- [ ] **Step 2: Confirm the worktree is clean and matches `main`, not the dirty primary clone**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
git status --short
grep -n "resolve_cited_sources" scripts/orchestrator_runner.py
```

Expected: `git status --short` prints **nothing**, and the grep prints exactly one line:

```
1794:                cited_sources = _citation_exists.resolve_cited_sources(
```

Two ways the number can legitimately differ, and neither is a problem — the line **content** is what matters, and every edit in this plan is anchored on text:

- `1795` — **Track A (CCE-138) has landed on `main`.** Expected, and correct: Track A inserts one line at `+1572`, which is above this one. Continue.
- anything else — `main` moved for some other reason. Continue, but re-read the surrounding code before the Task 6 edit rather than trusting this plan's navigation aids.

The one state that _is_ a problem: `git status --short` printing anything other than nothing. That means the worktree was branched off a dirty tree. Remove it (`git worktree remove --force /Users/theo/Projects/engineering-docs-agent-trackC`) and redo Step 1 from a clean `main`.

- [ ] **Step 3: Record the baseline**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
```

Expected final line: **`1203 passed, 5 skipped in <N>s`** on a pristine `main`, or **`1208 passed, 5 skipped`** if Track A (CCE-138) has already landed — Track A adds exactly five tests in `tests/orchestrator/test_authoring_truncation_advance.py`. Both are correct; the spec's ordering (A → C) makes 1208 the more likely one.

Whichever you see, **write the number down before proceeding** — every later expected pass count in this plan is `this baseline + tests added so far`, and an inherited-but-wrong baseline is exactly the failure mode the spec's Risk 2 warns about. Record which it was:

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
git log --oneline -20 | grep -c 'CCE-138' || true
```

Non-zero means Track A has landed and your baseline is 1208.

- [ ] **Step 4: Create the test module Tasks 2 to 5 append to, with only its imports and shared fixtures**

Write `/Users/theo/Projects/engineering-docs-agent-trackC/tests/lint/test_citation_source_roots.py`:

```python
"""CCE-139: lint.citation_source_roots — the nested-monorepo resolution widening.

A flat host (this plugin) cites `scripts/foo.py` and resolves from the repo
root. A nested monorepo cites `app/core/destination_engine.py` — the
import-path form the code uses for itself — which is repo-relative only from
inside `backend/`. Declared roots are tried AFTER the repo root and docs_dir,
so a root can only widen resolution; it can never redirect a path that already
resolves.

Every test here pairs a widening with a control proving an invented path under
the SAME declared root still blocks. A widened resolver without its control is
a block rule that has quietly stopped blocking.
"""

from __future__ import annotations
import subprocess
from pathlib import Path

from scripts.lint import citation_exists


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )


def _monorepo(tmp_path: Path) -> Path:
    """A nested host: two package roots holding a real module, a retired one and
    a component, plus a docs tree. Mirrors the shape of the ADIS host."""
    repo = tmp_path / "host"
    (repo / "backend" / "app" / "core").mkdir(parents=True)
    (repo / "backend" / "app" / "core" / "real_module.py").write_text(
        "def real_fn():\n    return 1\n"
    )
    (repo / "backend" / "app" / "core" / "legacy.py").write_text("LEGACY = 1\n")
    (repo / "frontend" / "components").mkdir(parents=True)
    (repo / "frontend" / "components" / "widget.tsx").write_text(
        "export function Widget() { return null }\n"
    )
    (repo / "docs" / "site-src").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _page(repo: Path, body: str) -> Path:
    p = repo / "docs" / "site-src" / "page.md"
    p.write_text(body)
    return p


CFG = {"lint": {"citation_source_roots": ["backend", "frontend"]}}
```

Run it. A module with no tests collects zero and exits 5:

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest \
  tests/lint/test_citation_source_roots.py -q 2>&1 | tail -3
```

Expected: `no tests ran in <N>s`. That is the correct state for this step — it proves the module imports cleanly (`from scripts.lint import citation_exists` resolves) before any test depends on it.

- [ ] **Step 5: Commit the scaffold**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
git add tests/lint/test_citation_source_roots.py
git commit -q -m "test(CCE-139): scaffold the citation source-roots test module"
git log --oneline -1
```

Expected: one line ending in `test(CCE-139): scaffold the citation source-roots test module`.

---

## Task 2 — `source_roots()` and the package-root constraint

**Interfaces**

- Consumes: nothing.
- Produces: **`citation_exists.source_roots(config: dict) -> tuple[str, ...]`** — the single reader of `lint.citation_source_roots`. Consumed by `check_path` (Tasks 3 and 4) and by `orchestrator_runner.run` (Task 6). Track D consumes the config key `lint.citation_source_roots`, a YAML list of single-segment strings.

- [ ] **Step 1: Write the four failing tests**

Append to `tests/lint/test_citation_source_roots.py`:

```python
# ---------- source_roots(): the config accessor ----------


def test_source_roots_defaults_to_empty():
    """Generic-first: a host that declares nothing keeps today's behavior."""
    assert citation_exists.source_roots({}) == ()
    assert citation_exists.source_roots({"lint": {}}) == ()
    assert citation_exists.source_roots({"lint": {"citation_source_roots": []}}) == ()


def test_source_roots_reads_declared_roots_in_order():
    cfg = {"lint": {"citation_source_roots": ["backend", "frontend"]}}
    assert citation_exists.source_roots(cfg) == ("backend", "frontend")


def test_source_roots_strips_surrounding_slashes():
    cfg = {"lint": {"citation_source_roots": ["/backend/", "frontend/"]}}
    assert citation_exists.source_roots(cfg) == ("backend", "frontend")


def test_source_roots_drops_nested_tails_and_dot_entries():
    """Spec: roots must be PACKAGE roots, never a tail like `backend/storage`.
    A root list deep enough to catch tails is suffix-matching in disguise, and
    suffix-matching admits confabulated paths. Dropping fails CLOSED (no
    widening), which is the correct degradation for a block rule."""
    cfg = {
        "lint": {
            "citation_source_roots": ["backend", "backend/storage", "..", ".", ""]
        }
    }
    assert citation_exists.source_roots(cfg) == ("backend",)
```

- [ ] **Step 2: Run them and observe the failure**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest \
  tests/lint/test_citation_source_roots.py -q 2>&1 | tail -6
```

Expected: `4 failed`, each with `AttributeError: module 'scripts.lint.citation_exists' has no attribute 'source_roots'`.

- [ ] **Step 3: Implement `source_roots()`**

In `scripts/lint/citation_exists.py`, insert this function immediately **after** `exempt_tokens` (which ends with `return set(DEFAULT_EXEMPT_TOKENS) | {str(t) for t in host}`) and **before** `def _resolves(`:

```python
def source_roots(config: dict) -> tuple[str, ...]:
    """Extra package roots citation_exists tries when resolving a cited path.

    A nested monorepo's prose cites the import-path form the code uses for
    itself (`app/core/destination_engine.py`), which is repo-relative only
    from inside the package root (`backend/`). Declared roots are tried AFTER
    the repo root and docs_dir, never before, so a root can only widen
    resolution — it can never redirect a path that already resolves.

    PACKAGE ROOTS ONLY. A multi-segment entry (`backend/storage`) is
    suffix-matching in disguise, and suffix-matching admits confabulated
    paths, so such entries are dropped here and rejected outright by
    templates/config.schema.json. Dropping fails closed: no widening, which is
    the safe direction for a block rule. Empty by default — a host that
    declares nothing keeps today's exact behavior.
    """
    lint = config.get("lint") or {}
    out: list[str] = []
    for raw in lint.get("citation_source_roots") or []:
        root = str(raw).strip("/")
        if root and "/" not in root and not root.startswith("."):
            out.append(root)
    return tuple(out)
```

- [ ] **Step 4: Re-run and observe green**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest \
  tests/lint/test_citation_source_roots.py -q 2>&1 | tail -3
```

Expected: `4 passed in <N>s`.

- [ ] **Step 5: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
git add scripts/lint/citation_exists.py tests/lint/test_citation_source_roots.py
git commit -q -m "feat(CCE-139): add source_roots() reader for lint.citation_source_roots"
```

---

## Task 3 — Sites 1 and 2, `_resolves()` and both `check_path()` call sites

**Interfaces**

- Consumes: `citation_exists.source_roots` (Task 2).
- Produces: **`citation_exists._resolves(rel: str, repo_root: Path, files: set[str], docs_dir: str, build_dir: str, roots: tuple[str, ...]) -> bool`**. `roots` is a **required positional**, deliberately not defaulted. This is a private helper with exactly two call sites, both inside `check_path`; a default would let one of them silently keep the narrow behaviour, and a block rule that has stopped blocking reports nothing. With no default, an un-threaded call site is a `TypeError` at test time instead of a silent hole.

The two call sites differ in behaviour and need distinct tests.

- `:344`, `if not _resolves(...)` — the **problem-reporting** path. Un-widened, the page blocks on a citation that does resolve.
- `:339`, `if _resolves(...)` inside the `cited in exempt` branch — the **stale-exemption** path. Un-widened, a host that exempts a token which has since started resolving under a package root is never told, and the exemption list rots silently. This is the only assertion that can tell the two call sites apart.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lint/test_citation_source_roots.py`:

```python
# ---------- site 1 + site 2a: _resolves() and the paths loop ----------


def test_import_relative_path_resolves_under_a_declared_root(tmp_path):
    """The reported failure class: a nested monorepo cites the import-path form
    (`app/core/real_module.py`) that only resolves from inside backend/."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "The entry point is `app/core/real_module.py`.\n")
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, CFG)
    assert ok is True, msg


def test_second_declared_root_also_resolves(tmp_path):
    """Roots are tried in declaration order; the list is not single-valued."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "The widget is `components/widget.tsx`.\n")
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, CFG)
    assert ok is True, msg


def test_invented_path_under_a_declared_root_still_blocks(tmp_path):
    """CONTROL for sites 1 and 2a. Widening resolution must not become a blanket
    pass: a file that exists under NO declared root is still a confabulation."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "See `app/core/nonexistent_module.py` for the logic.\n")
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, CFG)
    assert ok is False
    assert "cites nonexistent path 'app/core/nonexistent_module.py'" in msg


def test_undeclared_root_does_not_resolve(tmp_path):
    """CONTROL: only DECLARED roots widen. A host that declares only backend must
    not get frontend/ for free."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "The widget is `components/widget.tsx`.\n")
    files = citation_exists.tracked_files(repo)
    cfg = {"lint": {"citation_source_roots": ["backend"]}}
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is False
    assert "cites nonexistent path 'components/widget.tsx'" in msg


def test_no_declared_roots_keeps_todays_behavior(tmp_path):
    """CONTROL: generic-first. A host with no roots is byte-identical to today.
    This is the guard that makes Track C safe to merge before Track D."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "The entry point is `app/core/real_module.py`.\n")
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is False
    assert "cites nonexistent path 'app/core/real_module.py'" in msg


def test_nested_tail_root_does_not_widen(tmp_path):
    """CONTROL for the package-roots-only constraint at the rule level: declaring
    `backend/app` must not make `core/real_module.py` resolve."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "See `core/real_module.py`.\n")
    files = citation_exists.tracked_files(repo)
    cfg = {"lint": {"citation_source_roots": ["backend/app"]}}
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is False
    assert "cites nonexistent path 'core/real_module.py'" in msg


# ---------- site 2b: the stale-exemption call site ----------


def test_exempt_token_that_resolves_under_a_root_reports_drift(tmp_path):
    """Site 2b. An exempt token whose file has appeared under a declared package
    root must surface as `stale exemption`, or the host's exemption list rots
    with no signal. This is the ONLY assertion that distinguishes the two
    _resolves() call sites."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "The retired shim `app/core/legacy.py` is gone.\n")
    files = citation_exists.tracked_files(repo)
    cfg = {
        "lint": {
            "citation_source_roots": ["backend", "frontend"],
            "citation_exempt_tokens": ["app/core/legacy.py"],
        }
    }
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is True, msg
    assert "stale exemption: 'app/core/legacy.py' now resolves" in msg


def test_exempt_token_that_resolves_nowhere_reports_no_drift(tmp_path):
    """CONTROL for site 2b: the drift note must not be fabricated for a token
    that genuinely resolves under no root."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "There is deliberately no `app/core/never_there.py`.\n")
    files = citation_exists.tracked_files(repo)
    cfg = {
        "lint": {
            "citation_source_roots": ["backend", "frontend"],
            "citation_exempt_tokens": ["app/core/never_there.py"],
        }
    }
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is True, msg
    assert "stale exemption" not in msg
```

- [ ] **Step 2: Run and observe the failures**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest \
  tests/lint/test_citation_source_roots.py -q 2>&1 | tail -12
```

Expected: `3 failed, 9 passed`. The three failures are `test_import_relative_path_resolves_under_a_declared_root` and `test_second_declared_root_also_resolves` (both `AssertionError: cites nonexistent path '…'`), and `test_exempt_token_that_resolves_under_a_root_reports_drift` (`AssertionError: assert "stale exemption: 'app/core/legacy.py' now resolves" in 'ok'`).

The six control tests pass **before** the change. That is what a control is for — they must still pass after.

- [ ] **Step 3: Widen `_resolves()`**

Replace the whole function (currently `scripts/lint/citation_exists.py:293-311`) with:

```python
def _resolves(
    rel: str,
    repo_root: Path,
    files: set[str],
    docs_dir: str,
    build_dir: str,
    roots: tuple[str, ...],
) -> bool:
    """True when a cited repo-relative path names something real.

    Four ways to resolve, in order: it is generated build output; it is tracked
    or present on disk (the disk fallback covers same-run siblings not yet added
    to git); it resolves under docs_dir, which is how a docs page naturally
    cites a sibling page; or it resolves under one of the host's declared
    package roots (CCE-139, `lint.citation_source_roots`). Roots come last, so
    declaring one can only widen resolution — it can never redirect a path that
    already resolves.

    `roots` is REQUIRED, not defaulted. This is a private helper with exactly
    two call sites; a default would let one of them silently keep the narrow
    behavior, and a block rule that has stopped blocking reports nothing. With
    no default an un-threaded call site is a TypeError, not a silent hole.
    """
    if build_dir and (rel == build_dir or rel.startswith(build_dir + "/")):
        return True
    if rel in files or (repo_root / rel).exists():
        return True
    if docs_dir:
        alt = f"{docs_dir}/{rel}"
        if alt in files or (repo_root / alt).exists():
            return True
    for root in roots:
        alt = f"{root}/{rel}"
        if alt in files or (repo_root / alt).exists():
            return True
    return False
```

- [ ] **Step 4: Thread `roots` through `check_path`**

In `check_path`, immediately after the line `exempt = exempt_tokens(config)`, add:

```python
    roots = source_roots(config)
```

Then update **both** call sites. Change:

```python
        if cited in exempt:
            if _resolves(rel, repo_root, files, docs_dir, build_dir):
```

to:

```python
        if cited in exempt:
            if _resolves(rel, repo_root, files, docs_dir, build_dir, roots):
```

and change:

```python
        if not _resolves(rel, repo_root, files, docs_dir, build_dir):
```

to:

```python
        if not _resolves(rel, repo_root, files, docs_dir, build_dir, roots):
```

- [ ] **Step 5: Re-run the new module together with the whole existing lint suite**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest \
  tests/lint/test_citation_source_roots.py tests/lint/test_citation_exists.py -q 2>&1 | tail -3
```

Expected: `0 failed`, with 12 tests contributed by the new module.

If any pre-existing `test_citation_exists.py` test fails with `TypeError: _resolves() missing 1 required positional argument: 'roots'`, a call site was missed. Find it:

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
grep -n "_resolves(" scripts/lint/citation_exists.py
```

Expected: exactly three hits — the `def`, and the two call sites, both ending `, roots):`.

- [ ] **Step 6: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
git add scripts/lint/citation_exists.py tests/lint/test_citation_source_roots.py
git commit -q -m "feat(CCE-139): resolve cited paths under declared package roots"
```

---

## Task 4 — Site 3, the symbol loop's target resolution and the silent-skip site

**Interfaces**

- Consumes: `citation_exists.source_roots` (Task 2).
- Produces: **`citation_exists._resolve_target(rel: str, repo_root: Path, roots: tuple[str, ...]) -> Path | None`** — the symbol loop's resolver. Private; no external consumer.

This is the site the round-1 analysis missed, and it fails **differently** from the others. The loop reads `if not target.exists(): continue`. Once Task 3 lands, the paths loop stops reporting `app/core/real_module.py`, and an un-widened symbol loop then skips the file entirely — so a **confabulated symbol attributed to a real file** ships unreported. Measured (M8): sites 1 and 2 widened with site 3 narrow returns `ok=True, msg='ok'` for `app/core/real_module.py:ghost_fn`.

Measured (M9): a **positive** control (`:real_fn` passes) does **not** discriminate this site — it returns `ok=True` either way. Only the negative control does.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lint/test_citation_source_roots.py`:

```python
# ---------- site 3: the symbol loop (the silent-skip site) ----------


def test_confabulated_symbol_in_a_root_resolved_file_blocks(tmp_path):
    """THE silent-skip regression. Once the paths loop resolves
    `app/core/real_module.py` under backend/, the symbol loop must resolve the
    SAME file or it hits `if target is None: continue` and never checks the
    symbol at all — an invented symbol attributed to a real file, which reads as
    authoritative, ships with no report. Measured: sites 1+2 widened and site 3
    narrow yields ok=True, msg='ok' for exactly this input."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "See `app/core/real_module.py:ghost_fn` for the logic.\n")
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, CFG)
    assert ok is False, msg
    assert "cites nonexistent symbol 'ghost_fn' in 'app/core/real_module.py'" in msg


def test_real_symbol_in_a_root_resolved_file_passes(tmp_path):
    """The positive case. NOTE: this test does NOT discriminate site 3 — it
    passes whether or not the symbol loop is widened, because a narrow loop
    `continue`s and reports nothing. It is here to prove the widening does not
    false-block, not to guard the silent skip."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "The entry point is `app/core/real_module.py:real_fn`.\n")
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, CFG)
    assert ok is True, msg


def test_symbol_on_an_invented_root_path_reports_path_not_symbol(tmp_path):
    """CONTROL for site 3: a :symbol citation on a file that exists under NO
    declared root must report the path problem once (from the paths loop) and
    must not double-report it as a symbol problem."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "See `app/core/nonexistent_module.py:whatever`.\n")
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, CFG)
    assert ok is False
    assert "cites nonexistent path 'app/core/nonexistent_module.py'" in msg
    assert "nonexistent symbol" not in msg


def test_symbol_resolution_prefers_the_repo_root_over_a_declared_root(tmp_path):
    """CONTROL: roots are tried AFTER the repo root, so a real top-level file is
    never shadowed by a same-named file inside a package root. The symbol must be
    looked up in the repo-root copy."""
    repo = _monorepo(tmp_path)
    (repo / "app" / "core").mkdir(parents=True)
    (repo / "app" / "core" / "real_module.py").write_text(
        "def top_level_only():\n    return 1\n"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "shadow")
    page = _page(repo, "See `app/core/real_module.py:top_level_only`.\n")
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, CFG)
    assert ok is True, msg
```

- [ ] **Step 2: Run and observe the failure**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest \
  tests/lint/test_citation_source_roots.py -q 2>&1 | tail -8
```

Expected: `1 failed, 15 passed`. The single failure is `test_confabulated_symbol_in_a_root_resolved_file_blocks` with `AssertionError: ok` — the message is literally `'ok'`, which is the silent skip made visible.

The other three pass already: two are controls, and `test_real_symbol_in_a_root_resolved_file_passes` is the non-discriminating positive documented in its own docstring.

- [ ] **Step 3: Add `_resolve_target()`**

Insert immediately **after** `_resolves()` and **before** `def check_path(`:

```python
def _resolve_target(rel: str, repo_root: Path, roots: tuple[str, ...]) -> Path | None:
    """First on-disk file a cited repo-relative path names: the repo root first,
    then each declared package root in declaration order. None when nothing
    exists on disk.

    The symbol loop's resolver, and it must widen in lockstep with _resolves()
    (CCE-139). The loop reads `if target is None: continue`, so a narrow target
    under a widened paths loop produces a SILENT SKIP, not a phantom report: the
    path resolves, the symbol is never checked, and a confabulated symbol
    attributed to a real file ships unreported. Repo root is tried first so a
    declared root can never shadow a real top-level file.
    """
    for cand in (rel, *(f"{root}/{rel}" for root in roots)):
        target = repo_root / cand
        if target.exists():
            return target
    return None
```

- [ ] **Step 4: Use it in the symbol loop**

In `check_path`, replace:

```python
        target = repo_root / rel
        if not target.exists():
            continue  # nonexistent path already reported by the paths loop
```

with:

```python
        target = _resolve_target(rel, repo_root, roots)
        if target is None:
            continue  # nonexistent path already reported by the paths loop
```

- [ ] **Step 5: Re-run and observe green**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest \
  tests/lint/test_citation_source_roots.py tests/lint/test_citation_exists.py -q 2>&1 | tail -3
```

Expected: `0 failed`, with 16 tests contributed by the new module.

- [ ] **Step 6: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
git add scripts/lint/citation_exists.py tests/lint/test_citation_source_roots.py
git commit -q -m "fix(CCE-139): widen the symbol loop's target resolution, closing a silent skip"
```

---

## Task 5 — Site 4a, `resolve_cited_sources()`

**Interfaces**

- Consumes: `citation_exists.source_roots` (Task 2).
- Produces: **`citation_exists.resolve_cited_sources(text: str, repo_root: Path, roots: tuple[str, ...] = ()) -> list[str]`**. Unlike `_resolves`, `roots` **defaults to `()`**: this is a public shared helper whose module docstring declares a cross-capability contract, and M13 confirms exactly one production caller plus two existing tests that pass two arguments. The default keeps those callers valid; Task 6's sentinel is what catches a forgotten call site.

**Behavioural change to note:** the function now returns paths in **resolved** form. A citation that only resolves under `backend/` comes back as `backend/app/core/real_module.py`, not the `app/core/real_module.py` the prose wrote, because the fact-checker opens each `cited_sources` entry relative to `repo_root` and would otherwise get a missing file. When `roots` is empty the returned value is byte-identical to today.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lint/test_citation_source_roots.py`:

```python
# ---------- site 4a: resolve_cited_sources (the fact-checker's resolver) ----------


def test_resolve_cited_sources_widens_and_returns_the_resolved_path(tmp_path):
    """Site 4 is a SECOND, independent resolver feeding the fact-checker's
    admission gate (`if not cited_sources: continue`). Widening only the linter
    would make it accept citations the fact-checker cannot see. The returned path
    must be the RESOLVED one — the fact-checker opens it relative to repo_root,
    so the as-written `app/core/…` form would be a missing file."""
    repo = _monorepo(tmp_path)
    text = "The entry point is `app/core/real_module.py`.\n"
    roots = citation_exists.source_roots(CFG)
    assert citation_exists.resolve_cited_sources(text, repo, roots) == [
        "backend/app/core/real_module.py"
    ]


def test_resolve_cited_sources_skips_invented_paths_under_a_root(tmp_path):
    """CONTROL for site 4: widening must not feed the fact-checker a path that
    does not exist. A confabulated citation still yields nothing."""
    repo = _monorepo(tmp_path)
    text = "See `app/core/nonexistent_module.py` and `app/core/real_module.py`.\n"
    roots = citation_exists.source_roots(CFG)
    assert citation_exists.resolve_cited_sources(text, repo, roots) == [
        "backend/app/core/real_module.py"
    ]


def test_resolve_cited_sources_without_roots_is_unchanged(tmp_path):
    """CONTROL: the two-argument shared-helper contract still holds, and a host
    with no declared roots gets byte-identical output to today."""
    repo = _monorepo(tmp_path)
    text = "The entry point is `app/core/real_module.py`.\n"
    assert citation_exists.resolve_cited_sources(text, repo) == []
    assert citation_exists.resolve_cited_sources(text, repo, ()) == []


def test_resolve_cited_sources_prefers_the_repo_root_copy(tmp_path):
    """CONTROL: roots are tried after the repo root, so the fact-checker reads
    the top-level file when one exists, not a same-named file under a root."""
    repo = _monorepo(tmp_path)
    (repo / "app" / "core").mkdir(parents=True)
    (repo / "app" / "core" / "real_module.py").write_text("X = 1\n")
    text = "The entry point is `app/core/real_module.py`.\n"
    roots = citation_exists.source_roots(CFG)
    assert citation_exists.resolve_cited_sources(text, repo, roots) == [
        "app/core/real_module.py"
    ]
```

- [ ] **Step 2: Run and observe the failures**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest \
  tests/lint/test_citation_source_roots.py -q 2>&1 | tail -10
```

Expected: `2 failed, 18 passed`. The two failures are `test_resolve_cited_sources_widens_and_returns_the_resolved_path` and `test_resolve_cited_sources_skips_invented_paths_under_a_root`, both with `TypeError: resolve_cited_sources() takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Implement**

Replace the whole `resolve_cited_sources` function (currently `scripts/lint/citation_exists.py:376-384`) with:

```python
def resolve_cited_sources(
    text: str, repo_root: Path, roots: tuple[str, ...] = ()
) -> list[str]:
    """Cited paths that exist on disk — the fact-checker's cited_sources input.

    Ordered, deduped, and returned in RESOLVED form: a citation that only
    resolves under a declared package root (CCE-139) comes back as
    `backend/app/core/x.py`, not as the `app/core/x.py` the prose wrote, so the
    fact-checker can open it relative to repo_root. The repo root is tried
    first, so a declared root never shadows a real top-level file.

    This is a SECOND, independent resolver from _resolves(): it feeds the
    fact-checker's admission gate (`if not cited_sources: continue`), so
    widening only the lint would let the linter accept citations the
    fact-checker cannot see.

    `roots` defaults to () to keep the two-argument shared-helper contract in
    this module's docstring intact for existing callers.
    """
    out: list[str] = []
    for cited in extract_citations(text)["paths"]:
        rel = _relativize(cited, repo_root)
        if rel is None:
            continue
        for cand in (rel, *(f"{root}/{rel}" for root in roots)):
            if (repo_root / cand).exists():
                if cand not in out:
                    out.append(cand)
                break
    return out
```

- [ ] **Step 4: Re-run, including the two pre-existing `resolve_cited_sources` tests**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/lint/ -q 2>&1 | tail -3
```

Expected: `0 failed`. In particular `test_resolve_cited_sources_returns_existing_relative_paths` and `test_resolve_cited_sources_handles_symbol_suffix` in `tests/lint/test_citation_exists.py` must still pass unmodified — they call the function with two arguments and expect the as-written path, which the `roots=()` default preserves.

- [ ] **Step 5: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
git add scripts/lint/citation_exists.py tests/lint/test_citation_source_roots.py
git commit -q -m "feat(CCE-139): widen resolve_cited_sources, the fact-checker's second resolver"
```

---

## Task 6 — Site 4b, the orchestrator call site, and the four-site sentinel

**Interfaces**

- Consumes: `citation_exists.source_roots` and the widened `citation_exists.resolve_cited_sources` (Tasks 2 and 5).
- Produces: the wired fact-checker admission gate. Track B's auto-merge work reads `state["current_run"]["fact_check_warnings"]`, which this task can now populate for pages it previously skipped. No signature changes, no new state.

Measured (M5): only **3** of the host's 152 pages flip from an empty `cited_sources` to a non-empty one. That is a much smaller effect than the 33-to-17 lint delta, because most rescued citations sit on pages that already resolved some other source. The spec's acceptance criterion is satisfiable, but by 3 pages. Record that; do not oversell it.

The seam this test uses: in dry-run mode the orchestrator's lint-revert loop consumes the `content-validator` **fixture** (`{"passed": [], "failed": []}`), so no real lint runs and the page is never reverted. That isolates block E to the admission gate alone.

- [ ] **Step 1: Write the failing sentinel**

Create `/Users/theo/Projects/engineering-docs-agent-trackC/tests/orchestrator/test_citation_source_roots_sentinel.py`:

```python
"""CCE-139: the four-site sentinel.

ONE test that goes red if ANY of the four resolution sites named in the spec is
left un-widened. It lives under tests/orchestrator/ because that is the only
directory whose conftest provides `init_host`, and because block E has to drive
the real orchestrator to reach the fact-checker's admission gate.

Blocks, and the site each one pins:
  A  _resolves() + the check_path paths-loop call site   (spec items 1, 2a)
  B  the check_path stale-exemption call site            (spec item 2b)
  C  the symbol loop's target resolution                 (spec item 3)
  D  resolve_cited_sources()                             (spec item 4a)
  E  the orchestrator call site                          (spec item 4b)

Task 6 Step 5 of the plan runs a six-way mutation proof against this file: each
site is reverted in turn and the sentinel is observed to go red with the named
message. Do not weaken an assertion here without redoing that proof.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import orchestrator_runner  # noqa: E402

from scripts.lint import citation_exists  # noqa: E402

CONFIG_YAML = """
docs:
  framework: mkdocs
  source_dir: docs/site-src
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths:
    core: docs/site-src/core
sources:
  git: { host: github }
lint:
  tier1: default
  citation_source_roots: [backend]
  citation_exempt_tokens: ["app/core/legacy.py"]
publishing:
  base_url: https://example.com
  build_workflow: deploy.yml
  url_map_rule: standard
  verify_timeout_seconds: 60
notifications:
  slack: { enabled: false }
  email: { enabled: false }
"""

SEED = {
    "backend/app/core/real_module.py": "def real_fn():\n    return 1\n",
    "backend/app/core/legacy.py": "LEGACY = 1\n",
}

CITED_PAGE = """\
---
status: draft
sources: []
synthesized_into: null
---
# Page

This page cites `app/core/real_module.py` in prose.
"""


def _write_fakes(fakes: Path) -> None:
    """Minimal dry-run fixture set: one PR -> one core page, plus a fact-checker
    that returns a contradiction so a dispatch is observable."""
    fakes.mkdir(parents=True, exist_ok=True)
    (fakes / "fake_source_collector.json").write_text(
        json.dumps(
            {
                "prs": [
                    {
                        "number": 1,
                        "url": "https://example.test/pr/1",
                        "merge_sha": "",
                        "files": [{"path": "backend/app/core/real_module.py"}],
                        "jira_keys": [],
                    }
                ],
                "jira_issues": [],
            }
        )
    )
    (fakes / "fake_pr_summarizer.json").write_text(
        json.dumps(
            {
                "pr_number": 1,
                "what_changed": "module behavior",
                "doc_targets": [
                    {"lens": "core", "page_hint": "page.md", "action": "edit"}
                ],
            }
        )
    )
    (fakes / "fake_page_author.json").write_text(
        json.dumps({"ok": True, "path": "docs/site-src/core/page.md", "action": "edit"})
    )
    (fakes / "fake_content_validator.json").write_text(
        json.dumps({"passed": [], "failed": []})
    )
    (fakes / "fake_gap_detector.json").write_text(
        json.dumps({"pr_id": "o/r#1", "needs_spec": False})
    )
    (fakes / "fake_notifier.json").write_text(
        json.dumps({"slack_ok": True, "email_ok": True})
    )
    (fakes / "fake_fact_checker.json").write_text(
        json.dumps(
            {
                "ok": True,
                "verdict": "contradiction",
                "page": "docs/site-src/core/page.md",
                "findings": [
                    {
                        "claim": "page says X but code does Y",
                        "source_path": "backend/app/core/real_module.py",
                        "evidence": "real_fn returns 1",
                    }
                ],
            }
        )
    )


def test_source_roots_threaded_through_all_four_resolution_sites(
    init_host, tmp_path, read_current_run
):
    state_path = init_host({"version": "1"}, CONFIG_YAML, SEED)
    repo = tmp_path
    config = yaml.safe_load(CONFIG_YAML)
    files = citation_exists.tracked_files(repo)
    roots = citation_exists.source_roots(config)
    assert roots == ("backend",), "site 0: source_roots() must read the config"

    # A probe page at the repo root, outside docs/site-src, so nothing the
    # orchestrator stages can see it. Removed before block E runs.
    probe = repo / "probe.md"

    # --- Block A: sites 1 + 2a. An import-relative path resolves under a root.
    probe.write_text("The entry point is `app/core/real_module.py`.\n")
    ok, msg = citation_exists.check_path(probe, repo, files, config)
    assert ok is True, f"block A (sites 1+2a) not widened: {msg}"

    # --- Block A control: an invented path under the SAME root still blocks.
    probe.write_text("See `app/core/nonexistent_module.py`.\n")
    ok, msg = citation_exists.check_path(probe, repo, files, config)
    assert ok is False, "block A control: invented path must still block"
    assert "cites nonexistent path 'app/core/nonexistent_module.py'" in msg

    # --- Block B: site 2b. An exempt token now resolving under a root drifts.
    probe.write_text("The retired shim `app/core/legacy.py` is gone.\n")
    ok, msg = citation_exists.check_path(probe, repo, files, config)
    assert ok is True, msg
    assert (
        "stale exemption: 'app/core/legacy.py' now resolves" in msg
    ), f"block B (site 2b, the stale-exemption call site) not widened: {msg}"

    # --- Block C: site 3. The SILENT SKIP: with A widened and C not, this
    # returns ok=True / 'ok' and the confabulated symbol ships unreported.
    probe.write_text("See `app/core/real_module.py:ghost_fn` for the logic.\n")
    ok, msg = citation_exists.check_path(probe, repo, files, config)
    assert ok is False, f"block C (site 3, symbol loop) silently skipped: {msg}"
    assert "cites nonexistent symbol 'ghost_fn' in 'app/core/real_module.py'" in msg

    # --- Block D: site 4a. The fact-checker's second resolver, resolved form.
    resolved = citation_exists.resolve_cited_sources(
        "The entry point is `app/core/real_module.py`.\n", repo, roots
    )
    assert resolved == [
        "backend/app/core/real_module.py"
    ], f"block D (site 4a, resolve_cited_sources) not widened: {resolved}"

    # --- Block D control: an invented path is never handed to the fact-checker.
    assert (
        citation_exists.resolve_cited_sources(
            "See `app/core/nonexistent_module.py`.\n", repo, roots
        )
        == []
    )

    probe.unlink()

    # --- Block E: site 4b. The orchestrator call site. With it un-threaded,
    # resolve_cited_sources returns [] for this page, the admission gate
    # `if not cited_sources: continue` fires, and no fact-checker runs.
    page = repo / "docs" / "site-src" / "core" / "page.md"
    page.write_text(CITED_PAGE)
    fakes = tmp_path / "fakes"
    _write_fakes(fakes)

    rc = orchestrator_runner.run(repo, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    cr = read_current_run(state_path)
    assert len(cr["fact_check_warnings"]) == 1, (
        "block E (site 4b, the orchestrator call site) not threaded: the "
        f"fact-checker never ran. warnings={cr['fact_check_warnings']}"
    )
    assert "page says X but code does Y" in cr["fact_check_warnings"][0]
```

- [ ] **Step 2: Run it and observe the failure**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest \
  tests/orchestrator/test_citation_source_roots_sentinel.py -q 2>&1 | tail -12
```

Expected: `1 failed`, and the failure must be **block E specifically** — blocks A to D are already green from Tasks 2 to 5. The assertion message reads `block E (site 4b, the orchestrator call site) not threaded: the fact-checker never ran. warnings=[]`.

If it fails on an earlier block, one of Tasks 3 to 5 is incomplete. Fix that before touching the orchestrator.

- [ ] **Step 3: Implement the orchestrator call site**

In `scripts/orchestrator_runner.py`, inside `run()`'s fact-checker loop, replace:

```python
                cited_sources = _citation_exists.resolve_cited_sources(
                    page_text, repo_root
                )
```

with:

```python
                cited_sources = _citation_exists.resolve_cited_sources(
                    page_text, repo_root, _citation_exists.source_roots(config)
                )
```

`config` is in scope: assigned once at `load_config_validated(cfg_path)` near the top of `run()` and never reassigned (M14). **Locate this by text, not by line number** — the concurrent Track A edit shifts it (M15).

- [ ] **Step 4: Re-run and observe green**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest \
  tests/orchestrator/test_citation_source_roots_sentinel.py \
  tests/orchestrator/test_fact_checker.py -q 2>&1 | tail -3
```

Expected: `0 failed`. `tests/orchestrator/test_fact_checker.py` must stay green — its host declares no roots, so `source_roots(config)` returns `()` and the behaviour is unchanged.

- [ ] **Step 5: The six-way mutation proof**

This step discharges the spec's "every widened resolver needs a control" requirement, and it exists because the round-1 analysis missed site 4 entirely. Apply each mutation, observe the sentinel go **red with the named message**, then restore.

For each row, apply the edit, then run:

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest \
  tests/orchestrator/test_citation_source_roots_sentinel.py -q 2>&1 \
  | grep -E "AssertionError|TypeError|passed|failed" | head -4
```

then restore:

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
git checkout -- scripts/lint/citation_exists.py scripts/orchestrator_runner.py
```

| #   | Site | Mutation                                                                                                                                                               | Sentinel must report                                                                                  |
| --- | ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| M1  | 1    | In `_resolves`, delete the `for root in roots:` loop and its two-line body                                                                                             | `block A (sites 1+2a) not widened: cites nonexistent path 'app/core/real_module.py'`                  |
| M2a | 2a   | Change the `if not _resolves(rel, repo_root, files, docs_dir, build_dir, roots):` call to pass `()` instead of `roots`                                                 | `block A (sites 1+2a) not widened: cites nonexistent path 'app/core/real_module.py'`                  |
| M2b | 2b   | Change the `if _resolves(rel, repo_root, files, docs_dir, build_dir, roots):` call inside the `cited in exempt` branch to pass `()`                                    | `block B (site 2b, the stale-exemption call site) not widened: ok`                                    |
| M3  | 3    | Replace `target = _resolve_target(rel, repo_root, roots)` / `if target is None:` with `target = repo_root / rel` / `if not target.exists():`                           | `block C (site 3, symbol loop) silently skipped: ok`                                                  |
| M4a | 4a   | In `resolve_cited_sources`, replace the `for cand in (rel, *(...))` loop with the original `if rel and (repo_root / rel).exists() and rel not in out: out.append(rel)` | `block D (site 4a, resolve_cited_sources) not widened: []`                                            |
| M4b | 4b   | In `orchestrator_runner.py`, drop the third argument from the `resolve_cited_sources(...)` call                                                                        | `block E (site 4b, the orchestrator call site) not threaded: the fact-checker never ran. warnings=[]` |

All six must go red. **M3 and M4b are the two that matter most:** M3 is the one whose failure mode is a silent pass rather than an error, and M4b is the one the round-1 analysis missed. If any mutation leaves the sentinel green, the sentinel is not discriminating — fix the test, not the mutation.

- [ ] **Step 6: Confirm the tree is restored, then commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
git status --short
```

Expected: only `?? tests/orchestrator/test_citation_source_roots_sentinel.py` and ` M scripts/orchestrator_runner.py`. If `scripts/lint/citation_exists.py` still shows as modified, a mutation was not restored — run `git checkout -- scripts/lint/citation_exists.py` and redo Step 4 before committing.

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
git add scripts/orchestrator_runner.py tests/orchestrator/test_citation_source_roots_sentinel.py
git commit -q -m "feat(CCE-139): thread source roots into the fact-checker admission gate"
```

---

## Task 7 — Declare `lint.citation_source_roots` in the config schema

**Interfaces**

- Consumes: the config-key semantics fixed in Task 2.
- Produces: `templates/config.schema.json` → `properties.lint.properties.citation_source_roots`. Track D writes `lint.citation_source_roots: [backend, frontend]` into the host config and depends on this validating.

Measured (M10): the `lint` object is **not** sealed, so the host key validates against the unmodified schema today. Declaring the property is therefore not a blocker for Track D — but it is not cosmetic either. An undeclared key accepts **any** value; a declared one rejects `citation_source_roots: "backend"` (a bare string) and rejects a nested tail. That type-check is the behaviour this task buys, and it is what the two new negative tests assert.

**Do not add `additionalProperties: false` to the `lint` object.** Sealing it would break any host carrying an unknown lint key and is out of scope for this spec.

- [ ] **Step 1: Write the failing tests**

Append to `tests/schemas/test_config_schema.py`:

```python
# ---------- CCE-139: lint.citation_source_roots ----------

_BASE_CFG = """
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/core }
sources: { git: { host: github } }
publishing:
  base_url: https://x
  build_workflow: deploy.yml
  url_map_rule: standard
notifications: {}
"""


def test_citation_source_roots_package_roots_accepted():
    cfg = yaml.safe_load(
        _BASE_CFG
        + "lint: { tier1: default, citation_source_roots: [backend, frontend] }\n"
    )
    validate(cfg, SCHEMA)


def test_citation_source_roots_rejects_a_nested_tail():
    """Spec: roots must be PACKAGE roots, never a tail like `backend/storage`.
    A root list deep enough to catch tails is suffix-matching in disguise."""
    cfg = yaml.safe_load(
        _BASE_CFG
        + "lint: { tier1: default, citation_source_roots: [backend/storage] }\n"
    )
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


def test_citation_source_roots_rejects_a_bare_string():
    """The value is a list of roots, not one root. An undeclared key would have
    accepted this silently."""
    cfg = yaml.safe_load(
        _BASE_CFG + 'lint: { tier1: default, citation_source_roots: "backend" }\n'
    )
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)
```

- [ ] **Step 2: Run and observe the failure**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest \
  tests/schemas/test_config_schema.py -q 2>&1 | tail -8
```

Expected: `2 failed`. Both `test_citation_source_roots_rejects_a_nested_tail` and `test_citation_source_roots_rejects_a_bare_string` fail with `Failed: DID NOT RAISE <class 'jsonschema.exceptions.ValidationError'>`, because the undeclared key accepts anything. `test_citation_source_roots_package_roots_accepted` passes already; it is the control that the declaration must not over-tighten.

- [ ] **Step 3: Implement**

In `templates/config.schema.json`, inside `properties.lint.properties`, add a trailing entry after the `citation_exempt_tokens` block. Change:

```json
        "citation_exempt_tokens": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Exact citation tokens whose non-existence is intentional (CCE-131). Unioned with the plugin defaults, never replacing them."
        }
      }
    },
```

to:

```json
        "citation_exempt_tokens": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Exact citation tokens whose non-existence is intentional (CCE-131). Unioned with the plugin defaults, never replacing them."
        },
        "citation_source_roots": {
          "type": "array",
          "items": { "type": "string", "pattern": "^[A-Za-z0-9_][A-Za-z0-9._-]*$" },
          "description": "Extra package roots citation_exists tries when resolving a cited repo path, after the repo root and docs_dir (CCE-139). Additive; empty by default, so a host that declares nothing is unaffected. Single-segment package roots only (\"backend\", \"frontend\") — a nested tail like \"backend/storage\" is suffix-matching in disguise and admits confabulated paths, which is why the pattern rejects any entry containing a slash."
        }
      }
    },
```

- [ ] **Step 4: Re-run the schema and config-loading suites**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest \
  tests/schemas/ tests/state_io/ -q 2>&1 | tail -3
```

Expected: `0 failed`.

- [ ] **Step 5: Run the real consumer against the real host config**

A schema is only correct against the config a host will actually write. Validate the host config exactly as Track D will produce it, and confirm the constraint bites:

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -c "
import copy, json, yaml, jsonschema
schema = json.load(open('templates/config.schema.json'))
raw = yaml.safe_load(open('/Users/theo/Projects/advanced-data-importer/.engineering-docs-agent/config.yml').read())
cfg = copy.deepcopy(raw)
cfg['lint']['citation_source_roots'] = ['backend', 'frontend']
jsonschema.validate(cfg, schema)
print('host config + [backend, frontend] validates: OK')
cfg['lint']['citation_source_roots'] = ['backend/storage']
try:
    jsonschema.validate(cfg, schema)
    raise SystemExit('FAIL: nested tail was accepted')
except jsonschema.ValidationError as e:
    print('nested tail rejected at', e.json_path)
"
```

Expected, both lines:

```
host config + [backend, frontend] validates: OK
nested tail rejected at $.lint.citation_source_roots[0]
```

- [ ] **Step 6: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
git add templates/config.schema.json tests/schemas/test_config_schema.py
git commit -q -m "feat(CCE-139): declare lint.citation_source_roots in the config schema"
```

---

## Task 8 — Permit `notes` on a `pr_summarizer` `doc_targets` item

**Interfaces**

- Consumes: nothing.
- Produces: `agents/schemas/pr_summarizer.schema.json` → `properties.doc_targets.items.properties.notes`, typed `["string","null"]`. No Python signature changes: `scripts/contracts.py`'s `PrSummary.doc_targets` is `list[dict]`, so the dataclass view already carries the key.

Measured (M11): the rejection is scoped exactly as the spec says. The **root** object already permits `notes`; the `doc_targets` **item** object sets `additionalProperties: false` over `lens`/`action`/`page_hint`/`doc_kind` only. This task changes the item object and nothing else. `additionalProperties: false` stays on both objects — the fix is to name the one legitimate key, not to open the shape.

- [ ] **Step 1: Write the failing tests**

Append to `tests/schemas/test_pr_summarizer_schema.py`:

```python
# ---------- CCE-139: notes on a doc_targets item ----------


def test_doc_target_item_accepts_notes(validator: Draft7Validator) -> None:
    """Run #699 was rejected for emitting `notes` inside a doc_targets item. The
    root object already permitted notes; the item object did not."""
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {
                "lens": "core",
                "action": "edit",
                "page_hint": "backend/api.md",
                "notes": "the endpoint moved; keep the old anchor",
            }
        ],
    }
    validator.validate(doc)


def test_doc_target_item_accepts_null_notes(validator: Draft7Validator) -> None:
    """Symmetric with the root-level notes, which is ["string", "null"]."""
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {"lens": "core", "action": "edit", "page_hint": "a.md", "notes": None}
        ],
    }
    validator.validate(doc)


def test_doc_target_item_still_rejects_an_unknown_key(
    validator: Draft7Validator,
) -> None:
    """CONTROL: naming `notes` must not open the item shape. additionalProperties
    stays false, so a genuinely unknown key is still a contract violation."""
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {
                "lens": "core",
                "action": "edit",
                "page_hint": "a.md",
                "confidence": 0.9,
            }
        ],
    }
    with pytest.raises(ValidationError):
        validator.validate(doc)
```

- [ ] **Step 2: Run and observe the failure**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest \
  tests/schemas/test_pr_summarizer_schema.py -q 2>&1 | tail -8
```

Expected: `2 failed`. Both `test_doc_target_item_accepts_notes` and `test_doc_target_item_accepts_null_notes` fail with `jsonschema.exceptions.ValidationError: Additional properties are not allowed ('notes' was unexpected)`. `test_doc_target_item_still_rejects_an_unknown_key` passes already — it is the control.

- [ ] **Step 3: Edit the canonical schema**

In `agents/schemas/pr_summarizer.schema.json`, inside `properties.doc_targets.items.properties`, change:

```json
          "doc_kind": { "type": "string", "enum": ["architecture", "decision"] }
```

to:

```json
          "doc_kind": { "type": "string", "enum": ["architecture", "decision"] },
          "notes": { "type": ["string", "null"] }
```

- [ ] **Step 4: Mirror it into the agent prompt, in lockstep**

`tests/agents/test_schema_md_sync.py` asserts `json.loads`-equality between the schema file and the `## Output schema (canonical)` fenced block. In `agents/pr-summarizer.md`, apply the **identical** edit to that fenced JSON block — the `"doc_kind"` line inside `doc_targets.items.properties`.

While you are in that file, extend the illustrative `## Output contract` example so the prompt actually shows the key. Change:

```json
    {
      "lens": "core",
      "action": "edit",
      "page_hint": "architecture/orchestrator.md"
    },
```

to:

```json
    {
      "lens": "core",
      "action": "edit",
      "page_hint": "architecture/orchestrator.md",
      "notes": "per-target caveat; optional"
    },
```

The `## Output contract` block is prose, not schema-synced — `test_schema_md_sync.py` matches only the `## Output schema (canonical)` heading — so this second edit is safe, and it is what stops the agent guessing at the shape.

- [ ] **Step 5: Run the sync test and the schema tests**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest \
  tests/schemas/test_pr_summarizer_schema.py tests/agents/ -q 2>&1 | tail -3
```

Expected: `0 failed`. If `test_md_schema_block_matches_canonical_schema_file[pr-summarizer]` fails, the `.md` fenced block and the `.json` have drifted — re-read both and make them equal after `json.loads`.

- [ ] **Step 6: Regenerate the published contract doc with the real generator**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python scripts/contracts_doc.py \
  --repo-root . --config .engineering-docs-agent/config.yml
git status --short docs/site-src/api/contracts/
```

Expected: the script prints a JSON `{"written": [...], "skipped": [...]}` summary, and `git status --short` on that directory prints **nothing**. Measured (M12): `render_contract_page` iterates root-level `properties` only, so a nested item property produces no diff. If a diff does appear, commit it — the generated pages are never hand-edited, and a diff would mean the renderer is more capable than measured.

- [ ] **Step 7: Commit**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
git add agents/schemas/pr_summarizer.schema.json agents/pr-summarizer.md \
  tests/schemas/test_pr_summarizer_schema.py docs/site-src/api/contracts/
git commit -q -m "fix(CCE-139): permit notes on a pr-summarizer doc_targets item"
```

---

## Task 9 — Whole-suite green and real-host corpus verification

**Interfaces**

- Consumes: everything above.
- Produces: the measured 33-to-17 delta that Track D plans against, and the evidence that Track C's acceptance criteria hold.

- [ ] **Step 1: Full plugin suite**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: **the baseline you recorded in Task 1 Step 3, plus exactly 27** — 4 in Task 2, 8 in Task 3, 4 in Task 4, 4 in Task 5, 1 in Task 6, 3 in Task 7, 3 in Task 8.

| Baseline recorded in Task 1 Step 3       | Expected here            |
| ---------------------------------------- | ------------------------ |
| `1203` (pristine `main`, Track A not in) | `1230 passed, 5 skipped` |
| `1208` (Track A landed — the likely one) | `1235 passed, 5 skipped` |

**Assert on `0 failed` and on the delta being exactly 27**, not on either absolute number. The delta is this track's contract; the absolute is a property of whatever else is on `main`. Track B (CCE-140) lands after this and expects `1235` as _its_ starting baseline.

- [ ] **Step 2: Confirm all four resolution sites are threaded, by inspection**

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
grep -n "source_roots\|_resolves(\|_resolve_target(" scripts/lint/citation_exists.py
grep -n "resolve_cited_sources" scripts/orchestrator_runner.py
```

Expected:

- one `def source_roots(config: dict)` definition
- one `roots = source_roots(config)` call, inside `check_path`
- one `def _resolves(` plus exactly two call sites, both ending `, roots):`
- one `def _resolve_target(` plus exactly one call site, `target = _resolve_target(rel, repo_root, roots)`
- in the orchestrator, one `resolve_cited_sources(` call whose third argument is `_citation_exists.source_roots(config)`

Any `_resolves(...)` call without a `roots` argument, or any `repo_root / rel` still assigned to `target` in the symbol loop, is an un-threaded site.

- [ ] **Step 3: Measure the real host corpus, using a throwaway config copy**

> **HARD ORDERING PRECONDITION — check this before running Step 3 or Step 4.** Both steps measure the **live** host repo, and Track D (ADIS-490) edits exactly the two things they depend on. Track D Task 1 adds `lint.citation_source_roots` to `.engineering-docs-agent/config.yml`, which would make the `sed` below emit the key **twice** in the copy; Track D Task 9 adds `citation_exempt_tokens` including `db_engine_specs/mysql.py`, which would make Step 4's live control report **0** hits instead of 3, and Track D Task 8 rewrites 26 citations, which would move the `17` to something smaller. All three are correct Track D changes; none is a defect. They simply mean **Track C measures first, merges, and only then does Track D start** — which is the spec's own A → C → D → B ordering.
>
> Verify the host is untouched by Track D:
>
> ```bash
> H=/Users/theo/Projects/advanced-data-importer
> git -C $H status --short
> grep -c 'citation_source_roots\|citation_exempt_tokens' $H/.engineering-docs-agent/config.yml
> ```
>
> Required: `git status --short` prints nothing, and the grep prints `0`. If the grep is non-zero, Track D has already landed — **do not edit these expectations to match.** Re-measure the whole chain and record the new figures in the PR body, noting that the numbers now describe a partially-conformed corpus rather than the baseline this plan was written against.

Track D owns `.engineering-docs-agent/config.yml`, so this step must not modify it. `repo_root_for()` resolves the repo by running `git rev-parse` from the **config's own directory**, so the copy has to live inside the host repo — a copy in `/tmp` would make `repo_root` `None` and every page would pass trivially.

```bash
H=/Users/theo/Projects/advanced-data-importer
W=/Users/theo/Projects/engineering-docs-agent-trackC
V=/Users/theo/Projects/engineering-docs-agent/.venv/bin/python
CP=$H/.engineering-docs-agent/config.trackC-probe.yml
sed 's/^lint:$/lint:\n  citation_source_roots: [backend, frontend]/' \
  $H/.engineering-docs-agent/config.yml > $CP
cd $H
$V $W/scripts/lint/citation_exists.py --config $CP \
  --paths $(find docs/site-src -name '*.md' -type f | sort | tr '\n' ' ') \
  --json > /tmp/ce_trackC_after.json
$V -c "
import json
r = json.load(open('/tmp/ce_trackC_after.json'))['results']
bad = [x for x in r if not x['ok']]
print('pages:', len(r))
print('failing:', len(bad))
print('severities:', sorted({x['severity'] for x in bad}))
for x in bad:
    print(' ', x['path'], '::', x['message'])
"
rm -f $CP
git -C $H status --short
```

Expected: `pages: 152`, `failing: 17`, `severities: ['block']`, then the 17 paths, then `git -C $H status --short` printing **nothing**. The 17 must match the grouped list in §Measurements; a page outside that list means the widening did something unintended.

If `rm -f $CP` is skipped, the host repo is left dirty and Track D inherits a stray untracked config. Verify the empty `git status` before moving on.

- [ ] **Step 4: Discharge the live control from the spec's acceptance, against the real corpus**

```bash
V=/Users/theo/Projects/engineering-docs-agent/.venv/bin/python
$V -c "
import json
bad = {x['path']: x['message'] for x in json.load(open('/tmp/ce_trackC_after.json'))['results'] if not x['ok']}
hits = [p for p, m in bad.items() if 'db_engine_specs/mysql.py' in m]
assert len(hits) == 3, hits
print('control db_engine_specs/mysql.py still blocks on', len(hits), 'pages:')
for h in hits:
    print('  ', h)
"
```

Expected: `control db_engine_specs/mysql.py still blocks on 3 pages:` followed by `archive/adrs/superset-deployment.md`, `core/superset/deployment.md`, `future-me/gotchas.md`.

The spec names four controls; only this one is usable. Record why in the PR body:

- `.claude/skill-usage.log` **exists on disk** at the host root — untracked and gitignored, and the prose itself calls it machine-local — and `_resolves` has a `(repo_root / rel).exists()` disk fallback. It passes on a workstation and would block in CI. That is an environment-dependent result, not a control.
- `storage/_probe.py` and `.claude/rules/deploy-ci.md` appear **zero** times under `docs/site-src`. Confirm it yourself:

```bash
grep -rn "storage/_probe.py\|\.claude/rules/deploy-ci\.md" \
  /Users/theo/Projects/advanced-data-importer/docs/site-src | wc -l
```

Expected: `0`. They are not cited anywhere and cannot serve as controls.

The synthetic replacements are already in place: `test_invented_path_under_a_declared_root_still_blocks` (Task 3), `test_symbol_on_an_invented_root_path_reports_path_not_symbol` (Task 4), `test_resolve_cited_sources_skips_invented_paths_under_a_root` (Task 5), and the two control assertions inside the sentinel (Task 6).

- [ ] **Step 5: Discharge the `resolve_cited_sources` acceptance criterion, with its real magnitude**

```bash
H=/Users/theo/Projects/advanced-data-importer
W=/Users/theo/Projects/engineering-docs-agent-trackC
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -c "
import sys
from pathlib import Path
sys.path.insert(0, '$W/scripts/lint')
import citation_exists as ce
repo = Path('$H')
pages = sorted(repo.glob('docs/site-src/**/*.md'))
roots = ce.source_roots({'lint': {'citation_source_roots': ['backend', 'frontend']}})
e0 = e1 = t0 = t1 = 0
flipped = []
for p in pages:
    txt = p.read_text()
    a = ce.resolve_cited_sources(txt, repo)
    b = ce.resolve_cited_sources(txt, repo, roots)
    t0 += len(a); t1 += len(b)
    e0 += not a; e1 += not b
    if not a and b:
        flipped.append(str(p.relative_to(repo)))
print('pages:', len(pages))
print('empty today:', e0, '-> empty widened:', e1)
print('total resolved:', t0, '->', t1)
print('flipped empty -> non-empty:', len(flipped))
for f in flipped:
    print('  ', f)
"
```

Expected exactly:

```
pages: 152
empty today: 29 -> empty widened: 26
total resolved: 652 -> 706
flipped empty -> non-empty: 3
   docs/site-src/archive/specs/2026-04-16-multi-object-pipelines.md
   docs/site-src/c4/system-context.md
   docs/site-src/core/backend/data-model.md
```

The spec's criterion — `resolve_cited_sources` returns non-empty for pages that return empty today — is met by **3** pages. Say so plainly in the PR body rather than implying it tracks the 16-page lint improvement.

- [ ] **Step 6: Confirm both trees are clean, integrate `main`, then push**

```bash
git -C /Users/theo/Projects/advanced-data-importer status --short
cd /Users/theo/Projects/engineering-docs-agent-trackC && git status --short
git log --oneline main..HEAD
```

Expected: the host prints nothing, the worktree prints nothing, and the log shows the seven commits from Tasks 1 to 8.

Per the plugin's `CLAUDE.md` merge rule — merge on a green _integrated_ suite, never on GitHub's mergeable flag — merge `main` in locally and re-run the full suite before pushing, because Track A is landing into the same file:

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
git fetch origin
git merge origin/main
/Users/theo/Projects/engineering-docs-agent/.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: no conflict — Track A edits the authoring loop near `:1572`, Track C edits the fact-checker loop near `:1794`, which are different hunks in the same file and merge cleanly — and `0 failed`. If there is a conflict, resolve it by keeping **both** edits: Track A's `time_truncated = True` in the authoring loop and Track C's third argument on the `resolve_cited_sources` call.

```bash
cd /Users/theo/Projects/engineering-docs-agent-trackC
git push -u origin feat/CCE-139-citation-source-roots
gh pr create --title "[CCE-139] citation_exists — resolve cited paths under declared package roots" --body "$(cat <<'EOF'
Track C of the docs-agent self-sustaining design (host spec ADIS-490).
Lands second, after Track A (CCE-138) and before Track D (host, ADIS-490).

## What

`lint.citation_source_roots` — an additive, empty-by-default list of package
roots that `citation_exists` tries AFTER the repo root and `docs_dir`, never
before, so a declared root can only widen resolution and can never redirect a
path that already resolves.

Threaded through all four resolution sites the spec names, each with a control
proving an invented path under the same declared root still blocks:

1. `_resolves()` and both `check_path()` call sites — the reported failures, and
   the stale-exemption branch (the only assertion that tells the two apart).
2. `_resolve_target()`, new, for the symbol loop. This is the site whose failure
   mode is a SILENT PASS: the loop reads `if target is None: continue`, so a
   narrow target under a widened paths loop lets a confabulated symbol attributed
   to a real file ship unreported. Measured: `ok=True, msg='ok'` before the fix.
3. `resolve_cited_sources()` and its orchestrator call site — a second,
   independent resolver feeding the fact-checker's admission gate. Widening only
   the linter would let it accept citations the fact-checker cannot see.

A six-way mutation proof (Task 6 Step 5) reverts each site in turn and observes
the sentinel go red with the named message.

Also: `pr_summarizer.schema.json` now permits `notes` on a `doc_targets` item.
Run #699 was rejected for emitting it. The ROOT object already permitted `notes`;
the item object did not. `additionalProperties: false` stays on both — the fix
names the one legitimate key, it does not open the shape.

## Effect, measured, with its real magnitude

- `citation_exists` on the ADIS host: **33 -> 17** blocking pages. 16 fixed,
  ZERO newly failing (the widened set is a strict subset of today's).
- `resolve_cited_sources`: 29 empty pages -> 26, total resolved 652 -> 706.
  The spec's acceptance ("returns non-empty for pages that return empty today")
  is met by exactly **3** pages, not by anything resembling the 16-page lint
  improvement. Stating it without the number would overstate it.
- The remaining 17 are cause-grouped in the plan; five distinct causes, none
  fixable by more roots without violating the package-roots-only constraint.
  They are Track D's problem. `33 -> 17` is not `33 -> 0`.

## Controls

The spec names four "genuinely-bad host citations" that must still block. Only
ONE is usable: `db_engine_specs/mysql.py` (3 pages, blocks today and widened).
`.claude/skill-usage.log` EXISTS on disk at the host root (untracked, gitignored)
so it does not block today and is environment-dependent — it would block in CI
but not on a workstation. `storage/_probe.py` and `.claude/rules/deploy-ci.md`
are cited ZERO times anywhere under `docs/site-src`. The synthetic per-site
controls in `tests/lint/test_citation_source_roots.py` carry the load instead.

## Safety

Inert on every host that declares no roots — `source_roots()` returns `()` for an
absent key, guarded by `test_source_roots_defaults_to_empty` and
`test_no_declared_roots_keeps_todays_behavior`. That is the entire basis for
merging this to a repo consumed at `ref: main` with no release step. Do not
weaken either test.
EOF
)"
```

The PR title **must** carry `CCE-139` — `.github/workflows/jira-transition.yml` reads the key from the title only.

- [ ] **Step 7: Pre-merge gate**

Run `/simplify` and `/superpowers:requesting-code-review` with `BASE_SHA=$(git merge-base origin/main HEAD)` and `HEAD_SHA=$(git rev-parse HEAD)`. Fix Critical and Important findings before merge; note Minor.

Remember the deploy semantics (spec Risk 3): the plugin is consumed at `ref: main`, so a merge is live on the next nightly fire with no release step. Track C is inert on every host that declares no roots, which is why it is safe to merge before Track D — but that safety rests entirely on `source_roots` returning `()` for an absent key. `test_source_roots_defaults_to_empty` and `test_no_declared_roots_keeps_todays_behavior` are its guards. Do not weaken either.

- [ ] **Step 8: Clean up the worktree after the PR merges**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git worktree remove /Users/theo/Projects/engineering-docs-agent-trackC
git worktree prune
```

---

## Notes for Track D

- Set `lint.citation_source_roots: [backend, frontend]` in `/Users/theo/Projects/advanced-data-importer/.engineering-docs-agent/config.yml`. Measured: it validates against both the old and the new schema, so it can land in either order relative to this PR — but it does nothing until this PR merges to plugin `main`.
- Expect `citation_exists` to go from 33 to 17 blocking pages. The remaining 17 are enumerated and cause-grouped in §Measurements: five distinct causes, none of which more roots would fix without violating the package-roots-only constraint.
- One of the 17 — `archive/specs.md` — is regenerated by the host's own `scripts/generate_archive_indexes.py`, so editing the page is reverted on the next generator run.
- **`_resolves()` gains a required 6th positional here.** Track D's plan has three verification snippets that call the private `citation_exists._resolves()` with five positional arguments; all three raise `TypeError: _resolves() missing 1 required positional argument: 'roots'` once this PR merges. That plan now carries a signature-detecting shim (its §Environment) which works either side of this change — but if any _new_ ad-hoc probe is written against `_resolves`, it must pass `roots`. The un-defaulted parameter is deliberate: a silent narrowing in a block rule reports nothing, and a `TypeError` reports loudly.
- **Do not start Track D until this PR has merged AND this plan's Task 9 Steps 3-4 have been run.** Those steps measure the live host corpus, and Track D's first three tasks change exactly what they measure — Task 1 adds `citation_source_roots` to the config this plan's `sed` copies, Task 8 rewrites 26 of the citations being counted, and Task 9 exempts `db_engine_specs/mysql.py`, this plan's only usable real-corpus control. Serialise: C verifies, C merges, D starts.

## Notes for Track B (CCE-140)

- Track B edits `scripts/orchestrator_runner.py` too, but a different region (`_maybe_auto_merge`, the advance block, the admission and authoring loops) from this track's single line in the fact-checker loop. No textual conflict is expected.
- Track B also appends to `tests/schemas/test_config_schema.py` and hoists its own module-level constant, `_CCE140_BASE_CFG`. This plan's Task 7 hoists `_BASE_CFG`. The names differ and the contents differ (this one omits the `lint` key); Track B's plan explicitly instructs **not** to merge them. Leave both.
- Track B's starting suite baseline assumes this track has landed: `1203 + 5` (Track A) `+ 27` (this track) `= 1235`.

## Deliberately out of scope

- **The symbol loop does not consult `docs_dir`.** It never did (`target = repo_root / rel`), so a docs-sibling `:symbol` citation was already skipped. Pre-existing, harmless for `.md` targets, and outside this spec.
- **`resolve_cited_sources` does not consult `docs_dir` either.** Adding it would change what the fact-checker is handed in a way the spec does not ask for.
- **`lint` stays unsealed.** See Task 7.

---

## Reconciliation changes to this plan (2026-08-10)

Four tracks were planned independently. This is what changed here when they were reconciled against one another:

1. **Ticket key `CCE-138` → `CCE-139` throughout** — branch, every commit subject, the PR title, and every docstring. Track A independently claimed CCE-138 as well. The assignment table in §Global Constraints is now the shared source of truth: A = CCE-138, C = CCE-139, D = ADIS-490 (host, consumes no CCE key), B = CCE-140. File in that order.
2. **A hard ordering precondition added to Task 9 Step 3.** Steps 3 and 4 measure the live host corpus, and three separate Track D tasks change exactly what they measure. The precondition is now a runnable check (`git status --short` empty, and zero hits for `citation_source_roots|citation_exempt_tokens` in the host config) with an explicit instruction never to edit the expectations to match a moved corpus.
3. **The shared-clone caveat updated.** The concurrent agent's uncommitted `scripts/orchestrator_runner.py` edit and `test_zz_tmp_probe.py` are both gone; re-measured, the tree carries only ` M .gitignore` / `?? uv.lock` and `resolve_cited_sources` is back at `:1794`. The **rule** that episode produced still stands and is now justified by the permanent shift instead: when Track A lands, `:1794` becomes `:1795` for real.
4. **Task 1 Step 2's line-number check reframed.** It previously treated `1795` as evidence of a corrupt worktree. Post-Track-A, `1795` is the _expected_ value. The check now keys on the line's content and on `git status --short` being empty, which is the condition that actually matters.
5. **Baseline expectations made two-valued.** Task 1 Step 3 accepts `1203` (pristine) or `1208` (Track A landed, the likely case), and Task 9 Step 1 asserts on **the delta being exactly 27** rather than on the absolute `1230`.
6. **The PR now has a body.** `gh pr create` previously carried a title only. The body records the 33 → 17 delta, the 3-page (not 16-page) real magnitude of the `resolve_cited_sources` criterion, the four-controls correction, and the safety argument for merging to a repo consumed at `ref: main`.
7. **Two new hand-off notes added** — one telling Track D that `_resolves()` gains a required 6th positional (its plan had three five-argument call sites), and one telling Track B about the `test_config_schema.py` constant collision and its 1235 starting baseline.
