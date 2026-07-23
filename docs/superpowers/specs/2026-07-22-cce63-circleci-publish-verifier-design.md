# CCE-63: CircleCI provider seam for the publish-verifier (Option D′)

- **Ticket:** CCE-63 (priority Low) — parent CCE-58 (advanced-data-import-system onboarding)
- **Status:** design — awaiting operator review
- **Date:** 2026-07-22
- **Approach:** D′ (corrected D) — testable provider seam + honest degrade, poller left an explicit stub, publish-trigger gap tracked separately.

## 1. Problem

CCE-58 landed the `publishing.ci_provider` enum (`"github" | "circleci"`) into `templates/config.schema.json:99-104` as an **additive, forward-looking field with zero consumer code** — "only `github` implemented" (CCE-58 spec). CCE-63 is that deferred consumer: verify docs publishing for a host whose docs-publish CI runs on CircleCI.

Two facts, both confirmed against the tree, reshape the ticket from its original framing:

1. **`verify_runner.py` does not poll anything.** `scripts/verify_runner.py:run` is a thin orchestrator: it loads config/state, resolves changed paths via the dependency-injected `GhClient`, then hands the whole `publishing` block (which already carries `ci_provider` verbatim) to the **`publish-verifier` Sonnet subagent** via `dispatch_validated(...)` (`scripts/verify_runner.py:67-77`). The actual `gh run list --workflow` build-poll lives as **prose** in `agents/publish-verifier.md` Procedure step 1. Success resolution is `not failed_urls and build_status == "success"` (`scripts/verify_runner.py:101-112`).

2. **The docs publish is _triggered_ by a second, hardcoded GitHub-only seam.** The CCE-101 auto-merge path calls `gh.workflow_run(build_workflow)` (`scripts/orchestrator_runner.py:2886`, via `_maybe_auto_merge`) to fire the publish after merge, because a `GITHUB_TOKEN` merge cannot fire `on: push`. `GhClient.workflow_run` (`scripts/gh_client.py:115`) is a GitHub-Actions dispatch. On a CircleCI-publishing host the merge would land, this dispatch would no-op/error, CircleCI would never run, and the verifier would then poll for a build that never started.

**Consequence:** a working CircleCI host needs _both_ seams made provider-aware. This ticket owns the **verify** seam and makes the **trigger** seam a documented, loud gap tracked by a sibling issue. Verify-only, shipped silently, would be a non-functional feature that reads as complete.

**Additional reality:** there is **no live CircleCI-publishing host today.** The motivating host, `advanced-data-import-system`, runs CircleCI to gate user PRs but publishes docs via GitHub Actions and stays `ci_provider: github` (`templates/hosts/advanced-data-import-system.config.yml:34`). The CircleCI v2 REST API shape is therefore an **unvalidated guess**.

## 2. Goals

- Introduce a clean, testable **provider seam** in the verify path so CircleCI (and future providers) are a config value + a client class, not a new prose dialect in an LLM prompt.
- Keep the GitHub-Actions verify path **byte-for-byte** unchanged (regression floor).
- Degrade **honestly and gracefully** on a `circleci` host: emit a clear, non-promoting partial reason — never a crash, hang, empty artifact, or a green suite that overstates readiness.
- Keep the CircleCI token **off the LLM path** and make credential redaction cover header-form secrets.
- Make the second (publish-trigger) GitHub-only seam **visible and tracked**, not silently shipped as "done."

## 3. Non-goals

- **Implementing the real CircleCI poll.** `poll_circleci()` and `map_circleci_status()` ship as explicit `NotImplementedError` stubs. Green-testing a poller against self-authored fakes for an unvalidated API launders a guess into "tested" code that a future reader trusts; the FakeClient canned responses would be the very fiction being asserted. The seam's value is the _interface_, not a fictional implementation.
- **The publish-trigger fix** (`orchestrator_runner.py:2886`). Provider-aware dispatch is its own change with its own blast radius on the auto-merge path → sibling ticket (§9).
- **Extracting the working github poller from the agent into Python** (this was "Option B"). Moving a working, unit-untested, nightly-critical behavior off its path for zero current benefit is the single riskiest move on offer; explicitly rejected for CCE-63.
- **GitLab / Buildkite / Jenkins providers.** The seam accepts them (new `*Client` + enum value); none are built.
- **Migrating any existing host to CircleCI publishing.**

## 4. Why D′ (not A / B / C)

