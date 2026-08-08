---
description: 'Documents architecture publish verifier: Introduces a provider seam in the docs publish-verify path (new scripts/build_poller.py plus a fork in scripts/verify_runner.py) so hosts can declare publishing.ci_provider: circleci. On the CircleCI branch, verification now degrades honestly by returning a non-promoting verdict tagged UNVALIDATED_AGAINST_LIVE_HOST instead of attempting to poll a CircleCI API that has never been validated against a live host. The GitHub Actions path (gh run list polling) is untouched byte-for-byte. The actual CircleCI poller (poll_circleci/map_circleci_status) ships only as documented NotImplementedError stubs plus a FakeCircleCiClient for tests — no real polling logic is shipped or claimed as tested. agents/publish-verifier.md and agents/notifier.md were updated to describe the new provider fork, docs/site-src/setup-guide.md documents the new config option, and templates/config.schema.json gained the ci_provider field.'
source_files:
  - agents/notifier.md
  - agents/publish-verifier.md
  - docs/site-src/setup-guide.md
  - docs/superpowers/plans/2026-07-22-cce63-circleci-publish-verifier.md
  - docs/superpowers/specs/2026-07-22-cce63-circleci-publish-verifier-design.md
  - scripts/build_poller.py
  - scripts/stderr_emit.py
  - scripts/verify_runner.py
  - templates/config.schema.json
  - tests/orchestrator/test_build_poller.py
  - tests/orchestrator/test_verify_runner.py
  - tests/stderr_emit/test_stderr_emit.py
last_reviewed: '2026-08-08'
status: draft
---
# Publish verifier

`run()` in `scripts/verify_runner.py:run` fires after a docs-agent PR merges. It loads config/state, resolves the changed paths for the merged PR via `GhClient.pr_view_files`, then decides how to verify the downstream publish. That decision now forks on `publishing.ci_provider`.

## The provider fork

```python
provider = (cfg.get("publishing") or {}).get("ci_provider") or "github"
```

- **`provider == "github"`** (this includes an absent field) — the original path, unchanged. `verify_runner.run` calls `dispatch_validated("publish-verifier", ...)`, and the actual build-poll is prose in `agents/publish-verifier.md` Procedure step 1: poll `gh run list --workflow <build_workflow> --json databaseId,event,status,conclusion,createdAt` every 30s, select the newest run created at/after the merge time, wait for `status=completed`. This branch is byte-for-byte identical to pre-CCE-63 behavior — the fork exists so the new branch can't alter it.
- **`provider == "circleci"`** — routed to `resolve_build_verdict` in the new `scripts/build_poller.py` seam instead of the LLM subagent. No `gh` polling, no Claude dispatch for the verify step itself.

`agents/publish-verifier.md`'s Inputs list documents `ci_provider` for parity, but the agent is told explicitly: "Only `github` reaches this agent — `circleci` is handled Python-side... Do not branch on it here." The `circleci` branch never reaches the subagent at all.

## Why CircleCI degrades instead of polling

There is no live CircleCI-publishing host to validate the CircleCI v2 REST API shape against. `advanced-data-import-system` — the host that motivated `publishing.ci_provider` in the first place (CCE-58) — runs CircleCI to gate user PRs but still publishes its docs via GitHub Actions and stays `ci_provider: github`. Shipping a real poller against an unvalidated API guess, backed only by a self-authored fake, would launder that guess into code a future reader trusts as tested.

So `scripts/build_poller.py` ships a seam, not an implementation:

