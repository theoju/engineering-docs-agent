---
description: "PR #119 (CCE-105) replaces the flat API reference layout with a config-declared group structure."
source_files:
  - scripts/orchestrator_runner.py
last_reviewed: '2026-06-09'
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/119
synthesized_into: []
---

# API Reference Grouping

PR #119 (CCE-105) replaces the flat API reference layout with a config-declared group structure. The change is Phase 2a of the docs-site remediation roadmap.

## What changed

`gen_ref_pages.py` now calls `assign_group(ident, groups)` at build time to assign each module to a named group before emitting its SUMMARY entry. The function accepts both dotted (`scripts.orchestrator_runner`) and path-form (`scripts/orchestrator_runner.py`) identifiers and uses first-match-wins semantics. When no match is found, the module lands in an unclassified fallback bucket — the same flat behavior as before, so hosts without declared groups see no difference.

The groups themselves are declared in the host config under `site.sections[].groups`. Six groups cover all 22 modules on this dogfood host: Orchestrator, Generators, Lint, Setup, Verification, and Integrations. No module is left unclassified.

## JSON-schema contracts extractor

The dormant contracts extractor is now active. It runs against `agents/schemas/` and produces 7 contract pages plus an index. These pages appear in the API reference as first-class documentation entries, surfacing each agent's output contract alongside the Python module docs.

## Discovery hooks

`preflight_host._proposed_site` gains two generic discovery hooks — `contract_sources` and `api_groups` — so setup automatically proposes the contracts extractor and a skeleton groups config on conforming hosts. Hosts that carry neither `agents/schemas/` nor a declared `sections[].groups` are unaffected; the hooks degrade cleanly with no errors.

## Nav visibility

The group structure is written into the SUMMARY file at build time, but it is not yet user-visible in the site nav. Nav rendering requires literate-nav to consume the reference SUMMARY, which is wired in CCE-106. Until CCE-106 lands, the grouping is structurally correct in the generated SUMMARY but does not appear in the published navigation tree.

## Declaring groups on your host

Add a `groups` list to any section entry in your `site.sections` config:

```yaml
site:
  sections:
    - name: API Reference
      groups:
        - name: Orchestrator
          match:
            - scripts.orchestrator_runner
            - scripts.state_io
        - name: Lint
          match:
            - scripts/lint/
```

Each `match` entry is either a dotted module prefix or a path prefix. The build assigns a module to the first group whose match list contains it. Modules with no match degrade to the flat layout; no build error is raised.

If your host has no `sections[].groups` declared, `gen_ref_pages.py` produces the same flat output as before CCE-105. No config migration is required.
