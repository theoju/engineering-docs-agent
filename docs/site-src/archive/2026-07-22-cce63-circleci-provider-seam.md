---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/188
synthesized_into: []
doc_kind: decision
---

# CCE-63: CircleCI Provider Seam for the Publish-Verifier (2026-07-22)

## Context

`publishing.ci_provider` (`"github" | "circleci"`) has existed in `templates/config.schema.json` since CCE-58 as an additive, forward-looking field with zero consumer code. CCE-63 is the deferred consumer: verify docs publishing for a host whose docs-publish CI runs on CircleCI.

Two facts reshaped the ticket from its original framing. First, `verify_runner.py` does not poll anything itself — `run` (`scripts/verify_runner.py`) loads config and state, resolves changed paths via `GhClient`, then hands the whole `publishing` block to the `publish-verifier` subagent via `dispatch_validated`. The actual `gh run list --workflow` build-poll lives as prose in `agents/publish-verifier.md` step 1, and it stays github-only. Second, the docs publish is *triggered* by a separate, hardcoded GitHub-only seam: the CCE-101 auto-merge path calls `gh.workflow_run` to fire the publish after merge, because a `GITHUB_TOKEN` merge cannot fire `on: push`. Making a CircleCI host actually work end-to-end requires both seams to become provider-aware — verify and trigger.

There's also no live CircleCI-publishing host today. The motivating host for this work publishes docs via GitHub Actions even though it gates PRs on CircleCI, so the CircleCI v2 REST API shape a poller would need is an unvalidated guess.

## Decision

CCE-63 ships **Option D′**: a testable provider seam plus an honest degrade, with the real poller left as an explicit stub, and the publish-trigger gap documented and tracked separately rather than silently left unaddressed.

Three other options were on the table and rejected. A prompt-only conditional would push CircleCI logic into untestable agent prose and route a live token through an LLM subagent transcript. Extracting the whole polling path (including the working github poller) into Python now would rip out unit-untested, nightly-critical behavior with no red baseline to regress against, for a provider with zero current consumers. Shipping only the load-bearing enum plus a degrade, with no seam at all, would be honest and safe but would forfeit the provider interface and force a later re-derivation of the boundary under live-host pressure. D′ takes the honesty of that last option and adds the tested seam, while deliberately not faking a green CircleCI poller against self-authored fakes — that would launder an unvalidated guess into code a future reader trusts.

## What changed

- **`scripts/build_poller.py` (new)** — the provider seam, mirroring the `GhClient`/`FakeGhClient` dependency-injection pattern. `resolve_build_verdict` is the entry point verify_runner calls for a non-github provider; while the module-level `UNVALIDATED_AGAINST_LIVE_HOST` flag is `True`, it short-circuits to an honest degrade instead of polling: a non-promoting verdict (`build_status` set to the sentinel `circleci_unvalidated`, `failed` empty) plus the fixed-literal partial reason `circleci_provider_modeled_but_unvalidated`. `CircleCiClient` is a real client skeleton — it reads `CIRCLECI_TOKEN` from the environment and exposes `auth_headers()`, which sends the token only as a `Circle-Token` header, never a URL userinfo segment or query param, raising the typed `CircleCiTokenMissing` if the token is absent. Its API-walking method (`pipeline_for_commit`) is a `NotImplementedError` stub. `poll_circleci` and `map_circleci_status` are also explicit `NotImplementedError` stubs — they're reached only once the flag is flipped, and there are deliberately no behavioral tests against them, since the flag load-bearing test proves routing without asserting anything about a fictional live poll.
- **`scripts/verify_runner.py:run` provider fork.** `provider = (cfg.get("publishing") or {}).get("ci_provider") or "github"`. The `github`/absent branch is `dispatch_validated("publish-verifier", ...)`, byte-for-byte the same call as before this change. The `circleci` branch calls `resolve_build_verdict` instead — no LLM dispatch, no live poll. Reasons from either branch feed `add_partial`, and the promotion gate (`not failed_urls and build_status == "success"`) is unchanged, so the honest degrade's non-`success` sentinel simply never promotes.
- **Notifier digest.** `digest["partial_reasons"]` is only set when the poll returned a non-empty reasons list, so the existing github digest shape stays byte-for-byte unchanged. On a `circleci` verify, the digest carries the `circleci_provider_modeled_but_unvalidated` reason through to the notifier's partial-run-reasons section — a clear, informational line rather than a scary failure or an empty artifact.
- **Header-form credential redaction.** `_redact_credentials` (`scripts/stderr_emit.py`) previously matched only URL-embedded `user:token@host` credentials. It now also masks `Circle-Token`/`Authorization` header values via `_CREDENTIAL_HEADER_RE`, including the quoted dict-repr form (`{'Circle-Token': 'value'}`) that `str()`-ing a header dict — the shape `CircleCiClient.auth_headers()` returns — produces. This closes a redaction gap the existing gh path also benefits from.
- **Docs/config scaffolding.** `templates/config.schema.json`'s `ci_provider` enum description now notes CircleCI is modeled-but-unvalidated. `docs/site-src/setup-guide.md` gets a `CIRCLECI_TOKEN` row marked reserved / not yet wired, required only when `ci_provider: circleci`. `agents/publish-verifier.md` lists `ci_provider` in its Inputs for documentation parity and notes CircleCI is handled Python-side, while its Output schema and step 1's github prose are untouched.