A four-lens design panel (testability, backward-compat/blast-radius, security/secrets, YAGNI/architecture) plus an adversarial review evaluated four candidates. Summary:

- **A (prompt-only conditional):** worst — CircleCI logic becomes untestable prose, routes a live token through an LLM subagent transcript (persisted verbatim), and has an unverifiable crash/hang failure mode.
- **B (extract all polling to Python now):** right destination, wrong time — rips the working github poll out of the agent with no red baseline to regress against, spending the largest regression budget on the nightly-critical path for a provider with zero consumers.
- **C (load-bearing enum + degrade, no seam):** honest and safe, but under-delivers and forfeits the provider seam, forcing a later re-derivation of the boundary under live-host pressure.
- **D′ (this spec):** C's honesty gate **plus** the tested provider seam, **minus** D's fictional green poller. Production-grade (risky logic behind a stubbed-but-shaped seam, github path provably untouched, token off the LLM path) _and_ honest (nothing green pretends to validate CircleCI).

C remains an acceptable minimal fallback if the team wants the absolute fewest lines on `verify_runner.py` this cycle; D′ is preferred because the seam is thin and makes the eventual poll a well-scoped drop-in.

## 5. Design

### 5.1 Provider fork in `verify_runner.run` (the one behavioral change)

Resolve the provider explicitly and fork **before** the existing dispatch:

```
provider = (cfg.get("publishing", {}).get("ci_provider") or "github")
```

- `provider == "github"` (this includes absent / `None`) → **today's exact `dispatch_validated("publish-verifier", ...)` call, unchanged.** This is a new fork guard, not a bug fix — nothing reads `ci_provider` in Python today; the value rides inside `publishing_config` to the agent and the agent's step 1 is entirely github. The guard exists so the _new_ branch cannot alter the _old_ path.
- `provider == "circleci"` → call the build-poller seam (§5.2).

The `{verified, failed, build_status}` verdict shape and the promotion gate (`not failed_urls and build_status == "success"`) are unchanged.

### 5.2 `scripts/build_poller.py` (new) — the seam

Mirrors the trusted `GhClient` / `FakeGhClient` dependency-injection pattern (`scripts/gh_client.py`) so reviewers discharge it against a known-good template.

- `UNVALIDATED_AGAINST_LIVE_HOST = True` — module-level constant, asserted load-bearing by a test.
- `BuildPoller` — a protocol/interface documenting the poll contract (inputs: `build_workflow`, merge SHA, merge time, timeout; output: a `build_status` in `success | failure | timeout`).
- `CircleCiClient` — real client skeleton: reads `os.environ` for `CIRCLECI_TOKEN` in `__init__`, exposes header construction that sends the token **only** as a `Circle-Token` request header (never a userinfo URL or query param), and a typed "token missing" error. Its API-walking methods (pipeline → workflow → job) are `NotImplementedError` stubs pending a validated API.
- `FakeCircleCiClient` — canned-response double mirroring `FakeGhClient`, ready for the eventual poll implementation and used to prove the flag-flip routing.
- `poll_circleci(client, ...)` and `map_circleci_status(status)` — **explicit `NotImplementedError` stubs** with docstrings pointing at the open decisions (§10). These are the only pieces gated on the unvalidated API.

### 5.3 The honesty gate (behavior while `UNVALIDATED_AGAINST_LIVE_HOST is True`)

The `circleci` branch does **not** call the live poller. It short-circuits to a first-class honest degrade:

- Record a fixed-literal partial reason: `circleci_provider_modeled_but_unvalidated`.
- Return a **non-promoting** verdict (`build_status` left non-`"success"`, `failed` empty) so the promotion gate does not promote and no false "verified" is emitted.
- No crash, no hang, no empty artifact — via the existing `add_partial` channel (`scripts/verify_runner.py:78`), matching the plugin's generic-first graceful-degradation mandate.

Because no live CircleCI host exists, this branch is never exercised in production today; a future operator onboarding a CircleCI host immediately sees the honest "modeled but unvalidated" signal instead of a silent mis-verify.

### 5.4 Notifier contract for the non-`success` sentinel

The honest degrade produces a non-`success` `build_status`. The notifier / digest path (`scripts/verify_runner.py:82` onward) must render this as a **clear, non-empty, informational** line ("CircleCI publish verification is modeled but not yet validated — not verified"), never a scary failure and never an empty/misleading notification. The plan must locate the digest's `build_status` consumer, confirm it handles the sentinel, and add a test asserting a sane notification on a `circleci` verify.

