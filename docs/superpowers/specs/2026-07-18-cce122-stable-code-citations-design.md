# CCE-122: stable code citations — design

**Date:** 2026-07-18
**Ticket:** [CCE-122](https://designitright.atlassian.net/browse/CCE-122)
**Status:** approved
**Fix surface:** in-repo, ships via the plugin (`scripts/lint/citation_exists.py`, a new `scripts/lint/citation_line_free.py`, `scripts/lint/lint_runner.py`, `agents/fact-checker.md`, `agents/page-author.md`, a new `scripts/migrate_line_citations.py`, `docs/site-src/**` content, tests).
**Provenance:** the recurring root cause behind PR #179's eight fact-checker warnings (2026-07-16). `orchestrator_runner.py` grew ~60–83 lines across CCE-114/118/119/120; every `` `path:line` `` citation drifted downward; the nightly fact-checker re-flags the drift as `verdict: contradiction`; the CCE-101 zero-fact-checker-warnings gate then blocks docs-PR auto-merge. Brainstormed 2026-07-18 (Approach A′, "advisory warn" enforcement).

## Problem

Docs prose cites code as `` `path:line` `` (e.g. `` `scripts/orchestrator_runner.py:1240` ``). Line numbers are the single most churn-sensitive part of a citation: **any** edit above a cited line shifts it, so an unrelated change makes a correct citation "stale." The LLM fact-checker (`agents/fact-checker.md`) reads the cited source, greps the named symbol, and emits `verdict: contradiction` when the cited _location_ no longer matches — which fires on every benign drift. Those contradictions land in `state["current_run"]["fact_check_warnings"]` (`orchestrator_runner.py` ~:1799-1805), and the CCE-101 auto-merge gate requires **zero** fact-checker warnings. Net effect: docs PRs stop auto-merging until a human intervenes, on a purely cosmetic line shift.

Today there are **96** `` `path:line` `` inline spans across **21** published pages (`docs/site-src/architecture/`, `archive/`, `operations/`). Two token shapes appear:

- dir-qualified — `` `scripts/orchestrator_runner.py:1394` `` — matched by `citation_exists._REPO_PATH_RE`, so linted for file existence today;
- bare filename — `` `orchestrator_runner.py:128` `` — has no `/`, so it is **not** matched by `_REPO_PATH_RE` and is not linted at all today. It still drifts and the fact-checker still reads it.

### Root cause is layering, not format

One checker (the LLM fact-checker) is doing two jobs: (1) **behavioral truth** — "does the code actually do what the prose says?" — which is genuinely semantic and belongs to an LLM; and (2) **citation-location precision** — "does this line/location still point at the cited thing?" — which is deterministic and syntactic. Line drift is only "noise" because the semantic checker is policing the syntactic concern. A line citation drifts on _every_ edit (constant false alarm); a symbol citation drifts only on a _rename_ (rare, and then it is a _real_ staleness the docs should fix).

## Decision (brainstormed 2026-07-18)

Approach **A′**: split the two concerns. Make citations line-free, give citation-existence to a deterministic lint, and scope the fact-checker to behavioral truth. Enforcement level for a leftover `:line` is **advisory warn** (block would break un-migrated hosts; contract-only leaves no deterministic backstop).

| Concern                   | Chosen                                                                                                      | Rejected alternative                                                                                        |
| ------------------------- | ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| **Citation grammar**      | `` `path:symbol` `` for named code; bare `` `path` `` for config/non-symbol files; never `` `path:line` ``. | Bare-path only (Option 1) — loses machine-checkable symbol; leaves precision to the LLM.                    |
| **Existence check**       | Extend `citation_exists` (block) to verify a cited `:symbol` is defined in the file.                        | Leave symbols unverified — re-opens confabulation of a symbol the same way a bad file/test is caught today. |
| **`:line` going forward** | New advisory `SEVERITY="warn"` rule flags `` `path:line` `` spans; degrades gracefully.                     | Hard block (breaks un-migrated hosts / any future `:line`); contract-only (no deterministic backstop).      |
| **Fact-checker**          | Verify behavioral claims only; do NOT emit `contradiction` on line/location precision.                      | Keep it policing location — the drift-warning source we are removing.                                       |
| **Existing 96 pins**      | One-time deterministic migration to `:symbol`/bare, `ast`-resolved for `.py`.                               | Age-out / leave-as-is — the drift and the stale anchors persist.                                            |

Rationale: keeping the file **path** in every citation is load-bearing — `resolve_cited_sources` feeds the fact-checker by path, so "drop paths" (old Approach C) was rejected. Moving citation-existence to a deterministic lint converts "constant false alarms" (line drift) into "rare meaningful signal" (a rename that genuinely broke a citation), and frees the fact-checker to do only what it is good at, with no loss of confabulation-detection (a wrong symbol still fails the behavioral check → a _real_ contradiction).

## Architecture

Six changes. Every change is additive or backward-compatible; non-agent-authored and bare-`path` behavior is unchanged — generic-first, degrade-gracefully.

### 1. Citation grammar (convention)

- `` `path/to/file.py:symbol` `` when a named symbol exists (function / class / module constant); the leaf may be dotted for a method: `` `file.py:Class.method` ``.
- Bare `` `path/to/file.py` `` for whole-file references and non-symbol files (`.yml`, `.sh`, `.json`, `.md`, `.toml`).
- Never `` `path:line` `` / `` `path:start-end` ``.

### 2. Extend `scripts/lint/citation_exists.py` (block — the deterministic guard)

- **Grammar:** extend `_REPO_PATH_RE` so the optional suffix is `:digits(-digits)` **or** `:symbol` where `symbol = [A-Za-z_][\w.]*`. Extend the bare-path derivation so both suffix forms are stripped when producing the path handed to file-existence and to `resolve_cited_sources` (grounding still receives clean bare paths — the shared-helper contract that `orchestrator_runner.py` depends on is preserved; `extract_citations`'s `{"paths", "tests"}` return shape is byte-identical).
- **New symbol check:** add a standalone `extract_symbol_citations(text) -> list[tuple[str, str]]` returning `(bare_path, leaf_symbol)` for symbol-bearing cites (additive; does not alter `extract_citations`). In `check_path`, after the file is confirmed to exist, verify each cited symbol is **defined in that file**: read the file text and search for a definition of the leaf (last dotted component) — `def <leaf>(`, `class <leaf>`, or a module-level assignment/annotation `<leaf> =` / `<leaf>:` at column 0 (exact patterns pinned in the plan). A cited symbol with no definition in its file is a `problem` ("cites nonexistent symbol '<sym>' in <path>") — the same block severity as today's nonexistent-file/test finding. File-scoped (not repo-wide) because the path already pins the file. Known limitation: for `Class.method` only the leaf is verified, not the containment — cheap and deterministic; the fact-checker's behavioral check covers deeper correctness.

### 3. New advisory rule `scripts/lint/citation_line_free.py` (warn)

- `RULE_NAME = "citation_line_free"`, `SEVERITY = "warn"`. Flags any inline `` `path:digits` `` span as "prefer `path:symbol` or bare `path`." Detection reuses a small `line_pinned_citations(text) -> list[str]` helper added to `citation_exists` (single source of the path-citation grammar). Warn severity means `lint_runner.py:158` never fails the run on it — it is a non-blocking hygiene nudge that keeps drift from silently returning, and it does not break a host that still carries legacy `:line` pins.
- Register in `lint_runner.TIER1_DEFAULT` (runs by default; `markdown_hygiene_lang` is the existing Tier-1-default `warn` precedent, so a non-blocking Tier-1 rule is already an established shape — the other `warn` rules `reading_grade` / `sentence_variance` / `duplicate_content` are Tier-3 opt-in).

### 4. Fact-checker contract `agents/fact-checker.md` (the load-bearing change)

- Add an explicit instruction: verify the **behavioral claim** against the cited file (read the file, grep the named symbol); do **not** emit `verdict: contradiction` solely because a cited line number or location no longer matches — citation existence is owned by the `citation_exists` lint now. A wrong symbol still fails the behavioral check and is still a real `contradiction`. No confabulation-detection is lost; only line-position policing is removed.

### 5. Page-author contract `agents/page-author.md`

- Add to the authoring conventions / procedure: cite code as `` `path` `` or `` `path:symbol` ``, never `` `path:line` ``.

### 6. Migration `scripts/migrate_line_citations.py` (committed, tested, one-time, idempotent)

- Walk `docs/site-src/**.md`. For each inline `` `path:line` `` / `` `path:start-end` `` span:
  - Resolve the path. If bare-filename (no `/`), resolve the basename against `git ls-files`; unique hit → full path, otherwise leave the token as bare basename (strip only the `:line`).
  - If `.py` and resolvable: `ast`-map the (start) line to its enclosing `def`/`class` → `path:symbol` (`path:Class.method` for a method; `path:test_name` for a test ref); if the line sits at module level on a `NAME = …` assignment, use `path:NAME`; otherwise strip to bare `path`.
  - Non-`.py` or unresolvable: strip to bare `path`.
- Idempotent: a second run finds no `:line` spans and rewrites nothing. Verified by the **real consumer** — after migration, `citation_exists.check_path` passes on every touched page (per CLAUDE.md: verify with the tool, not `test -f`). Committed and unit-tested because it is reusable for any host with legacy `:line` pins (generic-first) and TDD is the repo norm.

## Data flow (authoring → verify, after A′)

```
page-author writes `path:symbol` / bare `path` (never `path:line`)
      │
      ├─► citation_exists (block): file exists? symbol defined in file?  ── confabulation → BLOCK
      ├─► citation_line_free (warn): any `path:line`?  ── advisory only, never blocks
      ├─► resolve_cited_sources → bare paths → fact-checker.cited_sources
      └─► fact-checker (LLM): behavioral claim vs cited file
                              (does NOT flag line/location precision)  ── real mismatch → contradiction
```

## Error handling / degradation

| Condition                                    | Behavior                                                                                                                          |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Cited `:symbol` not defined in its file      | `citation_exists` block ("cites nonexistent symbol")                                                                              |
| Cited file absent                            | `citation_exists` block (unchanged)                                                                                               |
| No git repo detected                         | `citation_exists` skips all path checks (unchanged degrade path)                                                                  |
| Leftover `` `path:line` `` on a page         | `citation_line_free` warn — advisory, run still passes                                                                            |
| Bare `` `path` `` (no symbol)                | file-existence only; symbol check not triggered                                                                                   |
| Non-`.py` file with a symbol-looking suffix  | symbol check runs but a config file rarely defines it → author uses bare `path` for these; migration strips their `:line` to bare |
| Migration: unresolvable / ambiguous basename | strip `:line` to bare token; never guess a wrong path                                                                             |
| Migration re-run                             | no `:line` spans remain → no-op                                                                                                   |

## Testing (TDD)

All via fixtures / real consumer tools.

**Lint (`citation_exists`)**

1. `` `path:symbol` `` where the symbol is defined → `check_path` passes.
2. `` `path:symbol` `` where the symbol is absent → `check_path` blocks with the symbol message.
3. Bare `` `path` `` unchanged; `resolve_cited_sources` returns clean bare paths for `path`, `path:symbol`, and `path:line` forms alike (grounding contract preserved).
4. `extract_citations` return shape (`{"paths","tests"}`, bare paths) is byte-identical to pre-change for existing inputs (shared-helper contract).

**Advisory rule (`citation_line_free`)** 5. A page with `` `path:line` `` yields a `warn` result; `lint_runner` exit code is **0** (warn does not fail). A page without any `:line` yields no findings.

**Fact-checker contract** 6. Contract-text assertion (mirrors `tests/orchestrator/test_page_author_contract.py`): `agents/fact-checker.md` contains the behavior-only / exclude-location-precision instruction, anchored on a load-bearing phrase.

**Page-author contract** 7. Contract-text assertion: `agents/page-author.md` forbids `` `path:line` `` and states the `path` / `path:symbol` convention.

**Migration** 8. Fixture page with a `.py` `:line` cite → produces the correct `:symbol`; a range cite → enclosing symbol of the start line; a non-`.py` `:line` cite → bare `path`; a bare-filename cite → resolved path + symbol when unique. After migration `citation_exists.check_path` passes on the output. A second migration run is a no-op (idempotent).

**Site content** 9. After running the migration over `docs/site-src`, `citation_exists.check_path` passes on all 21 touched pages, and no `` `path:line` `` span remains (grep assertion).

**Suite:** full `python3 -m pytest` green.

## Acceptance criteria

- **AC1** — extended `citation_exists` blocks a confabulated `:symbol`, passes a real `:symbol`, and `resolve_cited_sources` still returns clean bare paths for every citation form. _(change 2; tests 1–4)_
- **AC2** — a leftover `` `path:line` `` produces an advisory `warn`, never a run failure. _(change 3; test 5)_
- **AC3** — `agents/fact-checker.md` verifies behavior only and excludes citation-location precision. _(change 4; test 6)_
- **AC4** — `agents/page-author.md` forbids `` `path:line` `` and states the stable-citation convention. _(change 5; test 7)_
- **AC5** — all 96 existing pins are migrated to `:symbol`/bare, every touched page passes `citation_exists.check_path`, and the migration is idempotent. _(change 6; tests 8–9)_

## Out of scope

- `scripts/verify_citations.py` (capability C1, the `<!--pin:TOKEN-->` mechanism) — orthogonal, governs only pin-tokened pages, `info_only`; untouched.
- The CCE-101 auto-merge gate logic itself — unchanged; this fix removes the _warnings_ that were tripping it, not the gate.
- Rewriting page prose beyond citation tokens.
- Patching the on-main `orchestrator.md` stale anchors as a separate hotfix — the migration (change 6) supersedes it.
