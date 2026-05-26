# Phase 1 · S — Structure + Setup Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a configurable `site:` information-architecture block to the host config, and a setup engine that scaffolds a Material-themed `docs/site-src/` skeleton (sections, `.pages` ordering, grid-card home, `mkdocs.yml`) from it — idempotently, on any repo.

**Architecture:** A new optional `site:` config block (validated by JSON schema + a semantic check in `state_io.py`) describes ordered sections. A new pure module `scripts/site_structure.py` turns that config into a scaffold plan (files + contents); `apply_scaffold` writes it without ever clobbering authored content. A thin `scripts/setup_scaffold.py` CLI exposes it, and the setup skill calls it. Nav is directory-driven via `awesome-pages` `.pages` files, so there is no hand-maintained `nav:`.

**Tech Stack:** Python stdlib + `pyyaml` + `jsonschema` (already deps). The generated site uses the mkdocs ecosystem (Material, awesome-pages, mkdocstrings) — a _doc-build_ dependency only, pinned in a new `templates/docs-requirements.txt`.

**Scope note:** This is the **S** sub-plan of Phase 1. D (Decision Archive), API (reference), and M (doc↔source map) are separate plans written _after_ S lands, so they bind to S's real interfaces. The orchestrator retargeting (page-author → `site-src`, What's New demotion, `agent_editable_paths` shift) belongs to the integration step after the generators exist; it is **out of scope here**.

**Conventions to follow (verified in-repo):**

- Tests import scripts via `sys.path.insert(0, str(_REPO_ROOT / "scripts"))` then `import <module>` (see `tests/state_io/test_config_validation_lens_editable.py:17-20`).
- Schema tests load `templates/config.schema.json` and call `jsonschema.validate` (see `tests/schemas/test_config_schema.py:8-12`).
- `state_io.py` raises `ConfigError` with an operator-actionable message; validators are pure functions wired into `load_config_validated` (see `scripts/state_io.py:75-85`).
- The `site:` block is **optional** — existing configs without it must still validate (generic-first, backward compatible).

Run the full suite at any checkpoint with: `.venv/bin/python -m pytest -q` (expected baseline before this plan: `240 passed`).

---

### Task 1: `site:` config schema (optional block)

**Files:**

- Modify: `templates/config.schema.json` (add a top-level optional `site` property; do **not** add it to `required`)
- Test: `tests/schemas/test_config_schema.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/schemas/test_config_schema.py`:

```python
def test_site_block_valid():
    cfg = yaml.safe_load("""
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
site:
  docs_dir: docs/site-src
  theme: material
  sections:
    - { key: home, path: index.md, title: Home }
    - { key: api, path: api/, title: API reference, generator: api-extract }
""")
    validate(cfg, SCHEMA)


def test_site_section_requires_key_path_title():
    cfg = yaml.safe_load("""
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: {}
sources: { git: { host: github } }
lint: {}
publishing: { base_url: https://x, build_workflow: deploy.yml, url_map_rule: standard }
notifications: {}
site:
  docs_dir: docs/site-src
  sections:
    - { key: home }
""")
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


def test_site_unknown_generator_rejected():
    cfg = yaml.safe_load("""
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: {}
sources: { git: { host: github } }
lint: {}
publishing: { base_url: https://x, build_workflow: deploy.yml, url_map_rule: standard }
notifications: {}
site:
  docs_dir: docs/site-src
  sections:
    - { key: api, path: api/, title: API, generator: not-a-generator }
""")
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)


def test_config_without_site_block_still_valid():
    # Backward compatibility: site is optional.
    cfg = yaml.safe_load("""
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/core }
sources: { git: { host: github } }
lint: {}
publishing: { base_url: https://x, build_workflow: deploy.yml, url_map_rule: standard }
notifications: {}
""")
    validate(cfg, SCHEMA)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/schemas/test_config_schema.py -q`
Expected: the three new `site` tests behave wrong (unknown-generator + missing-fields do NOT raise yet because the schema ignores unknown `site`), so `test_site_unknown_generator_rejected` and `test_site_section_requires_key_path_title` FAIL. `test_config_without_site_block_still_valid` passes.

- [ ] **Step 3: Add the `site` schema block**

In `templates/config.schema.json`, add to `properties` (after `"notifications"`), keeping `site` out of the top-level `required` array:

