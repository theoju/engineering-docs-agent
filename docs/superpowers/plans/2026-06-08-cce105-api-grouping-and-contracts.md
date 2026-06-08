# CCE-105 — API Reference Grouping + Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group the flat API reference nav by config-declared service/component (degrading to flat when none declared) and turn on the dormant JSON-schema contracts extractor against `agents/schemas`.

**Architecture:** A new pure `assign_group(ident, groups)` helper in `scripts/site_structure.py` is embedded verbatim (via `inspect.getsource`) into the build-time `gen_ref_pages.py` template, so the mkdocs build stays hermetic (no plugin import at build time) with zero source drift. The `site.sections[]` schema gains an optional `groups` array; `_validate_api_sections` adds a unique-name cross-field check. The live `.engineering-docs-agent/config.yml` api section declares `groups` + the `json-schema` extractor (which `contracts_doc.generate_contracts` already consumes — it is wired into `run_site_generators` and merely no-ops today for lack of an extractor/sources).

**Tech Stack:** Python 3.11/3.12 stdlib (`fnmatch`, `inspect`), pytest, JSON Schema (draft-07, `jsonschema`), mkdocs-material + mkdocs-gen-files + literate-nav.

---

## File structure

- **Modify** `templates/config.schema.json` — add `groups` to `site.sections[].properties`; `minItems: 1` on group `modules`.
- **Modify** `scripts/site_structure.py` — add `assign_group`; rework `_GEN_REF_TEMPLATE` for grouped nav; thread `groups` through `apply_scaffold`.
- **Modify** `scripts/state_io.py` — extend `_validate_api_sections` with a unique-group-name check.
- **Modify** `scripts/preflight_host.py` — `_proposed_site` proposes the `json-schema` extractor + `groups`/`sources` via degrade-gracefully override hooks.
- **Modify** `.engineering-docs-agent/config.yml` — live api section gains `extractors: [..., json-schema]`, `sources: [agents/schemas]`, `groups:`.
- **Regenerate** `gen_ref_pages.py` (repo root) — re-rendered from the updated template with the live `groups` baked in.
- **Tests:** `tests/site/test_site_structure.py`, `tests/state_io/test_site_validation.py`, `tests/setup/test_preflight_host.py`, `tests/site/test_live_config_api.py` (new).

> **Note on the live `gen_ref_pages.py`:** `apply_scaffold` is idempotent (skips existing files), so it will NOT overwrite the committed root `gen_ref_pages.py`. Task 6 re-renders it explicitly. Do not expect scaffolding to refresh it.

---

## Task 1: Schema — add `groups` to `site.sections[]`

**Files:**

- Modify: `templates/config.schema.json:123-146` (the `site.sections.items.properties` block)
- Test: `tests/state_io/test_site_validation.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/state_io/test_site_validation.py`:

```python
def test_api_section_accepts_groups(tmp_path: Path):
    cfg = load_config_validated(
        _write(
            tmp_path,
            """
site:
  docs_dir: docs/site-src
  sections:
    - { key: home, path: index.md, title: Home }
    - key: api
      path: api/
      title: API reference
      generator: api-extract
      extractors: [python-mkdocstrings]
      groups:
        - { name: Generators, modules: [archive_indexes, contracts_doc] }
        - { name: Lint, modules: ["lint/*"] }
""",
        )
    )
    api = next(s for s in cfg["site"]["sections"] if s["key"] == "api")
    assert api["groups"][0]["name"] == "Generators"


def test_api_group_with_empty_modules_is_rejected_by_schema(tmp_path: Path):
    with pytest.raises(ConfigError):
        load_config_validated(
            _write(
                tmp_path,
                """
site:
  docs_dir: docs/site-src
  sections:
    - key: api
      path: api/
      title: API reference
      generator: api-extract
      extractors: [python-mkdocstrings]
      groups:
        - { name: Empty, modules: [] }
""",
            )
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/state_io/test_site_validation.py::test_api_section_accepts_groups tests/state_io/test_site_validation.py::test_api_group_with_empty_modules_is_rejected_by_schema -v`
Expected: `test_api_section_accepts_groups` FAILS — `jsonschema.ValidationError` ("Additional properties are not allowed ('groups' …)") wrapped as `ConfigError`. (The empty-modules test may already pass or error; both are expected to be green after Step 3.)

- [ ] **Step 3: Add `groups` to the schema**

In `templates/config.schema.json`, inside `site.sections.items.properties` (after the `repo_url_base` property at line ~145), add:

