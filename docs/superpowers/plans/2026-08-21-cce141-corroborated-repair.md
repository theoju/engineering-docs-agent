# CCE-141 Corroborated Repair Implementation Plan

> # ⛔ SUPERSEDED — DO NOT EXECUTE THIS PLAN
>
> Every unchecked step below builds a capability that **was deliberately
> deleted**. CCE-141 shipped as **detection only**: `citation_repair.diagnose`
> reports the tracked file a blocked citation was probably shortened from and
> stops. There is no `repair_text`, no `rewrite_token`, and no `Path.write_text`
> in the module — and there must never be one again.
>
> The rewrite was withdrawn after four adversarial review rounds produced four
> Criticals, each the same class in a new disguise: a repair moving a citation
> into a region `citation_exists` does not verify, so a BLOCK became a silent
> PASS and the page was never re-checked — against a measured production value
> of **zero firings** across the whole archived record.
>
> Authority: the design spec's Revision 3
> (`docs/superpowers/specs/2026-08-21-cce141-citation-path-repair-design.md`)
> and `CLAUDE.md`. This file is kept only as the record of what was tried.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make corroboration the entry condition for citation repair, so repair can never introduce a reference to a file the pipeline had not already accepted a reference to — and make every declined repair loud enough to act on.

**Architecture:** `repair_text` gains a required corroborator set and refuses any candidate outside it. The orchestrator builds that set from two sources the authoring agent did not write: a raw substring scan of the prior committed page (edits) and the batch's `grounding` set (every authoring). Declines are reported as non-`info_only` partials naming the refused candidate, and thread into the durable `skipped_prs` record.

**Tech Stack:** Python 3.11+, stdlib only, pytest.

**Spec:** `docs/superpowers/specs/2026-08-21-cce141-citation-path-repair-design.md` — **read "Revision 2" and the two corrected sections above it.** Revision 1's mechanism is superseded.

**Branch:** `feat/CCE-141-corroborated-repair`, based on `feat/CCE-141-citation-path-repair` at `5c72145`.

## Global Constraints

- Python stdlib only. No new dependencies.
- **The safety claim is set-invariance, not correctness.** Repair never introduces a reference to a file the pipeline had not already accepted a reference to; the set of files the finished page points at is invariant under repair, and only the spelling of an existing pointer changes. Do not restore the old "provably correct" language anywhere.
- **Corroborate the candidate path, never the cited token.** The cited token is what the agent wrote; the candidate is what we would rewrite it to. Only the candidate's provenance matters.
- **Import, never reimplement**, helpers from `scripts/lint/citation_exists.py`.
- **No default value for any corroborator parameter.** An un-threaded call site must fail loudly rather than silently reverting to unconditional repair. `citation_exists._resolves` documents this same precedent: "a block rule that has stopped blocking reports nothing."
- Run tests as: `PYTHONPATH=scripts .venv/bin/python -m pytest <path> -q` from the repo root.
- Suite baseline at branch point: **1484 passed / 4 skipped**.

---

### Task 1: Corroboration as a precondition in `repair_text`

**Files:**

- Modify: `scripts/citation_repair.py`
- Test: `tests/orchestrator/test_citation_repair.py`

**Interfaces:**

- Consumes: existing `suffix_candidates`, `rewrite_token`.
- Produces: `repair_text(text, repo_root, config, files, corroborators, prior_text=None) -> tuple[str, list[tuple[str,str]], list[tuple[str,str,str]]]`. Third element is `declines`: `(cited, candidate, reason)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestrator/test_citation_repair.py`:

