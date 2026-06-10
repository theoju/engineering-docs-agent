# CCE-110: Factual-accuracy guard for page-author confabulation — design

**Date:** 2026-06-09
**Ticket:** [CCE-110](https://designitright.atlassian.net/browse/CCE-110) (Bug, High)
**Status:** approved design, pre-plan

## Problem

The `page-author` subagent confabulates architecture-lens content. On 2026-06-09
two pages from the nightly backlog run stated the exact opposite of tested
behavior and cited tests and files that do not exist:

- `orchestrator-state-advancement.md` claimed "no advance on partial," a
  sentinel file, and three named tests. Reality (CCE-62, pinned by
  `tests/orchestrator/test_state_advancement_invariant.py`): partial runs
  intentionally DO advance the baseline. None of the cited artifacts exist.
- `orchestrator-git-staging.md` claimed the runner avoids `git add -A` and
  cited a verifying test. Reality: the runner uses `git add -A .` on purpose
  and documents why the alternative was rejected. The cited test does not
  exist.

Pattern: both pages document deliberately counterintuitive invariants. The
author wrote the conventional-but-wrong version instead of grounding in
source. The pipeline validates structure (frontmatter, Tier-1 lint,
`mkdocs build --strict`) but never factual accuracy — confabulated pages pass
every existing gate.

## Goals

1. A page that cites nonexistent tests, files, or paths never ships.
2. A page whose prose contradicts the code it cites is flagged prominently to
   the operator.
3. The author is steered toward grounding in source before writing.
4. Generic-first: every layer degrades cleanly on hosts without git
   conveniences, without test suites, or on pages that cite nothing.

## Non-goals

- Verifying claims about external systems (other repos, vendor behavior).
- Bare-symbol citation checking (e.g. a backticked `partial_reasons`) — too
  false-positive-prone for V1; the incident pages are fully caught by the
  path and test-identifier classes.
- Auto-rewriting flagged pages. Detection and surfacing only.
- New config knobs. Tier-1 placement follows the existing
  `lint.tier1: default` switch; the no-citations skip bounds fact-checker
  cost. Add a kill-switch only if real cost data demands one.

## Architecture: three independent layers

Prevention → cheap deterministic detection → semantic detection. The
asymmetry is deliberate: only the judge that cannot be wrong gets kill-power.

| Layer                  | Surface                                     | Mode                             | On failure                                                                                               |
| ---------------------- | ------------------------------------------- | -------------------------------- | -------------------------------------------------------------------------------------------------------- |
| 1. Grounding           | `agents/page-author.md` contract            | prevention, advisory             | — (steering only)                                                                                        |
| 2. Citation existence  | `scripts/lint/citation_exists.py`, Tier-1   | deterministic, `severity: block` | existing Tier-1 block path: page excluded, `partial_reasons` entry                                       |
| 3. Contradiction check | new `agents/fact-checker.md` (8th subagent) | LLM, warn                        | "Factual-accuracy warnings" section in nightly PR body; never drops content, never marks the run partial |

This extends the declare-then-discharge / SDD fidelity-ladder doctrine
(CLAUDE.md) from orchestration into authored content: layer 2 is the
universal mechanical floor (pure git), layer 3 lights up only when inputs
exist, and the author's self-report (layer 1 evidence) is advisory because
self-reports are never trusted.

## Component 1 — citation existence rule (`scripts/lint/citation_exists.py`)

New Tier-1 lint rule, stdlib-only.

**Registration:** append `"citation_exists"` to `TIER1_DEFAULT` in
`scripts/lint/lint_runner.py`.

**CLI contract:** identical to sibling rules — `--config <path> --paths
<p...> --json`; exit 0 all-pass / 1 any-fail / 2 invocation error; output
`{"rule": "citation_exists", "severity": "block", "results": [{"path", "ok",
"message"}]}`. Severity is module-level (the runner only reads module-level
severity).

**Host root:** `git -C <config_dir> rev-parse --show-toplevel`. No layout
assumption beyond "the config file lives inside the host repo."

**Extraction (importable functions + thin CLI wrapper):**

- Operates on inline code spans in prose only. Fenced code blocks are
  stripped before scanning — fenced examples are legitimately hypothetical.
- Citation classes:
  - **Repo path:** token containing `/` and a dot-extension
    (`scripts/orchestrator_runner.py`, optional `:123` line suffix stripped
    before lookup). Verified against `git ls-files`.
  - **Test identifier:** `test_[a-z0-9_]+`. Verified via
    `git grep -lF "def <name>"`, falling back to `git grep -lF "<name>("`
    for non-Python hosts.
- **Skip guards (precision):** tokens containing `<`, `>`, `*`, `{`, `}`,
  `YYYY`, or `...`; tokens starting with `~` or `$`; URLs; absolute paths
  outside the repo (environment references, not repo citations).
- Failure messages name the offending token, e.g.
  `cites nonexistent test 'test_state_not_advanced_on_partial'`.

**Shared-helper contract:** the extraction functions are imported by the
orchestrator (Component 4 data flow). Per CLAUDE.md, any signature change
requires a repo-wide caller grep in the same change.

## Component 2 — fact-checker subagent

New `agents/fact-checker.md` + `agents/schemas/fact-checker.json` following
the existing agent conventions (canonical schema block in the .md, JSON
schema file, dataclass view in `scripts/contracts.py`).

- **Tools:** Read, Grep. **Model:** sonnet (matches siblings).
- **Inputs:** `page_path`, `cited_sources` (resolved repo paths produced by
  the Component-1 extractor — reused, not re-extracted), `lens`,
  `plugin_root`.
- **Job:** read the page and each cited source; for every checkable
  behavioral claim, verify the source supports it. The prompt explicitly
  states: _counterintuitive code wins over convention — if the code does
  something surprising, the page must say the surprising thing._
- **Output schema:**
  `{page, verdict: "consistent" | "contradiction" | "unverifiable",
findings: [{claim, source_path, evidence}], ok, error}`.
  Raw-JSON-only output instruction included (CCE-83 lesson); the orchestrator
  parses with a try/except sentinel fallback regardless.
- `unverifiable` is a clean skip, never a block.

## Component 3 — page-author grounding (contract edit only)

`agents/page-author.md`:

- New optional input `source_paths`: code files touched by the PRs being
  documented (derived from pr-summarizer output the orchestrator already
  holds).
- Procedure addition: read the relevant `source_paths` before composing;
  claims about behavior, invariants, or tests must come from what was read,
  not from convention; cite only files/tests confirmed to exist.
- Output gains optional `evidence: {files_read: [...]}` — advisory, recorded
  in the run record for forensics, never gated (a confabulating author would
  confabulate its evidence too; external layers 2–3 do the verifying).

## Data flow (orchestrator)

All inside the existing authoring loop in `scripts/orchestrator_runner.py`:

1. page-author dispatched with `source_paths`.
2. content-validator runs the lint suite; `citation_exists` rides Tier-1. A
   block failure follows the existing block path — page excluded, and the
   existing reason format applies:
   `lint_block: <page> citation_exists: cites nonexistent test '<token>'`.
   No new enforcement machinery, including no new reason format.
3. For each surviving page, the orchestrator imports the Component-1
   extractor; pages with ≥1 resolvable cited source get one fact-checker
   dispatch, others skip.
4. `contradiction` findings render as a "Factual-accuracy warnings" section
   in the nightly PR body (extending CCE-89 D1 enrichment) and land in the
   run record. They never drop a page and never mark the run partial.

## Degradation matrix

Never error, never emit empty artifacts:

| Condition                                        | Behavior                                                             |
| ------------------------------------------------ | -------------------------------------------------------------------- |
| `git rev-parse` fails (no git / not a repo)      | rule passes trivially with explanatory message; fact-checker skipped |
| Page cites nothing                               | rule passes; no fact-checker dispatch                                |
| Host has no test suite                           | only fails if a page cites tests — exactly the lie being caught      |
| fact-checker dispatch fails / unparseable output | logged as a note; warn layer never blocks                            |
| Dry-run mode                                     | fact-checker fixture-driven like the other seven agents              |

## Testing (pytest, TDD, fixtures represent arbitrary hosts)

- Extractor unit tests: path and test-identifier recognition, `:line` suffix
  stripping, placeholder/URL/fenced-block/absolute-path exclusion.
- Rule CLI tests against a tmp-git fixture host: existing citation passes;
  nonexistent test blocks; no-git passes trivially; exit codes 0/1/2.
- **Regression fixtures:** condensed replicas of the two real confabulated
  pages; the rule must fail both on their fabricated test names.
- `lint_runner` registration: `citation_exists` in `TIER1_DEFAULT` and
  returned by `enabled_rules` under `lint.tier1: default`.
- Orchestrator tests (monkeypatched dispatch): fact-checker called only for
  cited pages; warnings reach the PR body; a fact-checker crash does not
  block the run.
- Schema tests: `fact-checker.json` validates the contract examples; the
  optional `evidence` field on page-author output is accepted and optional.

## Provenance

- Incident: 2026-06-09 nightly backlog run; pages salvaged into PR #126,
  reverted via PR #127.
- Ground truth that exposed the confabulation:
  `tests/orchestrator/test_state_advancement_invariant.py` (CCE-62/CCE-40 §7).
- Doctrine: CLAUDE.md SDD fidelity-gate bullet (declare-then-discharge,
  trust nothing the subagent authors about its own work).
