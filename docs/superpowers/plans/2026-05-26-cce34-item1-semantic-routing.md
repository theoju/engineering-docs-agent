# CCE-34 Item 1: Semantic Section Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stale `_agent-sandbox/` create-target constraint with discovery-driven semantic routing so generated pages land in the correct published sections of the live docs site.

**Architecture:** The orchestrator scans each lens root for top-level subdirectories before dispatching pr-summarizers, passing them as `available_sections`. The pr-summarizer contract is updated to route new pages into those sections instead of a hardcoded sandbox path. The lens enum in the JSON schema is opened to any non-empty string. Five supporting cleanups (contract text, schema, docstring, vestigial file, scaffold stubs) complete the work.

**Tech Stack:** Python 3.9+, pytest, jsonschema, MkDocs. No new dependencies.

---

## File map

| File                                              | Role                                                                                                        |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `scripts/orchestrator_runner.py:869`              | Add `available_sections_by_lens` scan + pass to pr-summarizer                                               |
| `agents/pr-summarizer.md`                         | Contract update (inputs, §1, example, step 6, §4, lens desc, line 193)                                      |
| `agents/schemas/pr_summarizer.schema.json`        | Open `lens` from enum → `"type": "string", "minLength": 1`                                                  |
| `tests/orchestrator/test_pipeline_integration.py` | 3 new tests for `available_sections`                                                                        |
| `tests/schemas/test_pr_summarizer_schema.py`      | Flip direction of `test_unknown_lens_rejected`, add `test_empty_lens_rejected`, update docstring + fixtures |
| `scripts/site_structure.py:47–55`                 | `_section_index_stub` — more descriptive body text                                                          |
| `tests/site/test_site_structure.py:39–43`         | Assert new body text, assert old text gone                                                                  |
| `docs/site-src/architecture/index.md`             | Update dogfood stub to specific description                                                                 |
| `docs/site-src/operations/index.md`               | Update dogfood stub to specific description                                                                 |
| `docs/site-src/archive/index.md`                  | Update dogfood stub to specific description                                                                 |
| `docs/_agent-sandbox/.gitkeep`                    | Delete via `git rm`                                                                                         |
| `scripts/state_io.py:30–31`                       | Update stale docstring                                                                                      |

---

## Task 1: Orchestrator — pass `available_sections` to pr-summarizer

**Model:** sonnet

**Files:**

- Modify: `scripts/orchestrator_runner.py` (around line 869)
- Modify: `tests/orchestrator/test_pipeline_integration.py`

**Context:** The orchestrator dispatches pr-summarizer once per PR in a loop starting at line 870 (`for pr in prs:`). The `summaries = []` declaration is at line 869. We insert the section-discovery block between these two lines. The test patterns follow `test_jira_context_threaded_to_pr_summarizer` exactly — monkeypatch `dispatch_subagent`, spy on `pr-summarizer` calls, assert on captured inputs. `_init_host` creates `docs/site-src/core/` with no subdirs; the CONFIG_YAML lens is `core: docs/site-src/core`.

- [ ] **Step 1: Write three failing tests**

Add to `tests/orchestrator/test_pipeline_integration.py` (after the existing `test_jira_context_threaded_to_pr_summarizer` test):

