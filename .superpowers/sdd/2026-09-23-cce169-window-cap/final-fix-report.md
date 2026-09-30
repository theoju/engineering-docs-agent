# CCE-169 — final whole-branch review, fix round

Branch `feat/CCE-169-window-cap`, worktree `/Users/theo/Projects/eda-cce181`.
Start HEAD `9d5e381`, end HEAD `138b25e`. Four new commits, one item needed none.

| item                                 | commit                 | status                                            |
| ------------------------------------ | ---------------------- | ------------------------------------------------- |
| 1. unanchored PR stranded by the cap | `00b0647`              | fixed, red→green proven                           |
| 2. tests cannot see admission        | `148227b`              | fixed, mutation-proven                            |
| 3. `> 0` guard's false justification | `233d0a1`              | fixed, claim verified first                       |
| 4. `run.window_pr_cap` undocumented  | `138b25e`              | fixed on 3 of 4 named surfaces — see disagreement |
| 5. delete `negcap_test.py`           | (untracked; no commit) | deleted                                           |

**Suite: 1639 passed / 4 skipped → 1643 passed / 4 skipped.** +4 tests, skips unchanged.

---

## Item 1 — a capped PR with no `merge_sha` is stranded permanently

### The regression, confirmed against the tree (not the brief)

Every claim in the brief was re-derived by content, not by line number:

- `_order_prs_oldest_first` builds `order` from `git rev-list --reverse`, sets
  `big = len(order) + 1`, and keys a PR by `order.get(sha[:7], big)`. A PR with a
  missing or blank `merge_sha` gets `big` and sorts **last**.
- The cut takes the tail (`prs[_window_cap:]`). So whenever the cap fires, an
  unanchored PR is **guaranteed** to be in the capped slice. Structural, not
  coincidental.
- `held_back` is built from `set(deferred_pages_by_pr) | {admission_deferred numbers}
| {window_capped numbers}`. `_deferred_all` is built from
  `list(admission_deferred) + [pr_by_number[n] for n in sorted(deferred_pages_by_pr)]`
  — capped PRs reach **neither** writer, so `still_deferred` is empty of them.
- The guard `elif any(not (p.get("merge_sha") or "").strip() for p in still_deferred)`
  therefore never sees a capped unanchored PR.
- `advance_cursor_list(prs, admission_deferred, held_back=held_back)` walks
  `admitted + deferred_tail`. A capped PR is in neither list, so the walk never
  breaks on it, yields a cursor, and sets `advance_cursor_backed=True`.
- `_clip_prs_to_window` records `merge_sha_missing: PR #n`, `degraded=True`, and
  **keeps** the PR; `merge_sha` is not in `required` in
  `agents/schemas/source_collector.schema.json`. Both confirmed.

Net: the baseline advances past the unanchored PR's real merge commit, the next
window is `cursor..HEAD`, and that PR is never returned again. rc 0, auto-merged.

### Fix — Option B, as ruled

At the cut, PRs with a blank/missing `merge_sha` are pulled out of the capped
tail and admitted. The predicate is `not (p.get("merge_sha") or "").strip()` —
byte-identical to the `_no_advance_unanchored_deferred` guard it was bypassing,
so the two stay in lockstep.

```python
if _window_cap > 0 and len(prs) > _window_cap:
    _tail = prs[_window_cap:]
    # The cap may only hold back a PR a LATER WINDOW CAN RE-ANCHOR. ...
    window_capped = [p for p in _tail if (p.get("merge_sha") or "").strip()]
    prs = prs[:_window_cap] + [
        p for p in _tail if not (p.get("merge_sha") or "").strip()
    ]
```

