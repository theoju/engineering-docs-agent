---
description: "The page-author subagent writes or edits a single documentation page per invocation."
source_files:
  - scripts/preflight_host.py
last_reviewed: '2026-06-09'
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/84
synthesized_into: []
---

# Page-Author Agent

The `page-author` subagent writes or edits a single documentation page per invocation. The orchestrator spawns one instance per target page per nightly run, passing it a set of PR summaries, voice samples, and a frontmatter template. The agent reads the existing file (on `edit`) or drafts from scratch (on `create`), integrates the PR content, and writes the result back to disk.

## Framework detection and section gating

The agent gates which sections it emits based on the `framework` key in the host's config. Supported frameworks each produce a fixed set of sections: dependency lists, framework-specific configuration snippets, and test-runner notes. When a host declares `framework: none` — or omits the key entirely — none of those sections apply.

Before PR #84, the `none`/omitted path fell through to the same section-rendering logic as named frameworks. The rendered output contained the section headings with empty content: structurally valid markdown, but useless and confusing to readers.

The agent now checks for `framework: none` explicitly before invoking any framework-specific renderer. If the check matches, those sections are skipped entirely. The page contains only sections whose content is framework-agnostic — introduction, data flow, configuration, and operational notes.

## Preflight config roundtrip

`scripts/preflight_host.py` computes the config the setup skill would write, without modifying the host repo. Before PR #84, when discovery found no recognised framework, the `framework` key was absent from the proposed config. On a subsequent nightly run, `proposed_config` re-read an absent key as `None`, which did not match the string `"none"` — causing the framework check to misfire.

The fix writes `framework: none` explicitly when discovery returns no framework (`preflight_host.py:112-113`):

```python
"framework": framework or "none",
```

This ensures the config roundtrips correctly. A host that picks "none" at setup time sees `framework: none` in `.engineering-docs-agent/config.yml`, and every subsequent run reads it back as the same value.

## Test coverage

Three tests were added alongside this change:

- **`none` selection**: verifies the page-author agent skips framework-specific sections when `framework` is `"none"`.
- **Config roundtrip**: verifies `proposed_config` emits `framework: none` when discovery returns no framework, and that re-parsing the written config produces the same value.
- **Graceful degradation**: verifies that a host config with no `framework` key at all (legacy state before the fix) is treated equivalently to `framework: none` — no crash, no empty stubs.

All three live in `tests/test_preflight_host.py` and follow the fixture-driven dry-run pattern — no host filesystem access required.

## Invariant

Any host that does not use a recognised framework must produce clean, stub-free documentation pages. The `framework: none` path is now first-class: explicitly detected, explicitly rendered, and explicitly tested. If you add a new framework-specific section to the page-author agent's rendering pipeline, add a corresponding guard that skips it when `framework` is `"none"` or absent.
