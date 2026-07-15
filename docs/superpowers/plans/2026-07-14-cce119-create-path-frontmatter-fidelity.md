# CCE-119 Create-Path Frontmatter Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the orchestrator's deterministic `agent_fields` the sole authority for an agent-authored create's frontmatter on both the dry-run and production dispatch paths, and source the description's `min_words` floor from the host's resolved lint config instead of a duplicated constant.

**Architecture:** Two independent hardening items on the incremental authoring **create** path. Item B resolves `description_quality.min_words` once from config and threads it into `_synthesize_agent_description` (deleting the duplicated `_DESC_MIN_WORDS`). Item A adds a `_enforce_agent_frontmatter` reconciliation step that runs after the page-author returns `ok` — it overwrites the written page's frontmatter with `agent_authored_frontmatter_text(**agent_fields)`, preserving the body — and decouples `agent_fields` from the `doc_kind` mutation so the production call can't hit a latent `TypeError`.

**Tech Stack:** Python 3 (stdlib-first), pytest, fixture-driven dry-run path (production CLI dispatch monkeypatched). Verification uses the real lint consumers (`frontmatter_schema.check_path`, `description_quality.check_path` / `check_fm`), never `test -f`.

**Branch:** `fix/CCE-119-create-path-frontmatter-fidelity` (off main; spec committed `eb049bc`).

**Spec:** `docs/superpowers/specs/2026-07-14-cce119-create-path-frontmatter-fidelity-design.md`

**Key existing surfaces (verified):**

- `scripts/orchestrator_runner.py:979` — `_DESC_MIN_WORDS = 6` (to delete).
- `scripts/orchestrator_runner.py:982` — `_synthesize_agent_description(summaries, *, hint)` (add `min_words`).
- `scripts/orchestrator_runner.py:1543-1596` — the agent-authored create callsite, dispatch, dry-run synth, ok-branch.
- `scripts/orchestrator_runner.py:1560-1562` — `_dk` / `fm_template["doc_kind"] = _dk` (mutates `agent_fields` today because `fm_template = agent_fields`, line 1550).
- `scripts/orchestrator_runner.py:65` — `_PLUGIN_ROOT`; `sys` already imported; `import frontmatter_contract as fmc` is **local** to functions (966/1469/2067).
- `scripts/lint/description_quality.py:36` — `_resolve_config(config)`; `:51` — `check_fm(fm, *, title, config)`; `:29` — `_DEFAULTS`.
- `scripts/frontmatter_contract.py:117` — `agent_authored_frontmatter_text(*, description, source_files, last_reviewed, status="draft")` (does **not** accept `doc_kind`).
- `scripts/archive_indexes.py:56` — `parse_frontmatter(text)` uses `text.split("---", 2)`; the reconciliation stripper mirrors this exact fence convention.
- Tests: `tests/orchestrator/test_synthesize_description.py` (8 calls to update), `tests/orchestrator/test_agent_authored_create_frontmatter.py` (module constants `FAKES`, `CONFIG_AGENT_AUTHORED`, `_SEED_STATE`, `init_host` fixture — reuse them), `tests/lint/test_description_quality.py`.

---

## Task 1: `resolve_min_words` public resolver (Item B, part 1)

**Files:**

