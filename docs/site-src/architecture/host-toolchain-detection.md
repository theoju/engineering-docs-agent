---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
---

# Host Toolchain Detection

The plugin discovers each host's language runtime and docs framework before install so the setup skill can tailor its output without prompting for information it can derive automatically.

## `detect_toolchain` — JS/TS runtime probing

`scripts/setup_discover.py:89` adds `detect_toolchain(cwd: Path) -> dict` for JavaScript and TypeScript hosts. It runs at the end of `discover()` and its output lands under the `toolchain` key of every discovery report.

The function returns five fields:

| Key | Type | Meaning |
|-----|------|---------|
| `node` | `bool` | `package.json` exists at the repo root |
| `bun` | `bool` | `bun.lockb` exists at the repo root |
| `deno` | `bool` | `deno.json` or `deno.jsonc` exists at the repo root |
| `package_manager` | `str \| None` | Lockfile-derived: `"bun"` beats all npm-family files; then `pnpm`, `yarn`, `npm` in order |
| `docusaurus_dep` | `bool` | Any `@docusaurus/*` key in `dependencies`, `devDependencies`, or `peerDependencies` of `package.json` |

`package_manager` is lockfile-derived, not config-derived. If a host has both `pnpm-lock.yaml` and `package-lock.json`, `pnpm` wins because it is checked first. `bun.lockb` takes priority over every npm-family lockfile.

`docusaurus_dep` reads at most 32 KB of `package.json` and swallows malformed JSON — a malformed file results in `docusaurus_dep: false`, not an error.

### Docusaurus detection and `discover()`

When `detect_framework` (`scripts/setup_discover.py:8`) already found a Docusaurus config file, `discover()` emits a `docusaurus_v0.1_unsupported` warning (`scripts/setup_discover.py:209`). The `toolchain.docusaurus_dep` flag is independent: a host with `@docusaurus/core` in `package.json` but no config file at the repo root would show `docusaurus_dep: true` while `framework` remains `None`.

## Workflow template — plugin vendoring

`templates/workflow-run.yml` was fixed in PR #83 to vendor the plugin into `.docs-agent-plugin/` rather than assume the orchestrator script lives in the host root.

The template now runs a second `actions/checkout` step:

```yaml
- name: Check out engineering-docs-agent plugin
  uses: actions/checkout@v5
  with:
    repository: theoju/engineering-docs-agent
    ref: main
    path: .docs-agent-plugin
```

The orchestrator step then invokes `python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .` (`templates/workflow-run.yml:52`).

This was a generic defect: any non-dogfood host would fail at the `python scripts/orchestrator_runner.py` invocation because its working directory is the host root, not the plugin clone. The vendoring pattern works on every host regardless of language stack.

## `preflight_host.py` — pre-install inspection

`scripts/preflight_host.py` is a read-only CLI you run against any host repo before running the setup skill. It does not modify anything.

```bash
python scripts/preflight_host.py --repo-root /path/to/host
python scripts/preflight_host.py --repo-root /path/to/host --format json
```

The text report shows three sections:

1. **Discovery** — the full `discover()` output, including `toolchain` and `python` blocks.
2. **Proposed config** — the `config.yml` the setup skill would write, with safe defaults for notification and lint blocks.
3. **Secrets checklist** — extracted from `templates/workflow-run.yml` via regex. Three secrets are marked `[required]`: `CLAUDE_CODE_OAUTH_TOKEN`, `DOCS_AGENT_APP_ID`, `DOCS_AGENT_APP_PRIVATE_KEY`. Others are `[optional]`.

The checklist is built from the shipped workflow template at `scripts/preflight_host.py:73`. If the template file is missing (e.g., running the CLI from a partial clone), the secrets list falls back to the three hardcoded required names only.

`preflight_host.py` also adds computed warnings beyond what `discover()` emits:

- `pages_not_auto_scaffolded` — Docusaurus detected but `pages_publishable` is false. The user needs to set `publishing.build_command` and `publishing.site_dir` manually.
- `node_only_host` — Node detected with no Python package. This is expected for JS/TS hosts; the orchestrator runs Python from `.docs-agent-plugin/`, not the host's own tree.

Run `preflight_host.py` before install on any new host. It surfaces config shape and the full secrets list without making any changes.

## JS/TS fixture

`tests/fixtures/setup_repos/js_docusaurus/` provides a minimal fixture for the new detection paths: a `package.json` with a `@docusaurus/core` dependency and a `docusaurus.config.js`. Tests covering `detect_toolchain` and the `node_only_host` warning path use this fixture to avoid coupling to this repo's own tree.
