---
description: 'Documents architecture publishing: Makes the post-merge publish-trigger seam in the orchestrator provider-aware: `_maybe_auto_merge` now forks on `publishing.ci_provider`. For the default `github` provider (absent or `"github"`), behavior is unchanged — it still dispatches the GitHub Actions build workflow via `gh.workflow_run(build_workflow)` and records the same info-only `pages_dispatch_succeeded`/`pages_dispatch_failed` reasons. For non-github providers (e.g. `circleci`), no GitHub Actions dispatch is attempted; instead the runner records a single info-only reason, `pages_dispatch_skipped: circleci_trigger_modeled_but_unvalidated`, via new `resolve_build_trigger`/`trigger_circleci`/`TRIGGER_UNVALIDATED_REASON` additions to `scripts/build_poller.py`. The real CircleCI trigger is stubbed behind `UNVALIDATED_AGAINST_LIVE_HOST` (raises `NotImplementedError` if flipped on) — an honest degrade rather than guesswork against a live host. No new config field is added and merge-eligibility logic is unchanged.'
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
# Publishing

After a docs-agent PR merges, the site still has to actually rebuild and deploy. This page documents that post-merge pipeline: the auto-merge gate, the publish-trigger seam that fires after merge, and the provider fork that keeps both honest when the host isn't GitHub Actions.

## Auto-merge gate

`_maybe_auto_merge` in `scripts/orchestrator_runner.py` decides, once a nightly PR is open, whether to squash-merge it. Eligibility is checked cheapest-first: `merge.policy` must be `auto` (the default when the `merge:` block is absent — `resolve_merge_settings`), the run must be non-partial, there must be zero fact-checker warnings, and every commit on the PR must be attributable to the docs-agent bot (`_commit_author_is_bot`). If all of that holds, the function polls `gh pr checks` — waiting `checks_grace_seconds` (default 120) for checks to register and up to `checks_timeout_seconds` (default 900) for them to settle — and merges only once every registered check is green. Zero registered checks after the grace window is treated as a no-App-token host: the in-run validation (content-validator, fact-checker) is the gate there instead.

Every skip path returns an info-only `auto_merge_skipped: <reason>` entry; nothing here ever flips the run to `partial` — merge automation is hygiene, mirroring the CCE-89 D2 auto-close behavior.

## Why the post-merge trigger exists at all

A `GITHUB_TOKEN`-authored merge cannot fire `on: push` workflows — that's a GitHub Actions restriction, not a bug. So the moment `gh.pr_merge` succeeds inside `_maybe_auto_merge`, the orchestrator has to explicitly kick the build. Skip this and the site simply never redeploys, even though the PR merged cleanly.

## Provider-aware trigger (CCE-123)

`_maybe_auto_merge` forks on `publishing.ci_provider` immediately after a successful merge:

- **`github`** (the default — absent field or the literal `"github"`): unchanged behavior. It calls `gh.workflow_run(build_workflow)` and records `pages_dispatch_succeeded: <build_workflow>` or `pages_dispatch_failed: <error>`, both info-only.
- **Any other provider** (currently only `circleci` is a recognized enum value in `templates/config.schema.json`): no GitHub Actions dispatch is attempted. Instead the runner calls `resolve_build_trigger(provider)` from `scripts/build_poller.py`, which returns a single info-only reason recorded as `pages_dispatch_skipped: <reason>`.

This mirrors the shape of the earlier CCE-63 work, which made the *verify* side of publishing (did the build actually go green?) provider-aware via `resolve_build_verdict`. CCE-123 closes the complementary *trigger* side, so a host configured with `ci_provider: circleci` gets a real degrade path after auto-merge instead of either a wrong GitHub Actions dispatch or a silently missing one.

### The CircleCI stub

`scripts/build_poller.py` gates both the trigger and verify paths behind one module-level flag, `UNVALIDATED_AGAINST_LIVE_HOST`. While it's `True` (which it is today — there is no live CircleCI-publishing host to validate the v2 API shape against):

- `resolve_build_trigger` returns `(False, [TRIGGER_UNVALIDATED_REASON])` without attempting any network call. `TRIGGER_UNVALIDATED_REASON` is the fixed literal `"circleci_trigger_modeled_but_unvalidated"` — never an interpolated token, response body, or header, so it can't leak credentials into a partial reason.
- `trigger_circleci` (the real trigger) and `poll_circleci` / `map_circleci_status` (the real verify path) are explicit `NotImplementedError` stubs, reached only once the flag is flipped off.
- `CircleCiClient.auth_headers` sends `CIRCLECI_TOKEN` only as a `Circle-Token` request header — never a URL userinfo segment or query param — so a future implementation can't leak the token via a logged URL even before it's wired up.

Flipping `UNVALIDATED_AGAINST_LIVE_HOST` to `False` is a deliberate, separate decision gated on validating the real CircleCI v2 API shape (see the CCE-63 spec's open question). Until then, `resolve_build_trigger` and `resolve_build_verdict` degrade honestly rather than guess.

No new config field was introduced for the trigger seam — `publishing.ci_provider` already existed from the CCE-63 verify work, and `_maybe_auto_merge`'s merge-eligibility logic is unaffected by which branch it takes after merging.

## Config reference

`publishing.ci_provider` (`templates/config.schema.json`) accepts `"github"` or `"circleci"`; omitting it is equivalent to `"github"`. Both post-merge seams read it: `scripts/build_poller.py`'s `resolve_build_verdict` for verification, and `_maybe_auto_merge` for the trigger documented above. Only `github` is end-to-end wired — `circleci` is modeled but explicitly unvalidated.
