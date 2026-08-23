---
description: "Documents architecture orchestrator: CCE-144 splits a blocking failure into blind (the run was prevented from judging — source-collector/pr-summarizer/content-validator/notifier failure) vs degraded (the run judged and withheld work — a lint block, a time-budget cut, an unlanded page batch), where only blind exits non-zero, freezes the watermark, and vetoes auto-merge; CCE-151 makes the cursor-backed watermark advance run on every code path, not only the time-truncated one; CCE-159 caches a merged PR's summary by merge SHA across nightly runs; the CCE-109/CCE-114 soft time-budget check bounds every expensive loop and, since CCE-152, cuts page authoring at a PR boundary rather than an arbitrary batch index; CCE-119 makes the orchestrator (not the page-author LLM) the authority over frontmatter on agent-authored create pages; CCE-125 makes a gap-detector 'couldn't judge' verdict an info-only advisory outcome; and CCE-127 degrades a failed GitHub App token mint to a blocking partial reason instead of killing the job."
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
  - templates/state.schema.json
  - tests/orchestrator/test_enforce_agent_frontmatter.py
  - tests/orchestrator/test_agent_authored_create_frontmatter.py
  - tests/orchestrator/test_gap_detector_unjudged.py
  - tests/orchestrator/test_classification_coverage.py
  - tests/orchestrator/test_blind_run_interlocks.py
  - tests/orchestrator/test_cursor_backed_merge.py
  - tests/orchestrator/test_pr_summary_reuse.py
  - tests/orchestrator/test_pr_boundary_authoring_cut.py
  - tests/orchestrator/test_degraded_advance_non_truncated.py
  - tests/templates/test_workflow_run_parity.py
last_reviewed: "2026-08-23"
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

Each stage that dispatches a subagent accumulates `partial_reasons` on failure via `add_partial`; a run with any non-`info_only` reason is marked `partial: true` and — per CCE-101 — never auto-merges.

## Blind vs. degraded: classifying a blocking failure

Not every failure that flips `partial` means the same thing, and conflating them cost two nights of undocumented history. Runs `31472240064` (2026-08-11) and `31579090583` (2026-08-12) both reported `conclusion: success` in GitHub Actions even though every subagent was rate-limited and returned nothing — the orchestrator returned exit code 0 on every path, so nothing alarmed. The next run's watermark advance (PR #215) then walked the cursor past three PRs (#211, #212, #213) whose documentation is now permanently unrecoverable — the cursor is consume-once, and a window it skips is never re-read.

CCE-144 splits `partial` into two orthogonal classifications carried on `state["current_run"]`:

- **`blind`** — the run was PREVENTED from judging its input. A blocking agent (source-collector, pr-summarizer, content-validator, notifier) never produced usable output, so the pipeline has no basis for a decision at all.
- **`degraded`** — the run JUDGED its input and deliberately withheld or rejected something: a lint `block` reverted a page, a time-budget cut deferred a PR, a page-author dispatch failed and its batch stayed unlanded. The pipeline knows exactly what it lost and why.

`add_partial` (`scripts/state_io.py:add_partial`) is the single writer of this classification, via two keyword arguments — `info_only` and `degraded`:

- `info_only=True` → advisory noise; touches neither `partial` nor `blind`.
- `degraded=True` (and not `info_only`) → flips `partial` only. Self-healing: the withheld content is retried next run.
- neither → flips `partial` AND `blind`, and appends the reason to `blind_reasons` too. This is the fail-safe default — an unclassified new failure mode fails loud rather than passing silently.