### 5.5 Token handling and required redaction

- The token is read in Python via `os.environ` inside `CircleCiClient` and sent **only** as a `Circle-Token` header — it never enters the agent prompt, the subagent Bash/WebFetch env, or the persisted `DOCS_AGENT_DEBUG_DIR` transcript.
- Every failure reason is a fixed literal (`circleci_token_missing`, `circleci_provider_modeled_but_unvalidated`, …) that never interpolates the token, response body, or headers.
- **Required:** extend the shared credential-redaction helper (`_redact_credentials`; the plan must `grep -rn` its callers per the shared-helper-contract rule and confirm the exact module/line) to also mask header-form secrets — `Circle-Token: <val>` and `Authorization: Bearer <val>`. Today's redaction matches only URL-embedded `user:token@host`, which misses header forms entirely. This hardening is generic and also protects the existing gh path.

### 5.6 Config / docs / fixture scaffolding

- `templates/config.schema.json` — enum already present; tighten the description to note CircleCI is modeled-but-unvalidated (no new required fields; provider-specific fields like vcs/branch/slug are deferred — §10).
- `docs/site-src/setup-guide.md` — add a `CIRCLECI_TOKEN` row to **both** the §2.4 Secrets table and the reference-appendix table, as a Secret (not a Variable), required only when `ci_provider: circleci`, marked "reserved / not yet wired."
- `agents/publish-verifier.md` — add `ci_provider` to the **Inputs** list for documentation parity; note that circleci is handled Python-side. **Leave the `## Output schema (canonical)` block untouched** so `tests/agents/test_schema_md_sync.py` stays green, and leave step 1's github prose byte-for-byte.
- Host fixture — a `ci_provider: circleci` host fixture under `tests/fixtures/host_onboarding/` auto-enrolls in `tests/setup/test_host_onboarding_fixtures.py`. To avoid signalling false end-to-end readiness (a committed fixture reads as a shippable config, but the host is not publishable until the trigger seam lands), its README **must** mark it **seam-only: CircleCI publishing is modeled-but-unvalidated and not end-to-end functional (see CCE-63 + trigger sibling ticket)**. (Whether to ship the fixture now with that warning or defer it until the trigger gap closes is an open call — §10.)

## 6. Acceptance criteria

1. `verify_runner.run` resolves `provider = ci_provider or "github"` and forks; `github`/absent behavior is proven byte-for-byte via the existing `fakes_verify_ok` / `fakes_verify_fail` dry-run outcomes (behavioral, not a dict snapshot).
2. `ci_provider: circleci` (flag on) → clean `circleci_provider_modeled_but_unvalidated` partial, non-promoting rc, no crash/hang.
3. `scripts/build_poller.py` exists with `BuildPoller`, `CircleCiClient` (real token handling, stubbed API walk), `FakeCircleCiClient`; `poll_circleci` and `map_circleci_status` are `NotImplementedError` stubs with doc pointers.
4. `UNVALIDATED_AGAINST_LIVE_HOST` is asserted load-bearing: a monkeypatched flip routes the fork to `poll_circleci` (asserted via the documented `NotImplementedError`), so the flag cannot silently rot.
5. The token never appears in any partial reason or persisted transcript; `_redact_credentials` masks `Circle-Token` / `Bearer` header forms, with the existing gh path unaffected.
6. The publish-trigger gap is documented and covered by an xfail/skip test asserting `orchestrator_runner.py:2886` (`gh.workflow_run`) is GitHub-Actions-only and that a CircleCI host needs a provider-aware trigger; the sibling ticket is referenced.
7. A `circleci` verify produces a sane, non-empty, non-misleading notification (test).
8. Config/docs/fixture scaffolding lands per §5.6; `test_schema_md_sync.py` and `test_host_onboarding_fixtures.py` stay green.
9. **No behavioral tests exist for `poll_circleci` / `map_circleci_status`** (they are stubs); tests assert only seam mechanics.

## 7. Test plan (pytest, TDD, fixture-driven dry-run, HTTP monkeypatched — never a live call)