```json
              "groups": {
                "type": "array",
                "items": {
                  "type": "object",
                  "required": ["name", "modules"],
                  "additionalProperties": false,
                  "properties": {
                    "name": { "type": "string", "minLength": 1 },
                    "modules": {
                      "type": "array",
                      "minItems": 1,
                      "items": { "type": "string", "minLength": 1 }
                    }
                  }
                }
              }
```

(Add a trailing comma to the preceding `repo_url_base` line so the object stays valid JSON.)

- [ ] **Step 4: Run to verify both pass**

Run: `python3 -m pytest tests/state_io/test_site_validation.py -v`
Expected: PASS (all, including the two new tests).

- [ ] **Step 5: Commit**

```bash
git add templates/config.schema.json tests/state_io/test_site_validation.py
git commit -m "feat(CCE-105): allow site.sections[].groups in config schema"
```

---

## Task 2: `_validate_api_sections` — unique group names

**Files:**

- Modify: `scripts/state_io.py:124-162` (`_validate_api_sections`)
- Test: `tests/state_io/test_site_validation.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/state_io/test_site_validation.py`:

```python
def test_api_duplicate_group_names_rejected(tmp_path: Path):
    with pytest.raises(ConfigError, match="duplicate group name"):
        load_config_validated(
            _write(
                tmp_path,
                """
site:
  docs_dir: docs/site-src
  sections:
    - key: api
      path: api/
      title: API reference
      generator: api-extract
      extractors: [python-mkdocstrings]
      groups:
        - { name: Core, modules: [state_io] }
        - { name: Core, modules: [contracts] }
""",
            )
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/state_io/test_site_validation.py::test_api_duplicate_group_names_rejected -v`
Expected: FAIL — no `ConfigError` raised (duplicate names currently pass validation).

- [ ] **Step 3: Add the check**

In `scripts/state_io.py`, inside `_validate_api_sections`, immediately before the `if "openapi" in extractors:` block (line ~151), add:

```python
        seen_groups: set[str] = set()
        for g in s.get("groups") or []:
            name = g.get("name", "")
            if name in seen_groups:
                raise ConfigError(
                    f"site.section '{s.get('key')}' has a duplicate group name "
                    f"{name!r}"
                )
            seen_groups.add(name)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/state_io/test_site_validation.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add scripts/state_io.py tests/state_io/test_site_validation.py
git commit -m "feat(CCE-105): reject duplicate api group names in validation"
```

---

## Task 3: `assign_group` helper

**Files:**

- Modify: `scripts/site_structure.py` (add imports + `assign_group` near the top, after the imports block at line ~13)
- Test: `tests/site/test_site_structure.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/site/test_site_structure.py`:

```python
_GROUPS = [
    {"name": "Generators", "modules": ["archive_indexes", "contracts_doc"]},
    {"name": "Lint", "modules": ["lint/*"]},
]


def test_assign_group_first_match_wins():
    assert site_structure.assign_group("archive_indexes", _GROUPS) == "Generators"


def test_assign_group_glob_matches_path_form():
    # a "lint/*" glob must match the dotted ident "lint.lint_runner"
    assert site_structure.assign_group("lint.lint_runner", _GROUPS) == "Lint"


def test_assign_group_unmatched_is_other():
    assert site_structure.assign_group("gh_client", _GROUPS) == "Other"


def test_assign_group_empty_groups_is_flat_sentinel():
    # no groups -> "" so the caller keeps the flat nav
    assert site_structure.assign_group("anything", []) == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/site/test_site_structure.py -k assign_group -v`
Expected: FAIL — `AttributeError: module 'site_structure' has no attribute 'assign_group'`.

- [ ] **Step 3: Implement `assign_group`**

In `scripts/site_structure.py`, change the import block (lines 9-13) to add `fnmatch` and `inspect`:

```python
from __future__ import annotations

import fnmatch
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
```

Then add this function immediately after the imports (before `@dataclass class ScaffoldFile`):