```python
def test_uncorroborated_candidate_is_declined_not_repaired(repo):
    """THE CORE GUARD. A unique suffix match with no corroboration must NOT
    be repaired — uniqueness alone establishes nothing about whether the
    token was ever a shortening of anything."""
    text = "See `references/checklist.md`.\n"
    files = cr.tracked_files(repo)
    out, repairs, declines = cr.repair_text(text, repo, CFG, files, corroborators=set())
    assert repairs == []
    assert out == text
    assert declines == [
        (
            "references/checklist.md",
            ".claude/skills/connector-builder/references/checklist.md",
            "uncorroborated",
        )
    ]


def test_corroborated_candidate_is_repaired(repo):
    """The ADIS shape, once the candidate is corroborated."""
    full = ".claude/skills/connector-builder/references/checklist.md"
    text = "See `references/checklist.md`.\n"
    out, repairs, declines = cr.repair_text(
        text, repo, CFG, cr.tracked_files(repo), corroborators={full}
    )
    assert repairs == [("references/checklist.md", full)]
    assert declines == []
    assert full in out


def test_corroboration_matches_the_candidate_not_the_cited_token(repo):
    """Corroborating the TOKEN would be circular — the token is what the
    agent wrote. Only the candidate's provenance counts."""
    text = "See `references/checklist.md`.\n"
    out, repairs, declines = cr.repair_text(
        text, repo, CFG, cr.tracked_files(repo),
        corroborators={"references/checklist.md"},
    )
    assert repairs == []
    assert len(declines) == 1


def test_confabulated_path_that_uniquely_suffix_matches_is_declined(repo):
    """THE REGRESSION PROOF. This is the defect that produced Revision 2.

    Write it against the PRE-FIX code first and watch it FAIL: today a
    unique suffix match is repaired regardless of provenance, so a page
    citing an invented path is silently re-pointed at a real file and the
    lint block becomes a pass."""
    nested = repo / "tests/fixtures/setup_repos/js_docusaurus/.github/workflows"
    nested.mkdir(parents=True)
    (nested / "ci.yml").write_text("on: push\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixture")

    text = "The workflow lives at `.github/workflows/ci.yml`.\n"
    out, repairs, declines = cr.repair_text(
        text, repo, CFG, cr.tracked_files(repo), corroborators=set()
    )
    assert repairs == [], (
        "an invented path that happens to uniquely suffix-match a test "
        "fixture must never be repaired"
    )
    assert out == text


def test_ambiguous_candidate_is_declined_even_when_corroborated(repo):
    """Corroboration narrows; it does not resolve ambiguity. Two candidates
    still fail closed."""
    second = repo / "other/references"
    second.mkdir(parents=True)
    (second / "checklist.md").write_text("# other\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second")

    both = {
        ".claude/skills/connector-builder/references/checklist.md",
        "other/references/checklist.md",
    }
    text = "See `references/checklist.md`.\n"
    out, repairs, _ = cr.repair_text(
        text, repo, CFG, cr.tracked_files(repo), corroborators=both
    )
    assert repairs == []
    assert out == text


def test_corroborators_has_no_default(repo):
    """An un-threaded call site must fail loudly, never silently revert to
    unconditional repair."""
    import inspect

    sig = inspect.signature(cr.repair_text)
    assert sig.parameters["corroborators"].default is inspect.Parameter.empty
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest tests/orchestrator/test_citation_repair.py -q`
Expected: FAIL. `test_confabulated_path_that_uniquely_suffix_matches_is_declined` fails with `repairs == [('.github/workflows/ci.yml', 'tests/fixtures/.../ci.yml')]` — **that failure is the regression proof; record its exact output in your report.** The others fail on the missing `corroborators` parameter.

- [ ] **Step 3: Implement**

In `scripts/citation_repair.py`, change the signature and promote the filter:

```python
def repair_text(
    text: str,
    repo_root: Path,
    config: dict,
    files: set[str],
    corroborators: set[str],
    prior_text: str | None = None,
) -> tuple[str, list[tuple[str, str]], list[tuple[str, str, str]]]:
    """Repair shortened citations. Returns (new_text, repairs, declines).

    Corroboration is the ENTRY CONDITION, not an ambiguity tiebreak. A unique
    suffix match establishes only that the candidate exists — never that the
    cited token was a shortening of it, and the sole entry condition ("does
    not resolve") is exactly the confabulation population citation_exists
    exists to block. See the spec's "Why uniqueness is necessary but NOT
    sufficient".

    The invariant this delivers: repair never introduces a reference to a file
    the pipeline had not already accepted a reference to. The set of files the
    finished page points at is invariant under repair; only the spelling of an
    existing pointer changes.
    """
```

Keep the existing exclusion chain unchanged. After the `if len(candidates) != 1: continue` guard, add the precondition:

```python
        candidate = candidates[0]
        if candidate not in corroborators:
            # Match the CANDIDATE, never the cited token: the token is what the
            # agent wrote, so corroborating it would be circular.
            declines.append((cited, candidate, "uncorroborated"))
            continue
        repairs.append((cited, candidate))
```

Delete the old `prior_cited` narrowing block under `len(candidates) > 1` — corroboration now subsumes it, and ambiguity keeps failing closed via the existing `len(candidates) != 1` guard. Keep the `prior_text` parameter (Task 2 feeds it), but it no longer participates in candidate selection.