- Modify: `scripts/lint/description_quality.py` (add function after `_resolve_config`, ~line 49)
- Test: `tests/lint/test_description_quality.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/lint/test_description_quality.py` (match the file's existing import of `description_quality`; it already puts `scripts/lint` on `sys.path`):

```python
def test_resolve_min_words_returns_default_when_no_override():
    import description_quality as dq
    assert dq.resolve_min_words({}) == dq._DEFAULTS["min_words"]
    # a tier1 sentinel string ("default") still yields the default floor
    assert dq.resolve_min_words({"lint": {"tier1": "default"}}) == dq._DEFAULTS["min_words"]


def test_resolve_min_words_honors_host_override():
    import description_quality as dq
    cfg = {"lint": {"tier1": {"description_quality": {"min_words": 12}}}}
    assert dq.resolve_min_words(cfg) == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/lint/test_description_quality.py::test_resolve_min_words_honors_host_override -v`
Expected: FAIL with `AttributeError: module 'description_quality' has no attribute 'resolve_min_words'`.

- [ ] **Step 3: Write minimal implementation**

In `scripts/lint/description_quality.py`, immediately after `_resolve_config` (after line 48):

```python
def resolve_min_words(config: dict[str, Any]) -> int:
    """The effective ``min_words`` floor for ``config`` — the host override
    under ``lint.tier1.description_quality`` if present, else the default.
    Single source of truth for callers that must satisfy this floor (CCE-119
    Item B); the synthesized agent-authored description pads to it.
    """
    return int(_resolve_config(config)["min_words"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/lint/test_description_quality.py -v`
Expected: PASS (both new tests + all pre-existing).

- [ ] **Step 5: Commit**

```bash
git add scripts/lint/description_quality.py tests/lint/test_description_quality.py
git commit -m "feat(CCE-119): resolve_min_words — public description_quality floor resolver"
```

---

## Task 2: synthesizer honors resolved `min_words` + callsite threads it (Item B, part 2)

The signature change and its sole caller move together (per the shared-helper rule — never leave a caller broken). This task keeps the suite green end-to-end.

**Files:**

- Modify: `scripts/orchestrator_runner.py:979-1008` (delete `_DESC_MIN_WORDS`; change `_synthesize_agent_description`)
- Modify: `scripts/orchestrator_runner.py:~1493` (resolve `_desc_min_words` before the authoring loop) and `:1544-1546` (pass `min_words`)
- Test: `tests/orchestrator/test_synthesize_description.py` (update 8 calls, add 1), `tests/orchestrator/test_agent_authored_create_frontmatter.py` (add callsite spy test)

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestrator/test_synthesize_description.py`:

```python
def test_pads_to_higher_min_words_floor():
    # A host raising description_quality.min_words must still get a description
    # that clears the raised floor — deterministically.
    out = _syn([{"what_changed": "Adds foo"}], hint="loader.md", min_words=12)
    assert len(out.split()) >= 12
    assert not out.endswith(":")
    assert out.strip().lower() != "loader.md".strip().lower()
    # determinism holds at the raised floor
    again = _syn([{"what_changed": "Adds foo"}], hint="loader.md", min_words=12)
    assert out == again
```

Append to `tests/orchestrator/test_agent_authored_create_frontmatter.py` (reuses `FAKES`, `CONFIG_AGENT_AUTHORED`, `_SEED_STATE`, `init_host`):

```python
def test_callsite_passes_resolved_min_words(tmp_path, init_host, monkeypatch):
    """The authoring callsite resolves description_quality.min_words from the
    host config and threads it into the synthesizer (CCE-119 Item B)."""
    cfg = CONFIG_AGENT_AUTHORED.replace(
        "lint: { tier1: default, tier2: {}, tier3: {} }",
        "lint: { tier1: { description_quality: { min_words: 12 } }, tier2: {}, tier3: {} }",
    )
    init_host(_SEED_STATE, config_yaml=cfg)
    import orchestrator_runner as runner

    captured: dict = {}
    orig = runner._synthesize_agent_description

    def spy(summaries, *, hint, min_words):
        captured["min_words"] = min_words
        return orig(summaries, hint=hint, min_words=min_words)

    monkeypatch.setattr(runner, "_synthesize_agent_description", spy)
    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)
    assert rc == 0
    assert captured["min_words"] == 12
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_synthesize_description.py::test_pads_to_higher_min_words_floor tests/orchestrator/test_agent_authored_create_frontmatter.py::test_callsite_passes_resolved_min_words -v`
Expected: FAIL — `test_pads...` with `TypeError: _synthesize_agent_description() got an unexpected keyword argument 'min_words'`; `test_callsite...` with `KeyError: 'min_words'` (spy never captured because the real call passes no `min_words`).

- [ ] **Step 3: Change the synthesizer — require `min_words`, delete the constant**

In `scripts/orchestrator_runner.py`, delete line 979 (`_DESC_MIN_WORDS = 6`) and replace the whole `_synthesize_agent_description` body (lines 982-1008) with:

```python
def _synthesize_agent_description(
    summaries: list[dict], *, hint: str, min_words: int
) -> str:
    """Deterministic one-line description for a freshly-created agent-authored
    page (CCE-117). Guarantees the description_quality invariants — >= ``min_words``
    words, not equal to the slug-derived H1, no trailing colon — by construction.
    ``min_words`` is the host's resolved floor (CCE-119 Item B); pass
    ``description_quality.resolve_min_words(config)``. Pure; never raises on
    malformed input.
    """
    change = ""
    for s in summaries or []:
        if isinstance(s, dict):
            wc = s.get("what_changed") or s.get("why")
            if isinstance(wc, str) and wc.strip():
                change = wc.strip()
                break
    base = hint[:-3] if hint.endswith(".md") else hint
    topic = (
        " ".join(base.replace("/", " ").replace("-", " ").replace("_", " ").split())
        or "this page"
    )
    if change and len(change.split()) >= 3:
        desc = f"Documents {topic}: {change}"
    else:
        desc = f"Reference documentation for {topic} in this codebase"
    desc = desc.rstrip(":").strip()
    # CCE-119 Item B: pad deterministically to the resolved floor (was a
    # hardcoded 6). Neutral, repeatable filler drawn from the topic; each append
    # re-strips a trailing colon so the invariant holds wherever the floor lands.
    filler = f"agent-authored reference for {topic}".split()
    fi = 0
    while len(desc.split()) < min_words:
        desc = f"{desc} {filler[fi % len(filler)]}".rstrip(":").strip()
        fi += 1
    return desc