- **github regression (behavioral):** existing `fakes_verify_ok` / `fakes_verify_fail` outcomes stay green; assert `github` and absent-provider produce identical promote / no-promote results.
- **`None → github` parity:** a config without `ci_provider` behaves identically to explicit `github`.
- **circleci honest degrade (live-testable now, zero API guess):** `ci_provider: circleci` → the fixed partial reason + non-promoting rc.
- **flag load-bearing:** `UNVALIDATED_AGAINST_LIVE_HOST is True`; a monkeypatched flip routes to `poll_circleci` (raises the documented `NotImplementedError`).
- **CircleCiClient token unit:** missing `CIRCLECI_TOKEN` → typed clean error; header built as `Circle-Token`; token never in any error/reason string.
- **redaction:** `_redact_credentials` masks `Circle-Token` / `Bearer` header forms; existing gh path unaffected.
- **trigger-gap xfail/skip:** documents `orchestrator_runner.py:2886` is github-only; fails loudly if someone changes it without addressing the sibling ticket.
- **notifier sentinel:** a `circleci` verify yields a sane, non-empty, non-misleading digest line.

## 8. Error handling / graceful degradation

- `ci_provider` absent / `None` → resolved to `github` → today's exact dispatch, no `CIRCLECI_TOKEN` ever required.
- `ci_provider: circleci` while `UNVALIDATED_AGAINST_LIVE_HOST` → clean partial, non-promoting, no crash.
- (future, flag flipped) missing/invalid `CIRCLECI_TOKEN` → clean partial + rc=1, never a hang.
- Never emit an empty artifact; every path yields a clear reason.

## 9. Sibling ticket — publish-trigger

A new CCE issue (proposed title: **"publish-trigger: provider-aware dispatch for non-GitHub docs CI"**) owns the second GitHub-only seam at `scripts/orchestrator_runner.py:2886`. Scope: on auto-merge, dispatch the publish in a provider-aware way (GitHub Actions `workflow_run` today; a CircleCI pipeline trigger for `ci_provider: circleci`), with the same DI/testability discipline. CCE-63 references it, marks the gap with the xfail test (AC6), and must not ship a fixture implying end-to-end CircleCI support until this lands. To be filed after this spec is approved.

## 10. Open decisions (deferred behind the flag; block flipping `UNVALIDATED_AGAINST_LIVE_HOST`, not this ticket)

- **CircleCI v2 API shape** — endpoint (`/project/gh/<owner>/<repo>/pipeline?branch=main` → walk pipeline → workflows → jobs) and, critically, how a merged-PR/commit SHA maps to the right pipeline (branch + created-after-merge, or `vcs.revision == merge_sha`).
- **Status vocabulary** — how CircleCI `running / success / failed / on_hold / blocked / canceled` collapse onto the fixed `success | failure | timeout`. `on_hold` (manual-approval gate) is the ambiguous one: keep-polling-until-timeout vs failure — a product/semantics call.
- **New config fields** — whether the CircleCI path needs vcs type (gh/bb), branch, and project slug added to `publishing`, or can derive them from the existing `repo{owner,name}` + a `branch=main` assumption. Any new fields are additive schema changes with their own fixture/test coverage.
- **Publisher-vs-gate** — confirm `ci_provider` names the _docs-publish_ CI only; it must never be read as "this host uses CircleCI for anything."
- **`CIRCLECI_TOKEN` scope** — confirm read-only pipeline/workflow/job scope suffices; document the exact token type operators mint.
- **Fixture timing** _(this-ticket decision, not a flag-flip blocker)_ — ship the seam-only `ci_provider: circleci` host fixture (§5.6) now with its README warning, or defer it until the trigger sibling ticket lands. Default: ship now with the warning; a reviewer may elect to defer. This is the only §10 item the implementation plan must resolve up front.

## 11. Security considerations

- Token stays in Python, header-only, never in the LLM path or persisted transcripts.
- Fixed-literal failure reasons; no interpolation of token / response / headers.
- Required header-form redaction closes the gap the URL-only redaction leaves open, hardening the gh path too.

## 12. References

- Ticket CCE-63; parent CCE-58 (onboarding, enum landed at `templates/config.schema.json:99-104`).
- Verify path: `scripts/verify_runner.py:67-112`; agent `agents/publish-verifier.md` step 1; dry-run fakes under `tests/orchestrator/`.
- Publish-trigger seam: `scripts/orchestrator_runner.py:2886`, `scripts/gh_client.py:115`.
- Design provenance: four-lens design panel + adversarial challenge (2026-07-22), which surfaced the trigger-gap blocker and the honesty correction that turned "D" into "D′".
- Invariants: `CLAUDE.md` — test the actual consumer; declare-then-discharge; generic-first / degrade-gracefully; shared helpers are contracts; stdlib-first; fixture-driven dry-run tests.