Classification happens by CALL SITE, never by matching on the reason string — a `schema_invalid:` reason is emitted by three different call sites (source-collector, page-author, gap-detector) that classify differently, and only the call site knows which. `_record_dispatch_reasons` (`scripts/orchestrator_runner.py:_record_dispatch_reasons`) is the one path all seven agent dispatches route their reasons through; page-author and gap-detector pass `degraded=True` explicitly (an unlanded page batch is held out of the watermark advance rather than lost — see the cursor-backed section below — and gap-detector's output is advisory and outside the merge gate anyway), and every other blocking dispatch takes the `degraded=False` default.

Three consumers read the flag:

- **`_exit_code`** (`scripts/orchestrator_runner.py:_exit_code`) returns 1 when `blind`, 0 otherwise — the same exit-1 class the runner already used when it couldn't open the docs PR, so an operator watching only run status takes one action for both.
- **`_should_advance_watermark`** (`scripts/orchestrator_runner.py:_should_advance_watermark`) refuses to move `last_successful_run` at all when `blind` — a run that never saw its input has nothing honest to advance to.
- **`_maybe_auto_merge`** (`scripts/orchestrator_runner.py:_maybe_auto_merge`) skips with `blind_run` unconditionally, ahead of the CCE-140 `partial and not advance_cursor_backed` carve-out — a cursor-backed advance proves the baseline is honest about what the run SAW, and a blind run did not see anything.

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

Deferring to a boundary is unbounded on its own, so `authoring_hard_cap` (`scripts/orchestrator_runner.py:resolve_authoring_hard_cap`) bounds the overrun: `run.authoring_hard_cap_seconds` (declared in `templates/config.schema.json`, integer, minimum 1), else `budget * 1.15`, then clamped down against `GITHUB_APP_TOKEN_TTL_SECONDS` minus the merge poll this host will actually run minus a 285s post-run tail. JSON Schema has no way to compare two sibling properties, so the schema can declare the field's shape but not reject a cap at or below the budget — that comparison is `resolve_authoring_hard_cap`'s own, at startup. That reserve is 285 because it is the largest value that still leaves a 2100s host its full 1.15 overrun (`2100 * 1.15 = 2415 <= 3600 - 900 - S` solves to `S <= 285`), and it has to cover more than its name suggests: the cut test is evaluated at the top of each authoring iteration, before that iteration dispatches, so the last admitted batch runs entirely past the hard deadline, on top of the site generators, the push and the PR create. An explicit value at or below the budget is a config error, not a clamp — equal collapses the hard deadline onto the soft one and restores the mid-group cut. A cap that is legal but above the ceiling — whether you wrote it in `run.authoring_hard_cap_seconds` or the `* 1.15` default produced it — is narrowed to the ceiling, and an advisory `authoring_hard_cap_clamped` reason names the resolved cap, which of those two sources produced it, the ceiling, and the poll term spending the difference, so the number the digest reports is the one the run used.

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

Every `time_budget_exceeded` reason is recorded `degraded=True` (see "Blind vs. degraded" above): the run judged that it ran out of time and deliberately deferred specific PRs or pages, rather than being prevented from judging anything. That classification is what keeps a time-truncated run eligible for the cursor-backed watermark advance described next, instead of being treated as blind.

## PR-summary caching

`pr-summarizer` used to be re-dispatched, from scratch, against every PR sitting in the collection window every night — because the window is a slow lookback, the same merged PRs stay in scope across many nightlies until the cursor advances past them. Measured on the ADIS host: 52 of the 58 PRs summarized on 2026-08-17 had already been summarized the night before, ~90% repeat work against content that cannot change (a merge commit is immutable).

CCE-159 caches a PR's summary by merge SHA and reuses it. `cached_pr_summary` (`scripts/orchestrator_runner.py:cached_pr_summary`) returns a stored summary only when three conditions all hold: an entry exists under the PR's identity (`{owner}/{name}#{pr}`, built by `deferral_key`); its stored `merge_sha` matches the PR's actual `merge_sha`; and its stored `fingerprint` matches `pr_summarizer_fingerprint()` (`scripts/orchestrator_runner.py:pr_summarizer_fingerprint` — a SHA-256 hash of `agents/pr-summarizer.md`, truncated to 16 hex chars). Editing the agent's own instructions therefore invalidates every cached entry automatically; an unreadable agent file hashes to `""`, which matches nothing, so the cache fails CLOSED to a full re-summarize rather than serving a summary it cannot prove is current.

The cache is opt-out, not opt-in: `run.reuse_pr_summaries` (declared in `templates/config.schema.json`, boolean, default `true`) needs no config edit for an existing host to gain the savings; setting it `false` restores the pre-CCE-159 behavior of re-summarizing every PR in the window on every run. The cache itself is persisted under the `pr_summaries` key declared in `templates/state.schema.json` — never seeded empty, so a host that caches nothing writes a byte-identical state file to one running the pre-CCE-159 code. `next_pr_summaries` (`scripts/orchestrator_runner.py:next_pr_summaries`) writes the persisted `state["pr_summaries"]` map each run, evicting entries after `PR_SUMMARY_RETENTION_DAYS` (30) days of not being seen — by last-seen date, not by window membership, because the window can shrink transiently when source-collector degrades, and wiping the cache at exactly the moment the pipeline is already struggling would be the worst time to lose it. A PR that keeps being deferred (and so never gets a fresh summary) still has its `last_seen_at` refreshed each run, so it never ages out while it is still in play.

A reused summary is re-stamped with the PR's actual `pr_number` before use, the same as a fresh dispatch — a cached entry's own echo is never trusted over the PR object driving the loop. When any summaries are served from cache, the run records an info-only `pr_summaries_reused: N/M PRs served from cache, N pr-summarizer dispatches skipped` reason, so the saving is visible in the digest rather than invisible.

## Cursor-backed watermark advance holds on every path

CCE-140 built a cursor walk that advances the baseline only as far as the last PR whose page batches all landed — `advance_cursor_list` (`scripts/orchestrator_runner.py:advance_cursor_list`) stops at the first PR number in a `held_back` set, so the watermark never crosses a PR whose content is still owed. CCE-144 added the complement writer that computes that set: every `per_target` batch key NOT in `landed_batches` folds its PRs into `deferred_pages_by_pr` — a complement rather than an enumeration of failure sites on purpose, so a new `continue` added to the authoring loop later is covered for free.

Until CCE-151, that whole apparatus — computing `held_back`, deciding forgiveness via `partition_deferrals` (`scripts/orchestrator_runner.py:partition_deferrals`), and walking the cursor — lived entirely inside `if time_truncated:`. Any run that was partial for a NON-time reason (a lint `block` that reverted a page, a `page_author_invalid` dispatch failure) fell into the `else` branch, which set `advance_sha` to the full window HEAD without ever reading `deferred_pages_by_pr`. Because the watermark is consume-once, the skipped window was gone for good, and the run still exited 0. Two production incidents (runs `32460602658` and `32495019606`, both 2026-08-21) each blocked a page on lint and then advanced straight past the very window that held the stranded content; recovery needed a hand-written baseline rewind.

CCE-151's fix is structural, not a new veto: `partition_deferrals` and `held_back` are now computed UNCONDITIONALLY every run, and the cursor walk is entered whenever `time_truncated or held_back` — not only on `time_truncated`. A clean run with nothing held back still takes the plain window-HEAD advance (the `else` branch, now gated on `held_back` being empty), so ordinary behavior is unchanged.

Two traps this took to get right:

- **Gating the watermark refusal on `partial` instead of on `held_back` would have reinstated the CCE-109 doom loop.** A permanently-unlintable page would freeze the baseline forever — the cursor has to keep MOVING, just never past undocumented work. `held_back` names exactly the unfinished content; `partial` alone does not.
- **Hoisting only the READ of `deferred_pages_by_pr` was not enough — `partition_deferrals` had to move too.** With `still_deferred` left at its default empty list on the non-truncated path, `next_deferral_counts` (`scripts/orchestrator_runner.py:next_deferral_counts`) silently cleared the deferral count of every held-back PR on every run that didn't time-truncate, so no PR could ever accumulate enough consecutive deferrals to reach the CCE-140 skip threshold. That release valve is what stops the first trap from recurring by another route.

The reason strings the walk emits are cause-dependent: `time_budget_*` on the time-truncated path (kept byte-identical, since `test_time_budget.py` and `test_deferral_skip.py` assert those exact strings and the CCE-109/CCE-140 runbooks tell operators to grep for them) and `held_back_*` on the newly-covered non-time path — e.g. `held_back_no_advance_no_cursor` when no admitted PR carries a usable `merge_sha`, or `held_back_no_advance_unanchored_deferred` when a still-deferred PR has none. Neither family is in `_MERGE_VETO_REASON_PREFIXES` (`scripts/orchestrator_runner.py:_MERGE_VETO_REASON_PREFIXES` — one entry, `app_token_unavailable`), and both keep `degraded=True`, so this change is orthogonal to the blind/degraded split above.

**Diagnostic reflex:** a green nightly with `partial: true` whose baseline moved anyway is not a linting bug — check `deferred_pages_by_pr` and `held_back` before suspecting the page-author.

## Advisory agents: a "couldn't judge" verdict must not degrade the run

`gap-detector` and `fact-checker` sit downstream of the blocking pipeline (source-collector, pr-summarizer, page-author, content-validator, notifier) as advisory layers — their output feeds a PR note, not a merge gate. A fact-checker dispatch failure is recorded `info_only=True` and never flips `partial` (CCE-118) — the warn layer just skips that page's warnings. A gap-detector dispatch failure is different since CCE-144: it now routes through `_record_dispatch_reasons(..., degraded=True)` (see "Blind vs. degraded" above), so it DOES flip `partial` — but is classified `degraded`, not `blind`: the pipeline judged that it could not check this one PR for gaps, it was not prevented from judging everything. The distinction that matters is between an agent that _failed_ and an agent that _ran and said "I can't tell"_ — the latter is a legitimate outcome, not a malfunction, and treating it as one was the last recurring driver of unnecessary `partial` nightlies (`schema_invalid: gap-detector: None is not of type 'boolean'`, observed on PR #189's run).

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

Only a genuinely broken agent output still flips `partial`: an **absent** `needs_spec` key, a wrong non-null type, or unparseable JSON all fail `validate_and_parse` before reaching this branch, so `dispatch_validated` returns `None` and the loop's ordinary `_record_dispatch_reasons(state, reasons, ok=False, degraded=True)` path records a blocking, `degraded` (not `blind`) reason. Only a _present_, schema-valid `null` is downgraded further, to `info_only` — the malfunction signal survives everywhere else.

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

Only the literal `"failure"` degrades the run — `"skipped"` is the documented bare-host path (no `DOCS_AGENT_APP_CLIENT_ID` configured), and `"success"` or an unset variable both stay silent. `ok=False` routes the reason through the ordinary blocking `_record_dispatch_reasons` path with no `degraded` argument, so — per "Blind vs. degraded" above — it defaults to `blind`, not merely `degraded`: the run was prevented from confirming its own PR can be trusted, not merely withholding a page it chose not to author. No new gate code is needed for the merge decision itself: `merge_veto_reason` (`scripts/orchestrator_runner.py:merge_veto_reason`) already matches the `app_token_unavailable` prefix in `_MERGE_VETO_REASON_PREFIXES` and `_maybe_auto_merge` (`scripts/orchestrator_runner.py:_maybe_auto_merge`) skips with `merge_vetoed` before it ever reaches the blind or partial checks, so a `GITHUB_TOKEN`-backed run reuses the existing interlock instead of auto-merging on an unvalidated PR — and, since CCE-144, its `blind` classification separately freezes the watermark via `_should_advance_watermark`. Placement of the check is deliberate — after the `current_run` dict literal is assigned (an earlier `add_partial` call would create a stub the literal would then silently overwrite) and before the merge decision reads `state["current_run"]["partial"]`.

## Agent-authored create-page frontmatter fidelity

Step 3 (page-authoring fan-out) hands `page-author` a `frontmatter_template` for every batch. For a `create` in an `agent-authored` section (the generator behind this very page — see `scripts/frontmatter_contract.py`), that template carries the four lint-guarded fields: `description`, `source_files`, `last_reviewed`, `status`. Until CCE-119, the orchestrator wrote that template to disk only as a dry-run synth fallback and otherwise trusted the LLM's own write — `agents/page-author.md` told it to "draft" frontmatter from the template, not emit it verbatim, so a reworded description or a dropped `source_files` entry could pass through untouched.

CCE-119 closes that gap on the real production dispatch path. After `page-author` returns `ok` for a `create` batch, the orchestrator calls `_enforce_agent_frontmatter(target_path, agent_fields)` (`scripts/orchestrator_runner.py:_enforce_agent_frontmatter`, invoked at `scripts/orchestrator_runner.py`): it reads the page back, strips whatever `---` block is on disk, and re-prepends `frontmatter_contract.agent_authored_frontmatter_text(**agent_fields)` — the same `agent_fields` dict the orchestrator computed before dispatch, never anything the LLM wrote. The authored body is preserved untouched; only the frontmatter block is replaced. This is declare-then-discharge applied to a single subagent write: the page-author's frontmatter output is now advisory, not authoritative.

The reconciliation is scoped narrowly and deliberately:

- **Create-only.** An `edit` batch keeps the existing page's curated frontmatter as-is — reconciling here would clobber accumulated `source_files` or a since-promoted `status: published` that the orchestrator never tracked itself.
- **Agent-authored sections only.** Pages generated under the default authoring template (`status`/`sources`/`synthesized_into`) are untouched; `agent_fields` is `None` for those batches and the enforcement call is skipped.
- **Idempotent.** A page-author write that already matches `agent_fields` byte-for-byte is a no-op after reconciliation.

A second, related CCE-119 fix removed a duplicated constant. `_synthesize_agent_description` (the deterministic description used when the orchestrator itself has to author placeholder content, e.g. in dry-run) used to pad to a hardcoded minimum word count; it now calls `description_quality.resolve_min_words(config)` (`scripts/lint/description_quality.py:resolve_min_words`, resolved once at `scripts/orchestrator_runner.py` before the batch loop starts) so a host that raises `lint.tier1.description_quality.min_words` above the library default of 6 gets a synthesized description that still clears Tier-1 lint, instead of one silently pinned to the old constant.

Neither gap was a live failure before this fix — the content-validator's Tier-1 lint-drop path caught a bad frontmatter write and reverted it, same as any other `block`-severity failure — but both were CCE-117 residuals that left the production dispatch path relying on an LLM cooperating with an instruction rather than on a value the orchestrator itself controls. Tracker: CCE-119 (closes the two residual gaps identified after CCE-117 fixed the recurring "partial" nightly run caused by 20 blocked architecture pages).