```

- [ ] **Step 4: Resolve `_desc_min_words` before the authoring loop**

In `scripts/orchestrator_runner.py`, find the authoring-stage setup (immediately before the `for i, ((lens, hint), batch_summaries) in enumerate(per_target.items()):` loop, right after `pr_by_number = {pr.get("number"): pr for pr in prs}`). Insert:

```python
        # CCE-119 Item B: resolve the description_quality min_words floor once
        # from config (single source of truth in the lint rule) so an
        # agent-authored create's synthesized description clears a host's
        # possibly-raised threshold, not a hardcoded 6.
        _lint_dir = str(_PLUGIN_ROOT / "scripts" / "lint")
        if _lint_dir not in sys.path:
            sys.path.append(_lint_dir)
        import description_quality as _description_quality

        _desc_min_words = _description_quality.resolve_min_words(config)
```

- [ ] **Step 5: Pass `min_words` at the synthesizer callsite**

In `scripts/orchestrator_runner.py:1544-1546`, change:

```python
                    description=_synthesize_agent_description(
                        batch_summaries, hint=hint
                    ),
```

to:

```python
                    description=_synthesize_agent_description(
                        batch_summaries, hint=hint, min_words=_desc_min_words
                    ),
```

- [ ] **Step 6: Update the 8 existing synthesizer test calls**

In `tests/orchestrator/test_synthesize_description.py`, add `min_words=6` to every `_syn(...)` call so the now-required keyword is supplied (6 is the default floor, keeping each test's intent). The calls to update, with their new form:

```python
# test_uses_what_changed_and_clears_min_words
out = _syn([{"pr_number": 1, "what_changed": "Adds a foo connector"}],
           hint="connectors/foo.md", min_words=6)

# test_not_equal_to_slug_title
out = _syn([{"what_changed": "Adds a foo connector"}], hint=hint, min_words=6)

# test_trailing_colon_stripped_even_if_source_ends_in_colon
out = _syn([{"what_changed": "Refactors the loader:"}], hint="loader.md", min_words=6)

# test_empty_summaries_fall_back_and_still_pass_min_words
out = _syn([], hint="orchestrator/state-advancement.md", min_words=6)

