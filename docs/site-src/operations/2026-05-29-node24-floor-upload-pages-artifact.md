---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/80
synthesized_into: []
---

# CI hardening: `actions/upload-pages-artifact` added to `NODE24_FLOOR`

**PR #80 · 2026-05-29 · CCE-34**

## What changed

`actions/upload-pages-artifact` was missing from the `NODE24_FLOOR` dict in the CI Node-24 runtime guard. That gap meant a host pinned to `@v4` of that action would pass the guard silently — `v4` ships Node 20, which is deprecated in June 2026. `v5` is the first major release that ships Node 24.

PR #80 adds the entry and pins the minimum version to `v5`:

```python
# scripts/ci_node24_floor.py (NODE24_FLOOR dict)
"actions/upload-pages-artifact": "v5",
```

A dedicated regression test — `test_upload_pages_artifact_in_node24_floor` — asserts the floor entry exists so future symmetry gaps in this dict surface immediately in CI rather than through a silent runtime regression.

## Why it matters

The Node-24 floor check exists to catch action regressions before they reach production. A missing entry is a silent exemption: the guard passes, the action runs on Node 20, and the failure surfaces only after the workflow runs. This fix closes the gap for the most commonly pinned Pages upload action.

## Scope of the CCE-34 audit

This change was the last open item from the CCE-34 scope audit. Three items were tracked:

1. **Dogfood verify-loop source mismatch** — refuted; already resolved in commit `32182e1`.
2. **`NODE24_FLOOR` symmetry gap for `actions/upload-pages-artifact`** — fixed here.
3. **Template `paths:` trigger breadth** — deferred; assessed as correctness-neutral with no action required.

The full audit record is in `docs/site-src/archive/2026-05-29-cce34-scope-audit.md`.

## What you need to do

If your host workflow pins `actions/upload-pages-artifact` at `@v4`, upgrade it to `@v5`. After upgrading, the guard passes and your Pages deploy runs on the required Node 24 runtime.

No config changes are needed in `.engineering-docs-agent/config.yml`. The floor check is internal to the guard script and takes effect automatically on the next nightly run.
