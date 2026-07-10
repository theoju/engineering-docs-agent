---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/137
synthesized_into: []
doc_kind: decision
---

# Decision: publish-verifier polls build runs event-agnostically

## Problem

`publish-verifier` (`agents/publish-verifier.md`) polls the host's downstream
build workflow after a docs-agent PR merges, then checks that the changed
pages are live. Before PR #137, step 1 of its procedure selected a run by
matching `event=push` and `head_branch=main` — it only recognized a build
triggered by a direct push to `main`.

Hosts that publish some other way never produced a matching run. Two real
trigger models hit this:

- `pull_request: closed` — republish-on-merged-docs-agent-PR, the setup used
  by `advanced-data-import-system` (ADIS-264).
- `workflow_dispatch` — manual or externally-triggered publish.

On both, the verifier burned the full `verify_timeout_seconds` waiting for a
run that would never arrive under the old filter, then reported
`build_status: "timeout"` (exit 1) — even when the publish had actually
succeeded.

## Fix

The run-selection step is now event-agnostic. `publish-verifier` waits for the
newest `build_workflow` run whose `createdAt` is at or after the merge time,
**regardless of which event triggered it** — push, `pull_request: closed`, or
`workflow_dispatch` all qualify. It still polls
`gh run list --workflow <build_workflow> --json databaseId,event,status,conclusion,createdAt`
every 30s, still waits for `status=completed`, and still maps the run's
`conclusion` to `build_status` the same way as before (`success` → proceed to
URL checks; anything else → `build_status: "failure"`; no matching run before
`verify_timeout_seconds` elapses → `build_status: "timeout"`).

See `agents/publish-verifier.md` §Procedure, step 1, for the current wording.

## Why this is safe

Merge-time is still the anchor: any run created before the merge is ignored,
so the verifier can't accidentally pick up a stale build from an unrelated
change. Narrowing to `event=push`/`head_branch=main` was never load-bearing
for correctness — it was an assumption about how hosts trigger their build,
and that assumption doesn't hold across hosts. Dropping it makes the verifier
match the plugin's generic-first mandate: detect the actual run instead of
hardcoding a trigger shape.

## Reference

PR #137. Root cause and fix confirmed against `agents/publish-verifier.md`.