```json
    "site": {
      "type": "object",
      "required": ["docs_dir", "sections"],
      "properties": {
        "docs_dir": { "type": "string" },
        "theme": { "type": "string", "enum": ["material", "mkdocs"], "default": "material" },
        "sections": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["key", "path", "title"],
            "additionalProperties": false,
            "properties": {
              "key": { "type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$" },
              "path": { "type": "string" },
              "title": { "type": "string" },
              "generator": {
                "type": "string",
                "enum": ["archive-index", "api-extract", "changelog", "agent-authored"]
              },
              "extractors": {
                "type": "array",
                "items": { "type": "string", "enum": ["python-mkdocstrings", "openapi", "json-schema"] }
              },
              "sources": { "type": "array", "items": { "type": "string" } }
            }
          }
        }
      }
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/schemas/test_config_schema.py -q`
Expected: PASS (all, including the four new tests).

- [ ] **Step 5: Commit**

```bash
git add templates/config.schema.json tests/schemas/test_config_schema.py
git commit -m "feat(CCE-23): add optional site: block to config schema

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Semantic validation of `site:` sections

JSON schema can't check cross-field rules (paths under `docs_dir`, unique keys). Add a pure validator and wire it into `load_config_validated`, mirroring `_validate_lens_paths_are_editable`.

**Files:**

- Modify: `scripts/state_io.py` (add `_validate_site_sections`; call it from `load_config_validated`)
- Test: `tests/state_io/test_site_validation.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/state_io/test_site_validation.py`:

```python
"""CCE-23: load_config_validated rejects internally-inconsistent site: blocks."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from state_io import ConfigError, load_config_validated  # noqa: E402

_TAIL = """
sources:
  git: { host: github.com }
lint: {}
publishing:
  base_url: "https://example.com"
  build_workflow: "ci.yml"
  url_map_rule: "strip-ext"
notifications: {}
"""

_DOCS = """
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths: {}
"""


def _write(tmp_path: Path, site_body: str) -> Path:
    p = tmp_path / "config.yml"
    p.write_text(_DOCS + site_body + _TAIL)
    return p


def test_valid_site_passes(tmp_path: Path):
    cfg = load_config_validated(_write(tmp_path, """
site:
  docs_dir: docs/site-src
  sections:
    - { key: home, path: index.md, title: Home }
    - { key: api, path: api/, title: API reference, generator: api-extract }
"""))
    assert cfg["site"]["sections"][0]["key"] == "home"


def test_duplicate_section_key_raises(tmp_path: Path):
    with pytest.raises(ConfigError) as exc:
        load_config_validated(_write(tmp_path, """
site:
  docs_dir: docs/site-src
  sections:
    - { key: api, path: api/, title: API }
    - { key: api, path: api2/, title: API 2 }
"""))
    assert "duplicate" in str(exc.value).lower() and "api" in str(exc.value)


def test_section_path_outside_docs_dir_raises(tmp_path: Path):
    with pytest.raises(ConfigError) as exc:
        load_config_validated(_write(tmp_path, """
site:
  docs_dir: docs/site-src
  sections:
    - { key: home, path: ../escape.md, title: Home }