Comment at the cut states the invariant ("the cap may only hold back a PR a later
window can re-anchor"), nine lines, not a retelling of the brief.

Routing table unchanged: rows 2 and 3 still exclude whatever remains in
`window_capped`; row 1 still includes it. The reason string's total,
`len(prs) + len(window_capped)`, is still the full window because the exempted
PRs moved into `prs`. `_MERGE_VETO_REASON_PREFIXES` untouched.

Rejected A and D were not reopened.

### Test evidence — red before, green after

New tests: `test_an_unanchored_pr_is_never_capped` (3 PRs, cap 2, PR 2 merged at
c2 and returned with no `merge_sha`) and
`test_the_cap_still_holds_back_an_anchored_pr_beside_an_unanchored_one` (cap 1,
so the tail holds both an anchored and an unanchored PR — proves the exemption is
not a disabled cap).

The primary assertion states the **harm**, not the mechanism: a PR the run did not
admit must still be inside the window the next run reads.

**BEFORE the change** (`pytest tests/orchestrator/test_window_cap.py -q`):

```
E       AssertionError: PR 2 merged at ee5d0a2b and was neither admitted nor left in the next window (d930610d..HEAD): it is outside every future window and is permanently undocumented. admitted=['1', '3'] capped=['2'] held_back=['2']
E       assert ('2' in ['1', '3'] or 'ee5d0a2b3a00192aea0f30cad97b85da0abdc996' in {'0f7fdbb9ab04d775986fb69a0776772bc1e4cbaf'})

tests/orchestrator/test_window_cap.py:352: AssertionError
...
E       AssertionError: {'admitted': ['1'], 'capped': ['3', '2'], 'deferred': [], 'held_back': ['2', '3'], ...}
E       assert ['1'] == ['1', '2']

=========================== short test summary info ============================
FAILED tests/orchestrator/test_window_cap.py::test_an_unanchored_pr_is_never_capped
FAILED tests/orchestrator/test_window_cap.py::test_the_cap_still_holds_back_an_anchored_pr_beside_an_unanchored_one
2 failed, 10 passed in 12.80s
```

`d930610d` is c3 and `ee5d0a2b` is c2: the baseline advanced to c3 while PR 2's
merge point c2 sits behind it, and the next window contains only c4. That is the
regression, printed by the test.

**AFTER the change**:

```
............                                                             [100%]
12 passed in 12.39s
```

Then `pytest tests/orchestrator -q` → `685 passed in 150.35s`.

### Accepted cost

The work bound is `cap + (number of unanchored PRs)` rather than exactly `cap`.
Bounded. `merge_sha_missing` appears in none of the 41 archived production PRs
under `.engineering-docs-agent/stale-prs-archive/`.

Degenerate case, recorded deliberately: if every PR in an over-cap window is
unanchored, the cap is fully inert for that run. That is the safe direction — the
alternative is stranding all of them.

---

## Item 2 — the tests could not distinguish a pre-admission cap from a post-admission one

### What was added

`_cursor_line(capsys)` parses the CCE-175 observability line
(`cursor: admitted=[...] deferred=[...] capped=[...] held_back=[...] skipped=[...]`)
into its five PR-number lists. The line was already emitted on every run and
nothing read it.

`test_a_capped_run_advances_to_the_cap_boundary_and_says_so` now asserts:

```python
cur = _cursor_line(capsys)
assert cur["admitted"] == ["1", "2"], cur
assert cur["capped"] == ["3"], cur
```

Parsed rather than substring-matched, so a test names the set it expects rather
than a rendering of it.

### Falsifiability — the mutation

Applied to a full scratch copy of the tree at
`<scratchpad>/mutant-v1` (tar copy excluding `.git`): save the pre-cut total,
compute `window_capped` as before, **do not truncate `prs`**, keep `window_prs`
free of capped PRs, render the reason from the saved total.

```python
_pre_cut_total = len(prs)  # MUTATION: saved pre-cut total
if _window_cap > 0 and len(prs) > _window_cap:
    _tail = prs[_window_cap:]
    window_capped = [p for p in _tail if (p.get("merge_sha") or "").strip()]
    # MUTATION: `prs` is NOT truncated -- a POST-admission cap.
...
    f"{_pre_cut_total} PRs held for a later run "
...
_mut_capped_numbers = {p.get("number") for p in window_capped}
window_prs = [p for p in prs if p.get("number") not in _mut_capped_numbers]
```

**Mutant, window-cap file:**

```
>       assert cur["admitted"] == ["1", "2"], cur
E       AssertionError: {'admitted': ['1', '2', '3'], 'capped': ['3'], 'deferred': [], 'held_back': ['3'], ...}
E       assert ['1', '2', '3'] == ['1', '2']
E         Left contains one more item: '3'
...
=========================== short test summary info ============================
FAILED tests/orchestrator/test_window_cap.py::test_a_capped_run_advances_to_the_cap_boundary_and_says_so
FAILED tests/orchestrator/test_window_cap.py::test_the_cap_still_holds_back_an_anchored_pr_beside_an_unanchored_one
2 failed, 10 passed in 10.84s
```

**Mutant, full suite** (run to confirm nothing _else_ catches it):

```
FAILED tests/lint/test_site_citations_line_free.py::test_migration_introduces_no_symbol_failures
FAILED tests/orchestrator/test_window_cap.py::test_a_capped_run_advances_to_the_cap_boundary_and_says_so
FAILED tests/orchestrator/test_window_cap.py::test_the_cap_still_holds_back_an_anchored_pr_beside_an_unanchored_one
3 failed, 1638 passed, 4 skipped in 276.50s (0:04:36)
```

The `test_site_citations_line_free` failure is a **copy artifact, not the
mutation**: the scratch copy has no `.git`, so
`citation_exists.repo_root_for(...)` returns `None` and the test dies on
`TypeError: unsupported operand type(s) for /: 'NoneType' and 'str'` at
`tests/lint/test_site_citations_line_free.py:38`. The same test passes in the
real tree (`2 passed in 4.62s`). So the mutation is caught by **exactly** the two
new admission assertions and by nothing else — which is the brief's finding
reproduced, then closed.

**Unmutated tree, same file:** `12 passed in 12.39s`. Reverted by discarding the
scratch copy; the real tree was never mutated.

---

## Item 3 — the `> 0` guard's justification was false

### Verified before editing

- `templates/config.schema.json` → `properties.run.properties.window_pr_cap` is
  `{"type": "integer", "minimum": 0}`. Confirmed by reading the parsed node.
- `run()` (`scripts/orchestrator_runner.py`) loads via
  `config = load_config_validated(cfg_path)` inside a `try`, and
  `except ConfigError: emit_log(...); return 2` — **before** the cut.
- `load_config_validated` (`scripts/state_io.py`) calls
  `jsonschema.validate(raw, schema)` against that file.
- Direct measurement, validating the shared test host config with each value:

```
window_pr_cap: -1 -> schema REJECTS at $.run.window_pr_cap: -1 is less than the minimum of 0
window_pr_cap: 0  -> schema ACCEPTS
window_pr_cap: 10 -> schema ACCEPTS
```

So no host can reach the cut with a negative cap. The brief's claim is correct
and the eight-line comment was false.

### What changed

The guard stays (it is real defence-in-depth for direct callers of the raw dict,
the unit tests among them). The justification drops from eight lines to six and
now says what is true: negative is truthy and would invert the slices; no host
can get here with one, because the schema sets `minimum: 0` and
`load_config_validated` exits 2 first.

Two unit tests keep the corrected prose honest, both at resolver/schema level and
neither end-to-end (an end-to-end negative-cap test would assert an unreachable
state, as instructed):

- `test_window_cap_resolver_does_not_clamp_a_negative` — pins
  `resolve_window_cap({"run": {"window_pr_cap": -1}}) == -1`, i.e. pins **where**
  the responsibility sits rather than asserting a clamp the resolver does not have.
- `test_the_schema_is_what_rejects_a_negative_cap` — pins `type: integer` and
  `minimum: 0`. Drop `minimum` and the new comment silently becomes false while
  the negative path becomes reachable again; this is the test that notices.

`pytest tests/orchestrator/test_window_cap.py -q` → `14 passed in 10.95s`.

---

## Item 4 — `run.window_pr_cap` was invisible to operators

### Measurement first

Presence of the five `run.*` keys, per surface:

| surface                                                  | `time_budget_seconds` | `reuse_pr_summaries` | `deferral_skip_threshold` | `authoring_hard_cap_seconds` | `window_pr_cap` |
| -------------------------------------------------------- | --------------------- | -------------------- | ------------------------- | ---------------------------- | --------------- |
| `README.md`                                              | yes                   | yes                  | yes                       | yes                          | **no**          |
| `CHANGELOG.md`                                           | yes                   | yes                  | yes                       | yes                          | **no**          |
| `docs/site-src/architecture/orchestrator.md`             | yes                   | yes                  | **no**                    | yes                          | **no**          |
| `.engineering-docs-agent/config.yml` (dogfood)           | yes                   | no                   | no                        | prose only                   | **no**          |
| `templates/hosts/advanced-data-import-system.config.yml` | no                    | no                   | no                        | no                           | no              |
| `skills/engineering-docs-agent-setup/SKILL.md`           | no                    | no                   | no                        | no                           | no              |
| `templates/config.schema.json`                           | yes                   | yes                  | yes                       | yes                          | **yes**         |

None of the docs surfaces is generated — no generator writes
`docs/site-src/architecture/`; `mkdocs.yml` and `gen_ref_pages.py` do not touch
it. Checked before editing, as instructed. (Generated contract docs under
`docs/site-src/api/contracts/` are a separate, untouched surface.)

### What changed

- **`README.md`** — one paragraph in `### Nightly authoring run`, between the
  CCE-159 PR-summary-cache paragraph and the time-budget paragraph, in the same
  `**Lead-in (CCE-nnn).**` format. Leads with the default-ON warning.
- **`CHANGELOG.md`** — `### Changed`, above CCE-101, as
  `**Behavior change (CCE-169):**` with the same hard wrap. CCE-101 is the only
  other default-ON behaviour change in the file and that is the format it uses;
  `### Fixed` (where the prose entries live) would have buried a change every
  existing host receives silently.
- **`docs/site-src/architecture/orchestrator.md`** — a new
  `## Pre-admission window cap` section immediately before `## Soft time budget`,
  which is execution order. Covers the resolver and default, the default-ON
  rationale, the three-row routing table with the reason each row holds, the
  `degraded=True` classification, why the reason is a plain literal rather than
  routed through the `time_budget`/`held_back` selector, why a capped run still
  auto-merges, and the unanchored-PR exemption from item 1.

### Verified with the consumer tools, not `test -f`

- Tier-1 lint over the edited page:
  `python3 scripts/lint/lint_runner.py --config .engineering-docs-agent/config.yml
--paths docs/site-src/architecture/orchestrator.md --json`
  → `rules run: 11 failures: 0`, exit 0. Every new `path.py:symbol` citation
  (`resolve_window_cap`, `DEFAULT_WINDOW_PR_CAP`, `advance_cursor_list`,
  `next_deferral_counts`, `partition_deferrals`, `_order_prs_oldest_first`)
  resolves under `citation_exists`.
- `mkdocs build --strict` → `Documentation built in 3.41 seconds`, exit 0.

### Disagreement with the brief — recorded, not implemented around

The brief says the key is absent from "the scaffolded config … while all four
sibling `run.*` keys are documented". Two parts of that do not hold:

1. **There is no scaffolded config carrying a `run:` block.**
   `templates/hosts/advanced-data-import-system.config.yml` has no `run:` key at
   all (top-level keys: `docs`, `sources`, `voice`, `lint`, `publishing`,
   `notifications`), and `skills/engineering-docs-agent-setup/SKILL.md` contains
   no config YAML — step 6 instructs the agent to write `config.yml` without a
   template. The only file with a `run:` block is the dogfood
   `.engineering-docs-agent/config.yml`, which sets `time_budget_seconds: 2100`
   and nothing else; two of the four siblings are absent from it too.
   I did **not** invent a surface there. Adding `window_pr_cap: 10` to the
   dogfood config would be _setting_ a knob to its own default, not documenting
   it, and the surrounding comment block is time-budget arithmetic that a cap
   paragraph would not match.
2. **`deferral_skip_threshold` is absent from the published orchestrator page**,
   so "all four siblings" is 3/4 there. Immaterial to the action taken (the page
   documents the majority of the family and is the right home), but the premise
   as stated is not accurate.

Everything else in item 4 held: the key genuinely was absent from README,
CHANGELOG and the published page, and it genuinely is a default-ON behaviour
change.

---

## Item 5 — `tests/orchestrator/negcap_test.py`

Deleted. It was untracked, so there is no commit; `git status` is clean of it.
Confirmed harmless to the counts: `pyproject.toml` sets
`python_files = ["test_*.py"]`, so it was never collected — the baseline of 1639
was measured with the file still present and the file's removal changed nothing.

---

## Suite counts

| point                            | passed   | skipped |
| -------------------------------- | -------- | ------- |
| baseline (`9d5e381`)             | 1639     | 4       |
| after all four items (`138b25e`) | **1643** | **4**   |

`1643 passed, 4 skipped in 261.71s`. +4 = 2 (item 1) + 2 (item 3). Item 2 added
assertions to an existing test, not a new test. **Skip count unchanged** — no
test was skipped to make the suite pass.

Intermediate greens: `tests/orchestrator/test_window_cap.py` 12 passed after item
1, 14 passed after item 3; `tests/orchestrator` 685 passed after item 1.

## Constraints check

- `_MERGE_VETO_REASON_PREFIXES` — untouched, still `("app_token_unavailable",)`.
- Reason string — unchanged literal
  `held_back_window_capped: {held} of {total} PRs held for a later run (cap {cap})`,
  not routed through `_rsn`, still `degraded=True`. Pinned verbatim by two tests
  (cap 2 → "1 of 3 … (cap 2)", cap 1 → "1 of 3 … (cap 1)").
- Routing rows 2 and 3 — unchanged; row 1 still includes everything still capped.
- stdlib only; no new runtime deps (`re` added to a test module).
- Branch `feat/CCE-169-window-cap` throughout. No merge, no push, no PR.
- Every commit subject carries `CCE-169`; every message ends with the
  `Co-Authored-By: Claude Opus 5 (1M context)` trailer.

## Concerns

1. **The exemption's blast radius is the whole capped tail when nothing is
   anchorable.** If every PR in an over-cap window lacks a `merge_sha` — e.g.
   `_order_prs_oldest_first` bailing out because git is unavailable, which also
   makes `_clip_prs_to_window` skip and returns everything unsorted — the cap is
   inert for that run and the unbounded-work property is gone for it. It is the
   safe direction (the alternative strands the lot), it is visible via the
   `cursor:` line, and no archived production PR exhibits `merge_sha_missing`,
   but it is not bounded by `cap`.
2. **The `cursor:` line is now load-bearing for tests.** Two assertions parse a
   free-text observability string that nothing else consumes. `_cursor_line`
   fails loudly if the prefix or a `field=[...]` token drifts, so a rename breaks
   the tests rather than silently passing — but the line is still prose, and
   `citation_exists` cannot protect it. A structured `current_run.admitted_prs`
   key would be the durable version; out of scope here.
3. **Item 4 surface gap left open deliberately.** `deferral_skip_threshold` is
   still undocumented on the published orchestrator page, and no config template
   or the setup skill documents any `run.*` key. Both predate this branch.