```python
def test_available_sections_passed_to_pr_summarizer(tmp_path, monkeypatch):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    captured: list[dict] = []
    real = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir, cwd=None, out_reasons=None):
        if name == "pr-summarizer":
            captured.append(inputs)
        return real(name, inputs, dry_run_dir=dry_run_dir, out_reasons=out_reasons)

    monkeypatch.setattr(runner, "dispatch_subagent", spying)

    _init_host(tmp_path)
    # Create subdirs inside the lens root after git init (scan is filesystem-only)
    (tmp_path / "docs" / "site-src" / "core" / "architecture").mkdir()
    (tmp_path / "docs" / "site-src" / "core" / "operations").mkdir()

    runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)

    assert captured, "expected at least one pr-summarizer dispatch"
    sections = captured[0].get("available_sections", {})
    assert sections.get("core") == ["architecture", "operations"]


def test_available_sections_empty_when_no_subdirs(tmp_path, monkeypatch):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    captured: list[dict] = []
    real = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir, cwd=None, out_reasons=None):
        if name == "pr-summarizer":
            captured.append(inputs)
        return real(name, inputs, dry_run_dir=dry_run_dir, out_reasons=out_reasons)

    monkeypatch.setattr(runner, "dispatch_subagent", spying)

    _init_host(tmp_path)  # core/ dir exists but has no subdirs
    runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)

    assert captured
    assert captured[0]["available_sections"] == {"core": []}


def test_available_sections_empty_when_lens_root_missing(tmp_path, monkeypatch):
    """Lens root that does not exist on disk → empty list, no crash."""
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    captured: list[dict] = []
    real = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir, cwd=None, out_reasons=None):
        if name == "pr-summarizer":
            captured.append(inputs)
        return real(name, inputs, dry_run_dir=dry_run_dir, out_reasons=out_reasons)

    monkeypatch.setattr(runner, "dispatch_subagent", spying)

    _init_host(tmp_path)
    # Add a second lens pointing to a dir that does not exist
    cfg = tmp_path / ".engineering-docs-agent" / "config.yml"
    cfg.write_text(
        cfg.read_text().replace(
            "    core: docs/site-src/core",
            "    core: docs/site-src/core\n    extra: docs/site-src/missing-dir",
        )
    )

    runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)

    assert captured
    assert captured[0]["available_sections"]["extra"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/orchestrator/test_pipeline_integration.py::test_available_sections_passed_to_pr_summarizer tests/orchestrator/test_pipeline_integration.py::test_available_sections_empty_when_no_subdirs tests/orchestrator/test_pipeline_integration.py::test_available_sections_empty_when_lens_root_missing -v
```

Expected: FAIL — `KeyError: 'available_sections'` or `AssertionError`.

- [ ] **Step 3: Implement the `available_sections` scan in the orchestrator**

In `scripts/orchestrator_runner.py`, find the block:

```python
    summaries = []
    for pr in prs:
```

Replace it with:

```python
    summaries = []
    available_sections_by_lens: dict[str, list[str]] = {}
    for _ln in list(config.get("docs", {}).get("lens_paths", {}).keys()):
        try:
            _lp, _ = resolve_lens(config, _ln)
            _root = repo_root / _lp
            available_sections_by_lens[_ln] = (
                sorted(p.name for p in _root.iterdir() if p.is_dir())
                if _root.is_dir()
                else []
            )
        except (KeyError, OSError):
            available_sections_by_lens[_ln] = []
    for pr in prs:
```

Then in the same loop, find the `dispatch_validated("pr-summarizer", {...})` call and add `"available_sections"` to the input dict:

```python
        summary, reasons = dispatch_validated(
            "pr-summarizer",
            {
                "pr": pr,
                "jira_context": jira_context,
                "lens_names": list(config.get("docs", {}).get("lens_paths", {}).keys()),
                "available_sections": available_sections_by_lens,
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
```

- [ ] **Step 4: Run the three new tests to verify they pass**

```bash
python3 -m pytest tests/orchestrator/test_pipeline_integration.py::test_available_sections_passed_to_pr_summarizer tests/orchestrator/test_pipeline_integration.py::test_available_sections_empty_when_no_subdirs tests/orchestrator/test_pipeline_integration.py::test_available_sections_empty_when_lens_root_missing -v
```

Expected: all three PASS.

- [ ] **Step 5: Run the full orchestrator suite to confirm no regressions**

```bash
python3 -m pytest tests/orchestrator/ -v
```

Expected: all existing tests pass plus the three new ones.

- [ ] **Step 6: Commit**

```bash
git checkout -b feat/CCE-34-item1-semantic-routing
git add scripts/orchestrator_runner.py tests/orchestrator/test_pipeline_integration.py
git commit -m "feat(CCE-34): orchestrator passes available_sections to pr-summarizer

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: `agents/pr-summarizer.md` — contract update

**Model:** sonnet

**Files:**

- Modify: `agents/pr-summarizer.md`

**Context:** Five targeted edits. Do NOT touch the `## Output schema (canonical)` block — that is handled atomically with the `.json` schema file in Task 3. The sync test (`tests/agents/test_schema_md_sync.py`) will fail if the inline schema and the `.json` file disagree, so they must be updated together. Each edit below is described with the exact old string to find and the new string to replace it with.

