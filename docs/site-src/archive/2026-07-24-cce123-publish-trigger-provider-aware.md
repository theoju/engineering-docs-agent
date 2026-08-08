---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/190
synthesized_into: []
doc_kind: decision
---

# CCE-123: Publish-Trigger Provider-Aware Dispatch (2026-07-24)

## Context

CCE-63 made the post-merge **verify** seam provider-aware: `scripts/verify_runner.py` forks on `publishing.ci_provider`, and a non-github provider degrades honestly through `build_poller.resolve_build_verdict` — a non-promoting verdict plus a fixed `circleci_provider_modeled_but_unvalidated` reason — instead of mis-verifying a build it can't actually see. That work deliberately left a second GitHub-only seam open: the post-merge **trigger**.

After a docs PR auto-merges (CCE-101), `_maybe_auto_merge` in `scripts/orchestrator_runner.py` kicks the host's build/deploy by calling `gh.workflow_run(build_workflow)` — a GitHub Actions `workflow_dispatch`. This dispatch exists because a `GITHUB_TOKEN` merge cannot fire an `on: push` workflow; without it, the site never redeploys. For a host configured with `publishing.ci_provider: circleci`, that call is meaningless — there's no GitHub Actions workflow to run, and the CCE-63 verifier would have nothing to poll afterward.

A strict-xfail acceptance test guarded the gap ahead of time: `tests/orchestrator/test_build_poller.py::test_publish_trigger_is_provider_aware` asserted `"ci_provider" in inspect.getsource(orchestrator_runner._maybe_auto_merge)`. Because it ran `strict=True`, it was designed to flip to a hard failure the moment the seam became provider-aware, forcing the xfail marker's removal as part of the same change.

## Decision

Make the trigger seam provider-aware, symmetric with the CCE-63 verify seam, rather than reaching for a generic config-driven trigger command or blocking auto-merge for non-github hosts:

- `github` → byte-for-byte unchanged behavior (`gh.workflow_run(build_workflow)`).
- non-github (`circleci`) → honest degrade: no dispatch, exactly one `info_only` reason, `pages_dispatch_skipped: circleci_trigger_modeled_but_unvalidated`.

The real CircleCI pipeline trigger stays a `NotImplementedError` stub behind the same `UNVALIDATED_AGAINST_LIVE_HOST` flag `resolve_build_verdict` already uses — there's no live CircleCI-publishing host to validate the v2 trigger API against, so the module models the shape of the seam without guessing at its implementation.

A generic `trigger_command` config field (run a host-supplied shell command) was considered and deferred: it adds a config/schema surface and a command-injection concern for one known second provider, and it diverges from the `ci_provider` enum the verify seam already forks on. Blocking auto-merge for non-github hosts was rejected outright — it changes merge *eligibility* to solve a trigger problem, and CircleCI's VCS integration likely rebuilds on the merge push anyway, so blocking would be strictly worse than a no-op skip.

The skip reason is deliberately framed as "modeled but unvalidated" rather than "not required, builds on push": there's no live host to confirm the target CircleCI project is actually push-triggered, so the honest-degrade vocabulary stays consistent across both seams. Promoting to a "not required" framing is a later decision, gated on live-host confirmation.

## What changed