# test_deterministic (both calls)
a = _syn(*args, hint="connectors/foo.md", min_words=6)
b = _syn(*args, hint="connectors/foo.md", min_words=6)

# test_tolerates_malformed_entries
out = _syn(["not-a-dict", {"what_changed": None}, {"why": "Because reasons here"}],
           hint="x.md", min_words=6)

# test_what_changed_beats_why_when_both_present
out = _syn([{"what_changed": "Adds foo connector logic", "why": "backward compat"}],
           hint="connectors/foo.md", min_words=6)

# test_no_padding_when_description_already_long
out = _syn([{"what_changed": "Refactors the loader module for clarity"}],
           hint="loader.md", min_words=6)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_synthesize_description.py tests/orchestrator/test_agent_authored_create_frontmatter.py -v`
Expected: PASS — the new floor test, all 8 updated calls, the callsite spy test, and the pre-existing agent-authored tests.

- [ ] **Step 8: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_synthesize_description.py tests/orchestrator/test_agent_authored_create_frontmatter.py
git commit -m "feat(CCE-119): synthesizer pads to config-resolved min_words; drop _DESC_MIN_WORDS"
```

---

## Task 3: `_enforce_agent_frontmatter` reconciliation helper (Item A, part 1)

Defines the helper (module-level, unused until Task 4). It imports `frontmatter_contract` locally (matching the codebase's local-import pattern — `fmc` is not a module global).

**Files:**

- Modify: `scripts/orchestrator_runner.py` (add helper immediately after `_synthesize_agent_description`, ~line 1010)
- Test: `tests/orchestrator/test_enforce_agent_frontmatter.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/orchestrator/test_enforce_agent_frontmatter.py`:

```python
"""CCE-119 Item A: _enforce_agent_frontmatter makes the orchestrator's
deterministic agent_fields the authoritative frontmatter of a freshly-created
agent-authored page, regardless of what the page-author (the real LLM on the
production path) actually wrote. Verified with the real description_quality
consumer, not test -f.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "lint"))

import orchestrator_runner as runner  # noqa: E402
import frontmatter_contract as fmc  # noqa: E402
import description_quality  # noqa: E402
from archive_indexes import parse_frontmatter  # noqa: E402

_GOOD = fmc.agent_authored_frontmatter_dict(
    description="Documents the foo connector and its retry semantics in detail",
    source_files=["backend/connectors/foo.py"],
    last_reviewed="2026-07-14",
)


def test_enforce_overwrites_deviating_frontmatter(tmp_path):
    page = tmp_path / "foo.md"
    # A deviating production write: description under the floor, source_files dropped.
    page.write_text(
        "---\ndescription: short\nstatus: draft\n---\n"
        "# Foo\n\nReal body the author wrote about the foo connector.\n"
    )
    runner._enforce_agent_frontmatter(page, _GOOD)

    text = page.read_text()
    fm = parse_frontmatter(text)
    # Real consumer, not test -f: the description now passes description_quality.
    ok, msg = description_quality.check_fm(fm, title="Foo", config={})
    assert ok, msg
    # Authoritative fields present with the orchestrator's values.
    assert fm["source_files"] == ["backend/connectors/foo.py"]
    assert fm["last_reviewed"] == "2026-07-14"
    # Body preserved; deviation gone.
    assert "Real body the author wrote about the foo connector." in text
    assert "description: short" not in text


def test_enforce_is_idempotent(tmp_path):
    page = tmp_path / "foo.md"
    page.write_text("---\ndescription: short\n---\n# Foo\n\nBody.\n")
    runner._enforce_agent_frontmatter(page, _GOOD)
    once = page.read_text()
    runner._enforce_agent_frontmatter(page, _GOOD)
    assert page.read_text() == once


def test_enforce_handles_file_without_frontmatter(tmp_path):
    page = tmp_path / "foo.md"
    page.write_text("# Foo\n\nBody with no frontmatter at all.\n")
    runner._enforce_agent_frontmatter(page, _GOOD)
    text = page.read_text()
    assert text.startswith("---\n")
    assert "Body with no frontmatter at all." in text
    fm = parse_frontmatter(text)
    ok, msg = description_quality.check_fm(fm, title="Foo", config={})
    assert ok, msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_enforce_agent_frontmatter.py -v`
Expected: FAIL with `AttributeError: module 'orchestrator_runner' has no attribute '_enforce_agent_frontmatter'`.

- [ ] **Step 3: Write the helper**

In `scripts/orchestrator_runner.py`, immediately after `_synthesize_agent_description` (after its `return desc`, ~line 1010):

```python
def _enforce_agent_frontmatter(path: Path, agent_fields: dict) -> None:
    """CCE-119 Item A: make the orchestrator's deterministic ``agent_fields`` the
    authoritative frontmatter of a freshly-created agent-authored page.

    The page-author (the real LLM on the production dispatch path) is handed
    these fields as a template but may reword or drop the lint-guarded ones; the
    orchestrator's values win — declare-then-discharge, never trust the
    subagent's own write. Strips whatever leading ``---`` block is on disk
    (mirroring the fence convention of ``archive_indexes.parse_frontmatter``:
    ``split("---", 2)``) and re-prepends
    ``agent_authored_frontmatter_text(**agent_fields)``, keeping the body.
    ``agent_fields`` carries only the four agent-authored keys (see Task 4's
    decoupling), so this never passes an unexpected kwarg. Idempotent; a file
    with no well-formed block keeps its whole text as the body.
    """
    import frontmatter_contract as fmc

    text = path.read_text()
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            body = parts[2].lstrip("\n")
    path.write_text(fmc.agent_authored_frontmatter_text(**agent_fields) + body)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_enforce_agent_frontmatter.py -v`
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_enforce_agent_frontmatter.py
git commit -m "feat(CCE-119): _enforce_agent_frontmatter reconciliation helper"
```

---

## Task 4: wire reconciliation into the authoring loop + decouple `doc_kind` (Item A, part 2)

Wires the helper so it runs on both paths, and stops the `doc_kind` mutation from polluting `agent_fields` (so the production `agent_authored_frontmatter_text(**agent_fields)` call is `doc_kind`-free — `doc_kind` is consumed only by routing, never read back from a page's frontmatter).

**Files:**

- Modify: `scripts/orchestrator_runner.py:1550` (`fm_template = dict(agent_fields)`) and `:1582-1596` (add reconciliation in the ok-branch)
- Test: `tests/orchestrator/test_agent_authored_create_frontmatter.py` (add integration test)

- [ ] **Step 1: Write the failing test**

Append to `tests/orchestrator/test_agent_authored_create_frontmatter.py`:

```python
def test_reconciliation_overwrites_production_frontmatter_deviation(tmp_path, init_host):
    """Production-seam proof (not only dry-run): when the file already exists with
    deviating frontmatter — as a real page-author LLM could write — the dry-run
    synth is skipped and reconciliation still makes the deterministic frontmatter
    authoritative, so the page passes REAL Tier-1 lint. (CCE-119 Item A / AC2.)"""
    init_host(_SEED_STATE, config_yaml=CONFIG_AGENT_AUTHORED)
    target = tmp_path / "docs" / "site-src" / "core" / "connectors" / "foo.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "---\ndescription: short\nstatus: draft\n---\n"
        "# foo\n\nBody the author wrote about the foo connector.\n"
    )
    import orchestrator_runner as runner

    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)
    assert rc == 0

    text = target.read_text()
    assert "Body the author wrote about the foo connector." in text  # body preserved
    assert "description: short" not in text  # deviation overwritten

    import frontmatter_schema
    import description_quality

    config = yaml.safe_load(CONFIG_AGENT_AUTHORED)
    ok_fs, msg_fs = frontmatter_schema.check_path(target, config)
    ok_dq, msg_dq = description_quality.check_path(target, config)
    assert ok_fs, f"frontmatter_schema: {msg_fs}"
    assert ok_dq, f"description_quality: {msg_dq}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_agent_authored_create_frontmatter.py::test_reconciliation_overwrites_production_frontmatter_deviation -v`
