---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/188
synthesized_into: []
doc_kind: decision
---

# Decision: CircleCI Provider Seam for the Publish-Verifier Is Modeled but Unvalidated (CCE-63)

- **Ticket:** CCE-63 (parent CCE-58)
- **Date:** 2026-07-22
- **Approach:** Option D′ — a real, testable provider seam plus an honest degrade, with the actual CircleCI poll left as an explicit stub.

## Problem

CCE-58 landed the `publishing.ci_provider` enum (`"github" | "circleci"`) into `templates/config.schema.json` as an additive, forward-looking field with zero consumer code behind it. CCE-63 is the deferred consumer: verifying a docs publish for a host whose docs-publish CI runs on CircleCI instead of GitHub Actions.

Two facts reshaped the ticket from its original framing. First, `verify_runner.py` doesn't poll anything itself — `run()` in `scripts/verify_runner.py` loads config and state, resolves changed paths via `GhClient`, and hands the whole `publishing` block to the `publish-verifier` Sonnet subagent via `dispatch_validated`. The actual `gh run list --workflow` build-poll lives as prose in `agents/publish-verifier.md`, not in Python. Second, the docs publish is *triggered* by a separate, hardcoded GitHub-only seam in `_maybe_auto_merge` (a `GITHUB_TOKEN` merge can't fire `on: push`, so the orchestrator explicitly dispatches the build workflow via `gh.workflow_run`). A working CircleCI host needs both seams made provider-aware; this decision covers only the verify seam.

There is also no live CircleCI-publishing host today. The CircleCI v2 REST API shape a real poller would need is therefore an unvalidated guess, not a confirmed contract.

## Decision

Ship the provider seam now, but keep it honest: build the interface and the config plumbing, and make the branch that would talk to CircleCI degrade cleanly instead of guessing at a live call.

`scripts/build_poller.py` is the new seam. It exposes `resolve_build_verdict(provider, publishing_config, repo, pr_number)`, a `BuildPoller` protocol documenting the poll contract, a `CircleCiClient` real-client skeleton, and a `FakeCircleCiClient` test double mirroring the existing `GhClient`/`FakeGhClient` pattern. The token-mint path (`CircleCiClient.auth_headers`) sends `CIRCLECI_TOKEN` only as a `Circle-Token` request header — never a URL userinfo segment or query param — and raises `CircleCiTokenMissing` (a typed, fixed-literal error) when the token is absent.

The functions that would actually talk to CircleCI, `poll_circleci` and `map_circleci_status`, are explicit `NotImplementedError` stubs. Green-testing a poller against self-authored fakes for an API nobody has validated would launder a guess into something that reads as tested; the value of the seam right now is the interface, not a fictional implementation.

A module-level constant, `UNVALIDATED_AGAINST_LIVE_HOST` (`scripts/build_poller.py`), gates the honest-degrade path. While it is `True`, `resolve_build_verdict` never reaches `poll_circleci` — it short-circuits to a non-promoting verdict (`build_status` set to the sentinel `circleci_unvalidated`, `failed` empty) and returns the fixed reason `circleci_provider_modeled_but_unvalidated`. Flipping the flag is the only way to route into the real poll, and it's reserved for once a live CircleCI-publishing host exists to validate the API shape against.

`scripts/verify_runner.py`'s `run` function now forks explicitly on `provider = (cfg.get("publishing") or {}).get("ci_provider") or "github"`, resolved *before* the existing dispatch. The `github` branch (which also covers an absent `ci_provider`) is untouched — it's still today's exact `dispatch_validated("publish-verifier", ...)` call, so the guard exists to protect the old path from the new one, not to change it. The `circleci` branch calls `resolve_build_verdict` instead of dispatching the LLM publish-verifier at all: no live poll, no token anywhere near a subagent prompt or a persisted debug transcript. Reasons from either branch flow through the same `add_partial` channel, and a non-empty `poll_reasons` list populates a new `digest["partial_reasons"]` key so the notifier's "Partial-run reasons" section renders a clear, non-scary explanation of why verification didn't promote — the `github` digest shape stays byte-for-byte unchanged.

`scripts/stderr_emit.py`'s `_redact_credentials` gained a second pattern, `_CREDENTIAL_HEADER_RE`, to mask header-form secrets (`Circle-Token: ...`, `Authorization: Bearer ...`) including the quoted dict-repr form that `str()`-ing a headers dict produces — the redaction previously only matched URL-embedded `user:token@host` and would have missed a token if it ever leaked into an error string via a header. This hardens the existing GitHub path too, not just the new one.

`templates/config.schema.json`'s `ci_provider` description was tightened to state plainly that `circleci` is modeled but unvalidated against a live host, and that both post-merge seams (verify here, and the trigger seam from CCE-123) degrade honestly rather than acting for a non-`github` provider. `docs/site-src/setup-guide.md` reserves a `CIRCLECI_TOKEN` secret, marked not yet wired.

## What's explicitly out of scope

The real CircleCI poll (`poll_circleci`, `map_circleci_status`) is not implemented — the status-vocabulary mapping (in particular how CircleCI's `on_hold` state should collapse onto `success | failure | timeout`) and the exact pipeline-lookup endpoint are open decisions blocked on having a live host to validate against.

The publish-*trigger* gap — `_maybe_auto_merge`'s hardcoded `gh.workflow_run` dispatch — was tracked as a sibling concern at the time this seam landed and was closed separately by CCE-123, which gave the trigger path its own provider fork: a non-github provider now records an info-only `pages_dispatch_skipped: circleci_trigger_modeled_but_unvalidated` reason instead of attempting a GitHub Actions dispatch, using the same `UNVALIDATED_AGAINST_LIVE_HOST` honesty gate (`resolve_build_trigger` in `scripts/build_poller.py`).

## Why this shape

Four alternatives were on the table: a prompt-only conditional inside the LLM agent (rejected — untestable, and it would route a live token through a persisted subagent transcript); extracting the entire working GitHub poller into Python right now (rejected — the largest regression budget on the nightly-critical path, spent for a provider with zero current consumers); a bare enum-plus-degrade with no seam at all (safe but under-delivers, forcing a later re-derivation of the boundary under live-host pressure); and this option, a tested seam with the API-shape-dependent parts left as visible stubs. The last one gets the production-grade parts — the GitHub path provably untouched, the token kept off the LLM path, redaction hardened — without pretending a guessed API surface is validated.

## Current behavior, honestly stated

Because no live CircleCI-publishing host exists yet, the `circleci` branch of `resolve_build_verdict` is not exercised in production today. A host that sets `ci_provider: circleci` gets a clean, non-crashing, non-hanging, non-promoting verify result on every run, with a partial reason and a notifier line that say exactly what's true: modeled, not yet validated. That's the intended failure mode until a real host forces the open API-shape decisions to get made.