Rewrite the module docstring: remove the "provably `X`" proof and state the set-invariance invariant instead.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest tests/orchestrator/test_citation_repair.py -q`
Expected: the 6 new tests pass. **Pre-existing tests in this file will now fail** — they call `repair_text` with the old signature. Update their call sites to pass an explicit `corroborators=` set; do not add a default to make them pass. Tests that assert a repair fires need the candidate in the set; tests asserting no repair can pass `set()`.

- [ ] **Step 5: Commit**

```bash
git add scripts/citation_repair.py tests/orchestrator/test_citation_repair.py
git commit -m "feat(citation-repair): corroboration as the entry condition — CCE-141"
```

---

### Task 2: The corroborator ladder

**Files:**

- Modify: `scripts/citation_repair.py`
- Test: `tests/orchestrator/test_citation_repair.py`

**Interfaces:**

- Consumes: Task 1's `repair_text`.
- Produces: `build_corroborators(prior_text: str | None, source_paths: set[str], files: set[str]) -> set[str]`, exported in `__all__`.

- [ ] **Step 1: Write the failing tests**

```python
def test_rung1_raw_scan_sees_frontmatter_and_table_sites():
    """The ADIS incident cited the full path in frontmatter (line 6), prose
    (27) and a table (92). extract_citations sees only backticked spans in
    unfenced prose, so a rung built on it could miss the very evidence this
    ticket exists for. The scan must be raw."""
    full = ".claude/skills/connector-builder/references/checklist.md"
    prior = (
        "---\n"
        f"sources:\n  - {full}\n"
        "---\n\n"
        f"| step | ref |\n| --- | --- |\n| 1 | {full} |\n"
    )
    got = cr.build_corroborators(prior, set(), {full})
    assert full in got


def test_rung1_only_admits_tracked_paths():
    """A raw scan must not admit arbitrary strings from the prior page."""
    prior = "See totally/invented/thing.md for details.\n"
    assert cr.build_corroborators(prior, set(), {"real/file.md"}) == set()


def test_rung2_admits_the_batch_source_set():
    got = cr.build_corroborators(None, {"a/b/c.md"}, {"a/b/c.md"})
    assert got == {"a/b/c.md"}


def test_rung2_excludes_glob_entries():
    """Manifest source_files carry globs (core/**). Expanding them would make
    the gate ceremony while the diff still reads `if candidate in corroborated`."""
    got = cr.build_corroborators(None, {"core/**", "docs/superpowers/**"}, {"core/x.md"})
    assert got == set()


def test_no_prior_and_no_sources_corroborates_nothing():
    assert cr.build_corroborators(None, set(), {"a/b.md"}) == set()
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest tests/orchestrator/test_citation_repair.py -q -k corroborators`
Expected: FAIL — `build_corroborators` does not exist.

- [ ] **Step 3: Implement**

```python
_GLOB_CHARS = ("*", "?", "[", "{")


def build_corroborators(
    prior_text: str | None, source_paths: set[str], files: set[str]
) -> set[str]:
    """Tracked paths corroborated by a source the authoring agent did not write.

    Rung 1 (edits, git-authoritative): a RAW substring scan of the prior
    committed page. Deliberately not extract_citations — that reads only
    backticked spans in unfenced prose and on this repo's 108-page corpus sees
    69.9% of path tokens, missing frontmatter-only and link-target-only ones.
    A raw scan does not violate the imported-never-reimplemented contract: it
    is not deciding what a citation IS, only whether a known-tracked path was
    already present.

    Rung 2 (every authoring, orchestrator-authoritative): the batch's source
    set. On a create _enforce_agent_frontmatter writes this into the page's own
    source_files, OVERWRITING the agent — so every action has a corroborator
    the agent did not author. Glob entries are excluded: expanding them would
    make the gate ceremony.

    evidence.files_read is deliberately NOT a source — an author that
    confabulates a citation can equally confabulate a files_read entry.
    """
    out = {p for p in source_paths if p in files and not any(c in p for c in _GLOB_CHARS)}
    if prior_text:
        out |= {f for f in files if f in prior_text}
    return out
```

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest tests/orchestrator/test_citation_repair.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/citation_repair.py tests/orchestrator/test_citation_repair.py
git commit -m "feat(citation-repair): corroborator ladder with raw prior-page scan — CCE-141"
```

---

### Task 3: Thread `grounding`, report declines loudly, fix the UTF-8 crash

**Files:**

- Modify: `scripts/orchestrator_runner.py`
- Test: `tests/orchestrator/test_citation_repair_wiring.py`

**Interfaces:**

- Consumes: `build_corroborators`, the 3-tuple `repair_text`.
- Produces: `_repair_citation_paths(path, repo_root, config, state, source_paths)` — `source_paths` required, no default.

- [ ] **Step 1: Write the failing tests**