- **`build_poller.resolve_build_trigger(provider) -> (bool, list[str])`** (new, `scripts/build_poller.py`) — symmetric with the existing `resolve_build_verdict`. While `UNVALIDATED_AGAINST_LIVE_HOST` is `True` it returns `(False, [TRIGGER_UNVALIDATED_REASON])` with no dispatch attempted. Once the flag is flipped, it routes into `trigger_circleci`, which raises `NotImplementedError` until the real trigger ships.
- **`build_poller.trigger_circleci(client) -> bool`** (new) — the `NotImplementedError` stub for the real CircleCI v2 pipeline trigger, reached only past the flag flip.
- **`build_poller.TRIGGER_UNVALIDATED_REASON`** (new) — the fixed literal `"circleci_trigger_modeled_but_unvalidated"`. It never interpolates a token or response, the same discipline `PROVIDER_UNVALIDATED_REASON` already follows.
- **`_maybe_auto_merge` fork** (`scripts/orchestrator_runner.py`) — gained a keyword param `ci_provider: str | None = None`. After a successful merge, `provider = ci_provider or "github"` selects the path: the `github` branch is untouched (still `gh.workflow_run(build_workflow)` with `pages_dispatch_succeeded`/`pages_dispatch_failed` reasons); any other provider calls `resolve_build_trigger(provider)` and appends its reasons under the `pages_dispatch_skipped:` prefix instead. All reasons on both branches stay `info_only=True` — the trigger seam is hygiene and never flips a run to `partial`.
- **Call-site wiring** — the `_maybe_auto_merge(...)` call now passes `ci_provider=config.get("publishing", {}).get("ci_provider")`. An absent field resolves to `None`, which resolves to `"github"`, so behavior for existing github hosts is unchanged.
- **`tests/orchestrator/test_build_poller.py`** — the `strict=True` xfail on `test_publish_trigger_is_provider_aware` was removed; it now passes as a normal test.
- No new config field was introduced, and merge eligibility is unaffected — this changes only what happens *after* a merge already deemed eligible.

## Deliberate non-coverage

No test drives `_maybe_auto_merge` with `ci_provider="circleci"` *and* `UNVALIDATED_AGAINST_LIVE_HOST=False`. In that combination `resolve_build_trigger` calls `trigger_circleci`, which raises `NotImplementedError` *after* the merge has already happened, and the dispatch fork is intentionally not wrapped in try/except. That raise is the honesty gate doing its job — "you flipped the flag without shipping the real trigger" — symmetric with how `resolve_build_verdict` behaves on the verify side. Wrapping it in a try/except would silence the signal. In production the flag is a hardcoded, always-`True` module constant, so this path is unreachable through any host config; the loud crash is a developer-time guardrail, not a live runtime path.

## Testing

`tests/orchestrator/test_build_poller.py` covers `resolve_build_trigger("circleci")` returning `(False, ["circleci_trigger_modeled_but_unvalidated"])`, the flag-flipped-to-`False` path raising `NotImplementedError` through both `resolve_build_trigger` and the `trigger_circleci` stub directly, and that the reason is a fixed literal with no token interpolation.

`tests/orchestrator/test_auto_merge.py` covers the circleci branch end-to-end: eligible PR, green checks, `ci_provider="circleci"` → merge succeeds, no `workflow_run` call appears in `gh.calls`, and `("pages_dispatch_skipped: circleci_trigger_modeled_but_unvalidated", True)` is in the returned reasons. The existing github-path tests (`test_successful_merge_dispatches_pages_workflow`, `test_no_build_workflow_skips_dispatch`, `test_dispatch_failure_is_info_only_after_merge`, `test_all_reasons_are_info_only`) stay green unchanged; `test_all_reasons_are_info_only` doesn't reach the circleci branch at all — it drives the github default with a red check, which short-circuits at `checks_failed` before the dispatch fork ever runs.

Per the PR's own notes, adversarial review caught two vacuous tests before merge, fixed via mutation testing. Full `python3 -m pytest` is green on the integrated tree.

## Out of scope

- The real CircleCI pipeline trigger implementation — deferred until a live CircleCI-publishing host exists to validate against; the stub and flag are in place.
- A generic `trigger_command` config field (the deferred config-driven approach).
- Any change to merge eligibility or to the CCE-63 verify seam itself.

## See also

- CCE-63: the sibling decision that made the publish-*verify* seam provider-aware (`scripts/verify_runner.py`, `build_poller.resolve_build_verdict`).
- CCE-101: the auto-merge gate this trigger fires after.
- `docs/superpowers/specs/2026-07-23-cce123-publish-trigger-provider-aware-design.md`: design spec.
- `docs/superpowers/plans/2026-07-23-cce123-publish-trigger-provider-aware.md`: implementation plan.
- `scripts/build_poller.py`, `scripts/orchestrator_runner.py`, `templates/config.schema.json`: the changed surfaces.
