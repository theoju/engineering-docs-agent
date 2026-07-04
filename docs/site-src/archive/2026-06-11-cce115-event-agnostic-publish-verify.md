---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/137
synthesized_into: []
doc_kind: decision
---

# CCE-115: make publish-verifier event-agnostic

## Context

`publish-verifier` polls the host's downstream build workflow after a docs-agent PR merges, then checks that the changed pages are live. Before this change, the procedure (`agents/publish-verifier.md:61`) required a `build_workflow` run with `event=push` and `head_branch=main` — the shape produced when a merge to `main` fires the workflow directly.

That assumption breaks on hosts whose publish workflow doesn't trigger on `push`. `advanced-data-import-system`'s ADIS-264 setup republishes only on `pull_request: closed` for merged `docs-agent/*` PRs; other hosts trigger via `workflow_dispatch`. On those hosts, `gh run list` never returns a run matching `event=push`, so the verifier burned the full `verify_timeout_seconds` on every run, reported `build_status: "timeout"`, and exited red — even when the publish had actually succeeded.

## Decision

`publish-verifier` now selects the newest run of the configured `build_workflow` with `createdAt` at or after the merge time, **regardless of which event triggered it**. It waits for that run to reach `status=completed`, then maps `conclusion` to `build_status` as before (`success` → proceed to URL checks; anything else → `failure`).

The procedure step (`agents/publish-verifier.md:61`) still polls `gh run list --workflow <build_workflow> --json databaseId,event,status,conclusion,createdAt` every 30s, but the run-selection filter is now createdAt-only, not event+branch.

## Why

Filtering on `event=push` encoded one host's trigger model as if it were universal. It isn't: `pull_request: closed` and `workflow_dispatch` are both legitimate ways for a host to gate a rebuild on a merged docs PR rather than every push to `main`. The old filter made the verifier fail closed on any host that didn't match the dogfood repo's own workflow shape — the generic-first mandate this plugin is built on.

Timestamp-based selection is the weaker, more portable assumption: whatever fired the build, the run that matters is the newest one created after the merge.

## Scope of this change

This was a doc-only change to `agents/publish-verifier.md` — the agent's own spec — not to `scripts/verify_runner.py`. The dispatch contract's `publishing_config` keys (`base_url`, `build_workflow`, `url_map_rule`, `verify_timeout_seconds`) are unchanged; no caller needs to update its config shape.

End-to-end validation is deferred to the first `docs-agent/*` merge on `advanced-data-import-system` after its ADIS-264 PR lands — that's the host this fix was written for, and the one that will exercise the `pull_request: closed` trigger path for real.
