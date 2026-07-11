---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/137
synthesized_into: []
doc_kind: decision
---

# Decision: Publish-Verifier Run Selection Is Event-Agnostic (CCE-115)

The `publish-verifier` subagent's step 1 no longer filters build-workflow runs by trigger event. It now selects the newest `build_workflow` run whose `createdAt` is at or after the merge time, whatever fired it, then polls that run until `status=completed` and maps its `conclusion` to `build_status`.

## Problem

Before this fix, step 1 of `agents/publish-verifier.md` filtered candidate runs by `event=push` and `head_branch=main`. That assumption holds for hosts that redeploy on a straight push to `main`, but not for every host.

`advanced-data-import-system` (ADIS-264) triggers its publish workflow on `pull_request: closed`, and some hosts use `workflow_dispatch` for manual redeploys. On those hosts the push/head_branch filter never matched a real run. The verifier polled for a run that would never appear, burned the full `verify_timeout_seconds`, and reported `build_status: "timeout"` (surfaced as a red build status) even when the publish workflow had actually succeeded.

## Fix

Run selection is now driven purely by timing, not trigger identity: `gh run list --workflow <build_workflow> --json databaseId,event,status,conclusion,createdAt`, polled every 30s, picking the newest run with `createdAt` at or after the merge time. The verifier waits for that run's `status` to reach `completed`, then maps `conclusion=success` to proceeding with the URL checks in steps 2–4, and any other conclusion to `build_status: "failure"`. The event/branch fields are still present in the polled JSON but no longer used as a selection filter — see `agents/publish-verifier.md:61`.

This makes the run-selection criterion agnostic to whether a host redeploys on `push`, `pull_request: closed`, or `workflow_dispatch`. No config change is required on hosts already publishing correctly; the fix only removes false-red reports on hosts whose trigger model differed from push-to-main.

## Reference

PR #137 (CCE-115). Failure handling on no matching run is unchanged: retry until `verify_timeout_seconds` elapses, then emit `build_status: "timeout"`.
