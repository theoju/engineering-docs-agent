---
description: 'Documents architecture publish verifier: Added a provider seam to the docs publish-verify path so hosts can set publishing.ci_provider: circleci. The existing GitHub Actions polling path is byte-for-byte unchanged. The CircleCI path currently returns an honest ''modeled but unvalidated'' non-promoting verdict instead of live-polling the CircleCI v2 API — the actual poller (poll_circleci/map_circleci_status) ships as documented NotImplementedError stubs because there is no live CircleCI-publishing host yet to validate the API shape against. Also closed a credential-redaction gap so header-form secrets (the dict-repr of Circle-Token/Authorization headers) get masked, and wired the CircleCI verdict''s reason through to the notifier digest.'
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
last_reviewed: '2026-07-23'
status: draft
---
# Publish verifier

After a docs-agent PR merges, the pipeline still has one job left: confirm the
host's build actually shipped the new pages. `scripts/verify_runner.py:run`
is the entry point — it's invoked by the post-merge workflow with a repo root
and the merged PR number, and it decides which of two paths to take based on
`publishing.ci_provider` in the host config.

## Two paths, one digest

`run` reads `provider = (cfg.get("publishing") or {}).get("ci_provider") or "github"`.
That single branch point is the whole seam:

- **`github` (default, and the only end-to-end-wired path).** `verify_runner`
  dispatches the `publish-verifier` subagent (`agents/publish-verifier.md`),
  which polls `gh run list --workflow <build_workflow>` for a run created at
  or after the merge, waits for `status=completed`, and on
  `conclusion=success` derives each changed page's live URL from
  `publishing.base_url` and `url_map_rule`, then `curl`s each one to confirm a
  200. Its output — `{verified, failed, build_status}` — is unchanged by the
  CircleCI work; this path is byte-for-byte the same as before CCE-63.
- **Any other value of `ci_provider` (today, only `circleci`).** `verify_runner`
  skips the LLM dispatch entirely and calls
  `resolve_build_verdict` in `scripts/build_poller.py` instead. No subagent
  runs, no live network call happens.

Both paths converge back into the same digest shape and the same
`notifier` dispatch, so the "PR landed" Slack/email message looks the same
regardless of which branch produced it — except for one added field, below.

## The CircleCI seam is honest, not real

`build_poller.py` exists because CCE-63 generalized a hard-coded
GitHub-Actions-only assumption in the publish-verifier, surfaced while
prepping a hybrid-CI host for onboarding. The team's option was to guess at
CircleCI's v2 API shape and ship a poller no one could validate against a
real host, or build the seam and have it degrade honestly until a real
CircleCI-publishing host exists. They took the second option.

The module-level flag `UNVALIDATED_AGAINST_LIVE_HOST` (`scripts/build_poller.py`)
gates everything. While it's `True` — which is always, today —
`resolve_build_verdict` returns a fixed, non-promoting verdict:

```python
{"verified": [], "failed": [], "build_status": "circleci_unvalidated"}
```

paired with a single fixed reason string, `circleci_provider_modeled_but_unvalidated`
(`PROVIDER_UNVALIDATED_REASON`). No token is read, no request is sent. The
real implementation — `poll_circleci` walking a pipeline to a workflow to a
job, and `map_circleci_status` collapsing CircleCI's status vocabulary onto
`{success, failure, timeout}` — exists only as documented
`NotImplementedError` stubs in `build_poller.py`. Both stubs point back to
"CCE-63 spec section 10," which is where the open questions live (notably
how to map CircleCI's `on_hold` status). They're reached only once someone
flips the flag to `False` after validating the real API shape against a live
host — nothing does that yet.

`CircleCiClient` (also a skeleton) does define one real behavior worth
knowing: `auth_headers` sends the CircleCI token as a `Circle-Token` request
header, never as URL userinfo or a query param, specifically so a logged
request URL can't leak it.

Because `build_status` is never `"success"` on this path,
`verify_runner`'s promotion gate (`failed_urls == [] and build_status ==
"success"`) never fires for a CircleCI host — the run stays open for
operator review rather than silently marking itself verified. That's the
point of the honest degrade: a CircleCI host gets a clearly-labeled
"not actually checked yet" result instead of a false green.

## What the operator sees

The non-github branch in `run` collects `poll_reasons` from
`resolve_build_verdict` and threads them two places:

1. Into `state["partial_reasons"]` via `add_partial`, same as any other
   partial-run reason.
2. Into the notifier digest as `digest["partial_reasons"]` — but only when
   non-empty, so the `github` path's digest shape is untouched.

`agents/notifier.md`'s procedure treats a `build_status` outside
`{success, failure, timeout}` (i.e. the `*_unvalidated` sentinel) as
**informational**, not a failure: it renders alongside the partial-run
reasons, not with failure wording, as long as there are no failed URLs.
The reader gets a plain statement that CircleCI support is modeled but
unvalidated, not a scary red build-failed banner.

## Credential redaction

`scripts/stderr_emit.py` is the single choke point for stderr writes from
the pipeline — a leaf module (stdlib-only, no imports from `state_io` or
`orchestrator_runner`) that both of those depend on. `emit_stderr` redacts
every reason it prints via `_redact_credentials`, which historically only
handled URL-embedded credentials (`https://user:token@host` → `<redacted>`).

CCE-63 closed a second leak vector: header-form secrets. `CircleCiClient.auth_headers`
returns a dict, and `str()`-ing a dict with a `Circle-Token` or `Authorization`
key produces something like `{'Circle-Token': 'abc123'}` — a form the old URL
regex never matched. `_CREDENTIAL_HEADER_RE` now masks the value after a
`Circle-Token` or `Authorization` key (case-insensitive), tolerating both the
plain `Header: value` form and the quoted dict-repr form, while preserving
the header name and any `Bearer`/`Basic` scheme so the redacted log line
stays legible.

## Config

`publishing.ci_provider` is validated by `templates/config.schema.json`
against the enum `["github", "circleci"]`. Absent field defaults to
`github`. The schema description is explicit that `circleci` is "modeled but
UNVALIDATED against a live host" and that only `github` is end-to-end wired
— read that field before pointing a host at it.

## Scope boundary

This seam covers verification only — the *publish trigger* is out of scope
and stays GitHub-only. `_maybe_auto_merge`'s call into `gh.workflow_run` in
`orchestrator_runner.py` is what dispatches the build workflow after a merge,
and it isn't provider-aware yet. A strict-xfail test marks that gap so it
turns red (and gets picked up) the moment the trigger becomes
provider-aware; no ticket is filed for that follow-up yet.

Also deliberately deferred: an onboarding fixture for `ci_provider:
circleci` in the setup skill. Shipping one now would signal end-to-end
readiness that doesn't exist. Until `poll_circleci` and
`map_circleci_status` are implemented and validated against a real
CircleCI-publishing host, treat `ci_provider: circleci` as "the config knob
exists and degrades safely," not "CircleCI hosts are supported."
