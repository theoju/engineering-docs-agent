---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/80
synthesized_into: []
---

# Node 24 Floor: Pages Upload Guard (CCE-34)

The `NODE24_FLOOR` CI check enforces a minimum Node.js runtime version across
all workflow steps. PR #80 (CCE-34) extended that check to cover the
`upload-pages-artifact` step, which had been left out of the original
CCE-32 guard scope.

## What changed

The `upload-pages-artifact` action is now included in the set of workflow steps
the `NODE24_FLOOR` runtime check validates. Before this change, the step could
run on a pre-Node-24 runner without triggering a CI failure.

The guard logic lives in `tests/ci/test_workflow_node_runtime.py`. That test
file carries the authoritative list of steps that must satisfy the Node 24 floor.
If you add a new workflow step that invokes a Node action, add its step ID there.

## Why this matters

GitHub Pages upload is a late-stage step: it runs after your docs are built and
after the pages artifact is assembled. A runtime mismatch at that point produces
an opaque failure that's hard to distinguish from a publish-path bug. The guard
catches the mismatch at CI time, before merge, with a clear error message.

## CCE-34 scope disposition

CCE-34 was an audit umbrella over three scope items carried forward from CCE-32:

| Item | Disposition |
|------|------------|
| 1 | No further work required |
| 2 | Implemented — `upload-pages-artifact` added to `NODE24_FLOOR` check |
| 3 | No further work required |

The formal record is in `docs/superpowers/plans/2026-05-29-cce34-scope-audit.md`
and `docs/superpowers/specs/2026-05-29-cce34-scope-audit-design.md`. Those files
document the rationale for items 1 and 3 being closed without code changes.
