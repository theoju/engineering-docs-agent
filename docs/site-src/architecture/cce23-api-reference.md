---
description: "How the CCE-23 API reference generation capability works \u2014 the\
  \ scripts, extractors, and site build path that turn Python modules, JSON schemas,\
  \ and OpenAPI specs into a published reference section."
source_files:
- <docs_dir>/gen_ref_pages.py
- <import_paths>/*.py
- api/contracts/*.md
- api/reference/*.md
- scripts/contracts_doc.py
- scripts/setup_discover.py
- scripts/site_structure.py
- scripts/state_io.py
- tests/site/test_api_build_smoke.py
last_reviewed: '2026-05-27'
status: draft
doc_kind: architecture
---

# CCE-23: API Reference Generation

CCE-23 adds a self-updating API reference section to any host repo's docs site. The setup skill scaffolds the section once; from then on, the three extractors regenerate their pages automatically at every `mkdocs build`.

## How the section is declared

Your `.engineering-docs-agent/config.yml` site block includes a section with `generator: api-extract` and an `extractors` list. Example:

```yaml
site:
  docs_dir: docs/site-src
  sections:
    - key: api
      path: api/
      title: API reference
      generator: api-extract
      extractors: [python-mkdocstrings, json-schema, openapi]
      sources: [agents/schemas]
      openapi: openapi.json
```

`scripts/site_structure.py:_section_index_stub` reads this config block and produces a `ScaffoldFile` list. `apply_scaffold` writes the files; it never overwrites existing authored content.

## Three extractors

### Python modules — `python-mkdocstrings`

`scripts/site_structure.py` writes a `gen_ref_pages.py` at the docs root. At `mkdocs build` time, `mkdocs-gen-files` executes that script, which walks `SCAN_DIR` for `*.py` files (skipping `_`-prefixed and test modules), emits one page per module under `api/reference/`, and writes a `SUMMARY.md` for literate-nav.

The generated pages land at `<docs_dir>/<api_path>/reference/<ident>.md` — for example, `pkg.calc` maps to `api/reference/pkg/calc.md`.

### JSON schemas — `json-schema`

`scripts/contracts_doc.py:generate_contracts` (`generate_contracts`) reads every `*.json` under the section's `sources` directories, renders a Markdown property table per schema, and writes pages to `<docs_dir>/<api_path>/contracts/`. An `index.md` links all contract pages.

Duplicate stems across sources are resolved by first-source-wins. Missing or malformed source directories are skipped with a `stderr` warning — the build continues and `generate_contracts` returns a `skipped` list so you can inspect what was dropped.

### OpenAPI — `openapi`

When `openapi` is listed in `extractors` and the section config includes an `openapi` key, `site_structure.py` writes an `http/index.md` stub that renders the spec via the `render_swagger` MkDocs plugin. The stub points at the path declared in `openapi` relative to the docs directory.

## Discovery

`scripts/setup_discover.py` detects the host's framework (`mkdocs` or `docusaurus`), source directory, and existing lens paths. The setup skill calls these functions before generating the scaffold so it never assumes a fixed layout. Detection returns `None` on a miss; the caller degrades gracefully.

## Config validation

`scripts/state_io.py:StateError` (`_validate_lens_paths_are_editable`) enforces the invariant that every lens in `docs.lens_paths` is covered by at least one `docs.agent_editable_paths` glob. The check runs at config load time; a miscovered lens raises `ConfigError` immediately rather than silently producing writes the agent can't make.

## Build smoke test

`tests/site/test_api_build_smoke.py` runs a full `mkdocs build --strict` against a fixture host in a temp directory. It asserts that all three extractor outputs exist in the built site:

- `site/api/reference/pkg/calc/index.html` — Python module page
- `site/api/contracts/widget/index.html` — JSON schema page
- `site/api/http/index.html` — OpenAPI page

A second test (`test_no_convention_host_skips_cleanly`) verifies that a host with no Python package and no populated schema source produces an empty `written` list and a passing build — no empty page artifacts.

The test is skipped automatically if `mkdocs` is not installed in the tool environment.

## Adding a new extractor type

1. Add the extractor name to the `extractors` list in your site config.
2. Implement a render function in `scripts/contracts_doc.py` or a new sibling script following the `generate_contracts` pattern: pure render function + single writer entry point + `{"written": [...], "skipped": [...]}` return shape.
3. Wire the extractor into `site_structure.apply_scaffold` so the setup skill emits the needed scaffold files.
4. Add a fixture case to `tests/site/test_api_build_smoke.py` asserting the built output path exists.
