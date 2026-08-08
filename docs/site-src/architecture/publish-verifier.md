---
description: 'Documents architecture publish verifier: The post-merge publish-trigger dispatch seam in the auto-merge flow is now provider-aware, forking on `publishing.ci_provider`. For the github provider (default, or when `ci_provider` is absent), behavior is unchanged: `gh.workflow_run(build_workflow)` still fires with the existing info-only `pages_dispatch_succeeded`/`pages_dispatch_failed` reasons. For non-github providers (currently `circleci`), no GitHub Actions dispatch happens; instead the run records a single info-only reason, `pages_dispatch_skipped: circleci_trigger_modeled_but_unvalidated`. The real CircleCI trigger call is present as a stub (`trigger_circleci`) gated behind an `UNVALIDATED_AGAINST_LIVE_HOST` flag that raises `NotImplementedError` if flipped on before it''s been validated against a live host. No new config field is introduced and merge eligibility is unaffected.'
source_files:
  - CLAUDE.md
  - docs/superpowers/plans/2026-07-23-cce123-publish-trigger-provider-aware.md
  - docs/superpowers/specs/2026-07-23-cce123-publish-trigger-provider-aware-design.md
  - scripts/build_poller.py
  - scripts/orchestrator_runner.py
  - templates/config.schema.json
  - tests/orchestrator/test_auto_merge.py
  - tests/orchestrator/test_build_poller.py
last_reviewed: '2026-08-08'
status: draft
---
# Publish verifier & publish trigger

A docs-agent PR merging isn't the end of the pipeline — the host still has to build the docs site and redeploy it. Two seams handle that, on opposite sides of the merge:

- **Trigger seam.** Right after `_maybe_auto_merge` in `scripts/orchestrator_runner.py` squash-merges the docs PR, it has to kick the host's build. A `GITHUB_TOKEN` merge does not fire an `on: push` workflow, so without an explicit dispatch the site never redeploys.
- **Verify seam.** Once a build has (or should have) run, `scripts/verify_runner.py` polls for it and confirms the changed pages are actually live at their published URLs.

Both seams fork on the same config field, `publishing.ci_provider`, and both degrade the same way when the host isn't GitHub: honestly, with an info-only reason, never by guessing at an unvalidated live API call.

## Trigger seam: kicking the build after merge

For a `github` host (the default, or any config where `ci_provider` is absent), `_maybe_auto_merge` calls `gh.workflow_run(build_workflow)` exactly as before. Success records `pages_dispatch_succeeded: <workflow>`; failure records `pages_dispatch_failed: <error>`. Both are `info_only` — a dispatch failure is hygiene, not a reason to flip the run to partial.

For a non-`github` provider (currently only `circleci`), `_maybe_auto_merge` routes into `resolve_build_trigger` in `scripts/build_poller.py` instead of calling `gh.workflow_run`. No GitHub Actions dispatch happens at all — there's nothing for it to fire, since the host's build lives on CircleCI. `resolve_build_trigger` returns a single reason, wrapped by the caller as `pages_dispatch_skipped: circleci_trigger_modeled_but_unvalidated`.

The real CircleCI trigger — `trigger_circleci` — exists as a stub. It's reachable only if the module-level `UNVALIDATED_AGAINST_LIVE_HOST` flag in `build_poller.py` is flipped to `False`; while it's `True` (the shipped, production value), `resolve_build_trigger` short-circuits before ever calling it. If the flag were flipped without the real trigger being implemented, `trigger_circleci` raises `NotImplementedError` — deliberately, and deliberately not caught, since the merge has already happened by that point and swallowing the exception would hide the "you turned this on before it was ready" signal.

## Verify seam: confirming the build actually shipped

The verify seam runs from a separate entry point, `verify_runner.py`, dispatched by the host's post-merge workflow with the merged PR number. It reads the same `publishing.ci_provider` field and forks the same way.

For `github`, it dispatches the `publish-verifier` subagent (`agents/publish-verifier.md`), which polls `gh run list` for a build_workflow run created at or after the merge, derives each changed page's live URL from `publishing.base_url` and `url_map_rule`, and curls each one to confirm a `200` response. `ci_provider` is deliberately not something the agent itself branches on — its own contract notes that only `github` ever reaches it; `circleci` is handled entirely in Python, before dispatch.

For a non-`github` provider, `verify_runner.py` calls `resolve_build_verdict` in `build_poller.py` instead of dispatching the agent. While `UNVALIDATED_AGAINST_LIVE_HOST` is `True`, this returns a non-promoting verdict — empty `verified`/`failed` lists and a `build_status` of `circleci_unvalidated`, which is not `"success"` and therefore never satisfies the promotion gate in `verify_runner.py:run` — plus the reason `circleci_provider_modeled_but_unvalidated`. That reason lands in the notifier digest's `partial_reasons` so an operator sees why verification didn't promote, rather than the run silently doing nothing.

## Shared honesty discipline

Both `resolve_build_verdict` and `resolve_build_trigger` sit behind the same `UNVALIDATED_AGAINST_LIVE_HOST` flag, and both return fixed-literal reason strings — `PROVIDER_UNVALIDATED_REASON` and `TRIGGER_UNVALIDATED_REASON` — that never interpolate a token, response body, or header. There is no live CircleCI-publishing host to validate either the v2 poll shape or the v2 trigger shape against, so rather than shipping code that might be silently wrong, both seams degrade to a predictable, greppable no-op plus a reason.

`CircleCiClient` in `build_poller.py` reads `CIRCLECI_TOKEN` from the environment and, once implemented, would send it only as a `Circle-Token` request header — never as a URL userinfo segment or query parameter — so a future real client can't leak credentials into a logged URL even before this discipline is exercised.

## Configuration

`publishing.ci_provider` is an optional enum, `github` or `circleci`, documented in `templates/config.schema.json`. Its absence resolves to `github` in both seams (`ci_provider or "github"`), so an existing host's config needs zero edits to keep its current behavior. Setting it to `circleci` opts a host into the honest-degrade path on both seams — it does not change merge eligibility, and it introduces no other config field.

## What's not live yet

Only the `github` path is end-to-end wired. `circleci` support today is: a real dispatch call replaced by an honest skip, and a real poll replaced by an honest non-promoting verdict — both stubbed, both gated behind the same flag, both waiting on a live CircleCI-publishing host to validate the v2 API shape against before `UNVALIDATED_AGAINST_LIVE_HOST` can move to `False`.