"""))
    assert "docs_dir" in str(exc.value) or "outside" in str(exc.value)


def test_no_site_block_is_fine(tmp_path: Path):
    cfg = load_config_validated(_write(tmp_path, ""))
    assert "site" not in cfg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/state_io/test_site_validation.py -q`
Expected: `test_duplicate_section_key_raises` and `test_section_path_outside_docs_dir_raises` FAIL (no validator yet). The other two pass.

- [ ] **Step 3: Implement the validator**

In `scripts/state_io.py`, add after `_validate_lens_paths_are_editable` (before `load_config_validated`):

```python
def _validate_site_sections(config: dict) -> None:
    """Cross-field checks for the optional site: block.

    - section keys are unique
    - every section path resolves *inside* docs_dir (no traversal/escape)
    Schema (templates/config.schema.json) already enforces presence/types
    and the generator enum; this covers what schema can't express.
    """
    site = config.get("site")
    if not site:
        return
    docs_dir = (site.get("docs_dir") or "").rstrip("/")
    sections = site.get("sections", []) or []

    seen: set[str] = set()
    dupes: list[str] = []
    for s in sections:
        k = s.get("key", "")
        if k in seen:
            dupes.append(k)
        seen.add(k)
    if dupes:
        raise ConfigError(f"site.sections has duplicate key(s): {sorted(set(dupes))}")

    base = PurePosixPath(docs_dir)
    for s in sections:
        rel = (s.get("path") or "").rstrip("/")
        full = (base / rel)
        # Reject any path that climbs out of docs_dir.
        if ".." in PurePosixPath(rel).parts or not str(full).startswith(docs_dir):
            raise ConfigError(
                f"site.section '{s.get('key')}' path {rel!r} resolves outside "
                f"docs_dir {docs_dir!r}"
            )
```

Add the import at the top of `state_io.py` (next to the existing `from pathlib import Path`):

```python
from pathlib import Path, PurePosixPath
```

Wire it into `load_config_validated`, right after the existing lens check:

```python
    _validate_lens_paths_are_editable(raw)
    _validate_site_sections(raw)
    return raw
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/state_io/test_site_validation.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/state_io.py tests/state_io/test_site_validation.py
git commit -m "feat(CCE-23): semantic validation for site: sections (unique keys, contained paths)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Default `site:` template (Candidate A)

**Files:**

- Create: `templates/site.default.yaml`
- Test: `tests/site/__init__.py` (create, empty), `tests/site/test_default_template.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/site/test_default_template.py`:

```python
"""CCE-23: the shipped default site template is valid and is Candidate A."""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import validate

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = json.loads((_REPO_ROOT / "templates" / "config.schema.json").read_text())


def test_default_template_matches_schema_and_candidate_a():
    site = yaml.safe_load((_REPO_ROOT / "templates" / "site.default.yaml").read_text())
    # validate just the site fragment against the schema's site subschema
    validate({"site": site}, {"type": "object", "properties": _SCHEMA["properties"]})
    keys = [s["key"] for s in site["sections"]]
    assert keys == ["home", "architecture", "api", "operations", "archive", "whats-new"]
    assert site["docs_dir"] == "docs/site-src"
    assert site["theme"] == "material"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/site/test_default_template.py -q`
Expected: FAIL — `FileNotFoundError` (template not created yet).

- [ ] **Step 3: Create the default template**

Create `templates/site.default.yaml`:

```yaml
docs_dir: docs/site-src
theme: material
sections:
  - { key: home, path: index.md, title: Home }
  - {
      key: architecture,
      path: architecture/,
      title: Architecture,
      generator: agent-authored,
    }
  - {
      key: api,
      path: api/,
      title: API reference,
      generator: api-extract,
      extractors: [python-mkdocstrings],
    }
  - { key: operations, path: operations/, title: Operations }
  - {
      key: archive,
      path: archive/,
      title: Decision Archive,
      generator: archive-index,
      sources:
        [
          docs/superpowers/specs,
          docs/superpowers/plans,
          docs/superpowers/measurements,
        ],
    }
  - {
      key: whats-new,
      path: whats-new.md,
      title: What's New,
      generator: changelog,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/site/test_default_template.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/site.default.yaml tests/site/__init__.py tests/site/test_default_template.py
git commit -m "feat(CCE-23): ship default site template (Candidate A IA)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: Scaffold plan — `scripts/site_structure.py`

A pure function that turns a `site:` config into a list of files to create. No I/O here (testable in isolation); writing happens in Task 7.

**Files:**

- Create: `scripts/site_structure.py`
- Test: `tests/site/test_site_structure.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/site/test_site_structure.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import site_structure  # noqa: E402

SITE = {
    "docs_dir": "docs/site-src",
    "theme": "material",
    "sections": [
        {"key": "home", "path": "index.md", "title": "Home"},
        {"key": "api", "path": "api/", "title": "API reference", "generator": "api-extract"},
    ],
}


def test_plan_scaffold_emits_index_and_section_dirs():
    files = {f.path: f for f in site_structure.plan_scaffold(SITE)}
    # the home page
    assert "docs/site-src/index.md" in files
    # a directory section gets an index stub + a .pages
    assert "docs/site-src/api/index.md" in files
    assert "docs/site-src/api/.pages" in files
    # a root .pages orders the sections
    assert "docs/site-src/.pages" in files


def test_section_index_stub_has_title_and_draft_frontmatter():
    files = {f.path: f for f in site_structure.plan_scaffold(SITE)}
    stub = files["docs/site-src/api/index.md"].content
    assert "title: API reference" in stub
    assert "status: draft" in stub


def test_page_section_has_no_directory():
    # whats-new style single-page section (path ends in .md) → no dir/.pages
    site = {"docs_dir": "docs/site-src", "sections": [
        {"key": "whats-new", "path": "whats-new.md", "title": "What's New"}]}
    paths = {f.path for f in site_structure.plan_scaffold(site)}
    assert "docs/site-src/whats-new.md" in paths
    assert "docs/site-src/whats-new.md/.pages" not in paths
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/site/test_site_structure.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'site_structure'`.

- [ ] **Step 3: Implement the module**

Create `scripts/site_structure.py`:

```python
"""Pure helpers that turn a site: config block into a scaffold plan.

