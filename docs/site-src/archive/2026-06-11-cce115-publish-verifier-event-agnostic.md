---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/137
synthesized_into: []
doc_kind: decision
---

# Publish-verifier: poll build workflow runs regardless of trigger event

## Decision

`publish-verifier`'s first procedure step no longer filters candidate build-workflow runs by `event=push, head_branch=main`. It now selects the newest run of the host's `publishing_config.build_workflow` with `createdAt` at or after the merged PR's merge time — regardless of which event triggered that run — then polls `gh run list --workflow <build_workflow> --json databaseId,event,status,conclusion,createdAt` every 30s until that run reaches `status=completed`, and maps its `conclusion` to `build_status` (`success` → proceed to URL checks; anything else → `build_status: "failure"`).

See `agents/publish-verifier.md` Procedure step 1.

## Why

The old filter assumed every host republishes docs via a plain `push` to `main`. That assumption doesn't hold generically:

- `advanced-data-import-system` (ADIS-264) republishes only on merged `docs-agent/*` PRs — its build workflow fires on `pull_request: closed`, never `push`.
- Hosts that trigger builds via `workflow_dispatch` produce runs with neither `event=push` nor `head_branch=main`.

On both patterns, the old step-1 filter never matched a run, so the verifier burned the full `verify_timeout_seconds` waiting for a run that would never appear and reported a red `build_status: "timeout"` on every merge — even when the publish itself had already succeeded. Event-agnostic selection by `createdAt` fixes this false-negative on any host whose publish trigger isn't a bare push to main.

## What did not change

This is a doc-only edit to `agents/publish-verifier.md`; no runtime script was touched. `scripts/verify_runner.py`'s `publishing_config` keys (`base_url`, `build_workflow`, `url_map_rule`, `verify_timeout_seconds`) are unchanged, and steps 2–5 of the procedure (URL derivation, `curl` status checks, optional fingerprinting, timeout handling) are unaffected.

## Verification status

PR #137's test-plan checkboxes were unchecked at merge time. End-to-end validation is deferred to the first `docs-agent/*` merge on `advanced-data-import-system` after its ADIS-264 PR lands, since that host is the one that consumes plugin `main` at runtime and exercises the `pull_request: closed` trigger path this change targets.

## Reference

PR #137. Host repo: `advanced-data-import-system`, ticket ADIS-264.