```python
def assign_group(ident: str, groups: list) -> str:
    """Return the name of the first group whose module glob matches ``ident``,
    else "Other". An empty ``groups`` returns "" so the caller keeps the flat
    nav. Globs match against both the dotted ident ("a.b") and its path form
    ("a/b"), so a "lint/*" pattern matches a "lint.lint_runner" module.

    This function is embedded verbatim into the generated gen_ref_pages.py
    (see _GEN_REF_TEMPLATE) via inspect.getsource — keep it self-contained:
    use only the stdlib ``fnmatch`` imported at the template's top, and no
    brace literals (so str.format on the template is safe).
    """
    if not groups:
        return ""
    path_form = ident.replace(".", "/")
    for group in groups:
        for pattern in group.get("modules", []):
            if fnmatch.fnmatchcase(ident, pattern) or fnmatch.fnmatchcase(
                path_form, pattern
            ):
                return group["name"]
    return "Other"
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/site/test_site_structure.py -k assign_group -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/site_structure.py tests/site/test_site_structure.py
git commit -m "feat(CCE-105): add assign_group module->component matcher"
```

---

## Task 4: Grouped nav in the gen_ref template + scaffold wiring

**Files:**

- Modify: `scripts/site_structure.py:165-196` (`_GEN_REF_TEMPLATE`) and `scripts/site_structure.py:278-298` (`apply_scaffold`)
- Test: `tests/site/test_site_structure.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/site/test_site_structure.py`:

```python
import types
import contextlib
import io


def _exec_gen_ref(rendered: str, repo: Path, monkeypatch) -> dict:
    """Exec a rendered gen_ref_pages.py against a fake mkdocs_gen_files and
    return the captured Nav (a dict of nav_key -> doc path)."""
    fake = types.ModuleType("mkdocs_gen_files")

    class _Nav(dict):
        def build_literate_nav(self):
            return []

    @contextlib.contextmanager
    def _open(path, mode="r"):
        yield io.StringIO()

    fake.Nav = _Nav
    fake.open = _open
    fake.set_edit_path = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "mkdocs_gen_files", fake)
    monkeypatch.chdir(repo)
    g = {"__name__": "gen_ref_pages"}
    exec(compile(rendered, "gen_ref_pages.py", "exec"), g)
    return dict(g["nav"])


def _seed_modules(repo: Path):
    pkg = repo / "scripts"
    (pkg / "lint").mkdir(parents=True)
    for name in ("archive_indexes.py", "contracts_doc.py", "gh_client.py"):
        (pkg / name).write_text("")
    (pkg / "lint" / "lint_runner.py").write_text("")
    (pkg / "_private.py").write_text("")  # underscore-prefixed: excluded


def test_rendered_gen_ref_groups_nav(tmp_path: Path, monkeypatch):
    _seed_modules(tmp_path)
    rendered = site_structure._GEN_REF_TEMPLATE.format(
        scan_dir="scripts",
        path_root="scripts",
        out_root="api",
        groups_literal=repr(_GROUPS),
        assign_group_src=inspect.getsource(site_structure.assign_group),
    )
    nav = _exec_gen_ref(rendered, tmp_path, monkeypatch)
    assert ("Generators", "archive_indexes") in nav
    assert ("Generators", "contracts_doc") in nav
    assert ("Lint", "lint", "lint_runner") in nav
    assert ("Other", "gh_client") in nav
    assert not any("_private" in "".join(k) for k in nav)  # excluded


def test_rendered_gen_ref_flat_when_no_groups(tmp_path: Path, monkeypatch):
    _seed_modules(tmp_path)
    rendered = site_structure._GEN_REF_TEMPLATE.format(
        scan_dir="scripts",
        path_root="scripts",
        out_root="api",
        groups_literal=repr([]),
        assign_group_src=inspect.getsource(site_structure.assign_group),
    )
    nav = _exec_gen_ref(rendered, tmp_path, monkeypatch)
    assert ("archive_indexes",) in nav  # flat key, no group prefix
    assert ("lint", "lint_runner") in nav
```

