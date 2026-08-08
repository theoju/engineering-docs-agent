---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/188
synthesized_into: []
doc_kind: decision
---

# Decision: CircleCI Provider Seam for the Publish-Verifier (CCE-63)

- **Ticket:** CCE-63 (parent: CCE-58, `advanced-data-import-system` onboarding)
- **Date:** 2026-07-22
- **Approach:** "Option D′" — a testable provider seam plus an honest degrade, with the real poller left as an explicit stub.

## Problem

CCE-58 added the `publishing.ci_provider` enum (`github` | `circleci`) to `templates/config.schema.json` as an additive field with zero consumer code behind it. CCE-63 is the deferred consumer: what happens when a host's docs-publish CI actually runs on CircleCI instead of GitHub Actions.

Two things about the existing verify path shaped the fix:

1. `scripts/verify_runner.py:run` doesn't poll a build itself. It resolves changed paths, then hands the whole `publishing` config block to the `publish-verifier` Sonnet subagent via `dispatch_validated`. The real `gh run list --workflow` poll lives as prose in `agents/publish-verifier.md`'s procedure — there was no Python seam to fork on, only an LLM prompt that assumed GitHub.
2. The docs publish is *triggered* by a second, separate GitHub-only path: CCE-101's auto-merge calls `gh.workflow_run(build_workflow)` (a `GITHUB_TOKEN` merge can't fire `on: push`, so the runner dispatches explicitly). That trigger seam is out of scope here — see below.

There was also no live CircleCI-publishing host to validate against. The motivating host, `advanced-data-import-system`, runs CircleCI to gate PRs but still publishes docs via GitHub Actions, so it stays `ci_provider: github`. Any CircleCI verify logic written for CCE-63 would be guessing at the v2 REST API shape.

## Decision

Ship the provider seam, not the poller. `scripts/verify_runner.py` now resolves `provider = cfg.get("publishing", {}).get("ci_provider") or "github"` and forks before the existing dispatch:

- `provider == "github"` (including absent/`None`) takes the exact prior `dispatch_validated("publish-verifier", ...)` path, unchanged.
- Any other provider routes into `scripts/build_poller.py:resolve_build_verdict`.

`resolve_build_verdict` is gated by a module-level constant, `UNVALIDATED_AGAINST_LIVE_HOST = True`, in `build_poller.py`. While that flag is `True`, a `circleci` verify never attempts a live poll. It returns a non-promoting verdict (`build_status` set to the sentinel `circleci_unvalidated`, `failed` empty) and a fixed-literal partial reason, `circleci_provider_modeled_but_unvalidated`, which `verify_runner` threads into `add_partial(state, ...)` and into the notifier digest's `partial_reasons`. The promotion gate (`not failed_urls and build_status == "success"`) never fires for this sentinel, so nothing is falsely marked verified.

`build_poller.py` ships the shape of a real client without the behavior: `CircleCiClient` reads `CIRCLECI_TOKEN` from the environment and sends it only as a `Circle-Token` header (never a URL or query param), and a `FakeCircleCiClient` mirrors it for tests. `poll_circleci` and `map_circleci_status` are explicit `NotImplementedError` stubs — reachable only once `UNVALIDATED_AGAINST_LIVE_HOST` is flipped to `False` by a future change. A `BuildPoller` protocol documents the intended contract for that future implementation.

The same module also carries a `resolve_build_trigger` seam (added under CCE-123, not this ticket) that applies the identical honesty pattern to the publish-*trigger* side: while unvalidated, it records `circleci_trigger_modeled_but_unvalidated` instead of dispatching.

### Why not implement the real poller now

Three other options were on the table: prompt-only conditional logic inside the agent (untestable, routes a live token through a persisted LLM transcript), extracting the working GitHub poller into Python at the same time (unrelated blast-radius on the nightly-critical github path, no red baseline to regress against), and shipping a "working" CircleCI poller tested only against self-authored fakes. That last option was rejected specifically because it launders a guess into something that reads as tested — the fakes' canned responses would be the very assumption being asserted, with no live host to check them against. The chosen shape (seam real, poller stubbed, honesty gate load-bearing) keeps the GitHub path provably untouched, keeps the token off the LLM path, and leaves the eventual poll implementation a well-scoped drop-in once a live CircleCI host exists to validate the v2 API shape against.

## Consequences

- The GitHub Actions verify path is byte-for-byte unchanged; this ships as a fork guard around it, not a rewrite.
- A host that sets `ci_provider: circleci` today gets a clean, informative degrade — a `partial` run with a clear reason — never a crash, a hang, or a false "verified" state.
- `agents/publish-verifier.md` documents `ci_provider` in its Inputs list for parity but explicitly does not branch on it; `circleci` never reaches that agent.
- `docs/site-src/setup-guide.md` documents `CIRCLECI_TOKEN` as a secret required only when `ci_provider: circleci`, marked reserved / not yet wired.
- The publish-*trigger* gap (`gh.workflow_run` in the auto-merge path being GitHub-only) was deliberately left open by this ticket and tracked separately; it was closed later by CCE-123 using the same `UNVALIDATED_AGAINST_LIVE_HOST` pattern in `resolve_build_trigger`.

## Follow-up

This page describes the state as of PR #188: `poll_circleci` and `map_circleci_status` are stubs, and `UNVALIDATED_AGAINST_LIVE_HOST` is `True`. Once a live CircleCI-publishing host exists to validate the v2 API shape (pipeline → workflow → job walk, and the `on_hold`/`blocked`/`canceled` status mapping) and the stubs are implemented, this decision record should be revisited or superseded rather than left describing a now-stale unvalidated state.