Expected: FAIL — reconciliation is not wired, so the pre-written `description: short` / missing `source_files` survives and `frontmatter_schema` / `description_quality` reject it (assertion on `msg_fs`/`msg_dq`, or `"description: short" not in text`).

- [ ] **Step 3: Decouple `agent_fields` from the `doc_kind` mutation**

In `scripts/orchestrator_runner.py:1550`, change:

```python
                fm_template = agent_fields
```

to:

```python
                # CCE-119 Item A: keep agent_fields the pure 4-field authoritative
                # set. doc_kind is attached to a COPY below (it is routing-only —
                # nothing reads it back from a page), so reconciliation's
                # agent_authored_frontmatter_text(**agent_fields) can't hit the
                # latent doc_kind TypeError.
                fm_template = dict(agent_fields)
```

(The `_dk` / `fm_template["doc_kind"] = _dk` block at lines 1560-1562 is unchanged — it now mutates the copy for the agent-authored branch and the default dict for the else branch, exactly as before, but never `agent_fields`.)

- [ ] **Step 4: Add the reconciliation call in the ok-branch**

In `scripts/orchestrator_runner.py`, the ok-branch currently ends after the dry-run synth block (line 1596). Add the reconciliation immediately after that `if dry_run_dir and not target_path.exists(): ...` block, still inside `if out.get("ok"):`:

