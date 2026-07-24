# CCE-123: Publish-Trigger Provider-Aware Dispatch — Design

**Status:** approved (brainstorming), 2026-07-23
**Sibling:** CCE-63 (the post-merge _verify_ seam). CCE-123 closes the **second** of the two GitHub-only seams identified during the CircleCI-migration adversarial review.
**Approach:** ① Provider-aware seam + honest degrade (mirror CCE-63), reason-framing (a).

## 1. Context

CCE-63 made the post-merge **verify** seam provider-aware: `scripts/verify_runner.py` forks on `publishing.ci_provider`; a non-github provider degrades honestly through `build_poller.resolve_build_verdict` (a non-promoting verdict + a fixed `circleci_provider_modeled_but_unvalidated` reason) rather than mis-verifying. It deliberately left the **second** GitHub-only seam open.

That seam is the post-merge **trigger**. After the docs PR auto-merges, `_maybe_auto_merge` (`scripts/orchestrator_runner.py:2884-2891`) kicks the host's build/deploy:

```python
if build_workflow:
    dispatch = gh.workflow_run(build_workflow)      # GitHub Actions workflow_dispatch
    ...
```

This dispatch exists because a `GITHUB_TOKEN` merge cannot fire an `on: push` workflow. For a `ci_provider: circleci` host the call is meaningless — there is no GitHub Actions workflow to run.

A **strict-xfail acceptance test already guards the gap**: `tests/orchestrator/test_build_poller.py::test_publish_trigger_is_provider_aware` asserts `"ci_provider" in inspect.getsource(orchestrator_runner._maybe_auto_merge)`. Because it is `strict=True`, it flips to a hard failure the moment the seam becomes provider-aware — forcing this change to complete cleanly (the marker must be removed as part of the change).

## 2. Goal

Make the trigger seam provider-aware, symmetric with the CCE-63 verify seam:

- `github` → **byte-for-byte unchanged behavior** (`gh.workflow_run(build_workflow)`).
- non-github (`circleci`) → honest degrade: **no dispatch**, exactly one `info_only` reason `pages_dispatch_skipped: circleci_trigger_modeled_but_unvalidated`. The real CircleCI pipeline trigger is a `NotImplementedError` stub behind the existing `UNVALIDATED_AGAINST_LIVE_HOST` flag.

## 3. Approach rationale (why ①+a)

Stack rank (full analysis in the brainstorming transcript):

1. **① Provider-aware seam + honest degrade — chosen.** Symmetric with CCE-63 (shared flag + honest vocabulary), smallest blast radius, GitHub path unchanged, fully testable with fakes and **no live host**, cleanly satisfies + removes the strict-xfail, observable.
2. **② Config-driven generic `trigger_command`** — deferred. Genuinely generic but adds a config/schema surface, a security concern (running host-supplied commands), and diverges from the `ci_provider` enum the verify seam already forks on. YAGNI for one known second provider.
3. **③ Real CircleCI v2 trigger** — deferred. Unvalidated against any live host (the exact risk CCE-63 deferred); untestable; violates "verify with the real consumer."
4. **④ Block auto-merge for non-github** — rejected. Wrong lever: changes merge _eligibility_, not the trigger. CircleCI likely rebuilds on the merge push, so blocking is strictly worse.
5. **⑤ Silent no-op** — rejected. No signal to an operator asking "why didn't my site redeploy?"; violates the repo's "log what's dropped" invariant.

**Reason-framing (a) over (b):** the reason is `circleci_trigger_modeled_but_unvalidated`, not `circleci_trigger_not_required_builds_on_push`. We have no live host to confirm the host's CircleCI project is push-triggered, so (a) keeps one honest vocabulary across both seams. Documented hypothesis: CircleCI's VCS integration typically rebuilds on the merge push, so an explicit trigger is likely _unnecessary_ — promote to (b) only after live-host confirmation.

## 4. Components

### 4.1 `build_poller.resolve_build_trigger` — new (symmetric with `resolve_build_verdict`)

```python
TRIGGER_UNVALIDATED_REASON = "circleci_trigger_modeled_but_unvalidated"

def trigger_circleci(client) -> bool:
    """Real CircleCI v2 pipeline trigger. NOT IMPLEMENTED — no live host to
    validate (CCE-123; mirrors CCE-63 §10). Reached only once the flag flips."""
    raise NotImplementedError("CircleCI trigger unvalidated — see CCE-123")

def resolve_build_trigger(provider: str) -> tuple[bool, list[str]]:
    """(triggered, reasons) for a non-github provider's post-merge build trigger.
    While UNVALIDATED_AGAINST_LIVE_HOST: (False, [TRIGGER_UNVALIDATED_REASON]) — no
    dispatch. Once flipped: route into trigger_circleci (raises until the real
    trigger ships). GitHub never routes here — it keeps its native gh.workflow_run
    dispatch in _maybe_auto_merge."""
```

`TRIGGER_UNVALIDATED_REASON` is a fixed literal — it never interpolates a token/response (same discipline as `PROVIDER_UNVALIDATED_REASON`). Minimal signature `(provider)` by design: a future real trigger threads config/repo/ref then (YAGNI now).

### 4.2 `_maybe_auto_merge` fork — modify (`orchestrator_runner.py`)

Add keyword param `ci_provider: str | None = None`. After a successful merge:

