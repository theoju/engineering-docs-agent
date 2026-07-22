---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/84
synthesized_into: []
doc_kind: architecture
---

# Setup Framework Detection

The setup skill probes the host repo root for a supported docs framework before writing any config. Detection is intentionally minimal: two files decide the outcome, and when neither is found, `framework: none` is recorded explicitly rather than left absent.

## Detection logic

`scripts/setup_discover.py:detect_framework` (`detect_framework`) checks for exactly two indicators:

- `mkdocs.yml` at the repo root → `"mkdocs"`
- `docusaurus.config.js` or `docusaurus.config.ts` at the repo root → `"docusaurus"`

If neither file exists, the function returns `None`. The preflight script (`scripts/preflight_host.py`) normalises that to the string `"none"` before writing it into the proposed config:

```python
"framework": framework or "none",
```

This means the config file always contains an explicit `framework` key. Before CCE-64, a host with no framework could end up with the field absent, which caused the page-author agent to fall through to framework-specific section templates and emit empty stubs.

## What changes with `framework: none`

When `docs.framework` is `"none"`, the following capabilities are skipped cleanly; everything else runs normally:

| Capability | Behavior |
|---|---|
| `framework_build` lint rule | Skipped — no build command to invoke |
| Publish-verifier build step | Skipped — no site artefact to verify |
| Framework-specific page sections (dependencies, configuration, testing) | Omitted by page-author agent — no empty stubs |
| PR summarisation, page authoring, what's-new updates | Run normally |

The page-author agent now explicitly tests for the none case and skips those sections entirely rather than rendering them with blank content.

## Preflight warning

When setup discovers no framework, `scripts/preflight_host.py` appends a `framework_none` entry to the warnings list with `severity: "info"` (not a blocking error). You will see:

```
Warnings
------------------------------------------------------------
  - framework_none: No mkdocs.yml or docusaurus.config.* found at the repo root.
    Config will write framework: none. The framework_build lint rule and the
    publish-verifier skip cleanly; PR summaries, page authoring, and what's-new
    updates run normally. If you want strict build-time link checking, scaffold
    mkdocs (`mkdocs init`) and re-run preflight.
```

The severity is `info` because a none-framework host is a valid, fully supported configuration — not a misconfiguration.

## Config round-trip

Once `framework: none` is written to `.engineering-docs-agent/config.yml`, subsequent runs read the field and follow the same skip-path they would have taken on first detection. The string `"none"` compares equal to itself; there is no ambiguity between an absent key and an explicit none value.

If you later add `mkdocs.yml` to the repo root and re-run the setup skill, detection returns `"mkdocs"`, the config is updated, and the previously-skipped capabilities activate automatically. No manual config surgery is required.

## Scaffolding mkdocs on a none-framework host

If you want build-time link checking, add a minimal mkdocs config to the repo root before running setup:

```bash
pip install mkdocs-material
mkdocs new .
# Edit mkdocs.yml: set docs_dir to match your source_dir
python scripts/preflight_host.py --repo-root . --format text
```

Re-running preflight after adding `mkdocs.yml` will show `framework: mkdocs` in the proposed config and remove the `framework_none` warning.