```python
                if agent_fields is not None and target_path.exists():
                    # CCE-119 Item A: enforce the deterministic frontmatter on the
                    # written page (production: the LLM wrote it; dry-run: the synth
                    # above wrote it). Runs on both paths; a no-op when the write
                    # already matches.
                    _enforce_agent_frontmatter(target_path, agent_fields)
```

- [ ] **Step 5: Run the targeted + regression tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_agent_authored_create_frontmatter.py -v`
Expected: PASS — the new reconciliation test, plus the pre-existing `test_agent_authored_create_uses_agent_template`, `test_created_agent_authored_page_passes_tier1_lint` (dry-run: synth writes good FM → reconciliation is a content no-op), and `test_default_section_create_unaffected` (`agent_fields is None` → reconciliation skipped).

- [ ] **Step 6: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_agent_authored_create_frontmatter.py
git commit -m "feat(CCE-119): reconcile agent-authored create frontmatter post-dispatch"
```

---

## Task 5: page-author contract requires verbatim frontmatter (Item A / AC1)

**Files:**

- Modify: `agents/page-author.md:29` and `:76`
- Test: `tests/orchestrator/test_page_author_contract.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/orchestrator/test_page_author_contract.py`:

```python
"""CCE-119 Item A / AC1: the page-author contract must require emitting the
lint-guarded agent-authored frontmatter fields verbatim for a create."""

from pathlib import Path

_CONTRACT = (Path(__file__).parent.parent.parent / "agents" / "page-author.md").read_text()


def test_contract_requires_verbatim_agent_authored_frontmatter():
    lowered = _CONTRACT.lower()
    assert "verbatim" in lowered, "contract must state the fields are emitted verbatim"
    # anchored to the agent-authored create field set
    assert "source_files" in _CONTRACT
    assert "last_reviewed" in _CONTRACT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_page_author_contract.py -v`
Expected: FAIL on `assert "verbatim" in lowered` (the contract says "draft frontmatter", not "verbatim").

- [ ] **Step 3: Edit the contract**

In `agents/page-author.md`, replace Procedure step 2 (line 76):

```markdown
2. Read existing page (if `edit`); for `create`, draft frontmatter from `frontmatter_template` (set `sources` to the PR URLs from summaries).
```

with:

```markdown
2. Read existing page (if `edit`); for `create`, draft frontmatter from `frontmatter_template` (set `sources` to the PR URLs from summaries). **For an agent-authored create — the template carries `description`, `source_files`, `last_reviewed` — emit those three fields verbatim from `frontmatter_template`: do not reword, shorten, or drop them. They are lint-guarded and the orchestrator's values are authoritative (it reconciles the written page against them regardless).**
```