**Note:** There is no automated test for the prompt text itself. Run `python3 -m pytest tests/agents/` after each change to confirm the schema-sync test still passes (it will, since we are not touching the schema block here).

- [ ] **Step 1: Add `available_sections` to the Inputs block**

Find:

```
- `lens_names`: list of host lens names from config (e.g. ["core","archive","onboarding"])
```

Replace with:

```
- `lens_names`: list of host lens names from config (e.g. ["core","archive","onboarding"])
- `available_sections`: dict mapping each lens name to a list of
  top-level section directories that currently exist under that lens root
  (e.g. `{"core": ["architecture", "archive", "operations"]}`).
  Empty list means the lens root has no subdirectories yet.
```

- [ ] **Step 2: Rewrite Forbidden outputs §1**

Find:

````
**§1 — `page_hint` outside the agent sandbox on `action: create`**:

```json
{ "lens": "core", "action": "create", "page_hint": "CHANGELOG.md" }
````

```json
{ "lens": "superpowers", "action": "create", "page_hint": "specs/new-thing.md" }
```

New pages may only land under `docs/_agent-sandbox/`. Use `lens: core` and
`page_hint: _agent-sandbox/<rel>.md`.

```

Replace with:
```

**§1 — `action: create` target in a non-publishable location**:

```json
{
  "lens": "core",
  "action": "create",
  "page_hint": "api/reference/new-thing.md"
}
```

Never create pages under `api/reference/` — those are auto-generated by
mkdocstrings at build time. Writing there would be clobbered on the next
build.

Also prohibited: using `_agent-sandbox/` as a prefix. That directory is no
longer in the host's `agent_editable_paths`; such a page would be silently
dropped by the orchestrator's editable-path guard.

```

- [ ] **Step 3: Update the Output contract example**

Find:
```

      "page_hint": "_agent-sandbox/2026-05-19-new-connector.md"

```

Replace with:
```

      "page_hint": "operations/2026-05-19-new-connector.md"

```

- [ ] **Step 4: Rewrite Procedure step 6 routing rules**

