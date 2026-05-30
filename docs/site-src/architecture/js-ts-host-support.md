---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
---

# JS/TS Host Support

The plugin runs against any host repo. JS/TS hosts — those built around Node, Bun, or Deno, typically publishing docs with Docusaurus — require toolchain-aware detection so the setup skill generates the right config and workflow without manual intervention.

## Toolchain detection

PR #83 adds `detect_toolchain()` to `scripts/setup_discover.py`. The function is wired into the top-level `discover()` call, so toolchain signals are always present in the discovery output when a host is scanned.

`detect_toolchain()` inspects the host root for:

- **Node signals** — presence of `package.json`, `node_modules/`, `.nvmrc`, or `.node-version`.
- **Bun signals** — presence of `bun.lockb` or `bunfig.toml`.
- **Deno signals** — presence of `deno.json` or `deno.jsonc`.
- **Docusaurus presence** — `docusaurus` listed as a dependency (or dev-dependency) in `package.json`, or a `docusaurus.config.js` / `docusaurus.config.ts` file at the root.

Detection is purely read-only and never modifies the host repo. If no JS/TS signals are found, the toolchain key in the discovery result is `null` and downstream stages skip JS/TS-specific handling cleanly.

## Discovery output shape

After detection, the `discover()` result includes a `toolchain` block:

```json
{
  "toolchain": {
    "runtime": "node",       // "node" | "bun" | "deno" | null
    "framework": "docusaurus" // "docusaurus" | null
  }
}
```

The `page-author` and `setup` agents read this block to decide which workflow template variant to render and which secrets checklist entries to surface.

## Fixture coverage

`tests/fixtures/setup_repos/js_docusaurus/` provides a minimal but realistic JS host fixture: a `docusaurus.config.js`, a `package.json` with Docusaurus listed as a dependency, and no Python tooling at the root. Fourteen new tests in the suite cover:

- `detect_toolchain()` returning the correct runtime and framework for the fixture.
- `discover()` propagating the toolchain block through to its output dict.
- The preflight CLI rendering the correct proposed config for a Docusaurus host (see [operations/preflight-host.md](../operations/preflight-host.md)).
- Edge cases: missing `package.json`, `package.json` with no Docusaurus dependency, Bun lockfile alongside `package.json`.

Run the suite with:

```bash
python3 -m pytest tests/ -k js_docusaurus
```

## Design constraints

Detection must not import `node`, `npm`, or any JS runtime. It reads the filesystem only — file existence checks and JSON parsing via Python's stdlib `json` module. This keeps the plugin dependency-free on the plugin side regardless of what the host uses.

The toolchain block is additive. Existing Python-only hosts continue to see `toolchain: null` and no behavior changes. The feature is strictly opt-in by the host's own file layout.

## Related pages

- [operations/workflow-template-generic-hosts.md](../operations/workflow-template-generic-hosts.md) — the workflow template fix that unblocks every non-dogfood host, including JS/TS ones.
- [operations/preflight-host.md](../operations/preflight-host.md) — the `preflight_host.py` CLI that prints the detection output and proposed config for any host.
- [setup-guide.md](../setup-guide.md) — comprehensive install walkthrough, including JS/TS-specific notes.