```python
def test_uncorroborated_repair_is_declined_and_reported_loudly(repo):
    """A silent decline reproduces the CCE-141 harm in a narrower band:
    block -> deferral -> forgiveness -> page never written."""
    page = repo / "page.md"
    page.write_text("See `references/checklist.md`.\n")
    state = _state()

    runner._repair_citation_paths(page, repo, {}, state, source_paths=set())

    assert page.read_text() == "See `references/checklist.md`.\n"
    cr_ = state["current_run"]
    assert any("citation_repair_declined" in r for r in cr_["partial_reasons"])
    assert cr_["partial"] is True, (
        "a decline must NOT be info_only — it means a page did not ship"
    )


def test_corroborated_repair_fires_and_stays_info_only(repo):
    full = ".claude/skills/connector-builder/references/checklist.md"
    page = repo / "page.md"
    page.write_text("See `references/checklist.md`.\n")
    state = _state()

    runner._repair_citation_paths(page, repo, {}, state, source_paths={full})

    assert full in page.read_text()
    assert state["current_run"]["partial"] is False
    assert any("citation_path_repaired" in r for r in state["current_run"]["partial_reasons"])


def test_prior_page_text_survives_a_non_utf8_page_at_head(repo):
    """A single non-UTF-8 byte in a committed page must not take down the run.
    Under corroborated repair this is on the hot path for every edit."""
    page = repo / "page.md"
    page.write_bytes(b"# Caf\xe9\n\nSee `references/checklist.md`.\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "latin1")
    page.write_text("# Cafe\n\nSee `references/checklist.md`.\n")

    got = runner._prior_page_text(repo, page)  # must not raise
    assert got is None or isinstance(got, str)


def test_source_paths_has_no_default():
    import inspect

    sig = inspect.signature(runner._repair_citation_paths)
    assert sig.parameters["source_paths"].default is inspect.Parameter.empty
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest tests/orchestrator/test_citation_repair_wiring.py -q`
Expected: FAIL. The UTF-8 test raises `UnicodeDecodeError` — capture that traceback in your report, it is the reproduction.

- [ ] **Step 3: Implement**

Fix `_prior_page_text` (around line 1566) — drop `text=True`, decode defensively:

```python
    r = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"HEAD:{rel}"],
        capture_output=True,
    )
    if r.returncode != 0:
        return None
    # errors="replace", not text=True: git show's stdout is decoded with the
    # locale codec under text=True, so one non-UTF-8 byte in a committed page
    # raises out of subprocess.run itself — outside the caller's try — and
    # takes down the whole run. Under corroborated repair this is on the hot
    # path for every edit.
    return r.stdout.decode("utf-8", errors="replace")
```

Update `_repair_citation_paths` to require `source_paths`, build the corroborator set, and report both outcomes:

```python
    corroborators = citation_repair.build_corroborators(
        _prior_page_text(repo_root, path), source_paths, files
    )
    new_text, repairs, declines = citation_repair.repair_text(
        text, repo_root, config, files, corroborators
    )
    for old, new, why in declines:
        # NOT info_only: a decline means the page does not ship. Silent here
        # reproduces exactly the CCE-141 harm this feature exists to fix.
        add_partial(
            state,
            f"citation_repair_declined: {label}: '{old}' -> candidate '{new}' ({why})",
        )
    if not repairs:
        return
    path.write_text(new_text)
    ...
```

At the call site (around line 2440), pass the already-computed `grounding`:

```python
                    _repair_citation_paths(
                        target_path, repo_root, config, state, source_paths=grounding
                    )
```

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest tests/orchestrator/ -q`
Then the full suite. `test_classification_coverage.py`'s census needs a bump for the new `add_partial` site — follow that file's existing convention (count, plus a rationale comment in the `N -> N+1:` format), and classify the decline as **not** `info_only` with the reason.

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/
git commit -m "feat(orchestrator): thread grounding into repair, report declines, fix git show decode — CCE-141"
```

---

### Task 4: `reason` on the durable skip record

**Files:**

- Modify: `scripts/state_io.py`, `templates/state.schema.json`
- Test: the existing skip-record test module

**Interfaces:**

- Consumes: the decline strings from Task 3.
- Produces: `skipped_prs` records carry an optional `reason` string.

CCE-151 already made forgiveness durable and loud. The narrow remainder: the record carries `{pr, url, pages, deferrals, skipped_at}` and no cause. The graveyard says what was lost, never why.

