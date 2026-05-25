# API Reference Section (Phase 1 — API) — Design

**Date:** 2026-05-25
**Status:** draft (awaiting review)
**Ticket:** [CCE-23](https://designitright.atlassian.net/browse/CCE-23)
**Branch:** `feat/CCE-23-api-reference`, stacked on `feat/CCE-23-structured-docs-site` (PR #24)
**Refines:** the **API** capability of the umbrella spec `docs/superpowers/specs/2026-05-24-structured-docs-site-generation-design.md` (lines 99–107).

---

## Why this exists

The umbrella spec names an `api` section (`generator: api-extract`) whose surface is **extracted from code, never authored by the LLM**. S shipped a partial foundation; this design finishes the wiring.

What S already pre-wired (do not rebuild):

- `templates/docs-requirements.txt` already declares `mkdocstrings[python]`, `mkdocs-gen-files`, `mkdocs-literate-nav`.
- `templates/config.schema.json` already defines `generator: api-extract` and `extractors: ["python-mkdocstrings", "openapi", "json-schema"]` (array of string enum, `additionalProperties: false`).
- `site_structure.py:render_mkdocs_yaml` already injects the `mkdocstrings` plugin block when `python_detected`.

The gap this design fills: real **Python detection**, the **gen-files auto-page recipe** (the script + the `gen-files`/`literate-nav` plugin lines + `mkdocstrings.paths`), the **JSON-schema contracts renderer**, the **OpenAPI render path** (+ its one missing plugin dep), `api-extract` **config validation**, and **verification**.

## Generic-first mandate (per CLAUDE.md)

This is the `/engineering-docs-agent:engineering-docs-agent-setup` skill running on **arbitrary host repos**. Every unit here is **detection- and config-driven**; this repo's paths (`scripts/`, `agents/schemas/`) are defaults and fixtures, never assumptions. Absence of a convention (no Python package, no schema dir, no OpenAPI file) makes the corresponding extractor **skip cleanly** — never error, never emit an empty artifact.

## Scope

All three extractors: **python-mkdocstrings**, **json-schema**, **openapi**. OpenAPI is opt-in (config-gated) and, on a repo with no HTTP API, exercised only by fixtures.

## Architecture — Hybrid

Each extractor uses the mechanism that fits:

| Extractor               | Mechanism                                                                                              | Rationale                                                                                                                        |
| ----------------------- | ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| **python-mkdocstrings** | Build-time: `mkdocstrings` + `mkdocs-gen-files` + `mkdocs-literate-nav`, `mkdocstrings.paths: [<src>]` | Self-refreshing extraction from source; the umbrella spec's chosen recipe; deps already declared.                                |
| **openapi**             | Build-time: an OpenAPI render plugin reading a **committed** schema file                               | Opt-in; mature plugins exist; never introspect a running app (importing/running host code is heavier and a security smell).      |
| **json-schema**         | **Deterministic stdlib generator** (`scripts/contracts_doc.py`, D-family)                              | We own this surface; stdlib gives output control, **zero new deps**, fast unit tests, and the same skip-clean ledger shape as D. |

Rejected: **all-build-time** (adds a third-party JSON-schema plugin → less control, brittle tests, upstream coupling); **all-stdlib** (reinventing mkdocstrings — large effort, worse output, contradicts the umbrella spec).

## Output layout (within the `api/` section)

- `api/index.md` — section landing (S scaffold; never clobbered).
- `api/reference/*.md` + `api/reference/SUMMARY.md` — **build-time virtual** Python module pages (mkdocs-gen-files writes them in-memory at build; nothing on disk except the script below).
- `api/contracts/*.md` + `api/contracts/index.md` — **on-disk**, written by the contracts generator (like D's archive pages).
- `api/http.md` — **on-disk** stub committed by setup; the OpenAPI plugin renders the committed schema into it at build.

Distinct sub-paths mean a single `api` section can carry all three extractors without collision.

## Design units

### 1. Detection — `scripts/setup_discover.py`

Add `detect_python(cwd) -> dict`:

- Resolve a source root generically, in order: (a) `pyproject.toml` `[tool.setuptools.packages]` / `[project]`-implied package dir; (b) the first top-level directory containing `__init__.py`; (c) fallback: a directory of loose `*.py` modules (this repo's `scripts/`). Returns `{"detected": bool, "source_root": str | None, "import_paths": [str]}` where `import_paths` is what becomes `mkdocstrings.paths` (so loose-module repos work without `__init__.py`).
- Add OpenAPI + schema hints to `discover()`: a committed `openapi.{json,yaml,yml}` at repo root or a conventional location, and a schema dir hint. These are **hints only** — activation is config-driven.

`discover()` output gains `python` (the dict above) and `openapi_hint`. The externally-passed `python_detected` flag is now sourced from detection.

### 2. Config + validation — `scripts/state_io.py`, `templates/config.schema.json`

Schema vocabulary mostly exists. Add one optional section field: `openapi` (string — the committed schema path), keeping `additionalProperties: false`. Per-extractor inputs:

- `python-mkdocstrings` ← detection (`import_paths`); optional override deferred (YAGNI).
- `json-schema` ← the section's existing `sources` (dirs/globs of `*.json`).
- `openapi` ← the new `openapi:` path field.

New validator `_validate_api_sections(config)` (called from `load_config_validated`):

- A section with `generator: api-extract` MUST declare a non-empty `extractors`.
- If `extractors` contains `json-schema`, the section SHOULD declare `sources` (path-shape already guarded by D's `_validate_site_sections`); absent sources → the extractor skips at runtime (not a config error).
- If `extractors` contains `openapi`, an `openapi:` path is required and must be repo-relative (reuse D's no-absolute/`..` guard).
- Unknown extractor strings already fail the schema enum.

### 3. mkdocs wiring — `scripts/site_structure.py`

Extend `render_mkdocs_yaml` (and its inputs) so that, given the resolved API config:

- When Python is present: emit the `mkdocs-gen-files` and `mkdocs-literate-nav` plugin lines and set `mkdocstrings.handlers.python.paths: [<import_paths>]` (extend the existing `_MKDOCSTRINGS_BLOCK`).
- When the `openapi` extractor is configured: emit the OpenAPI render plugin line.
- awesome-pages remains the top-level nav driver; literate-nav drives only the `api/reference/` subtree via its `SUMMARY.md`. Coexistence is a verification item (below).

### 4. Gen-files recipe script

`apply_scaffold` writes a committed `<docs_dir>/gen_ref_pages.py` (new `ScaffoldFile` kind `"gen-script"`, never-clobber). At **build time** it walks `<import_paths>/*.py` (excluding tests, `__pycache__`, dunder/private modules), writes one virtual `api/reference/<module>.md` containing a `::: <module>` autodoc directive, and a virtual `api/reference/SUMMARY.md` for literate-nav. Standard mkdocstrings recipe, parameterized by the detected source root.

### 5. Contracts generator — `scripts/contracts_doc.py` (new, stdlib)

D-shaped CLI. Reads the `json-schema` section's `sources` (dirs of `*.json`). For each schema:

- Title from schema `title` (fallback: filename), `description` paragraph, a properties table `| Property | Type | Required | Description |`, plus `enum` values and `$defs`/`definitions` expansion.
- Writes `<docs_dir>/api/contracts/<name>.md` (auto-generated banner; overwritten each run) + an `index.md` listing the contracts.
- Returns `{"written": [...], "skipped": [...]}`; **skips cleanly** when a source dir is missing/empty. mkdocs-`--strict`-safe output (no links escaping `docs_dir`).
- CLI mirrors `archive_indexes.py`: `--repo-root`, `--config` (required), JSON ledger to stdout; malformed YAML → `ConfigError`, not a traceback.

### 6. OpenAPI page

When the `openapi` extractor is configured, `apply_scaffold` writes an `api/http.md` stub that references the committed schema for the render plugin. Absent config → nothing emitted (opt-in by construction).

### 7. Orchestrator

**No new pipeline stage.** API is a build-time mkdocs concern (umbrella spec line 126). The contracts generator is a CLI/`make` target invoked by setup and re-runnable on demand, like D's archive generator — not a nightly orchestrator stage. Orchestrator integration is deferred to the later integration step.

### 8. Dependencies

Add **one** build-time dep to `templates/docs-requirements.txt`: an OpenAPI render plugin (candidate `mkdocs-render-swagger-plugin`; final pin chosen during implementation as the one that builds clean under headless `--strict`). Justified per the stdlib-first rule: it is a documentation-build dependency, not an agent-runtime dependency. No new agent-runtime deps; the contracts generator is stdlib + the already-present `pyyaml`.

## Error handling & verification

- **Config validation** as in unit 2.
- **`mkdocs build --strict`** is the build gate.
- **Build-smoke test** (`tests/site/test_api_build_smoke.py`): a fixture host with a small importable Python package, a fixture schema dir, and a fixture `openapi.json`; asserts the build produces the reference pages, contracts pages, and the OpenAPI page, and that `--strict` passes. **Skips cleanly** when the mkdocs tool env lacks the required plugins (extends D's `skipif(shutil.which("mkdocs") is None)` to also check the plugins import). The plan documents installing the plugins into the `uv` mkdocs tool env so the test runs for real locally and in CI.
- **No-convention fixture**: a host with no Python package, no schema dir, no `openapi:` → asserts each extractor skips, no empty pages, build still passes.

## Testing strategy

TDD throughout, fixture-driven (the existing dry-run pattern):

- **Detection** — `detect_python` resolves package / `__init__.py` / loose-`.py` fallback; returns no-detection on a non-Python fixture.
- **Config validation** — `api-extract` without `extractors` fails; `openapi` extractor without an `openapi:` path fails; absolute/`..` paths fail; valid config passes.
- **Contracts generator** — fixture schemas → expected markdown (properties table, required, enums, `$defs`); missing/empty source → skip ledger; malformed schema JSON → skip (recorded), not abort.
- **mkdocs wiring** — `render_mkdocs_yaml` emits gen-files/literate-nav/`paths` when Python present, the OpenAPI plugin when configured, and neither when absent.
- **Gen-files script** — generated script content is correct for a fixture source root (unit-level), plus the build-smoke covers it end-to-end.
- **Build** — the build-smoke + no-convention fixtures above.

## Risks & open questions

- **mkdocs tool-env plugins.** The `mkdocs` binary is a separate `uv` tool env; the build-smoke runs for real only if `mkdocstrings`, `mkdocs-gen-files`, `mkdocs-literate-nav`, and the OpenAPI plugin are installed there. Mitigation: skip-clean guard + a documented install step.
- **awesome-pages × literate-nav coexistence.** literate-nav must own only the `api/reference/` subtree. Verified by the build-smoke; if they conflict, fall back to a static generated nav stub for the subtree.
- **OpenAPI plugin choice.** Pinned during implementation against the headless `--strict` smoke; render-to-static-HTML preferred over CDN-JS for offline/CI reproducibility.
- **Multi-extractor section.** One `api` section carries all three; inputs are disambiguated by sibling fields (`sources` ← json-schema, `openapi:` ← openapi, detection ← python) and outputs by sub-path. Per-extractor object config is deferred unless a host needs it.

## Decisions locked

- **A.** Contracts = deterministic stdlib generator (not a plugin).
- **B.** OpenAPI = a committed schema file path (`openapi:` field); no running-app introspection.
- **C.** Python target via `mkdocstrings.paths: [<import_paths>]` (documents loose modules by stem without forcing a package).