No filesystem I/O lives here — `plan_scaffold` returns the intended files
and `apply_scaffold` (added later) does the writing. Keeping the planning
pure makes the structure trivially testable.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScaffoldFile:
    path: str          # repo-relative POSIX path
    content: str
    kind: str          # "home" | "section-index" | "pages" | "root-pages"


def _is_page(section: dict) -> bool:
    """A section whose path ends in .md is a single page, not a directory."""
    return section.get("path", "").endswith(".md")


def _section_index_stub(section: dict) -> str:
    return (
        "---\n"
        f"title: {section['title']}\n"
        "status: draft\n"
        "---\n\n"
        f"# {section['title']}\n\n"
        "_This section is scaffolded. Content will be added here._\n"
    )


def _page_stub(section: dict) -> str:
    return (
        "---\n"
        f"title: {section['title']}\n"
        "status: draft\n"
        "---\n\n"
        f"# {section['title']}\n"
    )


def plan_scaffold(site: dict) -> list[ScaffoldFile]:
    docs_dir = site["docs_dir"].rstrip("/")
    sections = site.get("sections", [])
    files: list[ScaffoldFile] = []

    # Root .pages: orders the top-level nav by section title, in config order.
    nav_lines = "\n".join(f"  - {s['title']}: {s['path']}" for s in sections)
    files.append(ScaffoldFile(f"{docs_dir}/.pages", f"nav:\n{nav_lines}\n", "root-pages"))

    for s in sections:
        path = s["path"].rstrip("/")
        if _is_page(s):
            files.append(ScaffoldFile(f"{docs_dir}/{path}", _page_stub(s), "section-index"))
            continue
        # directory section: index stub + a .pages giving the section its title
        files.append(
            ScaffoldFile(f"{docs_dir}/{path}/index.md", _section_index_stub(s), "section-index")
        )
        files.append(
            ScaffoldFile(f"{docs_dir}/{path}/.pages", f"title: {s['title']}\n", "pages")
        )

    return files
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/site/test_site_structure.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/site_structure.py tests/site/test_site_structure.py
git commit -m "feat(CCE-23): site_structure.plan_scaffold — pure scaffold planner

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: Render `mkdocs.yml` (Material + plugins)

`mkdocs.yml` is rendered from a template **string**, not `yaml.dump`, because the mermaid custom-fence needs the literal `!!python/name:pymdownx.superfences.fence_code_format` tag that a safe YAML dump cannot emit (this is the exact pitfall ADIS documents in its own `mkdocs.yml`).

**Files:**

