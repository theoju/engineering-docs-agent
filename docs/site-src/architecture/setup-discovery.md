---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
---

# Setup Discovery

`scripts/setup_discover.py` is the single source of truth for what the plugin knows about a host repo before any config file is written. Every downstream consumer — the setup skill, the preflight CLI, and the config-proposal logic — reads a single `discover()` call rather than probing the filesystem independently.

## `discover()` contract

**Signature:** `discover(cwd: Path) -> dict`

Call it once with the host repo root. The return dict is always fully populated; missing optional fields are `None` or `{}`, never absent.

```python
{
    "framework":         str | None,       # "mkdocs" | "docusaurus" | None
    "source_dir":        str | None,       # e.g. "docs/site-src"
    "lens_paths":        dict[str, str],   # subdirectory names → relative paths
    "ci":                str | None,       # "github_actions" | "gitlab_ci" | None
    "jira_hint":         dict | None,      # {"base_url": str | None} or None
    "python":            dict,             # see Python block below
    "openapi_hint":      str | None,       # filename at repo root, e.g. "openapi.yaml"
    "toolchain":         dict,             # see Toolchain block below
    "pages_publishable": bool,
    "warnings":          list[dict],       # only present when non-empty
}
```

### Python block

`python` is always a three-key dict:

| Key | Type | Meaning |
|---|---|---|
| `detected` | `bool` | A Python package or conventional loose-module directory was found. |
| `scan_dir` | `str \| None` | Directory to walk for `*.py` files (e.g. `"scripts"`). |
| `path_root` | `str \| None` | `mkdocstrings` `paths` entry so module identifiers are importable. |

The setup skill uses `scan_dir` and `path_root` to configure `mkdocstrings`. The preflight CLI uses `detected` to emit a `node_only_host` warning when the host is a pure JS/TS repo (Node found, no Python package) — expected for those hosts, but surfaces the fact early.

### Toolchain block

`toolchain` is always present, even on Python-only hosts (all fields default to `False`/`None`).

| Field | Type | Meaning |
|---|---|---|
| `node` | `bool` | `package.json` present at the repo root. |
| `bun` | `bool` | `bun.lockb` present. |
| `deno` | `bool` | `deno.json` or `deno.jsonc` present. |
| `package_manager` | `str \| None` | Lockfile-derived: `"bun"` > `"pnpm"` > `"yarn"` > `"npm"` > `None`. |
| `docusaurus_dep` | `bool` | Any `@docusaurus/*` key in `dependencies`, `devDependencies`, or `peerDependencies`. |

`bun.lockb` beats every npm-family lockfile for `package_manager` resolution. Malformed `package.json` is tolerated — `docusaurus_dep` falls back to `False` rather than raising.

### Warnings

Warnings are appended by `discover()` itself (only `docusaurus_v0.1_unsupported` today) and by `preflight_host.compute_warnings()` which adds host-shape warnings after the fact. Each warning is a dict with `code` and `message`, and an optional `severity` (`"info"` | `"warn"` | `"block"`). Absent severity is treated as `"block"` by older consumers.

## Downstream consumers

### Setup skill

The setup skill calls `discover()` to seed the generated `config.yml`. It uses `framework` to choose the docs framework, `source_dir` to set `docs.source_dir`, `lens_paths` to populate `docs.lens_paths`, and `python` to configure `mkdocstrings`. The `toolchain` block is available for future framework-specific scaffolding steps (e.g. emitting `npm run build` as the build command for Docusaurus hosts).

### Config proposal (`preflight_host.proposed_config`)

`scripts/preflight_host.py:28` derives a complete `config.yml` shape from the discovery dict without writing anything. The `toolchain.docusaurus_dep` field feeds the `framework` detection path indirectly (via `detect_framework`) and the `pages_publishable` flag (Docusaurus hosts are not auto-scaffolded for Pages). Operators see the proposed config before committing to any changes.

### Preflight CLI (`preflight_host.py`)

The preflight tool is a read-only diagnostic. Run it before the setup skill to confirm discovery is correct:

```bash
python scripts/preflight_host.py --repo-root /path/to/host
# or JSON output:
python scripts/preflight_host.py --repo-root /path/to/host --format json
```

It prints:

1. **Discovery** — the raw `discover()` output.
2. **Proposed config** — what `config.yml` would look like.
3. **Secrets checklist** — extracted from the workflow template via `secrets_from_workflow`.
4. **Warnings** — actionable messages from `compute_warnings()`.

Nothing is written. The tool exits zero on success even when warnings are present; use the `warnings` list in the JSON output to decide whether to proceed.

## Adding a new detection field

Every new field must be returned by `discover()` with a safe default (not absent). Add a corresponding `detect_*` helper, call it from `discover()`, and update the fixture at `tests/fixtures/setup_repos/js_docusaurus/` plus any Python-only fixture that tests the new field's fallback path. Tests for detection helpers live in the unit test file alongside the helper — see the JS/TS fixture for the `toolchain` coverage pattern.
