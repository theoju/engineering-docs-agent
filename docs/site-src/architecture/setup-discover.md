---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
---

# setup_discover — host detection

`scripts/setup_discover.py` is the plugin's host-repo scanner. The setup skill and `preflight_host.py` both call `discover(cwd)`, which runs every detector in sequence and returns a single structured dict. Nothing is written to disk; the output is a read-only snapshot of what the setup skill _would_ configure.

## Detection pipeline

`discover()` at `scripts/setup_discover.py:203` calls these detectors in order:

| Detector | Returns | Key use |
|---|---|---|
| `detect_framework` | `"mkdocs"` \| `"docusaurus"` \| `None` | Framework gate for source dir + publishability |
| `detect_source_dir` | path string \| `None` | Root for the docs lens |
| `detect_lens_paths` | `dict[name, path]` | Auto-populates `lens_paths` in config |
| `detect_ci` | `"github_actions"` \| `"gitlab_ci"` \| `None` | Determines publish scaffold path |
| `detect_python` | `{detected, scan_dir, path_root}` | Drives mkdocstrings config |
| `detect_openapi_hint` | filename \| `None` | Surfaces schema file for API docs |
| `detect_toolchain` | `{node, bun, deno, package_manager, docusaurus_dep}` | JS/TS host detection |
| `detect_jira_hint` | `{base_url}` \| `None` | Seeds Jira config block |

The result dict always contains all eight keys. Missing values are `None` or `{}`, never absent.

## Toolchain detection (JS/TS hosts)

`detect_toolchain` at `scripts/setup_discover.py:89` was added in PR #83 to support the first JS/TypeScript Docusaurus host. It answers two questions: what package manager is in use, and is this a Docusaurus project?

**Package manager resolution** checks for lockfiles in priority order: `bun.lockb` → `pnpm-lock.yaml` → `yarn.lock` → `package-lock.json`. The first match wins; `bun` beats every npm-family lockfile.

**Docusaurus detection** reads `package.json` (capped at 32 KB) and looks for any `@docusaurus/*` key in `dependencies`, `devDependencies`, or `peerDependencies`. A malformed `package.json` is silently tolerated — `docusaurus_dep` falls back to `False` rather than erroring.

The dict shape returned:

```python
{
    "node": bool,           # package.json present
    "bun": bool,            # bun.lockb present
    "deno": bool,           # deno.json or deno.jsonc present
    "package_manager": str | None,  # "npm" | "yarn" | "pnpm" | "bun" | None
    "docusaurus_dep": bool, # @docusaurus/* in package.json
}
```

## Python/MkDocs vs JS/Docusaurus paths

Both paths share the same `detect_framework` gate at `scripts/setup_discover.py:8`.

For **MkDocs hosts**, `detect_python` resolves the source root for mkdocstrings. It prefers a top-level Python package (a directory containing `__init__.py`), then falls back to conventional loose-module directories (`src/`, `scripts/`). `detect_pages_publishable` returns `True` only when `framework == "mkdocs"` and `ci == "github_actions"`.

For **Docusaurus hosts**, `detect_python` still runs but `detected` will be `False` for a pure JS/TS repo — expected. `discover()` emits a warning with code `docusaurus_v0.1_unsupported` (at `scripts/setup_discover.py:208`) noting that v0.1 only validates MkDocs builds. Lint rules still run; only the MkDocs build validation step is skipped.

`preflight_host.py:compute_warnings` at `scripts/preflight_host.py:113` adds a `node_only_host` advisory when `toolchain.node` is `True` and `python.detected` is `False`. This is informational — it tells operators that the orchestrator runs Python from the `.docs-agent-plugin/` install directory, not the host repo.

## Fixture coverage

`tests/fixtures/setup_repos/js_docusaurus/` represents a minimal Docusaurus repo for unit tests. If you add a new toolchain detection branch, add a corresponding fixture directory there and test against it directly — do not test against this repo's own tree.

## preflight_host.py

`scripts/preflight_host.py` is a read-only CLI that wraps `discover()` and surfaces what the setup skill would produce before you commit to installing.

```bash
python scripts/preflight_host.py --repo-root /path/to/host
python scripts/preflight_host.py --repo-root /path/to/host --format json
```

The text output shows discovery results, the proposed `config.yml` shape, a secrets checklist (`CLAUDE_CODE_OAUTH_TOKEN`, `DOCS_AGENT_APP_PRIVATE_KEY`), a repo Variables checklist (`DOCS_AGENT_APP_CLIENT_ID`, `JIRA_EMAIL`), and any warnings. No files are modified. Run it before `engineering-docs-agent-setup` to validate prerequisites and confirm the detection output matches your host's shape.

The secrets list is derived from `secrets.X` references in `templates/workflow-run.yml`. `GITHUB_TOKEN` is filtered out (always injected by Actions). The two blocking secrets — `CLAUDE_CODE_OAUTH_TOKEN` and `DOCS_AGENT_APP_PRIVATE_KEY` — are always included even if the template is missing them, as a defense-in-depth measure (`scripts/preflight_host.py:86`).
