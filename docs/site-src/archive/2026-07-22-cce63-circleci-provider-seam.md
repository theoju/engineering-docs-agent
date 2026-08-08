---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/188
synthesized_into: []
doc_kind: decision
---

# CCE-63: a CircleCI provider seam for the publish-verifier

The publish-verifier step (the post-merge check that confirms a docs-agent PR actually went live) only ever knew one CI: GitHub Actions. `publishing.ci_provider: circleci` had existed as a schema enum value since CCE-58, but nothing consumed it — a host could set it and nothing would happen differently. CCE-63 (PR #188) is the deferred consumer, and the decision worth recording here is less "what got built" and more "why it stops short of a real CircleCI poller."

## The problem, once you look at the actual code

Two facts reshaped this ticket away from its original framing:

`scripts/verify_runner.py:run` doesn't poll anything itself. It resolves changed paths, then hands the whole `publishing` config block to the `publish-verifier` subagent. The real `gh run list --workflow` polling loop lives as **prose** inside `agents/publish-verifier.md`'s Procedure — an LLM-driven Bash loop, not testable Python.

Publishing is also *triggered* by a second, separately hardcoded GitHub-only seam: the CCE-101 auto-merge path dispatches `gh.workflow_run(build_workflow)` because a plain `GITHUB_TOKEN` merge can't fire `on: push` workflows. On a CircleCI-publishing host, that dispatch would be a no-op — CircleCI would never run, and the verifier would then poll for a build that was never started. Shipping verify-awareness alone, silently, would read as "CircleCI support" while actually being a non-functional feature. That's why the design (Option D′, after a four-lens panel plus adversarial review) explicitly scopes this ticket to the verify side only and files the trigger gap as a tracked, tested sibling — later closed by CCE-123/PR #190.

The other constraint driving the design: **there is no live CircleCI-publishing host today.** The one host that runs CircleCI (`advanced-data-import-system`) uses it to gate user PRs but still publishes docs via GitHub Actions, so it stays `ci_provider: github`. That means the CircleCI v2 REST API shape — how a merge SHA maps to a pipeline, how workflow states collapse to success/failure/timeout — is an unvalidated guess. The design panel rejected building a "working" poller against that guess: a green test suite exercising a self-authored fake CircleCI response would launder an assumption as verified behavior.

## The decision: seam now, honest degrade now, real poll later

`scripts/build_poller.py` is the new seam. It ships:

- `resolve_build_verdict`, the entry point `verify_runner.run` calls for any non-`github` provider.
- `CircleCiClient`, a real client skeleton — it reads `CIRCLECI_TOKEN` from the environment and constructs a `Circle-Token` request header via `auth_headers`, but its API-walking methods (pipeline → workflow → job) are documented `NotImplementedError` stubs.
- `FakeCircleCiClient`, mirroring the existing `FakeGhClient` dependency-injection pattern, used today only to prove flag-flip routing — not to fake a poll response.
- `BuildPoller`, a `Protocol` naming the eventual poll contract without enforcing it yet.
- `poll_circleci` and `map_circleci_status`, both explicit stubs that raise `NotImplementedError` with a pointer back to the open API-shape decisions in the spec.

The gate holding all of this together is a single module-level constant: `UNVALIDATED_AGAINST_LIVE_HOST = True`. While it's `True`, `resolve_build_verdict` never reaches the stubs — it short-circuits to a fixed, non-promoting verdict (`build_status: circleci_unvalidated`, empty `verified`/`failed`) plus the reason `circleci_provider_modeled_but_unvalidated`. `scripts/verify_runner.py:run` forks on `provider` before its existing dispatch call: `github` (including absent config) takes the exact prior code path unchanged and never touches this module at all; a non-`github` provider skips the LLM `publish-verifier` dispatch entirely and calls `resolve_build_verdict` instead, threading its reason into `state`'s partial-reasons via `add_partial` and into the notifier digest's `partial_reasons` field (left absent on the `github` path, so that digest shape stays byte-for-byte identical).

`agents/notifier.md`'s Procedure step 3 was updated to treat a `build_status` outside `{success, failure, timeout}` — the `*_unvalidated` sentinel — as informational, not a failure: it renders plainly alongside the partial-run reasons instead of with failure wording, since "not yet validated" and "broken" are different signals an operator needs to tell apart.

The trigger side of provider-awareness (`orchestrator_runner._maybe_auto_merge`'s `gh.workflow_run` dispatch) was deliberately left untouched here, fenced by a strict-xfail test asserting it stays GitHub-only until the sibling ticket lands. It landed later as CCE-123/PR #190, using the symmetric `trigger_circleci`/`resolve_build_trigger` pair in the same module, gated behind the same `UNVALIDATED_AGAINST_LIVE_HOST` flag.

## Why not the alternatives

The design panel considered three other shapes before landing on this one:

- **Prompt-only conditional** (teach the agent's Bash prose to branch on provider): rejected — CircleCI logic would stay untestable, and a live token would flow through an LLM subagent transcript that gets persisted verbatim.
- **Extract the whole GitHub poller into Python now, CircleCI included**: rejected as right-destination-wrong-time — it would rip a working, nightly-critical poller off its current path with no failing test to prove the extraction is safe, for a provider with zero live consumers.
- **Load-bearing enum plus degrade, no seam at all**: the safe minimal fallback, but it forfeits the typed provider boundary and defers re-deriving it under live-host time pressure later.

The shipped design keeps the enum-plus-degrade honesty of the minimal option, adds the tested seam so the eventual real poll is a scoped drop-in, and refuses to fake the one thing nobody can currently verify — a live poll response.

## Secrets stay off the LLM path

Because `CircleCiClient` lives in Python and reads the environment directly, the token never enters an agent prompt or a persisted subagent transcript. The redaction hardening that shipped alongside it closes a real gap: `scripts/stderr_emit.py`'s `_redact_credentials` previously matched only URL-embedded `user:token@host` forms. It now also masks header-form secrets — `Circle-Token: <value>` and `Authorization: Bearer <value>` — including the quoted dict-repr shape that `str(auth_headers())` produces, which was the concrete leak vector surfaced during adversarial review. This redaction applies to the existing GitHub path too, not just the new CircleCI seam.

## What this means if you're onboarding a CircleCI-publishing host

Setting `publishing.ci_provider: circleci` and provisioning `CIRCLECI_TOKEN` today gets you a clean, informative partial run on every verify — never a crash, a hang, or a false "verified." It does not get you a working poll: `poll_circleci` and `map_circleci_status` still raise until a live host exists to validate the API shape against (see `docs/superpowers/specs/2026-07-22-cce63-circleci-publish-verifier-design.md` §10 for the specific open questions — pipeline lookup, status-vocabulary mapping for `on_hold`, and whether `publishing` needs new vcs/branch/slug fields). Flipping `UNVALIDATED_AGAINST_LIVE_HOST` to `False` is the explicit signal that gate has been cleared; nothing about this PR clears it.

## References

- Ticket: CCE-63 (parent CCE-58, which landed the unconsumed enum).
- Spec: `docs/superpowers/specs/2026-07-22-cce63-circleci-publish-verifier-design.md`.
- Plan: `docs/superpowers/plans/2026-07-22-cce63-circleci-publish-verifier.md`.
- Code: `scripts/build_poller.py`, `scripts/verify_runner.py:run`, `scripts/stderr_emit.py`.
- Sibling ticket (trigger seam): CCE-123, PR #190.