(Add `import inspect` and `import sys` at the top of the test file if not already present — `sys` is imported at line 3; add `import inspect`.)

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/site/test_site_structure.py -k rendered_gen_ref -v`
Expected: FAIL — `KeyError: 'groups_literal'` (the template has no such format field yet).

- [ ] **Step 3: Rework `_GEN_REF_TEMPLATE`**

Replace `_GEN_REF_TEMPLATE` (`scripts/site_structure.py:165-196`) with:

```python
_GEN_REF_TEMPLATE = '''\
"""Auto-generated by engineering-docs-agent setup. Runs at mkdocs build time
(mkdocs-gen-files) to emit one API page per module + a literate-nav SUMMARY,
grouped by service/component when GROUPS is non-empty (CCE-105)."""
import fnmatch
from pathlib import Path

import mkdocs_gen_files

SCAN_DIR = "{scan_dir}"
PATH_ROOT = "{path_root}"
OUT_ROOT = "{out_root}"
GROUPS = {groups_literal}


{assign_group_src}

nav = mkdocs_gen_files.Nav()
root = Path(PATH_ROOT)
for py in sorted(Path(SCAN_DIR).rglob("*.py")):
    if py.name.startswith("_") or any(p in ("tests", "test") for p in py.parts):
        continue
    try:
        ident_parts = py.relative_to(root).with_suffix("").parts
    except ValueError:
        continue  # a .py outside PATH_ROOT (when SCAN_DIR is broader); skip it
    if not ident_parts:
        continue
    doc = Path(*ident_parts).with_suffix(".md")
    ident = ".".join(ident_parts)
    group = assign_group(ident, GROUPS)
    nav_key = (group, *ident_parts) if group else ident_parts
    nav[nav_key] = doc.as_posix()
    with mkdocs_gen_files.open(Path(OUT_ROOT, "reference") / doc, "w") as fd:
        fd.write(f"# `{{ident}}`\\n\\n::: {{ident}}\\n")
    mkdocs_gen_files.set_edit_path(Path(OUT_ROOT, "reference") / doc, py)

with mkdocs_gen_files.open(Path(OUT_ROOT, "reference", "SUMMARY.md"), "w") as f:
    f.writelines(nav.build_literate_nav())
'''
```

- [ ] **Step 4: Thread `groups` through `apply_scaffold`**

In `scripts/site_structure.py`, replace the `api_path = next(...)` block (lines ~278-285) with a single section lookup:

```python
    api_section = next(
        (s for s in site.get("sections", []) if s.get("generator") == "api-extract"),
        None,
    )
    api_path = (api_section.get("path", "api").rstrip("/")) if api_section else "api"
    api_groups = (api_section.get("groups") or []) if api_section else []
```

Then update the `gen_ref_pages.py` ScaffoldFile (lines ~287-298) to pass the two new fields:

```python
    if python_detected:
        planned.append(
            ScaffoldFile(
                "gen_ref_pages.py",
                _GEN_REF_TEMPLATE.format(
                    scan_dir=python_scan_dir or ".",
                    path_root=python_path_root or ".",
                    out_root=api_path,
                    groups_literal=repr(api_groups),
                    assign_group_src=inspect.getsource(assign_group),
                ),
                "gen-script",
            )
        )
```

- [ ] **Step 5: Run to verify it passes**

Run: `python3 -m pytest tests/site/test_site_structure.py -v`
Expected: PASS (all, including the two `rendered_gen_ref` tests).

- [ ] **Step 6: Confirm the flat-build smoke test still passes**

Run: `python3 -m pytest tests/site/test_mkdocs_build_smoke.py -v`
Expected: PASS or SKIP ("mkdocs not installed"). The default scaffold declares no groups, so the rendered nav is byte-for-byte the old flat behavior. If mkdocs is installed locally, it must build green.

- [ ] **Step 7: Commit**

```bash
git add scripts/site_structure.py tests/site/test_site_structure.py
git commit -m "feat(CCE-105): grouped literate-nav in gen_ref_pages template"
```

---

## Task 5: Preflight proposes the contracts extractor + groups

**Files:**

- Modify: `scripts/preflight_host.py:38-82` (`_proposed_site`)
- Test: `tests/setup/test_preflight_host.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/setup/test_preflight_host.py` (import `preflight_host` directly — add at the top, after `FIX = ...`: `sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts")); import preflight_host`):

```python
def test_proposed_site_api_flat_by_default():
    site = preflight_host._proposed_site({}, "docs")
    api = next(s for s in site["sections"] if s["key"] == "api")
    assert api["extractors"] == ["python-mkdocstrings"]  # no json-schema by default
    assert "groups" not in api
    assert "sources" not in api


def test_proposed_site_api_honors_discovery_hooks():
    discovery = {
        "contract_sources": ["agents/schemas"],
        "api_groups": [{"name": "Gen", "modules": ["archive_indexes"]}],
    }
    site = preflight_host._proposed_site(discovery, "docs")
    api = next(s for s in site["sections"] if s["key"] == "api")
    assert "json-schema" in api["extractors"]
    assert api["sources"] == ["agents/schemas"]
    assert api["groups"][0]["name"] == "Gen"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/setup/test_preflight_host.py -k proposed_site_api -v`
