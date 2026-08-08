---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/190
synthesized_into: []
doc_kind: decision
---

# CCE-123: provider-aware publish trigger

The post-merge publish pipeline had two GitHub-only seams. CCE-63 fixed the
first — the post-merge **verify** step, in `scripts/verify_runner.py` — by
forking on `publishing.ci_provider` and degrading honestly for non-GitHub
hosts. CCE-123 closes the second: the post-merge **trigger** step inside
`_maybe_auto_merge`.

## The gap

After a docs PR auto-merges, `_maybe_auto_merge` in `scripts/orchestrator_runner.py`
kicks the host's build/deploy. It has to: a merge performed with the
workflow's `GITHUB_TOKEN` cannot itself fire an `on: push` workflow, so
without an explicit dispatch the site never redeploys. Before CCE-123 this
dispatch was unconditional — `gh.workflow_run(build_workflow)` — which is
meaningless for a host configured with `publishing.ci_provider: circleci`:
there's no GitHub Actions workflow to run.

A strict-xfail test guarded the gap directly:
`tests/orchestrator/test_build_poller.py::test_publish_trigger_is_provider_aware`
asserted that `"ci_provider"` appears in the source of `_maybe_auto_merge`.
Because it was `strict=True`, the test would flip to a hard failure the
moment the fork was added — forcing the fix to land cleanly rather than
partially.

## The fix

`_maybe_auto_merge` now takes a keyword-only `ci_provider: str | None = None`
and forks on it right after a successful merge:

- **`github`** (the default when the field is absent, or set explicitly) —
  byte-for-byte unchanged: `gh.workflow_run(build_workflow)` still fires, and
  the same info-only `pages_dispatch_succeeded` / `pages_dispatch_failed`
  reasons are recorded.
- **anything else** (`circleci`) — no GitHub Actions dispatch is attempted.
  Instead the runner calls the new `resolve_build_trigger(provider)` in
  `scripts/build_poller.py`, which records exactly one info-only reason,
  `pages_dispatch_skipped: circleci_trigger_modeled_but_unvalidated`, and
  triggers nothing.

The call site threads the provider straight from config:
`ci_provider=config.get("publishing", {}).get("ci_provider")`. No config
schema field was added — `ci_provider` already existed for the CCE-63 verify
seam, and its `templates/config.schema.json` description was extended to
note that both seams now fork on it.

All reasons stay `info_only=True`. The trigger seam is hygiene signaling,
never a merge-eligibility gate — a circleci host still merges normally, it
just doesn't get a (wrong) GitHub Actions dispatch.

## Honest degrade, not a guess

The real CircleCI trigger isn't implemented. `trigger_circleci` in
`build_poller.py` is a `NotImplementedError` stub, reached only if the
module-level `UNVALIDATED_AGAINST_LIVE_HOST` flag is flipped to `False` —
and that flag is a hardcoded, always-`True` constant in production, so the
stub is unreachable via any host config today. There's no live
CircleCI-publishing host to validate the v2 trigger API shape against, so
`resolve_build_trigger` degrades honestly instead of guessing: no dispatch,
one fixed-literal reason. The reason string never interpolates a
token/response, matching the discipline already used for the CCE-63 verify
seam's `PROVIDER_UNVALIDATED_REASON`.

The reason is framed as "modeled but unvalidated," not "not required because
it builds on push." CircleCI's VCS integration typically rebuilds on the
merge push already, which would make an explicit trigger unnecessary — but
that's a documented hypothesis, not a confirmed fact, so the reason string
doesn't assert it. It gets promoted to that framing only after live-host
confirmation.

This is deliberately symmetric with `resolve_build_verdict` (the CCE-63
verify-seam counterpart): same flag, same non-interpolating-literal
discipline, same "raise loudly if someone flips the flag without shipping
the real implementation" behavior.

## What was rejected

- **A generic `trigger_command` config field** — adds config/schema surface
  and a security concern (running host-supplied commands) for one known
  second provider. Deferred as YAGNI.
- **Implementing the real CircleCI v2 trigger now** — unvalidated against
  any live host, untestable, and violates the project's "verify with the
  real consumer tool" rule.
- **Blocking auto-merge for non-github hosts** — the wrong lever. This is a
  trigger problem, not a merge-eligibility problem, and CircleCI likely
  rebuilds on the merge push regardless, so blocking would be strictly
  worse.
- **Silent no-op** — gives an operator no signal to answer "why didn't my
  site redeploy?", violating the project's practice of logging what gets
  dropped.

## Result

The `github` path is unchanged: all pre-existing dispatch tests in
`tests/orchestrator/test_auto_merge.py` stay green. A `circleci` host now
merges without attempting a GitHub Actions dispatch and records the single
`pages_dispatch_skipped` reason, verified by
`test_circleci_provider_skips_dispatch_with_info_reason` and
`test_github_provider_still_dispatches` in that same file, plus the
now-unmarked `test_publish_trigger_is_provider_aware` in
`tests/orchestrator/test_build_poller.py`.