- `UNVALIDATED_AGAINST_LIVE_HOST = True` — a module-level, load-bearing constant. While it's `True`, `resolve_build_verdict` short-circuits to an honest degrade instead of calling the live poller.
- `poll_circleci` and `map_circleci_status` are explicit `NotImplementedError` stubs with docstrings pointing at the open spec decisions (API endpoint shape, how a merge SHA maps to a pipeline, how CircleCI's `on_hold`/`blocked`/`canceled` vocabulary collapses onto the fixed `success | failure | timeout` set).
- `CircleCiClient` is a real client skeleton: it reads `CIRCLECI_TOKEN` from the environment in `__post_init__` and exposes `auth_headers()`, which sends the token only as a `Circle-Token` request header — never a URL userinfo segment or query param. Its API-walking methods (`pipeline_for_commit`, and everything downstream of it) are `NotImplementedError` stubs.
- `FakeCircleCiClient` mirrors the shape for tests, proving flag-flip routing and token handling without asserting anything about the real API.

While the flag is `True`, `resolve_build_verdict` returns a fixed-literal partial reason, `circleci_provider_modeled_but_unvalidated`, and a **non-promoting** verdict — `build_status` is set to the sentinel `circleci_unvalidated` (never `"success"`), `failed` stays empty. No crash, no hang, no live call, and critically no false "verified" report. Flipping the flag to `False` is the only way to reach `poll_circleci`, and that function still raises until the real implementation lands.

The same pattern shows up a second time for the post-merge publish *trigger* (as opposed to verify): `resolve_build_trigger` in `scripts/build_poller.py` degrades a non-GitHub provider's dispatch to a `circleci_trigger_modeled_but_unvalidated` reason instead of firing a real CircleCI pipeline trigger — GitHub still fires its native `workflow_run` dispatch from `_maybe_auto_merge`. `trigger_circleci` is the equivalent `NotImplementedError` stub for that path (CCE-123).

## What the digest looks like on a CircleCI host

`scripts/verify_runner.py:run` keeps the digest byte-for-byte unchanged on the `github` path. On the `circleci` path, `resolve_build_verdict`'s reasons flow into a `digest["partial_reasons"]` key that's only populated when non-empty — so a `github` verify's digest never grows this field. `agents/notifier.md`'s Procedure step 3 tells the notifier to render a `build_status` outside `{success, failure, timeout}` (the `*_unvalidated` sentinel) as **informational**, alongside the partial-run reasons, "never with scary/failure wording when there are no failed URLs." The operator sees a clear "not yet verified" line, not a false failure banner and not silence.

## Token handling

`CIRCLECI_TOKEN` is read in Python, inside `CircleCiClient`, and never crosses into the LLM path — it isn't interpolated into any prompt, partial reason, or persisted subagent transcript. `scripts/stderr_emit.py`'s `_redact_credentials` was extended alongside this seam to mask header-form secrets, not just URL-embedded ones: a `_CREDENTIAL_HEADER_RE` pattern strips the value following a `Circle-Token` or `Authorization` header (tolerating both the plain `Header: value` form and the quoted dict-repr form that `str()`-ing a headers dict produces), leaving the header name and any `Bearer`/`Basic` scheme intact for legibility. The existing URL-credential redaction path is unaffected.

## Setup

`docs/site-src/setup-guide.md` documents `CIRCLECI_TOKEN` as a repo Secret, required only when `publishing.ci_provider: circleci` is set, and marks it explicitly "reserved / not yet wired." The per-host hybrid-CI notes reiterate that docs-publish verification on CircleCI is modeled but not end-to-end wired, and that a host publishing through GitHub Actions (even if its primary CI is CircleCI, like `advanced-data-import-system`) should stay on `ci_provider: github`.

## Non-goals

The real CircleCI poll and trigger implementations are explicitly out of scope for this seam. `templates/config.schema.json`'s `ci_provider` enum accepts `github` and `circleci`; only `github` has a working consumer. No behavioral tests exist for `poll_circleci` or `map_circleci_status` — the test suite (`tests/orchestrator/test_build_poller.py`, `tests/orchestrator/test_verify_runner.py`) asserts seam mechanics only: the `github`/absent-provider path stays byte-for-byte regression-tested, the `circleci` honest-degrade path is asserted live, and the flag's load-bearing status is asserted by monkeypatching it and confirming the fork routes into the documented `NotImplementedError`.