- Modify: `scripts/site_structure.py` (add `render_mkdocs_yaml`)
- Test: `tests/site/test_mkdocs_render.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/site/test_mkdocs_render.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import site_structure  # noqa: E402

SITE = {"docs_dir": "docs/site-src", "theme": "material", "sections": []}


def test_mkdocs_yaml_has_material_and_awesome_pages():
    out = site_structure.render_mkdocs_yaml(SITE, site_name="Demo", python_detected=False)
    assert "name: material" in out
    assert "navigation.sections" in out
    assert "awesome-pages" in out
    assert "docs_dir: docs/site-src" in out
    # the mermaid custom fence python tag must be present verbatim
    assert "!!python/name:pymdownx.superfences.fence_code_format" in out
    # no mkdocstrings when python not detected
    assert "mkdocstrings" not in out


def test_mkdocs_yaml_adds_mkdocstrings_when_python():
    out = site_structure.render_mkdocs_yaml(SITE, site_name="Demo", python_detected=True)
    assert "mkdocstrings" in out


def test_mkdocs_yaml_is_parseable_yaml():
    # The !!python/name: tag can't be safe_load'd, and unsafe_load would try to
    # *import* pymdownx (a doc-build dep we don't install in the unit venv). Use
    # a SafeLoader with a no-op constructor for that tag so this test is
    # deterministic regardless of what's installed.
    class _Loader(yaml.SafeLoader):
        pass

    _Loader.add_multi_constructor(
        "tag:yaml.org,2002:python/name:", lambda loader, suffix, node: None
    )
    out = site_structure.render_mkdocs_yaml(SITE, site_name="Demo", python_detected=False)
    loaded = yaml.load(out, Loader=_Loader)
    assert loaded["theme"]["name"] == "material"
    assert loaded["docs_dir"] == "docs/site-src"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/site/test_mkdocs_render.py -q`
Expected: FAIL — `AttributeError: module 'site_structure' has no attribute 'render_mkdocs_yaml'`.

- [ ] **Step 3: Implement `render_mkdocs_yaml`**

Append to `scripts/site_structure.py`:

```python
_MKDOCS_TEMPLATE = """\
site_name: {site_name}
docs_dir: {docs_dir}
site_dir: site

theme:
  name: {theme}
  features:
    - navigation.tabs
    - navigation.sections
    - navigation.indexes
    - navigation.top
    - toc.follow
    - search.suggest
    - content.code.copy

plugins:
  - search
  - awesome-pages
{mkdocstrings_plugin}
markdown_extensions:
  - admonition
  - attr_list
  - md_in_html
  - tables
  - toc:
      permalink: true
  - pymdownx.highlight
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
  - pymdownx.details
"""

_MKDOCSTRINGS_BLOCK = """\
  - mkdocstrings:
      handlers:
        python:
          options:
            show_source: false
"""


def render_mkdocs_yaml(site: dict, *, site_name: str, python_detected: bool) -> str:
    return _MKDOCS_TEMPLATE.format(
        site_name=site_name,
        docs_dir=site["docs_dir"].rstrip("/"),
        theme=site.get("theme", "material"),
        mkdocstrings_plugin=_MKDOCSTRINGS_BLOCK if python_detected else "",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/site/test_mkdocs_render.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/site_structure.py tests/site/test_mkdocs_render.py
git commit -m "feat(CCE-23): render Material mkdocs.yml (mermaid fence + optional mkdocstrings)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: Render the grid-card Home page

**Files:**

- Modify: `scripts/site_structure.py` (add `render_home`; call it from `plan_scaffold` for the `home` section)
- Test: `tests/site/test_home_render.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/site/test_home_render.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import site_structure  # noqa: E402

SITE = {
    "docs_dir": "docs/site-src",
    "sections": [
        {"key": "home", "path": "index.md", "title": "Home"},
        {"key": "api", "path": "api/", "title": "API reference"},
        {"key": "operations", "path": "operations/", "title": "Operations"},
    ],
}


def test_home_uses_grid_cards_and_links_non_home_sections():
    home = site_structure.render_home(SITE)
    assert '<div class="grid cards" markdown>' in home
    assert "API reference" in home and "api/" in home
    assert "Operations" in home and "operations/" in home
    # the home section itself is not a card linking to itself
    assert home.count("](index.md)") == 0


def test_plan_scaffold_home_uses_grid_cards():
    files = {f.path: f for f in site_structure.plan_scaffold(SITE)}
    assert '<div class="grid cards" markdown>' in files["docs/site-src/index.md"].content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/site/test_home_render.py -q`
Expected: FAIL — `render_home` missing, and `plan_scaffold` currently emits a plain page stub for `home`.

- [ ] **Step 3: Implement `render_home` and use it in `plan_scaffold`**

Append to `scripts/site_structure.py`:

```python
def render_home(site: dict) -> str:
    cards = []
    for s in site.get("sections", []):
        if s["key"] == "home":
            continue
        cards.append(f"-   __{s['title']}__\n\n    [Open →]({s['path']})")
    grid = '<div class="grid cards" markdown>\n\n' + "\n\n".join(cards) + "\n\n</div>"
    return (
        "---\ntitle: Home\nhide:\n  - toc\n---\n\n"
        "# Documentation\n\n"
        "Pick a section to get started.\n\n"
        f"{grid}\n"
    )
