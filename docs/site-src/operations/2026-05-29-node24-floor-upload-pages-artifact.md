---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/80
synthesized_into: []
---

# NODE24_FLOOR: adding `actions/upload-pages-artifact` (CCE-34 Item 2)

PR #80 closes the CCE-34 audit umbrella. The primary fix is a symmetry gap in the CI Node-24 runtime guard: `actions/upload-pages-artifact` was missing from the `NODE24_FLOOR` dict, meaning a host regression to `@v4` (Node 20, deprecated June 2026) would silently pass the guard.

## What changed

`actions/upload-pages-artifact` is now present in `NODE24_FLOOR` with a floor value of `5`. A dedicated regression test asserts the entry exists at that value so any future removal fails loudly.

The guard lives in the CI Node-24 runtime check. You can navigate directly to the floor dict and its new test to verify the coverage:

- Floor dict entry: search `NODE24_FLOOR` in the CI guard script for the new `actions/upload-pages-artifact: 5` line.
- Regression test: the test file asserts `NODE24_FLOOR["actions/upload-pages-artifact"] == 5`.

## CCE-34 scope summary

CCE-34 was a CCE-32 follow-up tracking three items:

**Item 1 — dogfood verify-loop source mismatch.** Shipped in commit `32182e1` before this PR.

**Item 2 — NODE24_FLOOR symmetry gap.** Fixed in PR #80 (this change). Without the floor entry, a host that pinned `actions/upload-pages-artifact@v4` would pass the runtime guard while running on a Node version that GitHub is deprecating in June 2026.

**Item 3 — template path-trigger breadth.** Assessed as correctness-neutral and formally deferred. No follow-up ticket was opened.

## What you need to do

No action required for hosts already on `actions/upload-pages-artifact@v5` or later. If your host pins `@v4`, upgrade the pin — the June 2026 Node 20 deprecation is the deadline, not this guard change.

If you maintain a fork of the CI guard script, add `actions/upload-pages-artifact` to your own `NODE24_FLOOR` dict and a matching regression test before the deprecation window closes.
