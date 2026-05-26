# API Reference Section (Phase 1 — API) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the `api-extract` capability S stubbed — auto-generated Python API reference, a deterministic JSON-schema contracts page, and an opt-in OpenAPI page — all detection/config-driven so they run on any host repo.

**Architecture:** Hybrid. Python + OpenAPI are **build-time** (mkdocs plugins wired by `render_mkdocs_yaml` + a committed `gen_ref_pages.py`); JSON-schema contracts are a **deterministic stdlib generator** (`scripts/contracts_doc.py`, same shape as D's `archive_indexes.py`). Every extractor **skips cleanly** when its convention is absent.

**Tech Stack:** Python 3.9+ stdlib + `pyyaml` (agent runtime); mkdocs-material + `mkdocstrings[python]` + `mkdocs-gen-files` + `mkdocs-literate-nav` + one OpenAPI render plugin (build-time only). pytest, fixture-driven, `--import-mode=importlib`.

**Branch:** `feat/CCE-23-api-reference`, stacked on `feat/CCE-23-structured-docs-site` (PR #24). Self-contained: does NOT depend on D's branch additions.

**Spec:** `docs/superpowers/specs/2026-05-25-cce23-api-reference-design.md`

---

## File Structure

| File                                    | Responsibility                                                                | Action |
| --------------------------------------- | ----------------------------------------------------------------------------- | ------ |
| `scripts/setup_discover.py`             | `detect_python` + OpenAPI hint; `discover()` output                           | Modify |
| `scripts/contracts_doc.py`              | JSON-schema → markdown contracts pages + CLI (stdlib)                         | Create |
| `scripts/state_io.py`                   | `_validate_api_sections` + call from `load_config_validated`                  | Modify |
| `templates/config.schema.json`          | add `openapi` string property to a section                                    | Modify |
| `scripts/site_structure.py`             | `render_mkdocs_yaml` API plugins; `gen_ref_pages.py` + `api/http.md` scaffold | Modify |
| `templates/docs-requirements.txt`       | add the OpenAPI render plugin                                                 | Modify |
| `tests/setup/test_detect_python.py`     | detection unit tests                                                          | Create |
| `tests/state_io/test_api_validation.py` | api-extract config validation                                                 | Create |
| `tests/site/test_contracts_render.py`   | pure render/parse                                                             | Create |
| `tests/site/test_contracts_generate.py` | generate ledger + skips                                                       | Create |
| `tests/site/test_contracts_cli.py`      | CLI                                                                           | Create |
| `tests/site/test_mkdocs_api_wiring.py`  | mkdocs.yml plugin wiring                                                      | Create |
| `tests/site/test_api_scaffold.py`       | gen-script + http stub scaffold                                               | Create |
| `tests/site/test_api_build_smoke.py`    | `mkdocs build --strict`, skip-clean                                           | Create |
| `tests/fixtures/api/**`                 | fixture host repos                                                            | Create |

**Detection contract (used across tasks):** `detect_python(cwd)` returns
`{"detected": bool, "scan_dir": str | None, "path_root": str | None}` where `scan_dir` is the directory to walk for `*.py`, and `path_root` is what goes on `mkdocstrings.handlers.python.paths` (so a module identifier is its path relative to `path_root`). Loose modules → `scan_dir == path_root` (e.g. `"scripts"`); a top-level package → `scan_dir == "<pkg>"`, `path_root == "."`.

**Module-identifier rule (used in Tasks 1, 7, 9):** `ident = ".".join(Path(py).relative_to(path_root).with_suffix("").parts)`.

---

### Task 1: Python detection

**Files:**

- Modify: `scripts/setup_discover.py`
- Test: `tests/setup/test_detect_python.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/setup/test_detect_python.py
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import setup_discover  # noqa: E402


def test_detects_top_level_package(tmp_path):
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text("def f(): ...\n")
    out = setup_discover.detect_python(tmp_path)
    assert out == {"detected": True, "scan_dir": "mypkg", "path_root": "."}


def test_detects_loose_modules_in_scripts(tmp_path):
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "thing.py").write_text("x = 1\n")
    out = setup_discover.detect_python(tmp_path)
    assert out == {"detected": True, "scan_dir": "scripts", "path_root": "scripts"}


def test_no_python_returns_undetected(tmp_path):
    (tmp_path / "README.md").write_text("# hi\n")
    out = setup_discover.detect_python(tmp_path)
    assert out == {"detected": False, "scan_dir": None, "path_root": None}


def test_package_wins_over_loose_dir(tmp_path):
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    loose = tmp_path / "scripts"
    loose.mkdir()
    (loose / "z.py").write_text("y = 2\n")
    out = setup_discover.detect_python(tmp_path)
    assert out["scan_dir"] == "app" and out["path_root"] == "."


def test_discover_includes_python_and_openapi_hint(tmp_path):
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "a.py").write_text("a = 1\n")
    (tmp_path / "openapi.json").write_text("{}")
    out = setup_discover.discover(tmp_path)
    assert out["python"]["detected"] is True
    assert out["openapi_hint"] == "openapi.json"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/setup/test_detect_python.py -q`
Expected: FAIL (`module 'setup_discover' has no attribute 'detect_python'`).

- [ ] **Step 3: Implement**

Add to `scripts/setup_discover.py` (after `detect_jira_hint`):

```python
_LOOSE_DIRS = ("src", "scripts")
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "build", "dist", "tests", "test"}


def detect_python(cwd: Path) -> dict:
    """Resolve a Python source root generically.

    Returns {"detected", "scan_dir", "path_root"}: scan_dir is walked for
    *.py; path_root goes on mkdocstrings' `paths` so a module identifier is
    its path relative to path_root. A top-level package (a dir with
    __init__.py) wins; else a conventional loose-module dir (src/scripts).
    """
    for child in sorted(cwd.iterdir()):
        if (
            child.is_dir()
            and child.name not in _SKIP_DIRS
            and not child.name.startswith(".")
            and (child / "__init__.py").exists()
        ):
            return {"detected": True, "scan_dir": child.name, "path_root": "."}
    for name in _LOOSE_DIRS:
        d = cwd / name
        if d.is_dir() and any(d.glob("*.py")):
            return {"detected": True, "scan_dir": name, "path_root": name}
    return {"detected": False, "scan_dir": None, "path_root": None}


def detect_openapi_hint(cwd: Path) -> str | None:
    """Return a repo-relative committed OpenAPI schema path, or None."""
    for name in ("openapi.json", "openapi.yaml", "openapi.yml"):
        if (cwd / name).exists():
            return name
    return None
```

Then extend `discover()` — add these two keys to the `out` dict (before the `if warnings:` block):

```python
        "python": detect_python(cwd),
        "openapi_hint": detect_openapi_hint(cwd),
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/setup/test_detect_python.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/setup_discover.py tests/setup/test_detect_python.py
git commit -m "feat(CCE-23): detect_python + openapi hint in setup_discover"
```

---

### Task 2: Contracts render — pure functions

**Files:**

- Create: `scripts/contracts_doc.py`
- Test: `tests/site/test_contracts_render.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/site/test_contracts_render.py
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import contracts_doc  # noqa: E402

SCHEMA = {
    "title": "Page Author Output",
    "description": "What the page-author subagent returns.",
    "type": "object",
    "required": ["page_path"],
    "properties": {
        "page_path": {"type": "string", "description": "Target path"},
        "status": {"type": "string", "enum": ["draft", "final"]},
        "lines": {"type": "array", "items": {"type": "integer"}},
    },
}


def test_type_str_handles_scalar_array_and_enum():
    assert contracts_doc._type_str({"type": "string"}) == "string"
    assert contracts_doc._type_str({"type": "array", "items": {"type": "integer"}}) == "array[integer]"
    assert contracts_doc._type_str({"enum": ["a", "b"]}) == "enum"
    assert contracts_doc._type_str({"$ref": "#/$defs/Foo"}) == "Foo"


def test_render_contract_page_has_title_banner_and_table():
    page = contracts_doc.render_contract_page("page_author", SCHEMA)
    assert page.startswith("# Page Author Output")
    assert "Auto-generated" in page
    assert "What the page-author subagent returns." in page
    assert "| Property | Type | Required | Description |" in page
    assert "| `page_path` | string | yes | Target path |" in page
    assert "| `status` | enum | no |" in page


def test_render_falls_back_to_name_when_no_title():
    page = contracts_doc.render_contract_page("notifier", {"type": "object"})
    assert page.startswith("# notifier")
    assert "_No properties documented._" in page


def test_render_escapes_pipe_in_description():
    schema = {"type": "object", "properties": {"x": {"type": "string", "description": "a | b"}}}
    page = contracts_doc.render_contract_page("x", schema)
    assert "a \\| b" in page
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/site/test_contracts_render.py -q`
Expected: FAIL (`No module named 'contracts_doc'`).

- [ ] **Step 3: Implement**

Create `scripts/contracts_doc.py`:

```python
"""Generate a JSON-Schema contracts reference page set (CCE-23 capability API).

Pure functions parse/render; `generate_contracts` is the only writer. Reads the
`json-schema` extractor's `sources` (dirs of *.json) from the site config and
emits one markdown page per schema under <docs_dir>/<api path>/contracts/, with
an index. Overwrites generated pages every run (auto-generated banner). Skips a
missing/empty source cleanly; never emits an empty page set.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import ConfigError, load_config_validated  # noqa: E402


def _type_str(prop: dict) -> str:
    if "$ref" in prop:
        return str(prop["$ref"]).rsplit("/", 1)[-1]
    if "enum" in prop:
        return "enum"
    t = prop.get("type")
    if t == "array":
        items = prop.get("items") or {}
        return f"array[{_type_str(items)}]" if items else "array"
    if isinstance(t, list):
        return " | ".join(str(x) for x in t)
    return str(t) if t else "—"


def render_contract_page(name: str, schema: dict) -> str:
    title = schema.get("title") or name
    lines = [
        f"# {title}",
        "",
        "_Auto-generated from JSON Schema; do not edit by hand — "
        "see `scripts/contracts_doc.py`._",
        "",
    ]
    desc = schema.get("description")
    if desc:
        lines += [str(desc), ""]
    props = schema.get("properties") or {}
    if not props:
        lines += ["_No properties documented._", ""]
        return "\n".join(lines)
    required = set(schema.get("required") or [])
    lines += ["| Property | Type | Required | Description |", "|---|---|---|---|"]
    for pname, pschema in props.items():
        pschema = pschema or {}
        ptype = _type_str(pschema).replace("|", "\\|")
        req = "yes" if pname in required else "no"
        pdesc = str(pschema.get("description", "") or "").replace("|", "\\|")
        lines.append(f"| `{pname}` | {ptype} | {req} | {pdesc} |")
    lines.append("")
    return "\n".join(lines)


def render_index(names: list[str]) -> str:
    lines = ["# Contracts", "", "_Auto-generated; do not edit by hand._", ""]
    for n in sorted(names):
        lines.append(f"- [{n}]({n}.md)")
    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/site/test_contracts_render.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/contracts_doc.py tests/site/test_contracts_render.py
git commit -m "feat(CCE-23): contracts_doc pure render (JSON Schema -> markdown)"
```

---

### Task 3: Contracts generate — writer + ledger + skips

**Files:**

- Modify: `scripts/contracts_doc.py`
- Test: `tests/site/test_contracts_generate.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/site/test_contracts_generate.py
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import contracts_doc  # noqa: E402

SITE = {
    "docs_dir": "docs/site-src",
    "sections": [
        {
            "key": "api",
            "path": "api/",
            "title": "API reference",
            "generator": "api-extract",
            "extractors": ["json-schema"],
            "sources": ["schemas"],
        }
    ],
}


def _seed_schemas(repo: Path):
    d = repo / "schemas"
    d.mkdir(parents=True)
    (d / "page_author.json").write_text(
        json.dumps({"title": "Page Author", "type": "object",
                    "properties": {"page_path": {"type": "string"}},
                    "required": ["page_path"]})
    )
    (d / "notifier.json").write_text(json.dumps({"title": "Notifier", "type": "object"}))


def test_generate_writes_pages_and_index(tmp_path):
    _seed_schemas(tmp_path)
    result = contracts_doc.generate_contracts(tmp_path, SITE)
    base = tmp_path / "docs/site-src/api/contracts"
    assert (base / "page_author.md").exists()
    assert (base / "notifier.md").exists()
    assert (base / "index.md").exists()
    assert "docs/site-src/api/contracts/page_author.md" in result["written"]
    assert "Page Author" in (base / "page_author.md").read_text()


def test_generate_skips_when_no_json_schema_extractor(tmp_path):
    site = {"docs_dir": "docs/site-src",
            "sections": [{"key": "api", "path": "api/", "title": "API",
                          "generator": "api-extract", "extractors": ["python-mkdocstrings"]}]}
    assert contracts_doc.generate_contracts(tmp_path, site) == {"written": [], "skipped": []}


def test_generate_skips_missing_source_dir(tmp_path):
    result = contracts_doc.generate_contracts(tmp_path, SITE)  # no schemas/ dir
    assert result["written"] == []
    assert "schemas" in result["skipped"][0]
    assert not (tmp_path / "docs/site-src/api/contracts").exists()


def test_generate_skips_empty_source_dir(tmp_path):
    (tmp_path / "schemas").mkdir()
    result = contracts_doc.generate_contracts(tmp_path, SITE)
    assert result["written"] == []
    assert result["skipped"]  # recorded, no empty page set


def test_generate_skips_malformed_schema_keeps_others(tmp_path):
    _seed_schemas(tmp_path)
    (tmp_path / "schemas" / "broken.json").write_text("{ not json ")
    result = contracts_doc.generate_contracts(tmp_path, SITE)
    base = tmp_path / "docs/site-src/api/contracts"
    assert (base / "page_author.md").exists()
    assert not (base / "broken.md").exists()
    assert any("broken.json" in s for s in result["skipped"])


def test_generate_overwrites_stale_page(tmp_path):
    _seed_schemas(tmp_path)
    base = tmp_path / "docs/site-src/api/contracts"
    base.mkdir(parents=True)
    (base / "page_author.md").write_text("STALE\n")
    contracts_doc.generate_contracts(tmp_path, SITE)
    assert "STALE" not in (base / "page_author.md").read_text()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/site/test_contracts_generate.py -q`
Expected: FAIL (`module 'contracts_doc' has no attribute 'generate_contracts'`).

- [ ] **Step 3: Implement**

Append to `scripts/contracts_doc.py`:

```python
def _find_contracts_section(site: dict) -> dict | None:
    for s in site.get("sections", []) or []:
        if s.get("generator") == "api-extract" and "json-schema" in (
            s.get("extractors") or []
        ):
            return s
    return None


def generate_contracts(repo_root: Path, site_config: dict) -> dict:
    """Render every *.json under the json-schema section's `sources` to a
    contracts page. Returns {"written": [...], "skipped": [...]} of repo-relative
    POSIX paths. Skips (records) missing/empty sources and malformed schemas;
    never emits an empty page set.
    """
    repo_root = Path(repo_root)
    written: list[str] = []
    skipped: list[str] = []

    section = _find_contracts_section(site_config)
    if section is None:
        return {"written": written, "skipped": skipped}
    sources = section.get("sources") or []
    if not sources:
        return {"written": written, "skipped": skipped}

    docs_dir = (site_config.get("docs_dir") or "").rstrip("/")
    section_path = (section.get("path") or "").rstrip("/")
    out_dir = repo_root / docs_dir / section_path / "contracts"

    names: list[str] = []
    for source in sources:
        src_dir = repo_root / source
        if not src_dir.is_dir():
            print(f"warning: contracts source not found: {source}", file=sys.stderr)
            skipped.append(source)
            continue
        schema_files = sorted(src_dir.glob("*.json"))
        if not schema_files:
            print(f"warning: no *.json in contracts source: {source}", file=sys.stderr)
            skipped.append(source)
            continue
        for path in schema_files:
            rel = f"{docs_dir}/{section_path}/contracts/{path.stem}.md"
            try:
                schema = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                print(f"warning: skipping malformed schema {path.name}: {exc}",
                      file=sys.stderr)
                skipped.append(str(Path(source) / path.name))
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{path.stem}.md").write_text(
                render_contract_page(path.stem, schema), encoding="utf-8"
            )
            written.append(rel)
            names.append(path.stem)

    if names:
        (out_dir / "index.md").write_text(render_index(names), encoding="utf-8")
        written.append(f"{docs_dir}/{section_path}/contracts/index.md")

    return {"written": written, "skipped": skipped}
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/site/test_contracts_generate.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/contracts_doc.py tests/site/test_contracts_generate.py
git commit -m "feat(CCE-23): generate_contracts — write/skip/overwrite per source"
```

---

### Task 4: Contracts CLI

**Files:**

- Modify: `scripts/contracts_doc.py`
- Test: `tests/site/test_contracts_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/site/test_contracts_cli.py
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI = _REPO_ROOT / "scripts" / "contracts_doc.py"

_CONFIG = """\
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths: {}
sources: { git: { host: github } }
lint: {}
publishing: { base_url: "https://x", build_workflow: "ci.yml", url_map_rule: "strip-ext" }
notifications: {}
site:
  docs_dir: docs/site-src
  sections:
    - { key: api, path: api/, title: API reference, generator: api-extract,
        extractors: [json-schema], sources: [schemas] }
"""


def test_cli_generates_and_reports_json(tmp_path):
    d = tmp_path / "schemas"
    d.mkdir()
    (d / "thing.json").write_text(json.dumps({"title": "Thing", "type": "object"}))
    cfg = tmp_path / "config.yml"
    cfg.write_text(_CONFIG)
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--repo-root", str(tmp_path), "--config", str(cfg)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert "docs/site-src/api/contracts/thing.md" in result["written"]


def test_cli_invalid_yaml_errors_cleanly(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(": bad: yaml: {{{\n")
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--repo-root", str(tmp_path), "--config", str(cfg)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "error" in proc.stderr.lower()
    assert "Traceback" not in proc.stderr
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/site/test_contracts_cli.py -q`
Expected: FAIL (CLI has no `main`, no `__main__`).

- [ ] **Step 3: Implement**

Append to `scripts/contracts_doc.py` (note: this branch's `load_config_validated` does NOT wrap YAML errors, so the CLI catches `yaml.YAMLError` itself):

```python
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument("--config", type=Path, required=True,
                    help="config.yml with a site: block")
    args = ap.parse_args(argv)
    try:
        config = load_config_validated(args.config)
    except (ConfigError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    site = config.get("site")
    if not site:
        print("error: config has no site: block", file=sys.stderr)
        return 1
    result = generate_contracts(args.repo_root, site)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/site/test_contracts_cli.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/contracts_doc.py tests/site/test_contracts_cli.py
git commit -m "feat(CCE-23): contracts_doc CLI (config-driven, JSON report)"
```

---

### Task 5: `api-extract` config validation + schema `openapi` field

**Files:**

- Modify: `templates/config.schema.json`
- Modify: `scripts/state_io.py`
- Test: `tests/state_io/test_api_validation.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/state_io/test_api_validation.py
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from state_io import ConfigError, load_config_validated  # noqa: E402

_DOCS = """
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths: {}
"""
_TAIL = """
sources: { git: { host: github.com } }
lint: {}
publishing: { base_url: "https://x", build_workflow: "ci.yml", url_map_rule: "strip-ext" }
notifications: {}
"""


def _write(tmp_path: Path, site_body: str) -> Path:
    p = tmp_path / "config.yml"
    p.write_text(_DOCS + site_body + _TAIL)
    return p


def test_api_extract_requires_extractors(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config_validated(_write(tmp_path, """
site:
  docs_dir: docs/site-src
  sections:
    - { key: api, path: api/, title: API, generator: api-extract }
"""))
    assert "extractors" in str(exc.value)


def test_openapi_extractor_requires_openapi_path(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config_validated(_write(tmp_path, """
site:
  docs_dir: docs/site-src
  sections:
    - { key: api, path: api/, title: API, generator: api-extract,
        extractors: [openapi] }
"""))
    assert "openapi" in str(exc.value).lower()


def test_openapi_path_must_be_repo_relative(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config_validated(_write(tmp_path, """
site:
  docs_dir: docs/site-src
  sections:
    - { key: api, path: api/, title: API, generator: api-extract,
        extractors: [openapi], openapi: /etc/openapi.json }
"""))
    assert "relative" in str(exc.value).lower() or "absolute" in str(exc.value).lower()


def test_valid_api_extract_passes(tmp_path):
    cfg = load_config_validated(_write(tmp_path, """
site:
  docs_dir: docs/site-src
  sections:
    - { key: api, path: api/, title: API, generator: api-extract,
        extractors: [python-mkdocstrings, json-schema, openapi],
        sources: [agents/schemas], openapi: openapi.json }
"""))
    assert cfg["site"]["sections"][0]["openapi"] == "openapi.json"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/state_io/test_api_validation.py -q`
Expected: FAIL — `valid` case fails on schema (`openapi` not an allowed property; `additionalProperties: false`); the others don't raise yet.

- [ ] **Step 3: Implement**

(a) In `templates/config.schema.json`, add to the section item `properties` (alongside `extractors`/`sources`):

```json
        "openapi": { "type": "string" }
```

(b) In `scripts/state_io.py`, add this validator and call it from `load_config_validated` (right after `_validate_site_sections(raw)`):

```python
def _validate_api_sections(config: dict) -> None:
    """Cross-field checks for api-extract sections (CCE-23 capability API).

    - an api-extract section must declare a non-empty `extractors`
    - the `openapi` extractor requires a repo-relative `openapi:` path
    Schema enforces the extractor enum and the `openapi` field type.
    """
    site = config.get("site")
    if not site:
        return
    for s in site.get("sections", []) or []:
        if s.get("generator") != "api-extract":
            continue
        extractors = s.get("extractors") or []
        if not extractors:
            raise ConfigError(
                f"site.section '{s.get('key')}' uses generator api-extract but "
                "declares no extractors"
            )
        if "openapi" in extractors:
            path = s.get("openapi")
            if not path:
                raise ConfigError(
                    f"site.section '{s.get('key')}' lists the openapi extractor "
                    "but has no `openapi:` schema path"
                )
            if path.startswith("/") or ".." in PurePosixPath(path).parts:
                raise ConfigError(
                    f"site.section '{s.get('key')}' openapi path {path!r} must be "
                    "relative to the repo (no absolute or '..' paths)"
                )
```

Call site in `load_config_validated`:

```python
    _validate_site_sections(raw)
    _validate_api_sections(raw)
    return raw
```

`PurePosixPath` is already imported at the top of `state_io.py`.

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/state_io/test_api_validation.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add templates/config.schema.json scripts/state_io.py tests/state_io/test_api_validation.py
git commit -m "feat(CCE-23): validate api-extract sections + openapi schema field"
```

---

### Task 6: mkdocs API plugin wiring

**Files:**

- Modify: `scripts/site_structure.py:170-176` (`render_mkdocs_yaml`)
- Test: `tests/site/test_mkdocs_api_wiring.py` (+ update any existing `render_mkdocs_yaml` test)

- [ ] **Step 1: Write the failing tests**

```python
# tests/site/test_mkdocs_api_wiring.py
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import site_structure  # noqa: E402

SITE = {"docs_dir": "docs/site-src", "theme": "material", "sections": []}


def test_python_wiring_emits_full_recipe():
    y = site_structure.render_mkdocs_yaml(
        SITE, site_name="X", python_detected=True,
        python_path_root="scripts", openapi_enabled=False,
    )
    assert "gen-files" in y
    assert "literate-nav" in y
    assert "mkdocstrings" in y
    assert 'paths: ["scripts"]' in y


def test_no_python_omits_recipe():
    y = site_structure.render_mkdocs_yaml(SITE, site_name="X", python_detected=False)
    assert "mkdocstrings" not in y
    assert "gen-files" not in y


def test_openapi_enabled_emits_swagger_plugin():
    y = site_structure.render_mkdocs_yaml(
        SITE, site_name="X", python_detected=False, openapi_enabled=True,
    )
    assert "render_swagger" in y


def test_backward_compatible_defaults():
    # S's original 3-arg call still works (new args default safely).
    y = site_structure.render_mkdocs_yaml(SITE, site_name="X", python_detected=True)
    assert "mkdocstrings" in y
    assert 'paths: ["."]' in y  # default path_root when none supplied
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/site/test_mkdocs_api_wiring.py -q`
Expected: FAIL (`render_mkdocs_yaml` has no `python_path_root`/`openapi_enabled` kwargs; no gen-files/literate-nav/render_swagger lines).

- [ ] **Step 3: Implement**

Replace the `_MKDOCSTRINGS_BLOCK` constant and `render_mkdocs_yaml` in `scripts/site_structure.py` with:

```python
_RENDER_SWAGGER_PLUGIN = "  - render_swagger\n"


def _python_plugins_block(path_root: str) -> str:
    root = path_root or "."
    return (
        "  - gen-files:\n"
        "      scripts:\n"
        "        - gen_ref_pages.py\n"
        "  - literate-nav:\n"
        "      nav_file: SUMMARY.md\n"
        "  - mkdocstrings:\n"
        "      handlers:\n"
        "        python:\n"
        f"          paths: [{_yaml_scalar(root)}]\n"
        "          options:\n"
        "            show_source: false\n"
    )


def render_mkdocs_yaml(
    site: dict,
    *,
    site_name: str,
    python_detected: bool,
    python_path_root: str | None = None,
    openapi_enabled: bool = False,
) -> str:
    plugins = ""
    if python_detected:
        plugins += _python_plugins_block(python_path_root or ".")
    if openapi_enabled:
        plugins += _RENDER_SWAGGER_PLUGIN
    return _MKDOCS_TEMPLATE.format(
        site_name=_yaml_scalar(site_name),
        docs_dir=site["docs_dir"].rstrip("/"),
        theme=site.get("theme", "material"),
        mkdocstrings_plugin=plugins,
    )
```

Note: `_yaml_scalar("scripts")` → `scripts`, so the test expects `paths: ["scripts"]` — adjust the helper call to emit a JSON-style list. Use this exact paths line instead:

```python
        f'          paths: ["{root}"]\n'
```

(Keep it simple: `root` is a directory name or `.`, both JSON-safe.) Then `test_python_wiring_emits_full_recipe` sees `paths: ["scripts"]` and the default case sees `paths: ["."]`.

If an existing test asserts the old exact `_MKDOCSTRINGS_BLOCK` string, find it and relax it to substring checks:

```bash
grep -rn "render_mkdocs_yaml\|show_source" tests/
```

Update those assertions to check `"mkdocstrings" in y` rather than the full block.

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/site/test_mkdocs_api_wiring.py tests/site -q`
Expected: PASS (new file 4 passed; existing site tests still green).

- [ ] **Step 5: Commit**

```bash
git add scripts/site_structure.py tests/site/test_mkdocs_api_wiring.py
git commit -m "feat(CCE-23): mkdocs wiring — gen-files/literate-nav/mkdocstrings + swagger"
```

---

### Task 7: Scaffold the gen-files script + OpenAPI page stub

**Files:**

- Modify: `scripts/site_structure.py` (`plan_scaffold` / `apply_scaffold` signature + new files)
- Test: `tests/site/test_api_scaffold.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/site/test_api_scaffold.py
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import site_structure  # noqa: E402

API_SITE = {
    "docs_dir": "docs/site-src",
    "theme": "material",
    "sections": [
        {"key": "home", "path": "index.md", "title": "Home"},
        {"key": "api", "path": "api/", "title": "API", "generator": "api-extract",
         "extractors": ["python-mkdocstrings", "openapi"], "openapi": "openapi.json"},
    ],
}


def test_apply_scaffold_writes_gen_script_when_python(tmp_path):
    site_structure.apply_scaffold(
        tmp_path, API_SITE, site_name="X", python_detected=True,
        python_scan_dir="scripts", python_path_root="scripts",
        openapi_path="openapi.json",
    )
    gen = tmp_path / "gen_ref_pages.py"
    assert gen.exists()
    body = gen.read_text()
    assert 'SCAN_DIR = "scripts"' in body
    assert 'PATH_ROOT = "scripts"' in body
    assert "mkdocs_gen_files" in body


def test_apply_scaffold_writes_openapi_stub(tmp_path):
    site_structure.apply_scaffold(
        tmp_path, API_SITE, site_name="X", python_detected=True,
        python_scan_dir="scripts", python_path_root="scripts",
        openapi_path="openapi.json",
    )
    http = tmp_path / "docs/site-src/api/http.md"
    assert http.exists()
    assert "openapi.json" in http.read_text()


def test_no_gen_script_without_python(tmp_path):
    site = {"docs_dir": "docs/site-src", "theme": "material",
            "sections": [{"key": "home", "path": "index.md", "title": "Home"}]}
    site_structure.apply_scaffold(tmp_path, site, site_name="X", python_detected=False)
    assert not (tmp_path / "gen_ref_pages.py").exists()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/site/test_api_scaffold.py -q`
Expected: FAIL (`apply_scaffold` rejects new kwargs; no gen script / http stub).

- [ ] **Step 3: Implement**

Add the gen-script template and stubs to `scripts/site_structure.py`:

```python
_GEN_REF_TEMPLATE = '''\
"""Auto-generated by engineering-docs-agent setup. Runs at mkdocs build time
(mkdocs-gen-files) to emit one API page per module + a literate-nav SUMMARY."""
from pathlib import Path

import mkdocs_gen_files

SCAN_DIR = "{scan_dir}"
PATH_ROOT = "{path_root}"

nav = mkdocs_gen_files.Nav()
root = Path(PATH_ROOT)
for py in sorted(Path(SCAN_DIR).rglob("*.py")):
    if py.name.startswith("_") or any(p in ("tests", "test") for p in py.parts):
        continue
    ident_parts = py.relative_to(root).with_suffix("").parts
    if not ident_parts:
        continue
    doc = Path(*ident_parts).with_suffix(".md")
    nav[ident_parts] = doc.as_posix()
    with mkdocs_gen_files.open(Path("api", "reference") / doc, "w") as fd:
        ident = ".".join(ident_parts)
        fd.write(f"# `{{ident}}`\\n\\n::: {{ident}}\\n")
    mkdocs_gen_files.set_edit_path(Path("api", "reference") / doc, py)

with mkdocs_gen_files.open(Path("api", "reference", "SUMMARY.md"), "w") as f:
    f.writelines(nav.build_literate_nav())
'''


def _openapi_stub(openapi_path: str) -> str:
    return (
        "---\ntitle: HTTP API\n---\n\n# HTTP API\n\n"
        f"!!swagger-http {openapi_path}!!\n"
    )
```

Extend `apply_scaffold`'s signature and body. New signature:

```python
def apply_scaffold(
    repo_root: Path,
    site: dict,
    *,
    site_name: str,
    python_detected: bool,
    python_scan_dir: str | None = None,
    python_path_root: str | None = None,
    openapi_path: str | None = None,
) -> dict:
```

Thread `python_path_root`/`openapi` into the `render_mkdocs_yaml` call:

```python
            render_mkdocs_yaml(
                site,
                site_name=site_name,
                python_detected=python_detected,
                python_path_root=python_path_root,
                openapi_enabled=bool(openapi_path),
            ),
```

After building `planned` (before the write loop), append the conditional files:

```python
    if python_detected:
        planned.append(
            ScaffoldFile(
                "gen_ref_pages.py",
                _GEN_REF_TEMPLATE.format(
                    scan_dir=python_scan_dir or ".",
                    path_root=python_path_root or ".",
                ),
                "gen-script",
            )
        )
    if openapi_path:
        docs_dir = site["docs_dir"].rstrip("/")
        api_path = next(
            (s["path"].rstrip("/") for s in site.get("sections", [])
             if s.get("generator") == "api-extract"),
            "api",
        )
        planned.append(
            ScaffoldFile(
                f"{docs_dir}/{api_path}/http.md",
                _openapi_stub(openapi_path),
                "section-index",
            )
        )
```

(The never-clobber write loop already skips existing files, so re-runs are safe.)

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/site/test_api_scaffold.py tests/site -q`
Expected: PASS (new 3 passed; existing site scaffold tests still green — they call `apply_scaffold` with the original kwargs, which still work via defaults).

- [ ] **Step 5: Commit**

```bash
git add scripts/site_structure.py tests/site/test_api_scaffold.py
git commit -m "feat(CCE-23): scaffold gen_ref_pages.py + OpenAPI http stub"
```

---

### Task 8: Add the OpenAPI render plugin to docs-requirements

**Files:**

- Modify: `templates/docs-requirements.txt`
- Test: `tests/site/test_docs_requirements.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/site/test_docs_requirements.py
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_docs_requirements_lists_api_plugins():
    text = (_REPO_ROOT / "templates" / "docs-requirements.txt").read_text()
    for dep in ("mkdocstrings[python]", "mkdocs-gen-files",
                "mkdocs-literate-nav", "mkdocs-render-swagger-plugin"):
        assert dep in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/site/test_docs_requirements.py -q`
Expected: FAIL (`mkdocs-render-swagger-plugin` absent).

- [ ] **Step 3: Implement**

Append to `templates/docs-requirements.txt`:

```text
# OpenAPI rendering (only used when an api-extract section lists the openapi extractor).
mkdocs-render-swagger-plugin>=0.1
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/site/test_docs_requirements.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add templates/docs-requirements.txt tests/site/test_docs_requirements.py
git commit -m "feat(CCE-23): declare OpenAPI render plugin in docs-requirements"
```

---

### Task 9: Build-smoke + no-convention fixtures (`mkdocs build --strict`)

**Files:**

- Create: `tests/fixtures/api/host/**` (a fixture host repo)
- Create: `tests/site/test_api_build_smoke.py`

**Plugin install note (do this once so the smoke runs for real):**

```bash
uv tool install --with mkdocs-material --with "mkdocstrings[python]" \
  --with mkdocs-gen-files --with mkdocs-literate-nav \
  --with mkdocs-awesome-pages-plugin --with mkdocs-render-swagger-plugin mkdocs
```

The test SKIPS cleanly when any plugin is missing, so the suite stays green without it.

- [ ] **Step 1: Create the fixture host**

```bash
mkdir -p tests/fixtures/api/host/pkg tests/fixtures/api/host/schemas
printf 'def add(a, b):\n    """Add two numbers."""\n    return a + b\n' > tests/fixtures/api/host/pkg/calc.py
: > tests/fixtures/api/host/pkg/__init__.py
printf '{\n  "title": "Widget",\n  "type": "object",\n  "required": ["id"],\n  "properties": {"id": {"type": "string", "description": "Widget id"}}\n}\n' > tests/fixtures/api/host/schemas/widget.json
printf '{\n  "openapi": "3.0.0",\n  "info": {"title": "X", "version": "1.0"},\n  "paths": {}\n}\n' > tests/fixtures/api/host/openapi.json
```

- [ ] **Step 2: Write the build-smoke test**

```python
# tests/site/test_api_build_smoke.py
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import contracts_doc  # noqa: E402
import site_structure  # noqa: E402

_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "api" / "host"


def _plugins_present() -> bool:
    if shutil.which("mkdocs") is None:
        return False
    out = subprocess.run(["mkdocs", "get-deps"], capture_output=True, text=True)
    # Fast proxy: try a help/build dry path; here we just check the binary +
    # import of plugins via a throwaway build below. Keep the guard simple.
    return True


pytestmark = pytest.mark.skipif(shutil.which("mkdocs") is None,
                                reason="mkdocs not installed (doc-build dep)")

_SITE = {
    "docs_dir": "docs/site-src",
    "theme": "material",
    "sections": [
        {"key": "home", "path": "index.md", "title": "Home"},
        {"key": "api", "path": "api/", "title": "API reference",
         "generator": "api-extract",
         "extractors": ["python-mkdocstrings", "json-schema", "openapi"],
         "sources": ["schemas"], "openapi": "openapi.json"},
    ],
}


def test_api_site_builds_strict(tmp_path):
    shutil.copytree(_FIXTURE, tmp_path, dirs_exist_ok=True)
    site_structure.apply_scaffold(
        tmp_path, _SITE, site_name="Fixture", python_detected=True,
        python_scan_dir="pkg", python_path_root=".", openapi_path="openapi.json",
    )
    result = contracts_doc.generate_contracts(tmp_path, _SITE)
    assert "docs/site-src/api/contracts/widget.md" in result["written"]

    proc = subprocess.run(["mkdocs", "build", "--strict"], cwd=tmp_path,
                          capture_output=True, text=True)
    if proc.returncode != 0 and "plugin" in (proc.stderr.lower()):
        pytest.skip(f"mkdocs plugins not installed in tool env: {proc.stderr[:200]}")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    built = tmp_path / "site"
    assert (built / "api" / "reference" / "calc" / "index.html").exists()
    assert (built / "api" / "contracts" / "widget" / "index.html").exists()
    assert (built / "api" / "http" / "index.html").exists()


def test_no_convention_host_skips_cleanly(tmp_path):
    # No package, no schemas, no openapi -> extractors skip, build still passes.
    site = {"docs_dir": "docs/site-src", "theme": "material",
            "sections": [{"key": "home", "path": "index.md", "title": "Home"},
                         {"key": "api", "path": "api/", "title": "API",
                          "generator": "api-extract", "extractors": ["json-schema"],
                          "sources": ["schemas"]}]}
    site_structure.apply_scaffold(tmp_path, site, site_name="Bare",
                                  python_detected=False)
    result = contracts_doc.generate_contracts(tmp_path, site)
    assert result["written"] == []
    assert not (tmp_path / "gen_ref_pages.py").exists()
    proc = subprocess.run(["mkdocs", "build", "--strict"], cwd=tmp_path,
                          capture_output=True, text=True)
    if proc.returncode != 0 and "plugin" in proc.stderr.lower():
        pytest.skip("mkdocs plugins not installed in tool env")
    assert proc.returncode == 0, proc.stdout + proc.stderr
```

- [ ] **Step 3: Run**

Run: `python3 -m pytest tests/site/test_api_build_smoke.py -q`
Expected: PASS or SKIP (skip if the mkdocs tool env lacks plugins). If it runs and a plugin/recipe fault appears, fix wiring (Tasks 6/7) per the actual `--strict` error — this is the spec's flagged risk (awesome-pages × literate-nav coexistence; gen-files script path).

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest -q`
Expected: all green (with the build-smoke passing or cleanly skipped).

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/api tests/site/test_api_build_smoke.py
git commit -m "test(CCE-23): mkdocs --strict api build-smoke + no-convention skip"
```

---

## Execution coda (do NOT skip — runs after Task 9)

These three steps are mandatory and run in order.

### Step A — subagent-driven-development final whole-branch review

Per the skill, dispatch the standard final code-reviewer subagent over the whole branch (`feat/CCE-23-structured-docs-site...HEAD`). Fix any Critical/Important before proceeding.

### Step B — ADDITIONAL dedicated validation pass (user-requested) — BEFORE /ship

Dispatch a **separate opus** reviewer whose sole job is a full **spec-compliance + quality** validation against `docs/superpowers/specs/2026-05-25-cce23-api-reference-design.md`, distinct from Step A. It must explicitly verify:

1. **Every spec requirement maps to code** — all three extractors; hybrid mechanisms (build-time Python/OpenAPI, stdlib contracts); output layout (`api/reference/**`, `api/contracts/**`, `api/http.md`); locked decisions A/B/C.
2. **Generic-first compliance (per CLAUDE.md)** — no capability hardcodes this repo's paths; behavior is detection/config-driven; the no-convention fixture proves clean skips. Flag ANY hardcoded `scripts/`, `agents/schemas/`, or `docs/superpowers/` in capability code (fixtures/defaults are fine).
3. **Self-containment** — no reliance on D's branch additions; the contracts CLI handles malformed YAML itself.
4. **Verification integrity** — the build-smoke genuinely exercises `--strict` (or skips honestly), and the full suite is green.

Output verdict: `Ready to ship: Yes/No` + Critical/Important/Minor. Fix Critical/Important; re-run this pass until clean.

### Step C — Ship via /ship

Invoke `/ship` with:

- Full gate (verify-agent + simplify + code review).
- **PR base `feat/CCE-23-structured-docs-site`** (stacked on #24, NOT `main`) → `gh pr create --base feat/CCE-23-structured-docs-site`.
- Test stage = `pytest` (expect full suite green).
- **Jira CCE-23: comment only, do NOT transition.**

After #24 merges to `main`, retarget this PR to `main`.

---

## Self-Review (completed by plan author)

**Spec coverage:** detection (Task 1) ✓; python-mkdocstrings recipe (Tasks 6/7 + gen script) ✓; json-schema contracts (Tasks 2–4) ✓; openapi (Tasks 5/7/8) ✓; config + validation (Task 5) ✓; mkdocs wiring (Task 6) ✓; no orchestrator stage (by omission — contracts is a CLI, like D) ✓; verification + no-convention skip (Task 9) ✓; extra validation round + ship (coda B/C) ✓.

**Placeholder scan:** no TBD/"handle edge cases"; every code step shows complete code. The one judgment call (Task 9 `--strict` fault-fixing) is tied to a concrete error-driven action, not a placeholder.

**Type consistency:** `detect_python` → `{detected, scan_dir, path_root}` used consistently in Tasks 1/7/9; `render_mkdocs_yaml(..., python_path_root, openapi_enabled)` matches Task 6 ↔ Task 7's `apply_scaffold` call; `apply_scaffold(..., python_scan_dir, python_path_root, openapi_path)` matches Tasks 7/9; `generate_contracts(repo_root, site_config) -> {"written","skipped"}` consistent across Tasks 3/4/9; `_validate_api_sections` call site matches Task 5.