```

Then replace the `for s in sections:` loop in `plan_scaffold` (from Task 4) with this version, which adds the `home` special-case before the generic page/dir handling. The lines after the new `if` branch are unchanged from Task 4:

```python
    for s in sections:
        if s["key"] == "home":
            files.append(
                ScaffoldFile(f"{docs_dir}/{s['path'].rstrip('/')}", render_home(site), "home")
            )
            continue
        path = s["path"].rstrip("/")
        if _is_page(s):
            files.append(ScaffoldFile(f"{docs_dir}/{path}", _page_stub(s), "section-index"))
            continue
        # directory section: index stub + a .pages giving the section its title
        files.append(
            ScaffoldFile(f"{docs_dir}/{path}/index.md", _section_index_stub(s), "section-index")
        )
        files.append(
            ScaffoldFile(f"{docs_dir}/{path}/.pages", f"title: {s['title']}\n", "pages")
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/site/test_home_render.py tests/site/test_site_structure.py -q`
Expected: PASS (both files green — the earlier `plan_scaffold` tests use no `home` section, so they are unaffected).

- [ ] **Step 5: Commit**

```bash
git add scripts/site_structure.py tests/site/test_home_render.py
git commit -m "feat(CCE-23): grid-card Home page renderer

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: Idempotent `apply_scaffold` (never clobber authored content)

**Files:**

- Modify: `scripts/site_structure.py` (add `apply_scaffold`)
- Test: `tests/site/test_apply_scaffold.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/site/test_apply_scaffold.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import site_structure  # noqa: E402

SITE = {
    "docs_dir": "docs/site-src",
    "theme": "material",
    "sections": [
        {"key": "home", "path": "index.md", "title": "Home"},
        {"key": "api", "path": "api/", "title": "API reference"},
    ],
}


def test_apply_creates_files(tmp_path: Path):
    result = site_structure.apply_scaffold(tmp_path, SITE, site_name="Demo", python_detected=False)
    assert (tmp_path / "docs/site-src/index.md").exists()
    assert (tmp_path / "docs/site-src/api/index.md").exists()
    assert (tmp_path / "mkdocs.yml").exists()
    assert "docs/site-src/api/index.md" in result["created"]


def test_apply_is_idempotent_and_never_clobbers(tmp_path: Path):
    site_structure.apply_scaffold(tmp_path, SITE, site_name="Demo", python_detected=False)
    # an author edits a stub
    page = tmp_path / "docs/site-src/api/index.md"
    page.write_text("# API\n\nReal authored content.\n")
    # re-run (structure-sync)
    result = site_structure.apply_scaffold(tmp_path, SITE, site_name="Demo", python_detected=False)
    assert page.read_text() == "# API\n\nReal authored content.\n"  # untouched
    assert "docs/site-src/api/index.md" in result["skipped"]


def test_apply_adds_new_section_on_resync(tmp_path: Path):
    site_structure.apply_scaffold(tmp_path, SITE, site_name="Demo", python_detected=False)
    site2 = {**SITE, "sections": SITE["sections"] + [
        {"key": "operations", "path": "operations/", "title": "Operations"}]}
    result = site_structure.apply_scaffold(tmp_path, site2, site_name="Demo", python_detected=False)
    assert (tmp_path / "docs/site-src/operations/index.md").exists()
    assert "docs/site-src/operations/index.md" in result["created"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/site/test_apply_scaffold.py -q`
Expected: FAIL — `apply_scaffold` missing.

- [ ] **Step 3: Implement `apply_scaffold`**

First add `from pathlib import Path` to the import block at the **top** of `scripts/site_structure.py` (alongside `from dataclasses import dataclass`). Then append this function to the end of the file:

```python
def apply_scaffold(
    repo_root: Path, site: dict, *, site_name: str, python_detected: bool
) -> dict:
    """Write the scaffold under repo_root. Idempotent: existing files are
    left untouched (never clobber authored content); only missing files are
    created. Returns {"created": [...], "skipped": [...]}.
    """
    repo_root = Path(repo_root)
    created: list[str] = []
    skipped: list[str] = []

    planned = list(plan_scaffold(site))
    planned.append(
        ScaffoldFile(
            "mkdocs.yml",
            render_mkdocs_yaml(site, site_name=site_name, python_detected=python_detected),
            "mkdocs",
        )
    )

    for f in planned:
        target = repo_root / f.path
        if target.exists():
            skipped.append(f.path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content)
        created.append(f.path)

    return {"created": created, "skipped": skipped}
```

Note: `mkdocs.yml` is in the "never clobber" set too — re-running setup won't overwrite a hand-tuned `mkdocs.yml`. (A future explicit `--force-mkdocs` flag can override; out of scope here.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/site/test_apply_scaffold.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/site_structure.py tests/site/test_apply_scaffold.py
git commit -m "feat(CCE-23): idempotent apply_scaffold (create-missing, never clobber)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: `setup_scaffold.py` CLI + docs-requirements + setup-skill wiring

**Files:**

- Create: `scripts/setup_scaffold.py`
- Create: `templates/docs-requirements.txt`
- Modify: `skills/engineering-docs-agent-setup/SKILL.md` (add the scaffold step)
- Test: `tests/site/test_setup_scaffold_cli.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/site/test_setup_scaffold_cli.py`:

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI = _REPO_ROOT / "scripts" / "setup_scaffold.py"


def test_cli_scaffolds_default_template(tmp_path: Path):
    # a python file present → mkdocstrings should be wired
    (tmp_path / "thing.py").write_text("x = 1\n")
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--repo-root", str(tmp_path), "--site-name", "Demo"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "docs/site-src/index.md").exists()
    assert (tmp_path / "docs/site-src/archive/index.md").exists()
    assert (tmp_path / "mkdocs.yml").exists()
    assert "mkdocstrings" in (tmp_path / "mkdocs.yml").read_text()


def test_cli_rerun_is_idempotent(tmp_path: Path):
    cmd = [sys.executable, str(_CLI), "--repo-root", str(tmp_path), "--site-name", "Demo"]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    (tmp_path / "docs/site-src/index.md").write_text("authored\n")
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert (tmp_path / "docs/site-src/index.md").read_text() == "authored\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/site/test_setup_scaffold_cli.py -q`
Expected: FAIL — CLI does not exist.

- [ ] **Step 3: Implement the CLI**

Create `scripts/setup_scaffold.py`:

```python
"""CLI: scaffold the site: structure into a host repo (idempotent).

Used by the engineering-docs-agent-setup skill. With no --config, uses the
shipped default template (templates/site.default.yaml). Detects Python in the
repo to decide whether to wire mkdocstrings into mkdocs.yml.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

# Run with scripts/ on the path so `import site_structure` resolves whether the
# CLI is launched as a script or imported. (Running it as a script already puts
# its own dir on sys.path[0]; this makes that explicit and import-safe too.)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_structure  # noqa: E402

_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def _python_detected(repo_root: Path) -> bool:
    # cheap heuristic: any .py outside common vendor dirs, or a pyproject.toml
    if (repo_root / "pyproject.toml").exists():
        return True
    for p in repo_root.rglob("*.py"):
        if not any(part in {".venv", "node_modules", "site", "__pycache__"} for part in p.parts):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument("--site-name", default="Documentation")
    ap.add_argument("--config", type=Path, default=None,
                    help="site: YAML; defaults to templates/site.default.yaml")
    args = ap.parse_args()

    site_path = args.config or (_TEMPLATES / "site.default.yaml")
    site = yaml.safe_load(site_path.read_text())

    result = site_structure.apply_scaffold(
        args.repo_root, site,
        site_name=args.site_name,
        python_detected=_python_detected(args.repo_root),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Create the docs-tooling requirements file**

Create `templates/docs-requirements.txt`:

```
# Documentation-build dependencies (NOT agent runtime deps).
# Installed in the host repo's docs tooling / CI to build the site.
mkdocs-material>=9.5
mkdocs-awesome-pages-plugin>=2.9
mkdocstrings[python]>=0.25
mkdocs-gen-files>=0.5
mkdocs-literate-nav>=0.6
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/site/test_setup_scaffold_cli.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Wire the setup skill**

Read `skills/engineering-docs-agent-setup/SKILL.md` first to find the Procedure list. Add the scaffold step **immediately after the step that writes `config.yml`/`state.json`** (so the config exists before scaffolding), and renumber any following steps. The added step:

```markdown
7. Scaffold the documentation site structure:
   `python <plugin_root>/scripts/setup_scaffold.py --repo-root . --site-name "<repo title>"`
   This writes `docs/site-src/` (sections + grid-card home + .pages) and a
   Material `mkdocs.yml` from `templates/site.default.yaml`. It is idempotent —
   re-running adds newly-configured sections and never overwrites authored
   pages. Tell the user to `pip install -r <plugin_root>/templates/docs-requirements.txt`
   to build the site locally (`mkdocs serve`).
```

- [ ] **Step 7: Commit**

```bash
git add scripts/setup_scaffold.py templates/docs-requirements.txt \
        skills/engineering-docs-agent-setup/SKILL.md tests/site/test_setup_scaffold_cli.py
git commit -m "feat(CCE-23): setup_scaffold CLI + docs-requirements + setup-skill wiring

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9: Build-gate smoke — scaffolded site builds under `mkdocs --strict`

Proves the generated `mkdocs.yml` + skeleton actually builds. Gated on mkdocs being installed; skipped cleanly otherwise (keeps the unit suite green on machines without the doc-build deps).

**Files:**

- Test: `tests/site/test_mkdocs_build_smoke.py` (create)

- [ ] **Step 1: Write the test**

Create `tests/site/test_mkdocs_build_smoke.py`:

```python
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI = _REPO_ROOT / "scripts" / "setup_scaffold.py"

pytestmark = pytest.mark.skipif(
    shutil.which("mkdocs") is None, reason="mkdocs not installed (doc-build dep)"
)


def test_scaffolded_site_builds_strict(tmp_path: Path):
    subprocess.run(
        [sys.executable, str(_CLI), "--repo-root", str(tmp_path), "--site-name", "Demo"],
        capture_output=True, text=True, check=True,
    )
    proc = subprocess.run(
        ["mkdocs", "build", "--strict"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/site/test_mkdocs_build_smoke.py -q`
Expected: PASS if mkdocs+material+awesome-pages are installed; otherwise SKIPPED. If it FAILS, the failure output names the mkdocs strict error (e.g. a nav/awesome-pages issue) to fix in `render_mkdocs_yaml`/`.pages`.

- [ ] **Step 3: Commit**

```bash
git add tests/site/test_mkdocs_build_smoke.py
git commit -m "test(CCE-23): mkdocs --strict build smoke for scaffolded site

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Run the full suite: `.venv/bin/python -m pytest -q` — expected `≥ 240 + new tests passed` (mkdocs smoke SKIPPED if deps absent), zero regressions.
- [ ] Manual smoke (optional, needs doc-build deps): in a scratch dir, `python scripts/setup_scaffold.py --repo-root . --site-name Demo && pip install -r templates/docs-requirements.txt && mkdocs serve`, then open the Home grid-card page and confirm section nav renders.

## Spec coverage check (S only)

| Spec requirement (S)                                                    | Task |
| ----------------------------------------------------------------------- | ---- |
| `site:` config block + validation                                       | 1, 2 |
| Default IA = Candidate A                                                | 3    |
| Scaffold dirs + section index stubs + `.pages`                          | 4    |
| Material `mkdocs.yml` (theme/features/mermaid/mkdocstrings-when-python) | 5    |
| Grid-card Home                                                          | 6    |
| Idempotent structure-sync (never clobber)                               | 7    |
| Setup-skill wiring + doc-build deps + CLI                               | 8    |
| `mkdocs build --strict` build gate                                      | 9    |
| Generic-first (site optional; Python-detected mkdocstrings)             | 1, 8 |

**Deferred to later Phase-1 sub-plans (not here):** D (Decision Archive generator — note `tests/orchestrator/test_archive_indexes.py` already exists; the D plan must reconcile with it), API (mkdocstrings `gen-files`/`literate-nav` page generation), M (doc↔source map), and the orchestrator integration (page-author → `site-src`, What's New demotion, `agent_editable_paths` shift, `lens_paths`→sections fold).
