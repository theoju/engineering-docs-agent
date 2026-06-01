---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
---

# Toolchain Detection

The plugin needs to know what kind of host repo it is running against before it can scaffold a docs site or run setup. Toolchain detection makes that identification explicit and automatic, replacing the previous implicit assumption that all hosts are Python projects.

## What detection does

`setup_discover.py` now includes a `detect_toolchain` function. The function inspects the host repo root for well-known markers and returns a structured result describing the detected toolchain type and any relevant metadata (framework, package manager, config files found).

The detection logic checks for, in order:

1. **JS/TS host** — presence of `package.json`. If found, the function also checks for `docusaurus.config.js` or `docusaurus.config.ts` to identify a Docusaurus site.
2. **Python host** — presence of `setup.py`, `pyproject.toml`, or `setup.cfg`.
3. **Unknown** — neither marker found; the function returns `toolchain: "unknown"` rather than erroring.

Detection is read-only. It never mutates the host repo. Setup and onboarding stages downstream consume the result and adjust their behavior accordingly.

## Adding a new toolchain

To support a new host type, add a detection branch inside `detect_toolchain` in `setup_discover.py`. The branch should:

- Check for a marker file that is unambiguous for the toolchain.
- Return a dict with at least `toolchain`, `framework`, and `config_files` keys.
- Fall through to the next branch on a negative match — never raise.

Add a corresponding fixture under `tests/fixtures/` that represents a minimal host repo of the new type. The JS/TS fixture at `tests/fixtures/js_docusaurus/` is the reference example.

## Why detection is separate from config

Config tells the plugin where to read and write on a host that is already set up. Detection tells the setup skill what that host looks like before any config exists. Keeping these two concerns in separate functions means you can run detection in a read-only preflight step without touching the host's config files.

The `preflight_host.py` CLI (see [Preflight Host](../operations/preflight-host.md)) calls `detect_toolchain` and reports the result before any setup action runs. This lets you verify detection is correct before committing to a setup run.

## Graceful degradation

When `detect_toolchain` returns `toolchain: "unknown"`, the setup skill logs a warning and proceeds with generic defaults rather than aborting. This preserves the plugin's contract: detection narrows the path taken; it does not gate the run. An operator can override the inferred toolchain by setting `toolchain:` explicitly in `.engineering-docs-agent/config.yml` after setup.

## Test coverage

The `js_docusaurus` fixture in `tests/fixtures/` exercises the JS/TS detection branch. The fixture contains a minimal `package.json` and a `docusaurus.config.js` so both the outer toolchain check and the inner framework check are covered. Run the suite with:

```bash
python3 -m pytest tests/ -k toolchain
```

All detection tests use the fixture-driven path; no real host repo is required.
