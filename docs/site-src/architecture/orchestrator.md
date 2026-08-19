---
description: "Documents architecture orchestrator: the CCE-109/CCE-114 soft time-budget check bounds every expensive loop in the nightly run, CCE-152 cuts the authoring fan-out at a PR boundary (bounded by an authoring hard cap) instead of an arbitrary batch, CCE-144 splits `partial` into `blind` (the pipeline was prevented from judging) versus `degraded` (the pipeline judged and rejected) and gates `_exit_code`/`_should_advance_watermark`/`_maybe_auto_merge` on `blind`, CCE-119 makes the orchestrator (not the page-author LLM) the authority over frontmatter on agent-authored create pages, CCE-125 makes a gap-detector 'couldn't judge' verdict an info-only advisory outcome, and CCE-127 degrades a failed GitHub App token mint to a blocking partial reason instead of killing the job."
source_files:
  - CHANGELOG.md
  - scripts/orchestrator_runner.py
  - scripts/state_io.py
  - agents/page-author.md
  - agents/gap-detector.md
  - agents/schemas/gap_detector.schema.json
  - scripts/lint/description_quality.py
  - templates/workflow-run.yml
  - templates/config.schema.json
  - tests/orchestrator/test_enforce_agent_frontmatter.py
  - tests/orchestrator/test_agent_authored_create_frontmatter.py
  - tests/orchestrator/test_gap_detector_unjudged.py
  - tests/orchestrator/test_authoring_hard_cap_bounds.py
  - tests/orchestrator/test_pr_boundary_authoring_cut.py
  - tests/orchestrator/test_blind_run_interlocks.py
  - tests/orchestrator/test_classification_coverage.py
  - tests/state_io/test_add_partial_blind.py
  - tests/templates/test_workflow_run_parity.py
last_reviewed: "2026-08-19"
status: draft
doc_kind: architecture
---

# Orchestrator

`run()` in `scripts/orchestrator_runner.py:run` is the nightly pipeline entry point. It runs as a straight-line sequence of stages against one window of merged PRs (`last_successful_run.head_sha` to the current `HEAD`):

1. **source-collector** dispatch — pulls PRs (and Jira context, if configured) for the window.
2. **PR admission loop** — dispatches `pr-summarizer` once per PR, oldest-first (`scripts/orchestrator_runner.py`).
3. **Page-authoring fan-out** — batches `doc_targets` by `(lens, page_hint)` and dispatches `page-author` once per batch (`scripts/orchestrator_runner.py`).
4. **content-validator** — Tier-1 lint over every authored page; `block`-severity failures are reverted or unlinked.
5. **fact-checker warn layer** — one dispatch per authored page that cites a resolvable repo source (`scripts/orchestrator_runner.py`).
6. Deterministic site generators, source-drift (M) and citation-drift (C1) checks, canonical-core drift (C2).
7. **gap-detector loop** — one dispatch per admitted PR (`scripts/orchestrator_runner.py`).
8. What's New composition and `last_successful_run.head_sha` promotion.