- [ ] **Step 1** Find `merge_skipped_pr_records` and its schema entry. Write a test asserting a `reason` threaded in is preserved on the record, and that a record without one still validates (the field is optional — do not break existing records).
- [ ] **Step 2** Run it, watch it fail.
- [ ] **Step 3** Add the field to the schema and thread the string through. Keep it optional.
- [ ] **Step 4** Full suite.
- [ ] **Step 5** Commit: `feat(state): record why a PR was forgiven — CCE-141`

---

### Task 5: Replace the strictness guard that never guarded

**Files:**

- Modify: `tests/orchestrator/test_citation_repair.py`

`test_confabulated_path_is_left_alone` uses `docs/invented-by-the-model.md` — a token that suffix-matches nothing, so it passes identically before and after any change. It is labelled "STRICTNESS GUARD" and it has never tested anything. It already survived commit `bde832f`, titled "make exclusion tests discriminating."

- [ ] **Step 1** Replace it with a token drawn from the confabulator's own vocabulary that **uniquely suffix-matches a real tracked file** (Task 1's `.github/workflows/ci.yml` case is the model). Keep the name and strengthen the docstring to say why the old fixture was inert.
- [ ] **Step 2** Add the **residual test** — an invented path that uniquely suffix-matches a real file _and_ sits in the corroborator set. Assert it **is** repaired, and label it as documenting the accepted residual:

```python
def test_corroborated_invention_is_still_repaired_this_is_the_residual(repo):
    """UNCOMFORTABLE BY DESIGN. Corroboration narrows the confabulation
    surface by ~2 orders of magnitude; it does not close it. ~56% of a real
    batch's source set still exposes a unique non-resolving suffix, and that
    set IS the author's prompt input. This test exists so the residual is
    visible in the suite rather than discovered in production."""
```

- [ ] **Step 3** Confirm the four exclusion tests (exempt, `example/`, gitignored, `_relativize`) pass **verbatim, untouched**. If any needs editing, stop and report — that means Task 1 changed behavior it should not have.
- [ ] **Step 4** Full suite.
- [ ] **Step 5** Commit: `test(citation-repair): a strictness guard that actually discriminates — CCE-141`

---

### Task 6: Correct the record

**Files:**

- Modify: `CLAUDE.md`

`CLAUDE.md:77` states the false proof and cites near-zero ambiguity as evidence of safety. It is the most durable artifact of this work.

- [ ] **Step 1** Rewrite item (2) of the CCE-141 bullet. It must: delete "provably correct"; state that uniqueness is necessary but not sufficient; **invert** the ambiguity reading — near-zero ambiguity is evidence the filter is _inert_, measured 2109 unique-match non-resolving tail tokens against 886 tracked files, so the set of invented strings that flip block→pass is larger than the repository; name the reproduced counterexample (`.github/workflows/ci.yml` → a Docusaurus test fixture); state the shipped design (corroboration as entry condition, the two sources, raw scan not `extract_citations`); and state the measured cost (~38% coverage lost, ~56% residual, zero firings against the production record).
- [ ] **Step 2** Verify: `PYTHONPATH=scripts .venv/bin/python -m pytest -q -k "claude_md or CLAUDE"` → 4 passed.
- [ ] **Step 3** Full suite.
- [ ] **Step 4** Commit: `docs(claude-md): correct the CCE-141 safety claim — CCE-141`

---

## Verification

- [ ] **Real-consumer check, four arms.** Extend the Revision 1 verification script. Through `lint_runner.py`, confirm: (a) an **uncorroborated** shortened citation is declined and still **blocks**; (b) a **corroborated** one is repaired and reports `ok`; (c) the `.github/workflows/ci.yml` confabulation is declined and still blocks; (d) the same page **unrepaired** blocks — the baseline arm that proves the rule is live on the page rather than skipping it. Without (d), a green (b) is indistinguishable from the linter not running.

- [ ] **Open the PR** with `--body-file` (never a heredoc containing patterns `block-destructive.sh` scans for).

## Notes for the executor

- **Do not restore the old proof language.** If a docstring or comment reads "provably correct," it is wrong.
- **Do not widen corroboration to `evidence.files_read`.** An author that confabulates a citation can confabulate a files_read entry. The spec excludes it deliberately.
- **Rung 3 (same-page self-corroboration) is not in this plan.** It is agent-written and rests on bounded-harm rather than an airtight argument. Ship rungs 1, 2 and 4 only.
- **Expect the coverage loss to look alarming in tests.** Pages blocking for want of corroboration is the design working. The decline partial is what makes it acceptable — verify it fires before concluding a test is wrong.
- If a test seems to require adding a default to `corroborators` or `source_paths`, stop. That defeats the entire change.