```python
reasons = [(f"auto_merge_succeeded: pr={pr_number}", True)]
provider = ci_provider or "github"
if provider == "github":
    if build_workflow:
        dispatch = gh.workflow_run(build_workflow)          # unchanged
        if dispatch.ok:  reasons.append((f"pages_dispatch_succeeded: {build_workflow}", True))
        else:            reasons.append((f"pages_dispatch_failed: {dispatch.error}", True))
else:
    _triggered, trigger_reasons = resolve_build_trigger(provider)
    for r in trigger_reasons:
        reasons.append((f"pages_dispatch_skipped: {r}", True))
```

All reasons stay `info_only=True` — the trigger seam is hygiene and never flips a run to partial. Requires `from build_poller import resolve_build_trigger` (build_poller imports only stdlib → no cycle).

### 4.3 Call-site wiring — modify (`orchestrator_runner.py:~2048`)

Add `ci_provider=config.get("publishing", {}).get("ci_provider")` to the `_maybe_auto_merge(...)` call. Absent field → `None` → `"github"` → unchanged behavior.

### 4.4 Strict-xfail removal — modify (`tests/orchestrator/test_build_poller.py`)

Remove the `@pytest.mark.xfail(..., strict=True)` decorator from `test_publish_trigger_is_provider_aware`; it becomes a normal passing test. **Atomic with 4.2** — a strict xfail that XPASSes is itself a failure, so the fork and the marker removal land in the same commit.

### 4.5 Docs — modify

- `templates/config.schema.json`: extend the `ci_provider` description to note that **both** the verify seam (`verify_runner.py`) and the trigger seam (`_maybe_auto_merge`) now fork on the field.
- `CLAUDE.md`: update the CircleCI-seam note so it no longer describes the trigger as an open GitHub-only seam deferred to CCE-123 (it's now provider-aware and honest-degrading, real trigger still stubbed).

## 5. Data flow

merge succeeds → provider fork → github dispatches / circleci records the skip reason → reasons flow through the caller's `add_partial(..., info_only=True)` loop into `current_run.partial_reasons` → the notifier digest renders them under "Partial-run reasons" (informational; never flips `partial`).

## 6. Test matrix

**`tests/orchestrator/test_build_poller.py`:**

- `resolve_build_trigger("circleci")` → `(False, ["circleci_trigger_modeled_but_unvalidated"])`.
- flag flipped to False (monkeypatch) → `NotImplementedError`.
- `trigger_circleci(...)` stub → `NotImplementedError`.
- reason is a fixed literal (no token interpolation).
- `test_publish_trigger_is_provider_aware` — xfail removed, passes normally.

**`tests/orchestrator/test_auto_merge.py`:**

- `_run` helper gains a `ci_provider=None` param threaded to `_maybe_auto_merge`.
- circleci provider + eligible + green checks → `merged True`, **no** `workflow_run` in `gh.calls`, `("pages_dispatch_skipped: circleci_trigger_modeled_but_unvalidated", True) in reasons`.
- github default (existing `test_successful_merge_dispatches_pages_workflow`, `test_no_build_workflow_skips_dispatch`, `test_dispatch_failure_is_info_only_after_merge`) — unchanged, still green.
- `test_all_reasons_are_info_only` — unchanged and still green, but note it does
  **not** reach the circleci path: it drives the github default with a red check,
  which short-circuits at `checks_failed` before the dispatch fork. The circleci
  reason's `info_only=True` is instead pinned by the `True` in the exact-tuple
  assertion of the circleci test above.

**Deliberate non-coverage (CCE-123 adversarial validation).** No test drives
`_maybe_auto_merge` with `ci_provider="circleci"` _and_
`UNVALIDATED_AGAINST_LIVE_HOST=False`. In that state `resolve_build_trigger` →
`trigger_circleci` raises `NotImplementedError` _after_ the (irreversible) merge,
and the dispatch fork is intentionally **not** wrapped in try/except: the raise is
the honesty gate's "you flipped the flag without shipping the real trigger" signal,
symmetric with the verify seam (`resolve_build_verdict`). Wrapping it would silence
that signal. The flag is a hardcoded, always-`True` module constant in production,
so this path is unreachable via any host config — the loud crash is a developer-time
guardrail, not a runtime path.

## 7. Acceptance criteria

1. `_maybe_auto_merge` forks on `ci_provider`; the github path behavior is unchanged (all existing `test_auto_merge` dispatch tests stay green).
2. circleci host: merge proceeds, **no** `workflow_run` call, exactly one `info_only` `pages_dispatch_skipped: circleci_trigger_modeled_but_unvalidated` reason.
3. `resolve_build_trigger` + `trigger_circleci` live in `build_poller` behind `UNVALIDATED_AGAINST_LIVE_HOST`, symmetric with `resolve_build_verdict`.
4. The strict-xfail is removed; `test_publish_trigger_is_provider_aware` passes as a normal test.
5. Full `python3 -m pytest` suite green on the integrated tree.
6. No new config field, no merge-eligibility change, github digest unchanged for github hosts.

## 8. Out of scope

- The real CircleCI pipeline trigger (deferred until a live host; stub + flag are in place).
- Generic `trigger_command` config (approach ②).
- Any change to merge eligibility or to the CCE-63 verify seam.

## 9. Open decisions

- Reason framing (a) chosen; promote to (b) `circleci_trigger_not_required_builds_on_push` only after live-host confirmation that the host's CircleCI project rebuilds on push.
- `resolve_build_trigger(provider)` minimal signature — a future real trigger threads `publishing_config`/`repo`/`ref` at that point (YAGNI now).
