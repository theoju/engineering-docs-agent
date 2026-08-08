---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/190
synthesized_into: []
doc_kind: decision
---

# Decision: Provider-Aware Publish Trigger (CCE-123)

**Date:** 2026-07-24  
**Ticket:** CCE-123  
**PR:** [#190](https://github.com/theoju/engineering-docs-agent/pull/190)
**Sibling:** CCE-63 (the post-merge *verify* seam)

## Context

CCE-63 made the post-merge **verify** seam provider-aware: `scripts/verify_runner.py` forks on `publishing.ci_provider`, and a non-`github` host degrades honestly through `build_poller.resolve_build_verdict` instead of mis-verifying against an API it can't validate. That change deliberately left a second GitHub-only seam open: the post-merge **trigger**.

After a docs-agent PR auto-merges, `_maybe_auto_merge` in `scripts/orchestrator_runner.py` has to kick the host's build — a `GITHUB_TOKEN` merge does not fire an `on: push` workflow, so without an explicit dispatch the site never redeploys. Before this change, that dispatch was unconditionally `gh.workflow_run(build_workflow)`. For a `ci_provider: circleci` host, that call is meaningless: there's no GitHub Actions workflow to run.

A strict-xfail acceptance test guarded the gap in the meantime: `tests/orchestrator/test_build_poller.py::test_publish_trigger_is_provider_aware` asserted `"ci_provider" in inspect.getsource(orchestrator_runner._maybe_auto_merge)`, `strict=True` so it would flip to a hard failure the moment the seam became provider-aware, forcing this change to remove the marker as part of landing.

## Decision

`_maybe_auto_merge` now forks on a new `ci_provider: str | None = None` keyword parameter, threaded from the call site as `config.get("publishing", {}).get("ci_provider")`. Absent field resolves to `"github"`, so an existing host's behavior is byte-for-byte unchanged with zero config edits.

- **`github`** (default, or `ci_provider` absent): `gh.workflow_run(build_workflow)` fires exactly as before. Success records `pages_dispatch_succeeded: <workflow>`; failure records `pages_dispatch_failed: <error>`.
- **Non-`github`** (currently only `circleci`): no GitHub Actions dispatch happens at all. `_maybe_auto_merge` instead calls `resolve_build_trigger(provider)` in `scripts/build_poller.py`, which returns a single reason recorded as `pages_dispatch_skipped: circleci_trigger_modeled_but_unvalidated`.

All reasons on this path stay `info_only=True` — the trigger seam is hygiene, mirroring D2 auto-close, and never flips a run to `partial`.

## The real trigger is still a stub

`resolve_build_trigger` and its underlying `trigger_circleci` live behind the same `UNVALIDATED_AGAINST_LIVE_HOST` module-level flag that gates the CCE-63 verify seam's `resolve_build_verdict`. While the flag is `True` (the shipped, production value), `resolve_build_trigger` short-circuits to the honest-degrade reason and never calls `trigger_circleci`. If the flag were flipped before a real trigger shipped, `trigger_circleci` raises `NotImplementedError` — deliberately, and deliberately uncaught: the merge has already happened by that point, so swallowing the exception would hide the "you turned this on before it was ready" signal. `TRIGGER_UNVALIDATED_REASON` is a fixed literal, never interpolating a token or response, the same discipline the verify seam's `PROVIDER_UNVALIDATED_REASON` follows.

There is no live CircleCI-publishing host to validate the trigger API shape against, so shipping an unvalidated real call was rejected in favor of the honest skip. The working hypothesis — undocumented as fact — is that CircleCI's VCS integration typically rebuilds on the merge push anyway, making an explicit trigger likely unnecessary; that hypothesis is only promotable to a `not_required_builds_on_push` reason framing after live-host confirmation, which hasn't happened.

## Alternatives considered

**Generic config-driven `trigger_command`.** Rejected as over-general for one known second provider: it adds a config/schema surface and a security concern (running host-supplied commands), and diverges from the `ci_provider` enum the verify seam already forks on.

**Ship the real CircleCI v2 trigger now.** Rejected — unvalidated against any live host, untestable, and violates the repo's "verify with the real consumer tool" invariant.

**Block auto-merge for non-`github` hosts.** Rejected as the wrong lever: it changes merge *eligibility*, not the trigger, and CircleCI likely rebuilds on the push anyway, so blocking would be strictly worse.

**Silent no-op.** Rejected — gives an operator no signal to answer "why didn't my site redeploy?", violating the standing "log what's dropped" discipline.

## What this does not change

No new config field is introduced; `publishing.ci_provider` already existed for the CCE-63 verify seam and both seams now read the same field. Merge eligibility is unaffected — this is purely a post-merge dispatch decision. The `github` path's digest output is unchanged for `github` hosts.

## See also

`docs/site-src/architecture/publish-verifier.md` documents both the trigger and verify seams together as the current architecture; this page records why the trigger seam was made provider-aware and what was rejected along the way.