Each stage that dispatches a subagent accumulates `partial_reasons` on failure via `add_partial` (`scripts/state_io.py:add_partial`); a run with any non-`info_only` reason is marked `partial: true` and — per CCE-101 — never auto-merges without also clearing the CCE-140 cursor-backed carve-out. Since CCE-144, every blocking reason also carries a second classification, `blind` or `degraded` — see [Blind vs degraded](#blind-vs-degraded-two-meanings-of-partial) below.

## Soft time budget

The run computes one deadline up front and carries it through every loop:

```python
budget = resolve_time_budget(config, time_budget_seconds)
deadline = clock() + budget if budget > 0 else None
```

`resolve_time_budget` (`scripts/orchestrator_runner.py:resolve_time_budget`) resolves precedence CLI override (including an explicit `0` for "unlimited") over `run.time_budget_seconds` in config over `DEFAULT_TIME_BUDGET_SECONDS` — 2700 seconds, 45 minutes (`scripts/orchestrator_runner.py:DEFAULT_TIME_BUDGET_SECONDS`). That default is a default, not a safe sizing: the job timeout is no longer what bounds it (both workflow files carry `timeout-minutes: 90` since CCE-140), and the binding bound is the GitHub App installation token's `GITHUB_APP_TOKEN_TTL_SECONDS` less the merge poll and the post-run tail. A stock 2700s host is squeezed flat by that ceiling — it gets no authoring overrun at all and emits an advisory `authoring_hard_cap_squeezed` reason on every run. See the hard-cap paragraph below for the arithmetic and for the budgets that do fit. A budget `<= 0` means no deadline at all: every per-loop check below is a no-op and the run authors, fact-checks, and gap-checks everything it admitted.

## Where the deadline is checked

CCE-109 introduced the deadline but only wired it into PR admission. CCE-114 closed the rest of the run — the page-author fan-out and the two advisory loops downstream of it — against the same clock. There are four checkpoints, and they don't all behave the same way. The page-authoring one is the outlier: it is the only checkpoint where passing the deadline is not by itself enough to cut.

**PR admission** (`scripts/orchestrator_runner.py`) — checked before summarizing PR `i`, guarded by `i > 0` so the run always admits at least one PR regardless of how slow it was to get there:

```python
if deadline is not None and i > 0 and clock() > deadline:
    ...
    prs = prs[:i]
    time_truncated = True
    break
```

A truncation here also decides whether the baseline is safe to advance — a deferred PR with no `merge_sha` can't be re-anchored by the next window, so `deferred_unanchored` blocks the advance in that case.

**Page-authoring fan-out** (`scripts/orchestrator_runner.py:run`) — two terms, not one. Passing the deadline arms the cut; a **PR boundary** or the **hard cap** is what fires it:

```python
if deadline is not None and i > 0:
    _now = clock()
    _past_hard = (
        authoring_hard_deadline is not None and _now > authoring_hard_deadline
    )
    _at_boundary = _owner != _prev_owner
    if _now > deadline and (_at_boundary or _past_hard):
        ...
        time_truncated = True
        break
```

This is the checkpoint CCE-109 was missing. Authoring is the single most expensive phase — one Claude dispatch per `(lens, page_hint)` batch — and admission alone completes too early in the run to bound it. Before CCE-114, a large window could pass the admission check in minutes and then author straight through the deadline into the workflow's hard kill; one observed run (27263616736) started roughly 20 page-author dispatches after the deadline had already passed, and — per `CHANGELOG.md` — six consecutive scheduled nightlies died this way with all work discarded.

CCE-114's version cut at whatever batch index it happened to reach, with an `i > 0` at-least-one-progress escape scoped to BATCHES. That guarantee turned out to be the wrong unit. `per_target` is built by walking the PRs oldest-first and `setdefault`-ing each doc target, so its batches arrive already grouped by the oldest PR that references each page — group(PR1), then group(PR2), and so on. Cutting at an arbitrary index therefore splits a group, and the PR whose group was split still owes a page: `advance_cursor_list` breaks at that index, and a run whose OLDEST PR fans out to more pages than the budget can author splits group(PR1) every single time. The ADIS host sat on one baseline for 20.6 days on exactly that, re-authoring the same leading pages and reporting `no_advance_no_cursor` four nightlies running.

CCE-152 changed the unit of the guarantee from one batch to **one complete PR group**. The soft deadline may only cut where `_owner != _prev_owner` — a PR boundary — which always leaves a complete prefix of PRs behind it, so the cursor is non-empty and the baseline moves. `i > 0` survives only to keep the very first batch unconditional.

Deferring to a boundary is unbounded on its own, so `authoring_hard_cap` (`scripts/orchestrator_runner.py:resolve_authoring_hard_cap`) bounds the overrun: `run.authoring_hard_cap_seconds`, else `budget * 1.15`, then clamped down against `GITHUB_APP_TOKEN_TTL_SECONDS` minus the merge poll this host will actually run minus a 285s post-run tail. That reserve is 285 because it is the largest value that still leaves a 2100s host its full 1.15 overrun (`2100 * 1.15 = 2415 <= 3600 - 900 - S` solves to `S <= 285`), and it has to cover more than its name suggests: the cut test is evaluated at the top of each authoring iteration, before that iteration dispatches, so the last admitted batch runs entirely past the hard deadline, on top of the site generators, the push and the PR create. An explicit value at or below the budget is a config error, not a clamp — equal collapses the hard deadline onto the soft one and restores the mid-group cut. A cap that is legal but above the ceiling — whether you wrote it in `run.authoring_hard_cap_seconds` or the `* 1.15` default produced it — is narrowed to the ceiling, and an advisory `authoring_hard_cap_clamped` reason names the resolved cap, which of those two sources produced it, the ceiling, and the poll term spending the difference, so the number the digest reports is the one the run used.

`resolve_authoring_hard_cap` (`scripts/orchestrator_runner.py:resolve_authoring_hard_cap`) therefore has four outcomes, each pinned by `tests/orchestrator/test_authoring_hard_cap_bounds.py`: **REJECTED** (an explicit `run.authoring_hard_cap_seconds` at or below the budget raises `ConfigError`), **NORMAL** (the resolved cap fits under the TTL ceiling and is returned unchanged), **CLAMPED** (the resolved cap is narrowed to the ceiling; advisory `authoring_hard_cap_clamped`), and **SQUEEZED** (the ceiling itself is at or below the budget, so the cap is held at the budget with no overrun; advisory `authoring_hard_cap_squeezed`). The two advisory outcomes are `info_only` and never flip `partial` — only REJECTED is a hard config error. `run.authoring_hard_cap_seconds` is a declared field in `templates/config.schema.json`; before CCE-152 the `run` block's `additionalProperties: false` silently rejected the documented key at `load_config_validated` before the resolver ever saw it, so a host that followed the docstring aborted its nightly at config load.

**What the clamp does and does not bound.** It bounds the _overrun_ — the stretch above `time_budget_seconds` — on the two paths where there is an overrun to bound: the normal path (the cap fits under the ceiling and is returned unchanged) and the clamped path (the cap is narrowed to the ceiling). It does not bound the budget. When the ceiling itself lands at or below the budget, the resolver returns the budget with no ceiling applied at all, records an advisory `authoring_hard_cap_squeezed` reason, and **that host is bounded by its own `time_budget_seconds` and nothing else** — `budget + merge poll` can reach the token's TTL exactly (the stock 2700s default does) and exceed it as the budget grows. Truncating or aborting a squeezed host would be strictly worse than the outcome it prevents, so the resolver degrades loudly instead: sizing a squeezed host against the token is the operator's, not the clamp's. Behaviour there is the pre-CCE-152 cut — never worse, never silent.

That gives the checkpoint **three distinct reasons**, sharing a prefix and diverging at the parenthetical and the trailing clause:

```text
time_budget_exceeded: authored 2/5 page batches (budget 2100s); deferring the rest
time_budget_exceeded: authored 2/5 page batches (hard cap 2415s over budget 2100s); cut inside PR #646, whose pages are now incomplete, so the baseline cannot advance to it
time_budget_exceeded: authored 2/5 page batches (hard cap held at budget 2700s by the App-token TTL); cut inside PR #646, whose pages are now incomplete, so the baseline cannot advance to it
```

The first is an ordinary deferral: the group behind the cut is complete and the run advances. The second is the bounded forced cut: the group is split, the run earns no advance, and the wording says so instead of reading like a deferral. The third is the same forced cut on a squeezed host — the one a stock-default host meets — worded so it does not read as a number over itself, since there the cap and the budget are the same number and "hard cap 2700s over budget 2700s" would hide the reason the overrun is missing. Past the hard cap **at** a boundary is still the first case — the cap only changes where a cut may land, never what a clean boundary means.

**fact-checker warn layer** (`scripts/orchestrator_runner.py`) and **gap-detector loop** (`scripts/orchestrator_runner.py`) drop the `i > 0` guard entirely — they skip outright the moment the deadline has passed, with no minimum-progress guarantee:

```python
if deadline is not None and clock() > deadline:
    add_partial(
        state,
        f"time_budget_exceeded: fact-checked {i}/"
        f"{len(fact_pages)} pages (budget {budget}s); "
        f"skipping the rest",
    )
    break
```

Both loops are otherwise advisory — a fact-checker `contradiction` verdict adds a PR-body warning, not a block, and gap-detector findings are informational flags — so their other failure paths use `info_only=True` reasons that don't affect `partial`. The time-budget cut is the one exception: it is deliberately _not_ `info_only`. Pages that were authored but never fact-checked, or PRs that were never gap-checked, must not slide into an auto-merge just because nothing else went wrong. Flipping `partial` here is what keeps the CCE-101 merge gate honest.

## Net effect

A time-budget cut anywhere in the run — admission, authoring, fact-checking, or gap-detection — sets `state["current_run"]["partial"] = True` with a `time_budget_exceeded: ...` reason describing exactly how much of that stage completed (`authored 1/3 page batches`, `fact-checked 0/3 pages`, `gap-checked 0/3 PRs`), and for the authoring cut, whether it landed on a PR boundary or was forced by the hard cap. Because authoring and the two advisory loops run in that fixed order, an authoring-loop cut also means the fact-checker and gap-detector loops never start — the pages that _were_ authored still exist and are still committed, but the run stays partial and open for manual review rather than auto-merging. Setting `time_budget_seconds: 0` (or passing `--time-budget 0` at the CLI) disables all four checkpoints and lets a run author, fact-check, and gap-check every admitted PR regardless of wall-clock time — useful for a manual `--no-pr` bootstrap run where you're willing to wait, dangerous to leave on for the scheduled nightly.

Every `time_budget_exceeded` reason is classified **degraded**, not blind (see the next section): the run held content back rather than being prevented from judging it, so it flips `partial` but never `blind`, `_exit_code` stays 0, and the watermark can still advance on the CCE-140 cursor-backed path.

## Blind vs degraded: two meanings of `partial`

Two nightly runs (2026-08-11 and 2026-08-12) reported `conclusion: success` while every subagent dispatch was rate-limited — zero calls succeeded. The 2026-08-12 run still advanced `last_successful_run` past three feature PRs whose pages were never authored. Nothing alarmed, because no code path made the job exit non-zero: `partial` was the only signal, and this pipeline's runs are *always* partial (fact-checker warnings, deferred PRs, and time-budget cuts all set it routinely), so an operator watching for `partial: true` had long since learned to ignore it. Because the baseline (`last_successful_run.head_sha`) is a consume-once cursor, that window's content is permanently undocumented.

CCE-144 splits `partial` into two classifications that were previously conflated under one flag:

- **`blind`** — the pipeline was *prevented from judging*. A blocking subagent dispatch produced no usable output (source-collector, pr-summarizer, content-validator, notifier, or a failed GitHub App token mint) and the run has no idea whether the content it skipped was fine or broken.
- **`degraded`** — the pipeline *judged and rejected* specific content. A lint `block`, a time-budget cut, an unsafe page path, or an unknown lens are all cases where the run looked at the work and made a defensible call to hold it back. Self-healing: the next run retries.

`add_partial` (`scripts/state_io.py:add_partial`) is the single writer of this distinction, via a `degraded` keyword argument:

```python
def add_partial(state, reason, *, info_only=False, degraded=False):
    ...
    if not info_only:
        cr["partial"] = True
        if not degraded:
            cr["blind"] = True
            cr.setdefault("blind_reasons", [])
            ...
```

The precedence is `info_only` > `degraded` > blind-by-default: an advisory reason (`info_only=True`) touches neither `partial` nor `blind`; a reason passed with `degraded=True` flips `partial` only; and a blocking reason that specifies neither flips **both** `partial` and `blind`, appending to a new `blind_reasons` list. That last branch is deliberate — it is the fail-safe default. An unclassified new blocking-failure mode is loud (`blind`) rather than silently passing as an ordinary `partial` reason nobody reads. Classification is by **call site**, never by reason string: the same `schema_invalid: ...` message is blind by default at source-collector but is passed `degraded=True` at page-author and gap-detector, because an unlanded page-author batch holds its PR out of the CCE-140 advance cursor regardless — the content isn't silently lost, it's held back. `_record_dispatch_reasons` (`scripts/orchestrator_runner.py:_record_dispatch_reasons`) is the single path for all blocking-agent dispatches and accepts the same `degraded` kwarg, so a failure changes classification based on where it happened, not on how well the agent explained itself.

Three consumers read `blind`:

- **`_exit_code`** (`scripts/orchestrator_runner.py:_exit_code`) returns `1` when the run is blind, joining the existing "docs PR could not be opened" failure class rather than competing with it — an operator reading only run status takes the same action for both. A merely-degraded run still exits `0`.
- **`_should_advance_watermark`** (`scripts/orchestrator_runner.py:_should_advance_watermark`) freezes `last_successful_run` on a blind run. Re-processing a window is cheap and idempotent; skipping one is not, so when in doubt the cursor does not move.
- **`_maybe_auto_merge`** (`scripts/orchestrator_runner.py:_maybe_auto_merge`) skips with `blind_run` unconditionally, checked *ahead of* the CCE-140 `partial and not advance_cursor_backed` carve-out. That ordering closes a real gap: a time-truncated run is cursor-backed by construction, and before CCE-144 a run that was simultaneously blind (say, a failed content-validator dispatch) and cursor-backed would have satisfied the CCE-140 carve-out and auto-merged unvalidated docs. Gating on the computed `blind` flag rather than adding another entry to `_MERGE_VETO_REASON_PREFIXES` closes the whole class of blind reasons at once, not just the one that happened to be observed.

`blind` is monotonic within a run and `blind_reasons` is always a subset of `partial_reasons` — same redaction, same append-once idempotency `add_partial` already applied to `partial_reasons`. `tests/orchestrator/test_classification_coverage.py` requires every blocking call site to pass an explicit `degraded` kwarg (an earlier registry-based design was rejected: its keys collided across `verify_runner` and decayed as call sites moved). The nightly workflow's "Print partial-run reasons" step (`templates/workflow-run.yml`) was repointed from `state.json` to the sibling `current_run.json` in the same change — `save_persistent_state` strips the ephemeral `current_run` key before writing `state.json`, so the step had been reading a key that was never there and printing nothing, on every run, since the ephemeral split. It now prints `blind_reasons` under their own `BLIND:` label alongside the ordinary `partial_reasons`.

## Advisory agents: a "couldn't judge" verdict must not degrade the run

`gap-detector` and `fact-checker` sit downstream of the blocking pipeline (source-collector, pr-summarizer, page-author, content-validator, notifier) as advisory layers — their output feeds a PR note, not a merge gate. A dispatch failure on either one is recorded `info_only=True` and never flips `partial` (fact-checker since CCE-118; gap-detector since CCE-125). The distinction that matters is between an agent that _failed_ and an agent that _ran and said "I can't tell"_ — the latter is a legitimate outcome, not a malfunction, and treating it as one was the last recurring driver of unnecessary `partial` nightlies (`schema_invalid: gap-detector: None is not of type 'boolean'`, observed on PR #189's run).

The gap-detector loop (`scripts/orchestrator_runner.py:run`) calls `dispatch_validated` per admitted PR and branches on the validated verdict's `needs_spec` field:

```python
if verdict.get("needs_spec") is None:
    add_partial(
        state,
        f"gap_detector_unjudged: pr_id={pr_id}",
        info_only=True,
    )
    continue
gap_verdicts.append(verdict)
```

`needs_spec: null` is the agent's documented fallback for malformed input — the gap-detector schema (`agents/schemas/gap_detector.schema.json`) types the field `["boolean", "null"]` and still marks it `required`, so a validated `null` is a legitimate, schema-conformant "unjudged" verdict rather than a parse failure. `_record_dispatch_reasons` (`scripts/orchestrator_runner.py:_record_dispatch_reasons`) already logged the dispatch as clean before this check runs; the `needs_spec is None` branch then records its own `gap_detector_unjudged` reason and `continue`s — the verdict is never appended to `gap_verdicts`, so it's excluded from both the "Gaps flagged" What's-New block and the CCE-89 PR digest.

Only a genuinely broken agent output still flips `partial`: an **absent** `needs_spec` key, a wrong non-null type, or unparseable JSON all fail `validate_and_parse` before reaching this branch, so `dispatch_validated` returns `None` and the loop's ordinary `_record_dispatch_reasons(state, reasons, ok=False)` path records a blocking reason. Only a _present_, schema-valid `null` is downgraded — the malfunction signal survives everywhere else.

## GitHub App-token mint failures degrade to `partial`, never kill the job

The nightly workflow mints a short-lived GitHub App installation token so the docs-agent's writes and its PR trigger host CI. `actions/create-github-app-token` runs under `continue-on-error: true` (`templates/workflow-run.yml`, kept in lockstep with the dogfood `.github/workflows/docs-agent-nightly.yml`) so a failed mint doesn't abort the job outright — the workflow falls back to `secrets.GITHUB_TOKEN` via `steps.app-token.outputs.token || secrets.GITHUB_TOKEN`. That fallback expression only evaluates for a _skipped_ step; without `continue-on-error`, a _failed_ step aborts the job before the `||` is ever reached, which is why this fallback was unreachable on the failure path for two months before CCE-127.

A `GITHUB_TOKEN`-backed run is silently weaker: it can commit and open the docs PR, but a `GITHUB_TOKEN` merge cannot fire `on: push` host CI, so the PR would register zero checks. Left unhandled, that reads to the CCE-101 auto-merge gate as "nothing failed" — exactly the failure mode CCE-127 closes. The step's outcome is exported at **step** scope (job-level `env:` cannot reference `steps.*`) as `DOCS_AGENT_APP_TOKEN_STATUS`, and `run()` checks it right after `current_run` is initialized and before the auto-merge decision:

```python
if os.environ.get("DOCS_AGENT_APP_TOKEN_STATUS", "") == "failure":
    _record_dispatch_reasons(
        state,
        [
            "app_token_unavailable: GitHub App installation token could not "
            "be minted; run degraded to GITHUB_TOKEN, so host CI will not "
            "fire on this PR. Verify the App is installed on this repo."
        ],
        ok=False,
    )
```

Only the literal `"failure"` degrades the run — `"skipped"` is the documented bare-host path (no `DOCS_AGENT_APP_CLIENT_ID` configured), and `"success"` or an unset variable both stay silent. `ok=False` routes the reason through the ordinary blocking `_record_dispatch_reasons` path with no `degraded` kwarg, so — per CCE-144 — `app_token_unavailable` sets `partial: true` **and** `blind: true`: a `GITHUB_TOKEN`-backed run never fires host CI, so the pipeline cannot judge whether the PR it opened is safe, the same "prevented from judging" shape as a failed source-collector dispatch. No new merge-gate code was needed for the original CCE-127 fix: `app_token_unavailable` is chained into `_MERGE_VETO_REASON_PREFIXES` (`scripts/orchestrator_runner.py:merge_veto_reason`) and `_maybe_auto_merge` (`scripts/orchestrator_runner.py:_maybe_auto_merge`) checks that veto list first, ahead of both CCE-144's later `blind` gate and the CCE-140 `partial and not advance_cursor_backed` carve-out — so a `GITHUB_TOKEN`-backed run is refused the merge on the first check regardless of how the other two gates would have resolved. Its `blind` classification still matters independently: `_exit_code` and `_should_advance_watermark` (CCE-144) read `blind` directly and are not scoped to the merge path, so an operator running with `merge: {policy: manual}` still gets the non-zero exit and the frozen watermark. Placement of the check is deliberate — after the `current_run` dict literal is assigned (an earlier `add_partial` call would create a stub the literal would then silently overwrite) and before the merge decision reads `state["current_run"]["partial"]`.

## Agent-authored create-page frontmatter fidelity

Step 3 (page-authoring fan-out) hands `page-author` a `frontmatter_template` for every batch. For a `create` in an `agent-authored` section (the generator behind this very page — see `scripts/frontmatter_contract.py`), that template carries the four lint-guarded fields: `description`, `source_files`, `last_reviewed`, `status`. Until CCE-119, the orchestrator wrote that template to disk only as a dry-run synth fallback and otherwise trusted the LLM's own write — `agents/page-author.md` told it to "draft" frontmatter from the template, not emit it verbatim, so a reworded description or a dropped `source_files` entry could pass through untouched.

CCE-119 closes that gap on the real production dispatch path. After `page-author` returns `ok` for a `create` batch, the orchestrator calls `_enforce_agent_frontmatter(target_path, agent_fields)` (`scripts/orchestrator_runner.py:_enforce_agent_frontmatter`, invoked at `scripts/orchestrator_runner.py`): it reads the page back, strips whatever `---` block is on disk, and re-prepends `frontmatter_contract.agent_authored_frontmatter_text(**agent_fields)` — the same `agent_fields` dict the orchestrator computed before dispatch, never anything the LLM wrote. The authored body is preserved untouched; only the frontmatter block is replaced. This is declare-then-discharge applied to a single subagent write: the page-author's frontmatter output is now advisory, not authoritative.

The reconciliation is scoped narrowly and deliberately:

- **Create-only.** An `edit` batch keeps the existing page's curated frontmatter as-is — reconciling here would clobber accumulated `source_files` or a since-promoted `status: published` that the orchestrator never tracked itself.
- **Agent-authored sections only.** Pages generated under the default authoring template (`status`/`sources`/`synthesized_into`) are untouched; `agent_fields` is `None` for those batches and the enforcement call is skipped.
- **Idempotent.** A page-author write that already matches `agent_fields` byte-for-byte is a no-op after reconciliation.

A second, related CCE-119 fix removed a duplicated constant. `_synthesize_agent_description` (the deterministic description used when the orchestrator itself has to author placeholder content, e.g. in dry-run) used to pad to a hardcoded minimum word count; it now calls `description_quality.resolve_min_words(config)` (`scripts/lint/description_quality.py:resolve_min_words`, resolved once at `scripts/orchestrator_runner.py` before the batch loop starts) so a host that raises `lint.tier1.description_quality.min_words` above the library default of 6 gets a synthesized description that still clears Tier-1 lint, instead of one silently pinned to the old constant.

Neither gap was a live failure before this fix — the content-validator's Tier-1 lint-drop path caught a bad frontmatter write and reverted it, same as any other `block`-severity failure — but both were CCE-117 residuals that left the production dispatch path relying on an LLM cooperating with an instruction rather than on a value the orchestrator itself controls. Tracker: CCE-119 (closes the two residual gaps identified after CCE-117 fixed the recurring "partial" nightly run caused by 20 blocked architecture pages).