Find the `action: create` sub-rule (exact text):
```

- **`action: create`** — `page_hint` MUST start with `_agent-sandbox/` and
  end in `.md`. New pages may only be written under the agent sandbox; the
  host's `agent_editable_paths` glob is `docs/_agent-sandbox/**`. Use
  `lens: core` for new sandbox pages (its lens path is `docs/`, so the
  final write is `docs/_agent-sandbox/<rel>.md`). Example:
  `{"lens": "core", "action": "create", "page_hint": "_agent-sandbox/2026-05-21-foo.md"}`.

```

Replace with:
```

- **`action: create`** — choose a semantic path using `available_sections`:
  1.  Check `available_sections[lens]`. Match the PR's change domain to the
      closest section by directory name:
      - Infrastructure, deployment, configuration, runbooks → `operations/`
      - Design decisions, ADRs, "why we chose X" → `archive/`
      - Architecture, component design, data flows → `architecture/`
  2.  If no section fits, or `available_sections[lens]` is empty, use a flat
      slug at the lens root: `YYYY-MM-DD-<slug>.md`.
  3.  Never prefix with `_agent-sandbox/` — that path is no longer editable.
  4.  Never create under `api/reference/` — auto-generated at build time.
  5.  `page_hint` must end in `.md`, have no leading slash, and must NOT
      include the lens-path prefix (the orchestrator prepends it).

```

- [ ] **Step 5: Update the lens description in step 6**

Find:
```

- `lens`: one of `core` or `superpowers` (the values from the orchestrator's
  `lens_names` input — these are the only valid lenses).

```

Replace with:
```

- `lens`: one of the values from the orchestrator's `lens_names` input. Use only lenses that appear in that list.

```

- [ ] **Step 6: Update the `action: edit` example lens name**

Find:
```

     `{"lens": "superpowers", "action": "edit", "page_hint": "measurements/2026-05-20-cce12-tool-use-baseline.md"}`.

```

Replace with:
```

     `{"lens": "core", "action": "edit", "page_hint": "architecture/orchestrator.md"}`.

```

- [ ] **Step 7: Update the line-193 example**

Find:
```

`_agent-sandbox/2026-05-21-orchestrator-changes.md` (new) or
`architecture/orchestrator.md` (edit, if such a page exists).

```

Replace with:
```

`architecture/orchestrator.md` (edit, if such a page exists) or
`2026-05-21-orchestrator-changes.md` (new flat slug at the lens root).

```

- [ ] **Step 8: Update §4 fallback example**

Find:
```

at least one `doc_target` (even if it's `{"lens": "core", "action": "create", "page_hint": "_agent-sandbox/whats-new.md"}` referring the digest). Empty

```

Replace with:
```

at least one `doc_target` (even if it's `{"lens": "core", "action": "create", "page_hint": "YYYY-MM-DD-digest.md"}` referring the digest). Empty

````

- [ ] **Step 9: Run schema-sync test to confirm schema block untouched**

```bash
python3 -m pytest tests/agents/test_schema_md_sync.py -v
````

Expected: PASS (we did not modify the `## Output schema (canonical)` block).

- [ ] **Step 10: Commit**

```bash
git add agents/pr-summarizer.md
git commit -m "fix(CCE-34): pr-summarizer contract — semantic routing, remove sandbox constraint

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Schema — open lens enum + sync inline block + fix schema tests

**Model:** haiku

**Files:**

- Modify: `agents/schemas/pr_summarizer.schema.json`
- Modify: `agents/pr-summarizer.md` (inline schema block only)
- Modify: `tests/schemas/test_pr_summarizer_schema.py`

**Context:** The `test_md_schema_block_matches_canonical_schema_file` test in `tests/agents/test_schema_md_sync.py` compares the JSON inside the `## Output schema (canonical)` block in `pr-summarizer.md` against `agents/schemas/pr_summarizer.schema.json`. Both must be updated in the same commit or the sync test fails. The schema test file needs a direction flip (`test_unknown_lens_rejected` must become `test_arbitrary_lens_accepted`) and a new `test_empty_lens_rejected`.

- [ ] **Step 1: Write the new failing schema tests**

In `tests/schemas/test_pr_summarizer_schema.py`:

1. Rename `test_unknown_lens_rejected` to `test_arbitrary_lens_accepted` and **invert** the assertion:

```python
def test_arbitrary_lens_accepted(validator: Draft7Validator) -> None:
    """Any non-empty lens string is valid; enforcement of known lenses is at runtime."""
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {"lens": "archive", "action": "edit", "page_hint": "specs/foo.md"}
        ],
    }
    validator.validate(doc)  # must NOT raise
```

2. Add `test_empty_lens_rejected` immediately after:

```python
def test_empty_lens_rejected(validator: Draft7Validator) -> None:
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {"lens": "", "action": "edit", "page_hint": "ops/foo.md"}
        ],
    }
    with pytest.raises(ValidationError):
        validator.validate(doc)
```

- [ ] **Step 2: Run these two tests to verify current state**

```bash
python3 -m pytest tests/schemas/test_pr_summarizer_schema.py::test_arbitrary_lens_accepted tests/schemas/test_pr_summarizer_schema.py::test_empty_lens_rejected -v
```

Expected: `test_arbitrary_lens_accepted` FAILS (currently rejected), `test_empty_lens_rejected` also FAILS (empty string currently passes because it matches the enum `["core", "superpowers"]`... actually it would fail the enum too, so this may pass already — confirm the output).

- [ ] **Step 3: Update `agents/schemas/pr_summarizer.schema.json`**

In `agents/schemas/pr_summarizer.schema.json`, find:

```json
          "lens": { "type": "string", "enum": ["core", "superpowers"] },
```

Replace with:

```json
          "lens": { "type": "string", "minLength": 1 },
```

- [ ] **Step 4: Update the inline schema block in `agents/pr-summarizer.md`**

In `agents/pr-summarizer.md`, inside the `## Output schema (canonical)` fenced block, find:

```json
          "lens": { "type": "string", "enum": ["core", "superpowers"] },
```

Replace with:

```json
          "lens": { "type": "string", "minLength": 1 },
```

- [ ] **Step 5: Update the schema test docstring and fixtures**

In `tests/schemas/test_pr_summarizer_schema.py`:

1. Update the module docstring line 6 from:
   `- lens must be one of ["core", "superpowers"]`
   to:
   `- lens must be a non-empty string (any host-defined lens name is valid)`

2. In `test_create_lens_relative_md_accepted` (line 44), rename the test to `test_create_lens_relative_semantic_path_accepted` and change the fixture path:
   `"page_hint": "_agent-sandbox/foo.md"` → `"page_hint": "operations/foo.md"`

3. In `test_extra_doc_target_field_rejected` (line 151), change:
   `"page_hint": "_agent-sandbox/foo.md",` → `"page_hint": "operations/foo.md",`

4. In `test_edit_allows_lens_relative_md` (line 105), change `"lens": "superpowers"` to `"lens": "onboarding"` to make the generic intent clear.

- [ ] **Step 6: Run the full schema test suite**

```bash
python3 -m pytest tests/schemas/test_pr_summarizer_schema.py tests/agents/test_schema_md_sync.py -v
```

Expected: all tests PASS including the renamed/new ones.

- [ ] **Step 7: Commit both schema files atomically**

```bash
git add agents/schemas/pr_summarizer.schema.json agents/pr-summarizer.md tests/schemas/test_pr_summarizer_schema.py
git commit -m "fix(CCE-34): open pr-summarizer lens enum to any non-empty string

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: `state_io.py` — update stale docstring

**Model:** haiku

**Files:**

- Modify: `scripts/state_io.py:30–31`

**Context:** Lines 30–31 of `state_io.py` still reference `docs/_agent-sandbox/**` as the example editable glob. This is stale since CCE-34 moved the editable path to `docs/site-src/**`. No behavioral change — docstring only.

- [ ] **Step 1: Update the docstring**

In `scripts/state_io.py`, find (lines 30–31):

```python
    (e.g., editable 'docs/_agent-sandbox/**' covers lens 'core' at 'docs/':
    the agent reads all of docs/ but writes only to the sandbox sub-path).
```

Replace with:

```python
    (e.g., editable 'docs/site-src/**' covers lens 'core' at 'docs/site-src/':
    the glob and lens root are co-located; any path under site-src is writable).
```

- [ ] **Step 2: Run state_io tests to confirm nothing broke**

```bash
python3 -m pytest tests/state_io/ -v
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add scripts/state_io.py
git commit -m "docs(CCE-34): update state_io editable-path docstring example

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: Delete `docs/_agent-sandbox/.gitkeep`

**Model:** haiku

**Files:**

- Delete: `docs/_agent-sandbox/.gitkeep`

**Context:** The `docs/_agent-sandbox/` directory was a placeholder for the old sandbox routing. It is vestigial — no tests reference it, no nav entry points to it, and the editable glob no longer includes it.

- [ ] **Step 1: Verify no tests reference `_agent-sandbox`**

```bash
grep -rn "_agent-sandbox" tests/ --include="*.py"
```

Expected: no output (the schema test fixtures were updated in Task 3; the state_io test was a docstring).

- [ ] **Step 2: Remove the file**

```bash
git rm docs/_agent-sandbox/.gitkeep
```

- [ ] **Step 3: Run the full suite to confirm nothing broke**

```bash
python3 -m pytest -x -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(CCE-34): remove vestigial docs/_agent-sandbox/.gitkeep

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: Scaffold stubs — meaningful section descriptions

**Model:** haiku

**Files:**

- Modify: `scripts/site_structure.py:47–55`
- Modify: `tests/site/test_site_structure.py:39–43`
- Modify: `docs/site-src/architecture/index.md`
- Modify: `docs/site-src/operations/index.md`
- Modify: `docs/site-src/archive/index.md`

**Context:** The `_section_index_stub` function at `scripts/site_structure.py:47` generates the `index.md` content when the setup skill scaffolds a new section. Currently it writes `_This section is scaffolded. Content will be added here._` — a generic placeholder that gives the pr-summarizer's LLM no signal about what belongs in the section. The fix: use the section title in a descriptive body line. The dogfood repo's three existing stubs must be updated directly (they were written by a previous scaffold run; re-running setup is not required).

- [ ] **Step 1: Write the failing test**

In `tests/site/test_site_structure.py`, update `test_section_index_stub_has_title_and_draft_frontmatter`:

```python
def test_section_index_stub_has_title_and_draft_frontmatter():
    files = {f.path: f for f in site_structure.plan_scaffold(SITE)}
    stub = files["docs/site-src/api/index.md"].content
    assert "title: API reference" in stub
    assert "status: draft" in stub
    assert "API reference: content will be added here" in stub
    assert "This section is scaffolded" not in stub
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python3 -m pytest tests/site/test_site_structure.py::test_section_index_stub_has_title_and_draft_frontmatter -v
```

Expected: FAIL — `AssertionError: assert "API reference: content will be added here" in ...`

- [ ] **Step 3: Update `_section_index_stub` in `scripts/site_structure.py`**

Find the function body (lines 47–55):

```python
def _section_index_stub(section: dict) -> str:
    return (
        "---\n"
        f"title: {_yaml_scalar(section['title'])}\n"
        "status: draft\n"
        "---\n\n"
        f"# {section['title']}\n\n"
        "_This section is scaffolded. Content will be added here._\n"
    )
```

Replace with:

```python
def _section_index_stub(section: dict) -> str:
    return (
        "---\n"
        f"title: {_yaml_scalar(section['title'])}\n"
        "status: draft\n"
        "---\n\n"
        f"# {section['title']}\n\n"
        f"_{section['title']}: content will be added here as the docs-agent runner summarizes merged changes._\n"
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python3 -m pytest tests/site/test_site_structure.py::test_section_index_stub_has_title_and_draft_frontmatter -v
```

Expected: PASS.

- [ ] **Step 5: Update the three dogfood section stubs**

**`docs/site-src/architecture/index.md`** — replace the body line:

```markdown
---
title: Architecture
status: draft
---

# Architecture

_Architecture: component design, agent contracts, data flows, and system internals._
```

**`docs/site-src/operations/index.md`** — replace the body line:

```markdown
---
title: Operations
status: draft
---

# Operations

_Operations: deployment workflows, configuration guides, and runbooks._
```

**`docs/site-src/archive/index.md`** — replace the body line:

```markdown
---
title: Decision Archive
status: draft
---

# Decision Archive

_Decision Archive: ADRs, design rationale, and "why we chose X" records._
```

- [ ] **Step 6: Run the full site test suite**

```bash
python3 -m pytest tests/site/ -v
```

Expected: all pass.

- [ ] **Step 7: Run the full suite for a final check**

```bash
python3 -m pytest -x -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add scripts/site_structure.py tests/site/test_site_structure.py \
    docs/site-src/architecture/index.md \
    docs/site-src/operations/index.md \
    docs/site-src/archive/index.md
git commit -m "fix(CCE-34): scaffold stubs use descriptive section body instead of generic placeholder

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Self-review checklist

After all tasks are committed, run before opening PR:

```bash
python3 -m pytest -x -q
```

Expected: all tests pass, no regressions.

Verify the five spec requirements are covered:

| Spec requirement                                                            | Task   |
| --------------------------------------------------------------------------- | ------ |
| Orchestrator passes `available_sections` to pr-summarizer                   | Task 1 |
| pr-summarizer contract updated (inputs, §1, example, step 6, §4, lens desc) | Task 2 |
| `lens` schema enum opened to any non-empty string + inline sync             | Task 3 |
| `state_io.py` docstring updated                                             | Task 4 |
| `docs/_agent-sandbox/.gitkeep` deleted                                      | Task 5 |
| Scaffold stubs descriptive + dogfood stubs updated                          | Task 6 |
