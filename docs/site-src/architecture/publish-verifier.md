---
description: 'Documents architecture publish verifier: Adds a testable provider seam to the docs publish-verify path so a host configured with publishing.ci_provider: circleci degrades honestly ("modeled but unvalidated") instead of mis-verifying, while the existing GitHub Actions verification path stays byte-for-byte unchanged. New scripts/build_poller.py introduces resolve_build_verdict, a CircleCiClient (auth via Circle-Token header), a FakeCircleCiClient for tests, and a BuildPoller protocol; the actual CircleCI v2 polling logic (poll_circleci/map_circleci_status) ships as documented NotImplementedError stubs because there is no live CircleCI-publishing host to validate the API shape against. scripts/verify_runner.py now forks on ci_provider: the circleci branch returns a non-promoting verdict with a fixed reason and skips the LLM publish-verifier dispatch entirely. scripts/stderr_emit.py''s credential redaction is hardened to mask header-form secrets, including the dict-repr form produced by str(auth_headers()), closing a leak vector surfaced during adversarial review. Docs and the config schema were updated: ci_provider''s description now says "modeled-but-unvalidated," CIRCLECI_TOKEN is reserved in the setup guide, and agent contract docs for publish-verifier and notifier document the new inputs.'
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

After a docs-agent PR merges, `scripts/verify_runner.py` runs the post-merge check that confirms the publish rebuilt and the changed pages are actually live. `run()` (`scripts/verify_runner.py:run`) loads the host config and state, resolves the merged PR's changed paths via `GhClient.pr_view_files` (`scripts/verify_runner.py`), and then forks on `publishing.ci_provider` before deciding how verification happens.

## GitHub path (default, unchanged)

When `ci_provider` is `github` — the default, and the field can be absent entirely — `run()` dispatches the `publish-verifier` LLM subagent (`agents/publish-verifier.md`) with `merged_pr_number`, `changed_paths`, `publishing_config`, and `repo`. That subagent's own procedure polls `gh run list --workflow <build_workflow>` for a run created at or after the merge time, waits for `status=completed`, and on `conclusion=success` derives each changed path's live URL from `publishing_config.url_map_rule` and curls it, returning a `{verified, failed, build_status}` verdict (`agents/publish-verifier.md`). This path is byte-for-byte unchanged by the work described below — every other provider forks around it, never through it.

## Non-GitHub provider seam (CCE-63)

Docs publish CI is not always GitHub Actions. Setting `publishing.ci_provider: circleci` (`templates/config.schema.json`) tells `verify_runner` to skip the LLM dispatch entirely and route into `resolve_build_verdict` (`scripts/build_poller.py:resolve_build_verdict`) instead — the Python seam for non-GitHub providers.

There is no live CircleCI-publishing host to validate the real polling logic against. Rather than guess at the CircleCI v2 API shape, ship it, and call it "tested," the seam degrades honestly. `UNVALIDATED_AGAINST_LIVE_HOST` (`scripts/build_poller.py`) is `True`, and while it is, `resolve_build_verdict` never makes a live call: it returns a non-promoting verdict — `build_status: "circleci_unvalidated"`, empty `failed` — plus one fixed-literal reason, `circleci_provider_modeled_but_unvalidated`. No crash, no hang, no laundered assumption reads as a validated integration.

The real polling logic exists only as documented stubs, reached solely once that flag is flipped: `poll_circleci` and `map_circleci_status` (`scripts/build_poller.py`) both raise `NotImplementedError`, citing the open API-shape decision. `CircleCiClient.pipeline_for_commit` (`scripts/build_poller.py:CircleCiClient.pipeline_for_commit`) does the same for the pipeline-lookup half of the walk. `CircleCiClient` does implement one real behavior today: `CircleCiClient.auth_headers` (`scripts/build_poller.py:CircleCiClient.auth_headers`) reads `CIRCLECI_TOKEN` from the environment and sends it only as a `Circle-Token` request header — never a URL userinfo segment or query param — raising `CircleCiTokenMissing` if the token is absent. `FakeCircleCiClient` (`scripts/build_poller.py:FakeCircleCiClient`) mirrors that shape for tests, so the flag-flip routing and token handling are exercised without a network dependency. A parallel `BuildPoller` protocol (`scripts/build_poller.py:BuildPoller`) documents the object-oriented contract a future provider-poller class could implement; nothing implements it yet.

## How verify_runner forks

`run()` computes `provider = (cfg.get("publishing") or {}).get("ci_provider") or "github"` and branches on it. On the `github` branch, reasons from the subagent dispatch feed `add_partial` and the notifier digest is built exactly as it was before this change — deliberately, so existing GitHub hosts see no behavioral difference. On any other branch, reasons from `resolve_build_verdict` populate a `digest_partial_reasons` list that is only attached to the notifier digest when non-empty, so a CircleCI host's digest carries a `partial_reasons` field the GitHub digest never has, and a GitHub host's digest never grows one.

Either way, `verify_succeeded` requires `build_status == "success"` with no `failed` entries before `state["last_successful_run"]` promotes. The CircleCI degrade path can never accidentally promote it, because `build_status` is `"circleci_unvalidated"`, which is never `"success"`.

## Credential redaction hardened for header-form secrets

Wiring in a real (if stubbed) HTTP client introduced a new credential-leak shape. `str(auth_headers())` on a Python dict produces a dict-repr like `{'Circle-Token': 'abc123'}`, and the pre-existing URL-only redaction pattern in `scripts/stderr_emit.py` never matched that shape. `_CREDENTIAL_HEADER_RE` (`scripts/stderr_emit.py`) now masks the value following a `Circle-Token` or `Authorization` header in both the plain `Header: value` form and the quoted dict-repr form, preserving the header name and any `Bearer`/`Basic` scheme so a redacted log line stays legible. `_redact_credentials` (`scripts/stderr_emit.py:_redact_credentials`) applies the URL pattern and the header pattern together, so every reason that reaches `emit_stderr` (`scripts/stderr_emit.py:emit_stderr`) — which is every `add_partial` call, including the ones this seam adds — gets both protections without any caller-side change.

## Config and setup

`publishing.ci_provider` (`templates/config.schema.json`) is an enum of `github` (default; omit the field entirely) and `circleci`; the schema's own description calls the `circleci` value "modeled but UNVALIDATED against a live host" so an operator reading the raw schema doesn't mistake it for a supported target. `CIRCLECI_TOKEN` is listed in the setup guide's secrets table (`docs/site-src/setup-guide.md`) as "Reserved / not yet wired" — setting it today has no effect, because `resolve_build_verdict` never reaches the code path that would read it.

## Scope: trigger is a separate seam

This page covers *verification* only — confirming a downstream build succeeded and pages are live. The complementary *trigger* seam — dispatching that build in the first place, via `_maybe_auto_merge`'s GitHub Actions `workflow_run` dispatch — stayed GitHub-only through this change. It was deliberately fenced by a strict-xfail test and picked up later under CCE-123, which gave it the matching honest-degrade treatment: `resolve_build_trigger` (`scripts/build_poller.py:resolve_build_trigger`) records an info-only `circleci_trigger_modeled_but_unvalidated` reason instead of dispatching, symmetric with the verify-side `circleci_provider_modeled_but_unvalidated` reason above. Don't conflate the two — a host can have a working trigger paired with a stubbed verify, or the reverse, depending on which of CCE-63 / CCE-123 has landed for it.