## Explicitly out of scope

- **The real CircleCI poll.** `poll_circleci`/`map_circleci_status` stay `NotImplementedError` until a live CircleCI-publishing host exists to validate the v2 API shape against — endpoint walk (pipeline → workflow → job), how a merged-PR SHA maps to the right pipeline, and how CircleCI's status vocabulary (including the ambiguous `on_hold`) collapses onto `success | failure | timeout` are all open decisions blocking that flip.
- **The publish-trigger fix.** `_maybe_auto_merge`'s `gh.workflow_run(build_workflow)` call in `orchestrator_runner.py` is still GitHub-only. A CircleCI host today would merge successfully but never actually fire a CircleCI publish. This is covered by a strict-xfail test asserting the trigger is GitHub-Actions-only, and is tracked as a sibling ticket rather than filed under CCE-63.
- **A `ci_provider: circleci` onboarding fixture.** Deliberately deferred — shipping one now would read as a shippable, end-to-end-ready host config when the host isn't actually publishable until the trigger gap closes.
- Extracting the working github poller out of `agents/publish-verifier.md` into Python, and any GitLab/Buildkite/Jenkins providers.

## Error handling / degradation

| Condition | Behavior |
| --- | --- |
| `ci_provider` absent or `None` | Resolved to `"github"` — today's exact `dispatch_validated` call, no `CIRCLECI_TOKEN` ever required. |
| `ci_provider: circleci`, flag on (current state) | Clean `circleci_provider_modeled_but_unvalidated` partial reason, non-promoting verdict, no crash or hang. |
| `ci_provider: circleci`, flag flipped (future) | Routes into `poll_circleci`, which raises `NotImplementedError` until implemented and validated. |
| Credential in a log line | Masked by `_redact_credentials` for both URL and header forms before it reaches stderr or a persisted transcript. |

## Testing

`tests/orchestrator/test_build_poller.py` and `tests/orchestrator/test_verify_runner.py` cover the seam: the github/absent-provider paths stay green against the existing `fakes_verify_ok`/`fakes_verify_fail` dry-run outcomes; a `circleci` config produces the fixed partial reason and a non-promoting return code; `UNVALIDATED_AGAINST_LIVE_HOST` is asserted load-bearing by monkeypatching it and confirming the fork routes to `poll_circleci`, which raises the documented `NotImplementedError`. `tests/stderr_emit/test_stderr_emit.py` covers header-form redaction, including the dict-repr shape, without touching the existing URL-credential assertions. All of this runs through fixture-driven dry-run with any HTTP monkeypatched — never a live CircleCI call.

## See also

- CCE-58: landed the `ci_provider` enum with zero consumer code.
- `docs/superpowers/specs/2026-07-22-cce63-circleci-publish-verifier-design.md`: design spec, including the four-option comparison and the full list of open decisions blocking the live poller.
- `docs/superpowers/plans/2026-07-22-cce63-circleci-publish-verifier.md`: implementation plan.
- `scripts/build_poller.py`, `scripts/verify_runner.py`, `scripts/stderr_emit.py`: the changed surfaces.
- `docs/site-src/setup-guide.md`: `CIRCLECI_TOKEN` secret documentation.
