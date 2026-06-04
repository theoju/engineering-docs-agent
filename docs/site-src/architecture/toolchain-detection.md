---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
---

# Toolchain Detection

The setup skill needs to know a host repo's runtime and package manager before it can scaffold correct workflow files. `detect_toolchain()` in `scripts/setup_discover.py` handles this. It runs as part of `discover()` and adds a `toolchain` block to the discovery output.

## What gets detected

`detect_toolchain()` walks the host root and checks for three things:

**Runtime.** The function looks for `node`, `bun`, and `deno` executables via `shutil.which`. The first match wins; the result lands in `toolchain.runtime`. If none are found, `runtime` is `null` and the setup skill falls back to Python-only scaffolding.

**Package manager.** Lockfile presence determines the manager — `bun.lockb` → `bun`, `pnpm-lock.yaml` → `pnpm`, `yarn.lock` → `yarn`, `package-lock.json` → `npm`. The check is ordered so more specific lockfiles win over `package-lock.json`. If no lockfile exists, `package_manager` is `null`.

**Docusaurus.** The function reads `package.json` (if present) and checks `devDependencies` for `@docusaurus/core`. When found, `toolchain.docs_framework` is set to `"docusaurus"`. This tells the setup skill to emit a Docusaurus-specific `mkdocs.yml` alternative and adjust the pages workflow accordingly.

## Output shape

`discover()` merges the toolchain result into its return dict:

```json
{
  "toolchain": {
    "runtime": "node",
    "package_manager": "npm",
    "docs_framework": "docusaurus"
  }
}
```

For a Python-only host (no Node/Bun/Deno, no `package.json`), all three fields are `null`. The downstream setup skill reads `toolchain.docs_framework` to pick the right site template; a `null` value means it defaults to MkDocs.

## Fixture coverage

`tests/fixtures/setup_repos/js_docusaurus/` is a minimal JS/Docusaurus host fixture: a `package.json` with `@docusaurus/core` in `devDependencies` and an `npm` lockfile. The 14 tests added in PR #83 cover:

- Runtime detection for each of `node`, `bun`, `deno`, and `null`.
- Package manager selection for each lockfile variant and the no-lockfile case.
- `docs_framework` detection with and without `@docusaurus/core`.
- The full `discover()` output shape when run against the JS fixture.
- Preflight CLI output for the same fixture (see [Preflight Host CLI](../operations/preflight-host.md)).

Run the suite with:

```bash
pytest tests/ -k "toolchain or js_docusaurus"
```

## Graceful degradation

If `package.json` is missing or malformed JSON, `detect_toolchain()` catches the parse error and returns `null` for `docs_framework`. It never raises. The rest of `discover()` continues unaffected.

If no runtime binary is on `PATH`, `runtime` is `null` but the function still checks for a lockfile — a repo can have a lockfile committed without the runtime present in the CI environment. The setup skill treats `runtime: null` + lockfile-present as a soft warning, not an error.

## Where detection fits in the setup flow

The setup skill calls `discover()` once at the start of a run. The returned `toolchain` block is passed forward to every subsequent step — workflow template selection, config generation, and the preflight checklist. Nothing re-runs detection mid-flow.

If you're adding support for a new runtime or docs framework, add the detection logic to `detect_toolchain()` in `scripts/setup_discover.py` and extend the fixture matrix in `tests/fixtures/setup_repos/`. Keep detection read-only: `detect_toolchain()` must never write files or mutate host state.