Expected: FAIL — `test_proposed_site_api_honors_discovery_hooks` fails (`json-schema` not in extractors; no `sources`/`groups` keys).

- [ ] **Step 3: Implement the hooks**

In `scripts/preflight_host.py`, replace the `api` section literal inside `_proposed_site` (lines ~60-66) with a computed section. Just before the `return {` in `_proposed_site`, add:

```python
    api_extractors = ["python-mkdocstrings"]
    contract_sources = discovery.get("contract_sources") or []
    if contract_sources:
        api_extractors.append("json-schema")
    api_section = {
        "key": "api",
        "path": "api/",
        "title": "API reference",
        "generator": "api-extract",
        "extractors": api_extractors,
    }
    if contract_sources:
        api_section["sources"] = contract_sources
    api_groups = discovery.get("api_groups") or []
    if api_groups:
        api_section["groups"] = api_groups
```

Then replace the inline api dict in the `sections` list with `api_section`:

```python
        "sections": [
            {"key": "home", "path": "index.md", "title": "Home"},
            {
                "key": "architecture",
                "path": "architecture/",
                "title": "Architecture",
                "generator": "agent-authored",
            },
            api_section,
            {"key": "operations", "path": "operations/", "title": "Operations"},
            {
                "key": "archive",
                "path": "archive/",
                "title": "Decision Archive",
                "generator": "archive-index",
                "sources": decision_sources,
            },
            {
                "key": "whats-new",
                "path": "whats-new.md",
                "title": "What's New",
                "generator": "changelog",
            },
        ],
```

