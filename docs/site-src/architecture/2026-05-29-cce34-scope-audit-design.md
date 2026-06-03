---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/80
synthesized_into: []
---

# CCE-34 Scope Audit — Design Record

**Ticket:** CCE-34 ("Dogfood verify-loop source reconciliation + Pages guard hardening (CCE-32 follow-up)")
**Branch:** `chore/CCE-34-scope-audit`
**Merged:** PR #80

CCE-34 was opened as a CCE-32 follow-up. Three items were on the original scope. This record captures the audit findings and the design decision for each.

## Original scope

1. **Dogfood verify-loop source mismatch** — `.engineering-docs-agent/config.yml` had `source_dir: docs`, but MkDocs published from `docs/site-src`. The publish-verifier's `url_map_rule=standard` strips `source_dir`; the mismatch meant the verifier could not resolve real URLs for the dogfood host.
2. **Missing Node-24 floor for `actions/upload-pages-artifact`** — `tests/ci/test_workflow_node_runtime.py` pinned floors for `actions/checkout`, `actions/setup-python`, `actions/configure-pages`, and `actions/deploy-pages`, but not for `actions/upload-pages-artifact`. The template-validity test hard-checked `@v5`, but the runtime guard would silently pass if a host regressed to `@v4` on that one action.
3. **Generic template path-trigger breadth** — `templates/workflow-pages.yml` triggers on `docs/**`. The setup skill could substitute the discovered `source_dir` so hosts with unrelated content under `docs/` don't rebuild the site on every change.

## Findings

### Item 1 — Refuted (already shipped)

Commit `32182e1` (`fix(CCE-34): publish-align docs-agent to docs/site-src`) already corrected the mismatch. `.engineering-docs-agent/config.yml:6` now sets `source_dir: docs/site-src`; line 11 sets `lens_paths.core: docs/site-src/`; line 9 sets `agent_editable_paths: ["docs/site-src/**"]`.

`scripts/setup_discover.py:18-27` (`detect_source_dir`) also handles arbitrary new hosts: it prefers `docs/site-src` when it exists, else falls back to `docs`. A fresh MkDocs host following the same convention is auto-aligned without manual config.

No residual work.

### Item 2 — Valid, shipped in PR #80

`tests/ci/test_workflow_node_runtime.py:25-30` contained:

```python
NODE24_FLOOR = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/configure-pages": 6,
    "actions/deploy-pages": 5,
}
```

`actions/upload-pages-artifact` was absent. The template (`templates/workflow-pages.yml:42`) and the dogfood workflow (`.github/workflows/docs-pages.yml:35`) both pin `@v5`, and `tests/ci/test_workflow_pages_template.py:22` asserts the template carries `@v5`. But the runtime guard (`test_no_workflow_pins_a_node20_action_major`, lines 40–47) only flags actions listed in `NODE24_FLOOR` — so a host regressing to `@v4` on this action would pass undetected.

v4 of `actions/upload-pages-artifact` ships Node 20 (deprecated June 2026). v5 is the first Node-24 major. PR #80 adds the missing entry:

```python
NODE24_FLOOR = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/configure-pages": 6,
    "actions/deploy-pages": 5,
    "actions/upload-pages-artifact": 5,
}
```

A new explicit test, `test_upload_pages_artifact_in_node24_floor`, asserts the key exists with value 5. Future deletion of the entry fails that test loudly. The pre-existing `test_no_workflow_pins_a_node20_action_major` now automatically covers `upload-pages-artifact` as well.

### Item 3 — Deferred (correctness-neutral)

`templates/workflow-pages.yml:10-11` triggers on `docs/**`. The setup skill (`skills/engineering-docs-agent-setup/SKILL.md:34`, Step 6a) does not substitute the `paths:` trigger with the discovered `source_dir`.

A broader trigger is never incorrect — it causes more conservative rebuilds, not wrong rebuilds. Narrowing it requires either post-write YAML edit logic in the setup skill or a `${SOURCE_DIR}` placeholder convention in the template plus substitution. The cost of that machinery outweighs the upside for v0.1.

This item is deferred without a new CCE issue. If a host reports unnecessary rebuild cycles, file a fresh ticket.

## What shipped

The only behavioral change in PR #80 is a single dict entry in `tests/ci/test_workflow_node_runtime.py` and one new test function. No source code outside the test file changed. No template edits. No setup-skill changes.

The scope-audit plan (`docs/superpowers/plans/2026-05-29-cce34-scope-audit.md`) and this spec (`docs/superpowers/specs/2026-05-29-cce34-scope-audit-design.md`) are the documentation artifacts that close the CCE-34 umbrella.

## Non-goals

- Re-opening item 1. The dogfood publish loop is correct; commit `32182e1` is the record.
- Implementing item 3's path-trigger narrowing.
- Touching any work from CCE-40, CCE-41, CCE-55, CCE-56, or CCE-59. None of those intersect the three original CCE-34 items.
