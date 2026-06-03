---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/80
synthesized_into: []
---

# CCE-34 Scope Audit — Archive

**Ticket:** CCE-34 ("Dogfood verify-loop source reconciliation + Pages guard hardening, CCE-32 follow-up")
**Closed by:** PR #80 (`chore/CCE-34-scope-audit`)
**Date:** 2026-05-29

## What CCE-34 covered

CCE-34 was opened as a CCE-32 follow-up. It enumerated three gaps in the publish pipeline and CI coverage:

1. **Publish-verifier `source_dir` mismatch** — `.engineering-docs-agent/config.yml` had `source_dir: docs`, but MkDocs published from `docs/site-src`. The verifier's `url_map_rule=standard` strips `source_dir`, so the dogfood verify-loop could not resolve real URLs.
2. **Missing `actions/upload-pages-artifact` in `NODE24_FLOOR`** — `tests/ci/test_workflow_node_runtime.py` guarded `actions/checkout`, `actions/setup-python`, `actions/configure-pages`, and `actions/deploy-pages`, but not `actions/upload-pages-artifact`. A host regressing to `@v4` of that action (which ships Node 20, deprecated June 2026) would pass the runtime guard undetected.
3. **Generic template path-trigger breadth** — `templates/workflow-pages.yml` triggers on `docs/**`. The setup skill could substitute the actual `source_dir` so hosts with non-site content under `docs/` don't rebuild unnecessarily.

## Audit findings

### Item 1 — Already shipped (REFUTED)

Commit `32182e1` (`fix(CCE-34): publish-align docs-agent to docs/site-src`) corrected the dogfood config before the audit PR landed. `.engineering-docs-agent/config.yml:6` sets `source_dir: docs/site-src`; line 11 sets `lens_paths.core: docs/site-src/`; line 9 sets `agent_editable_paths: ["docs/site-src/**"]`. The setup-skill's `scripts/setup_discover.py:18-27` (`detect_source_dir`) handles arbitrary hosts by preferring `docs/site-src` when it exists.

No residual work for item 1.

### Item 2 — Fixed by PR #80 (CLOSED)

PR #80 added `"actions/upload-pages-artifact": 5` to the `NODE24_FLOOR` dict in `tests/ci/test_workflow_node_runtime.py`. It also added an explicit regression test, `test_upload_pages_artifact_in_node24_floor`, which asserts the dict entry exists with value `5`. The pre-existing `test_no_workflow_pins_a_node20_action_major` now covers `upload-pages-artifact` automatically once the entry is present.

Without the floor entry, the runtime guard had a symmetry gap: `tests/ci/test_workflow_pages_template.py:22` asserted the template pinned `@v5`, but the guard itself would silently pass if a host used `@v4` on this one action.

### Item 3 — Deferred (MARGINAL)

The broader `docs/**` trigger is correctness-neutral — it causes more conservative rebuilds, never wrong ones. Narrowing it requires either post-write YAML edit logic in the setup skill or a `${SOURCE_DIR}` placeholder convention in the template plus substitution wiring. The cost outweighs the benefit for v0.1. If a host raises the rebuild overhead as a real issue, file a new ticket then. No new CCE issue was opened by this audit.

## What PR #80 shipped

- `tests/ci/test_workflow_node_runtime.py` — `NODE24_FLOOR` dict updated with `"actions/upload-pages-artifact": 5`; new `test_upload_pages_artifact_in_node24_floor` regression test added.
- `docs/superpowers/specs/2026-05-29-cce34-scope-audit-design.md` — the canonical design record, capturing the audit rationale and conclusions.
- `docs/superpowers/plans/2026-05-29-cce34-scope-audit.md` — the implementation plan that drove the test-first workflow.

No source-code changes outside the test file. No template edits. No setup-skill changes.

## Canonical records

The detailed investigation and design decisions live in the superpowers tree:

- **Spec:** `docs/superpowers/specs/2026-05-29-cce34-scope-audit-design.md`
- **Plan:** `docs/superpowers/plans/2026-05-29-cce34-scope-audit.md`
- **Architecture page:** [CCE-34 Scope Audit Design](../architecture/2026-05-29-cce34-scope-audit-design.md)
