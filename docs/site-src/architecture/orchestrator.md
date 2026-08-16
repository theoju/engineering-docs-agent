---
description: "Documents architecture orchestrator: the CCE-109/CCE-114 soft time-budget check bounds every expensive loop in the nightly run, CCE-119 makes the orchestrator (not the page-author LLM) the authority over frontmatter on agent-authored create pages, CCE-125 makes a gap-detector 'couldn't judge' verdict an info-only advisory outcome, and CCE-127 degrades a failed GitHub App token mint to a blocking partial reason instead of killing the job."
source_files:
  - CHANGELOG.md
  - scripts/orchestrator_runner.py
  - agents/page-author.md
  - agents/gap-detector.md
  - agents/schemas/gap_detector.schema.json
  - scripts/lint/description_quality.py
  - templates/workflow-run.yml
  - tests/orchestrator/test_enforce_agent_frontmatter.py
  - tests/orchestrator/test_agent_authored_create_frontmatter.py
  - tests/orchestrator/test_gap_detector_unjudged.py
  - tests/templates/test_workflow_run_parity.py
last_reviewed: "2026-08-08"
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

## Soft time budget

The run computes one deadline up front and carries it through every loop:

```python
budget = resolve_time_budget(config, time_budget_seconds)
deadline = clock() + budget if budget > 0 else None
```

`resolve_time_budget` (`scripts/orchestrator_runner.py:resolve_time_budget`) resolves precedence CLI override (including an explicit `0` for "unlimited") over `run.time_budget_seconds` in config over `DEFAULT_TIME_BUDGET_SECONDS` — 2700 seconds (45 minutes), deliberately below the nightly workflow's 60-minute hard kill (`scripts/orchestrator_runner.py:DEFAULT_TIME_BUDGET_SECONDS`). A budget `<= 0` means no deadline at all: every per-loop check below is a no-op and the run authors, fact-checks, and gap-checks everything it admitted.

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

Deferring to a boundary is unbounded on its own, so `authoring_hard_cap` (`scripts/orchestrator_runner.py:resolve_authoring_hard_cap`) bounds the overrun: `run.authoring_hard_cap_seconds`, else `budget * 1.15`, then clamped down against `GITHUB_APP_TOKEN_TTL_SECONDS` minus the merge poll this host will actually run minus a 120s post-run tail. An explicit value at or below the budget is a config error, not a clamp — equal collapses the hard deadline onto the soft one and restores the mid-group cut. When the TTL ceiling itself lands at or below the budget the cap is held at the budget and an advisory `authoring_hard_cap_squeezed` reason is recorded; behaviour then degrades to the pre-CCE-152 cut, which is never worse and never silent.

That gives the checkpoint **two distinct reasons**, sharing a prefix and diverging at the parenthetical and the trailing clause:

```text
time_budget_exceeded: authored 2/5 page batches (budget 2100s); deferring the rest
time_budget_exceeded: authored 2/5 page batches (hard cap 2415s over budget 2100s); cut inside PR #646, whose pages are now incomplete, so the baseline cannot advance to it
```

The first is an ordinary deferral: the group behind the cut is complete and the run advances. The second is the bounded forced cut: the group is split, the run earns no advance, and the wording says so instead of reading like a deferral. Past the hard cap **at** a boundary is still the first case — the cap only changes where a cut may land, never what a clean boundary means.

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

Only the literal `"failure"` degrades the run — `"skipped"` is the documented bare-host path (no `DOCS_AGENT_APP_CLIENT_ID` configured), and `"success"` or an unset variable both stay silent. `ok=False` routes the reason through the ordinary blocking `_record_dispatch_reasons` path, so it sets `partial: true` the same way a failed source-collector or page-author dispatch would. No new gate code is needed: `_maybe_auto_merge` (`scripts/orchestrator_runner.py:_maybe_auto_merge`) already skips with `partial_run` whenever `partial` is true, so a `GITHUB_TOKEN`-backed run reuses the existing interlock instead of auto-merging on an unvalidated PR. Placement of the check is deliberate — after the `current_run` dict literal is assigned (an earlier `add_partial` call would create a stub the literal would then silently overwrite) and before the merge decision reads `state["current_run"]["partial"]`.

## Agent-authored create-page frontmatter fidelity

Step 3 (page-authoring fan-out) hands `page-author` a `frontmatter_template` for every batch. For a `create` in an `agent-authored` section (the generator behind this very page — see `scripts/frontmatter_contract.py`), that template carries the four lint-guarded fields: `description`, `source_files`, `last_reviewed`, `status`. Until CCE-119, the orchestrator wrote that template to disk only as a dry-run synth fallback and otherwise trusted the LLM's own write — `agents/page-author.md` told it to "draft" frontmatter from the template, not emit it verbatim, so a reworded description or a dropped `source_files` entry could pass through untouched.

CCE-119 closes that gap on the real production dispatch path. After `page-author` returns `ok` for a `create` batch, the orchestrator calls `_enforce_agent_frontmatter(target_path, agent_fields)` (`scripts/orchestrator_runner.py:_enforce_agent_frontmatter`, invoked at `scripts/orchestrator_runner.py`): it reads the page back, strips whatever `---` block is on disk, and re-prepends `frontmatter_contract.agent_authored_frontmatter_text(**agent_fields)` — the same `agent_fields` dict the orchestrator computed before dispatch, never anything the LLM wrote. The authored body is preserved untouched; only the frontmatter block is replaced. This is declare-then-discharge applied to a single subagent write: the page-author's frontmatter output is now advisory, not authoritative.

The reconciliation is scoped narrowly and deliberately:

- **Create-only.** An `edit` batch keeps the existing page's curated frontmatter as-is — reconciling here would clobber accumulated `source_files` or a since-promoted `status: published` that the orchestrator never tracked itself.
- **Agent-authored sections only.** Pages generated under the default authoring template (`status`/`sources`/`synthesized_into`) are untouched; `agent_fields` is `None` for those batches and the enforcement call is skipped.
- **Idempotent.** A page-author write that already matches `agent_fields` byte-for-byte is a no-op after reconciliation.

A second, related CCE-119 fix removed a duplicated constant. `_synthesize_agent_description` (the deterministic description used when the orchestrator itself has to author placeholder content, e.g. in dry-run) used to pad to a hardcoded minimum word count; it now calls `description_quality.resolve_min_words(config)` (`scripts/lint/description_quality.py:resolve_min_words`, resolved once at `scripts/orchestrator_runner.py` before the batch loop starts) so a host that raises `lint.tier1.description_quality.min_words` above the library default of 6 gets a synthesized description that still clears Tier-1 lint, instead of one silently pinned to the old constant.

Neither gap was a live failure before this fix — the content-validator's Tier-1 lint-drop path caught a bad frontmatter write and reverted it, same as any other `block`-severity failure — but both were CCE-117 residuals that left the production dispatch path relying on an LLM cooperating with an instruction rather than on a value the orchestrator itself controls. Tracker: CCE-119 (closes the two residual gaps identified after CCE-117 fixed the recurring "partial" nightly run caused by 20 blocked architecture pages).