Update the `_proposed_site` docstring to note `contract_sources` and `api_groups` are degrade-gracefully discovery override hooks (no detector emits them yet; exercised by test), mirroring the existing `decision_sources` hook.

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/setup/test_preflight_host.py -v`
Expected: PASS (all — the existing site-block tests still pass because the default api section is unchanged in shape).

- [ ] **Step 5: Commit**

```bash
git add scripts/preflight_host.py tests/setup/test_preflight_host.py
git commit -m "feat(CCE-105): preflight proposes json-schema extractor + api groups via hooks"
```

---

## Task 6: Wire the live host config + regenerate + verify with the real consumer

**Files:**

- Modify: `.engineering-docs-agent/config.yml` (the `api` section under `site:`)
- Regenerate: `gen_ref_pages.py` (repo root)
- Test: `tests/site/test_live_config_api.py` (new)

- [ ] **Step 1: Write the failing test (live-config guard)**

Create `tests/site/test_live_config_api.py`:

```python
"""CCE-105: the live host config wires API grouping + json-schema contracts."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from state_io import load_config_validated  # noqa: E402


def test_live_config_api_section_has_groups_and_contracts():
    cfg = load_config_validated(_REPO_ROOT / ".engineering-docs-agent" / "config.yml")
    api = next(s for s in cfg["site"]["sections"] if s["key"] == "api")
    assert "json-schema" in api["extractors"]
    assert "agents/schemas" in api["sources"]
    assert api["groups"], "api section must declare service/component groups"
    names = {g["name"] for g in api["groups"]}
    assert {"Orchestrator", "Generators", "Lint"} <= names
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/site/test_live_config_api.py -v`
Expected: FAIL — `KeyError`/assertion: the live api section has no `groups`/`sources` and only `python-mkdocstrings`.

- [ ] **Step 3: Edit the live config**

In `.engineering-docs-agent/config.yml`, replace the `api` section under `site.sections` with:

```yaml
- key: api
  path: api/
  title: API reference
  generator: api-extract
  extractors:
    - python-mkdocstrings
    - json-schema
  sources:
    - agents/schemas
  groups:
    - name: Orchestrator
      modules: [orchestrator_runner, state_io, contracts, stderr_emit]
    - name: Generators
      modules:
        [
          archive_indexes,
          contracts_doc,
          core_manifest,
          site_structure,
          source_map,
          source_drift,
          frontmatter_contract,
        ]
    - name: Lint
      modules: ["lint/*"]
    - name: Setup
      modules:
        [
          setup_discover,
          setup_scaffold,
          preflight_host,
          scaffold_workflow,
          enable_pages,
        ]
    - name: Verification
      modules: [verify_citations, verify_diagrams, verify_runner]
    - name: Integrations
      modules: [gh_client, jira_transition_on_merge, prune_merged_branches]
```

- [ ] **Step 4: Run to verify the guard passes**

Run: `python3 -m pytest tests/site/test_live_config_api.py -v`
Expected: PASS.

- [ ] **Step 5: Regenerate the live `gen_ref_pages.py` with the new groups**

Run this one-off render (reads the live groups, rewrites the root `gen_ref_pages.py`):

```bash
python3 - <<'PY'
import sys, inspect
from pathlib import Path
sys.path.insert(0, "scripts")
import site_structure as s
from state_io import load_config_validated
cfg = load_config_validated(Path(".engineering-docs-agent/config.yml"))
api = next(x for x in cfg["site"]["sections"] if x["key"] == "api")
rendered = s._GEN_REF_TEMPLATE.format(
    scan_dir="scripts", path_root="scripts", out_root="api",
    groups_literal=repr(api.get("groups") or []),
    assign_group_src=inspect.getsource(s.assign_group),
)
Path("gen_ref_pages.py").write_text(rendered, encoding="utf-8")
print("wrote gen_ref_pages.py")
PY
```

Then sanity-check it compiles: `python3 -c "compile(open('gen_ref_pages.py').read(), 'gen_ref_pages.py', 'exec'); print('ok')"`
Expected: `ok`.

- [ ] **Step 6: Populate contracts + build with the real consumer**

```bash
python3 scripts/contracts_doc.py --repo-root . --config .engineering-docs-agent/config.yml
pip install -r templates/docs-requirements.txt >/dev/null 2>&1 || true
mkdocs build --strict
```

Expected: `contracts_doc.py` prints a `written` list including `docs/site-src/api/contracts/page_author.md` … and `contracts/index.md`; `mkdocs build --strict` exits 0 with a grouped API nav (Orchestrator / Generators / Lint / … sections) and the contracts pages resolved. If `mkdocs` is unavailable, install via the requirements line above; do not skip this — it is the real-consumer gate (the plugin's "verify with the real consumer, not `test -f`" invariant).

- [ ] **Step 7: Commit**

```bash
git add .engineering-docs-agent/config.yml gen_ref_pages.py docs/site-src/api/contracts tests/site/test_live_config_api.py
git commit -m "feat(CCE-105): wire live api groups + json-schema contracts; regenerate gen_ref + contracts"
```

---

## Task 7: Full integrated suite + simplify + review

**Files:** none (verification + polish)

- [ ] **Step 1: Run the full suite**

Run: `python3 -m pytest -q`
Expected: all green (the CCE-104 baseline of 886 + the new CCE-105 tests).

- [ ] **Step 2: Simplify**

Invoke the `pr-review-toolkit:code-simplifier` agent (or `/simplify`) scoped to the unstaged/this-branch diff: `git diff main...HEAD`. Apply only functionality-preserving simplifications; re-run `python3 -m pytest -q` after.

- [ ] **Step 3: Code review**

Invoke the `pr-review-toolkit:code-reviewer` agent on `git diff main...HEAD`. Triage findings: fix HIGH/correctness inline (with a test if behavioral), record MINOR/NIT decisions. Re-run the suite after any change.

- [ ] **Step 4: Final verification**

Run: `python3 -m pytest -q && python3 -c "compile(open('gen_ref_pages.py').read(),'g','exec'); print('gen_ref ok')"`
Expected: green suite + `gen_ref ok`. Confirm `mkdocs build --strict` is still green if mkdocs is installed.

- [ ] **Step 5: Commit any review/simplify changes**

```bash
git add -A
git commit -m "chore(CCE-105): apply simplify + code-review follow-ups"
```

---

## Self-review (author checklist — completed)

- **Spec coverage:** 2a schema→Task 1; 2b grouped nav→Tasks 3-4; 2c live contracts→Task 6; 2d preflight→Task 5; 2e validation→Task 2; 2f verify→Task 6 Step 6 + Task 7. All spec deliverables mapped.
- **Placeholder scan:** none — every code/test step carries complete code; the live-render is a full heredoc.
- **Type consistency:** `assign_group(ident, groups)` signature identical in Task 3 (impl), Task 4 (test + `inspect.getsource` embed), Task 6 Step 5 (render). `groups_literal`/`assign_group_src` are the only two new `.format` fields, introduced in Task 4 and reused identically in Task 6. The fake `mkdocs_gen_files` `Nav`/`open`/`set_edit_path` surface matches what the template calls.
- **Known constraint honored:** `apply_scaffold` idempotency means the live `gen_ref_pages.py` is re-rendered explicitly (Task 6 Step 5), not via scaffolding.
