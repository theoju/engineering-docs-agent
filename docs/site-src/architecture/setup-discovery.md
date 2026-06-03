---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
---

# Setup Discovery

`scripts/setup_discover.py` is the detection layer that runs before any setup scaffolding. It inspects the host repo root and emits a structured description of the repo's toolchain, docs framework, and existing conventions. The setup skill (`/engineering-docs-agent:engineering-docs-agent-setup`) consumes this output to make every downstream decision: which template to render, which config keys to populate, which workflow to emit.

## `discover()` — the top-level entry point

`discover(repo_root: str) -> dict` is the function the setup skill calls. It returns a dict with the following top-level keys:

- `toolchain` — output of `detect_toolchain()` (see below)
- `docs_framework` — detected framework (`mkdocs`, `docusaurus`, `unknown`)
- `existing_config` — path to an existing `.engineering-docs-agent/config.yml` if present, else `None`
- `package_manager` — `npm`, `yarn`, `pnpm`, `bun`, or `None`

Every key has a value. `discover()` never raises; unknown or absent signals produce `None` or `"unknown"` rather than exceptions.

## `detect_toolchain()`

`detect_toolchain(repo_root: str) -> dict` is new as of PR #83. It surfaces the language-ecosystem signals the setup skill needs to pick the right workflow template and preflight checks.

The returned dict has these keys:

| Key | Type | Description |
|---|---|---|
| `python` | `bool` | `True` if a `pyproject.toml`, `setup.py`, or `requirements.txt` is present at the repo root |
| `node` | `bool` | `True` if `package.json` is present |
| `bun` | `bool` | `True` if `bun.lockb` is present (implies `node: True`) |
| `deno` | `bool` | `True` if `deno.json` or `deno.jsonc` is present |
| `docusaurus` | `bool` | `True` if `docusaurus` appears as a dependency in `package.json` |

These flags are not mutually exclusive. A repo with both a Python package and a Docusaurus site produces `python: True, node: True, docusaurus: True`.

## How `detect_toolchain` feeds downstream decisions

The setup skill reads `toolchain` before selecting a workflow template. If `node` is `True`, it uses the Node-aware path in `templates/workflow-run.yml`; otherwise it uses the default Python path. If `docusaurus` is `True`, the docs framework detection in `discover()` short-circuits to `"docusaurus"` without inspecting `mkdocs.yml`.

`preflight_host.py` also calls `detect_toolchain()` directly and surfaces the result in its readiness report under the `toolchain` section. See [operations/preflight-host.md](../operations/preflight-host.md) for the CLI reference.

## Fixture coverage

The `tests/fixtures/setup_repos/js_docusaurus/` fixture (added in PR #83) is the canonical test bed for a JS/TS Docusaurus host. It contains a minimal `package.json` (with `@docusaurus/core` as a dependency), `docusaurus.config.ts`, and a minimal docs tree. All `detect_toolchain` tests for the Node/Docusaurus path run against this fixture, not against this repo's own tree.

This mirrors the plugin's generic-first principle: detection tests use representative fixtures, never the dogfood layout.

## Extending detection

To add a new signal to `detect_toolchain`, add a key to the returned dict and a corresponding test in `tests/` using the existing fixture pattern. If the new signal affects template selection, also update the setup skill's branching logic and add a fixture that exercises the new path. Keep the function side-effect free — it reads files, nothing else.