And extend the `frontmatter_template` input note (line 29) by appending to its sentence:

```markdown
For an agent-authored create, `description`/`source_files`/`last_reviewed` must be written verbatim (they are lint-guarded and orchestrator-authoritative).
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/orchestrator/test_page_author_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/page-author.md tests/orchestrator/test_page_author_contract.py
git commit -m "docs(CCE-119): page-author must emit agent-authored frontmatter verbatim"
```

---

## Task 6: CHANGELOG + full-suite green

**Files:**

- Modify: `CHANGELOG.md` ([Unreleased] > Fixed)

- [ ] **Step 1: Add the CHANGELOG entry**

Under `## [Unreleased]` → `### Fixed`, add as the first bullet:

```markdown
- **CCE-119** — create-path frontmatter fidelity. The orchestrator now reconciles a freshly-created agent-authored page's frontmatter against its own deterministic `agent_fields` after the page-author returns (declare-then-discharge — the LLM's write is no longer trusted on the production dispatch path), and the synthesized description's `min_words` floor is resolved from the host's `description_quality` config instead of a duplicated `_DESC_MIN_WORDS` constant. Both were CCE-117 residuals; neither was a live failure (the content-validator lint-drop safety net masked them).
```

- [ ] **Step 2: Run the full suite**

Run: `python3 -m pytest`
Expected: PASS (all pre-existing + the new CCE-119 tests; 0 failures). Note the passed/skipped counts.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(CCE-119): changelog — create-path frontmatter fidelity"
```

---

## Self-Review

**Spec coverage:**

- Item A / AC1 (contract requires verbatim) → Task 5.
- Item A / AC2 (deterministic description survives to the written page, tested at the production-dispatch seam not only dry-run) → Task 3 (helper + real-consumer unit tests incl. no-frontmatter and idempotence) and Task 4 (integration through `run()` with a pre-existing deviating file that skips the dry-run synth). ✅
- Item B / AC1 (helper reads resolved `min_words`, falling back to default) → Task 1 (`resolve_min_words`) + Task 2 (synthesizer pads to it; callsite resolves from config; `_DESC_MIN_WORDS` deleted → one source of truth). ✅
- Architecture change 1 (`_enforce_agent_frontmatter`) → Task 3. Change 2 (callsite reconciliation) → Task 4. Change 3 (contract) → Task 5. Change 4 (`resolve_min_words` + synthesizer) → Tasks 1-2. ✅
- Degradation table: edits & default sections skip reconciliation (`agent_fields is None`) — covered by `test_default_section_create_unaffected` (Task 4 Step 5) and the guard in Task 4 Step 4. No-frontmatter file — Task 3 `test_enforce_handles_file_without_frontmatter`. ✅

**Placeholder scan:** none — every code step shows complete code and exact commands/expected output.

**Type/name consistency:** `_synthesize_agent_description(summaries, *, hint, min_words)` — required keyword used identically in Task 2 (definition, callsite, all 8 updated tests, new floor test). `resolve_min_words(config) -> int` — same name in Task 1 (def + tests) and Task 2 (callsite). `_enforce_agent_frontmatter(path, agent_fields)` — same 2-arg signature in Task 3 (def + tests) and Task 4 (callsite). `agent_authored_frontmatter_text(**agent_fields)` receives only the 4 keys because Task 4 keeps `agent_fields` pure via `dict(agent_fields)` before the `doc_kind` mutation. ✅

**Ordering safety:** every task ends on a green suite. Task 2 changes the signature and its only caller together. Task 4 wires reconciliation and the `doc_kind` decoupling together, so `agent_fields` is never polluted at the moment reconciliation first runs. ✅

---

## Execution Handoff

Controller executes via **superpowers:subagent-driven-development** (fresh subagent per task, two-stage review), with the controller independently discharging each implementer's claims against the actual git tree + real pytest before dispatching reviews (declare-then-discharge per CLAUDE.md fidelity gate). Dedicated validation subagents verify the correctness of both the implementation and the tests.
