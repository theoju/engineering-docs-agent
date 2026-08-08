---
description: 'Documents architecture publish verifier ci provider seam: Adds a testable provider seam to the docs publish-verification path so hosts configuring `publishing.ci_provider: circleci` degrade honestly ("modeled but unvalidated") instead of being mis-verified, while the existing GitHub Actions verification path is unchanged. Introduces `scripts/build_poller.py` with `resolve_build_verdict`, a `CircleCiClient` (token auth via `Circle-Token` header only), a `FakeCircleCiClient`, and a `BuildPoller` protocol; the actual CircleCI polling logic (`poll_circleci`/`map_circleci_status`) ships as documented `NotImplementedError` stubs since there is no live CircleCI-publishing host to validate against yet. `scripts/verify_runner.py` now forks on `ci_provider`, with the circleci branch returning a fixed non-promoting verdict and never dispatching the LLM publish-verifier. `scripts/stderr_emit.py`''s credential redaction is hardened to mask the dict-repr form of CircleCI/Bearer/Basic auth headers. Docs and the config schema are updated to describe the CircleCI provider as modeled-but-unvalidated and reserve `CIRCLECI_TOKEN`.'
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
# Publish-verifier: the CircleCI provider seam

Post-merge, the docs-agent verifies that a merged docs PR actually built and published before it marks the run successful. That verification path was GitHub-only. CCE-63 gives it a provider seam so a host configuring `publishing.ci_provider: circleci` gets an honest, non-crashing degrade instead of a verifier silently mis-checking a build system it doesn't understand.

## Where the fork happens

`scripts/verify_runner.py:run` is the entry point, invoked by the post-merge workflow. It loads config and state, resolves the merged PR's changed paths via `GhClient`, then resolves the provider:

```python
provider = (cfg.get("publishing") or {}).get("ci_provider") or "github"
```

Absent `ci_provider` and explicit `"github"` take the same branch — `run` dispatches `dispatch_validated("publish-verifier", ...)` exactly as before. That subagent, defined in `agents/publish-verifier.md`, is the LLM-driven path: it polls `gh run list --workflow` for the build, derives page URLs from `publishing.url_map_rule`, and curls each one for a 200. This path is byte-for-byte unchanged by CCE-63 — the fork exists precisely so the new branch can't touch it.

Any other provider value — today just `"circleci"` — routes to `resolve_build_verdict` in `scripts/build_poller.py` instead. The LLM publish-verifier is never dispatched for a non-github provider: no token, no build details, and no live-build assumptions ride into a subagent transcript for a CI system the agent has no verified way to poll.

## The honest degrade

`resolve_build_verdict` is gated by a module-level constant, `UNVALIDATED_AGAINST_LIVE_HOST`, set to `True`. There is no live CircleCI-publishing host to validate the CircleCI v2 API shape against — the closest real host, `advanced-data-import-system`, runs CircleCI for PR gating but still publishes docs via GitHub Actions and stays on `ci_provider: github`. Rather than ship an untested guess at that API shape as if it worked, `resolve_build_verdict` short-circuits while the flag is `True`:

- returns a non-promoting verdict — `build_status` is the sentinel `circleci_unvalidated` (anything other than `"success"`), `failed` is empty
- returns the fixed-literal reason `circleci_provider_modeled_but_unvalidated`

`verify_runner.run` records that reason via `add_partial` and folds it into the notifier digest's `partial_reasons` field, so an operator watching a CircleCI-configured host sees exactly why the run didn't promote — not a false "verified," not a scary failure, not a silent no-op. Because `digest_partial_reasons` is only set on the non-github branch, the GitHub digest shape stays untouched.

`verify_runner.run`'s promotion gate is unchanged either way: `not failed_urls and build_status == "success"`. The CircleCI sentinel can never satisfy it, by construction.

## What's actually implemented vs. stubbed

`scripts/build_poller.py` ships a full dependency-injection seam, mirroring the `GhClient`/`FakeGhClient` pattern already used for the github path:

- `BuildPoller` — a `Protocol` documenting the intended interface (`poll(publishing_config, repo, pr_number) -> build_status`). Nothing implements it yet; it names the contract for the eventual real poller.
- `CircleCiClient` — reads `CIRCLECI_TOKEN` from the environment and builds an `auth_headers()` dict that sends the token only as a `Circle-Token` header, never as URL userinfo or a query parameter. Missing token raises `CircleCiTokenMissing`. Its actual API-walking method, `pipeline_for_commit`, raises `NotImplementedError`.
- `FakeCircleCiClient` — a canned-response test double mirroring `CircleCiClient`, used to prove flag-flip routing and token handling without a live call.
- `poll_circleci` and `map_circleci_status` — both explicit `NotImplementedError` stubs. `resolve_build_verdict` only reaches them once `UNVALIDATED_AGAINST_LIVE_HOST` is flipped to `False`, which hasn't happened.

This is a deliberate line: the seam's *shape* is tested now, but no test asserts real CircleCI behavior, because there's nothing real to assert against yet. Green-testing `poll_circleci` against self-authored fakes for an unvalidated API would launder a guess into something that reads as verified.

A separate, symmetric seam covers the *trigger* side. `resolve_build_trigger` in `scripts/build_poller.py` degrades the same way — a fixed `circleci_trigger_modeled_but_unvalidated` reason, no dispatch — for the CCE-101/CCE-123 auto-merge path, which still calls `gh.workflow_run` directly for GitHub hosts. See the CLAUDE.md CCE-123 entry for how that trigger-side reason surfaces as `pages_dispatch_skipped`.

## Credential handling

The CircleCI token never enters the LLM path — `resolve_build_verdict` is pure Python, and the non-github branch never dispatches `publish-verifier`. The remaining risk is the token leaking into a stderr line or persisted debug transcript.

`scripts/stderr_emit.py`'s `_redact_credentials` already masked URL-embedded `user:token@host` credentials (`_CREDENTIAL_URL_RE`). CCE-63 adds `_CREDENTIAL_HEADER_RE`, which masks `Circle-Token` and `Authorization` header values in both the plain `Header: value` form and the quoted dict-repr form (`{'Circle-Token': 'value'}`) produced by `str()`-ing a headers dict — the shape `CircleCiClient.auth_headers()` would produce if ever logged. It preserves the header name and an optional `Bearer`/`Basic` scheme so the redacted line stays legible. Every fixed-literal reason string (`circleci_provider_modeled_but_unvalidated`, `circleci_token_missing`) never interpolates the token, a response body, or headers in the first place — redaction is defense in depth, not the only guard.

## Known limitation: the trigger path is still GitHub-only

Verifying a build and triggering one are two different seams. CCE-63 scoped itself to verify only; the publish-trigger fork (`resolve_build_trigger`, referenced above) exists but the underlying `gh.workflow_run` call in the auto-merge path remains a GitHub Actions dispatch. On a hypothetical live CircleCI-publishing host, a merge would land, the trigger would no-op for CircleCI, and the verifier would then be polling for a build that never started. A regression test guards this: it asserts the trigger call stays GitHub-Actions-only so the gap can't silently widen or silently close without someone updating this page.

## Config and setup surface

`templates/config.schema.json`'s `publishing.ci_provider` enum (`"github" | "circleci"`) already existed before CCE-63; this change tightens its description to say CircleCI is modeled-but-unvalidated. `docs/site-src/setup-guide.md` reserves a `CIRCLECI_TOKEN` secret, marked required only when `ci_provider: circleci` and explicitly "reserved / not yet wired." `agents/publish-verifier.md`'s Inputs list documents `ci_provider` for parity, but the agent's procedure never branches on it — a non-github provider simply never reaches the agent.

## If you're onboarding a CircleCI-publishing host today

Don't. `ci_provider: circleci` is safe to set — it degrades cleanly, never crashes, never mis-verifies — but it does not verify or trigger a real CircleCI build. A host that needs CircleCI-based docs publishing to actually run end-to-end needs both `UNVALIDATED_AGAINST_LIVE_HOST` flipped (after the API shape in `poll_circleci`/`map_circleci_status` is implemented and validated against a live host) and the sibling publish-trigger seam completed. Until then, set `ci_provider: github` or omit it.
