---
description: "Documents architecture orchestrator: the CCE-109/CCE-114 soft time-budget check bounds every expensive loop in the nightly run, CCE-119 makes the orchestrator (not the page-author LLM) the authority over frontmatter on agent-authored create pages, and CCE-127 degrades a failed GitHub App-token mint to a blocking partial reason instead of a dead job."
source_files:
  - CHANGELOG.md
  - scripts/orchestrator_runner.py
  - agents/page-author.md
  - scripts/lint/description_quality.py
  - templates/workflow-run.yml
  - tests/orchestrator/test_enforce_agent_frontmatter.py
  - tests/orchestrator/test_agent_authored_create_frontmatter.py
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

CCE-109 introduced the deadline but only wired it into PR admission. CCE-114 closed the rest of the run — the page-author fan-out and the two advisory loops downstream of it — against the same clock. There are now four checkpoints, and they don't all behave the same way:

**PR admission** (`scripts/orchestrator_runner.py`) — checked before summarizing PR `i`, guarded by `i > 0` so the run always admits at least one PR regardless of how slow it was to get there:

```python
if deadline is not None and i > 0 and clock() > deadline:
    ...
    prs = prs[:i]
    time_truncated = True
    break
```

A truncation here also decides whether the baseline is safe to advance — a deferred PR with no `merge_sha` can't be re-anchored by the next window, so `deferred_unanchored` blocks the advance in that case.

**Page-authoring fan-out** (`scripts/orchestrator_runner.py`) — the same `i > 0` at-least-one-progress guarantee, but scoped to `per_target` batches rather than PRs:

```python
if deadline is not None and i > 0 and clock() > deadline:
    add_partial(
        state,
        f"time_budget_exceeded: authored {i}/{len(per_target)} "
        f"page batches (budget {budget}s); deferring the rest",
    )
    break
```

This is the checkpoint CCE-109 was missing. Authoring is the single most expensive phase — one Claude dispatch per `(lens, page_hint)` batch — and admission alone completes too early in the run to bound it. Before CCE-114, a large window could pass the admission check in minutes and then author straight through the deadline into the workflow's hard kill; one observed run (27263616736) started roughly 20 page-author dispatches after the deadline had already passed, and — per `CHANGELOG.md` — six consecutive scheduled nightlies died this way with all work discarded.

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

A time-budget cut anywhere in the run — admission, authoring, fact-checking, or gap-detection — sets `state["current_run"]["partial"] = True` with a `time_budget_exceeded: ...` reason describing exactly how much of that stage completed (`authored 1/3 page batches`, `fact-checked 0/3 pages`, `gap-checked 0/3 PRs`). Because authoring and the two advisory loops run in that fixed order, an authoring-loop cut also means the fact-checker and gap-detector loops never start — the pages that _were_ authored still exist and are still committed, but the run stays partial and open for manual review rather than auto-merging. Setting `time_budget_seconds: 0` (or passing `--time-budget 0` at the CLI) disables all four checkpoints and lets a run author, fact-check, and gap-check every admitted PR regardless of wall-clock time — useful for a manual `--no-pr` bootstrap run where you're willing to wait, dangerous to leave on for the scheduled nightly.

## Agent-authored create-page frontmatter fidelity

Step 3 (page-authoring fan-out) hands `page-author` a `frontmatter_template` for every batch. For a `create` in an `agent-authored` section (the generator behind this very page — see `scripts/frontmatter_contract.py`), that template carries the four lint-guarded fields: `description`, `source_files`, `last_reviewed`, `status`. Until CCE-119, the orchestrator wrote that template to disk only as a dry-run synth fallback and otherwise trusted the LLM's own write — `agents/page-author.md` told it to "draft" frontmatter from the template, not emit it verbatim, so a reworded description or a dropped `source_files` entry could pass through untouched.

CCE-119 closes that gap on the real production dispatch path. After `page-author` returns `ok` for a `create` batch, the orchestrator calls `_enforce_agent_frontmatter(target_path, agent_fields)` (`scripts/orchestrator_runner.py:_enforce_agent_frontmatter`, invoked at `scripts/orchestrator_runner.py`): it reads the page back, strips whatever `---` block is on disk, and re-prepends `frontmatter_contract.agent_authored_frontmatter_text(**agent_fields)` — the same `agent_fields` dict the orchestrator computed before dispatch, never anything the LLM wrote. The authored body is preserved untouched; only the frontmatter block is replaced. This is declare-then-discharge applied to a single subagent write: the page-author's frontmatter output is now advisory, not authoritative.

The reconciliation is scoped narrowly and deliberately:

- **Create-only.** An `edit` batch keeps the existing page's curated frontmatter as-is — reconciling here would clobber accumulated `source_files` or a since-promoted `status: published` that the orchestrator never tracked itself.
- **Agent-authored sections only.** Pages generated under the default authoring template (`status`/`sources`/`synthesized_into`) are untouched; `agent_fields` is `None` for those batches and the enforcement call is skipped.
- **Idempotent.** A page-author write that already matches `agent_fields` byte-for-byte is a no-op after reconciliation.

A second, related CCE-119 fix removed a duplicated constant. `_synthesize_agent_description` (the deterministic description used when the orchestrator itself has to author placeholder content, e.g. in dry-run) used to pad to a hardcoded minimum word count; it now calls `description_quality.resolve_min_words(config)` (`scripts/lint/description_quality.py:resolve_min_words`, resolved once at `scripts/orchestrator_runner.py` before the batch loop starts) so a host that raises `lint.tier1.description_quality.min_words` above the library default of 6 gets a synthesized description that still clears Tier-1 lint, instead of one silently pinned to the old constant.

Neither gap was a live failure before this fix — the content-validator's Tier-1 lint-drop path caught a bad frontmatter write and reverted it, same as any other `block`-severity failure — but both were CCE-117 residuals that left the production dispatch path relying on an LLM cooperating with an instruction rather than on a value the orchestrator itself controls. Tracker: CCE-119 (closes the two residual gaps identified after CCE-117 fixed the recurring "partial" nightly run caused by 20 blocked architecture pages).

## App-token degrade-to-partial (CCE-127)

A run's `run()` needs a GitHub token before it does anything else: pushing the `docs-agent/YYYY-MM-DD` branch, opening or appending to the PR, and — if a GitHub App is configured — letting that PR fire the host's own CI. `templates/workflow-run.yml`'s "Generate GitHub App installation token" step mints that token via `actions/create-github-app-token@v3`, and it can fail independently of whether an App is configured at all: `if: vars.DOCS_AGENT_APP_CLIENT_ID != ''` makes the step **skip** on a bare host with no App, but on a host that _has_ configured one, the mint call itself can still fail — the App was uninstalled, transferred to another account, or the repository was dropped from its installation's selection.

Before CCE-127, that failure killed the job outright, and it killed it silently. The step had no `continue-on-error`, so a failed mint aborted the workflow before the checkout step's `token: ${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}` fallback was ever evaluated — GitHub only resolves that expression for a step that reports `skipped`, not `failure`. The fallback line had existed since CCE-80, but on the failure path it was dead code: no run, no partial PR, no notification. The originating incident was an org transfer that deleted the App's installation on 2026-07-23; because neither host repo had `SLACK_WEBHOOK_URL` wired at the time, the silence went unnoticed for 15 consecutive nightlies (~30 runs across two repos) until 2026-08-07.

The fix has two parts, and both are required — either alone is inert:

1. **`continue-on-error: true`** on the App-token step (`templates/workflow-run.yml`) makes the step's `conclusion` report `success` regardless of what actually happened, so the job proceeds past it. This is what makes the checkout step's `||` fallback reachable on the failure path for the first time.
2. **Export `outcome`, never `conclusion`.** Because `continue-on-error` rewrites `conclusion` to `success`, only `steps.app-token.outcome` still carries the true `failure` value. The "Run docs-agent" step exports it at **step** env scope as `DOCS_AGENT_APP_TOKEN_STATUS: ${{ steps.app-token.outcome }}` — job-env can't reference `steps.*` at all, so this has to live on the step that consumes it.

`run()` reads that variable early, immediately after the fresh `current_run` dict is built and before any dispatch:

```python
if os.environ.get("DOCS_AGENT_APP_TOKEN_STATUS", "") == "failure":
    _record_dispatch_reasons(
        state,
        ["app_token_unavailable: GitHub App installation token could not "
         "be minted; run degraded to GITHUB_TOKEN, so host CI will not "
         "fire on this PR. Verify the App is installed on this repo."],
        ok=False,
    )
```

That placement is load-bearing, not incidental: `add_partial` (called by `_record_dispatch_reasons`, `ok=False`) would silently create a stub `current_run` if it ran before the dict literal above it — the literal would then overwrite the stub and swallow the reason. Only the literal string `"failure"` trips this. `"skipped"` (the documented bare-host path — no `DOCS_AGENT_APP_CLIENT_ID` configured) and `"success"` and an unset variable all stay silent; only a **configured-but-broken** App degrades the run.

Flipping `partial` here reuses the existing CCE-101 auto-merge interlock in `_maybe_auto_merge` (`if partial: return skip("partial_run")`) — CCE-127 adds no new gate code. That reuse is the actual point: a PR built on the `GITHUB_TOKEN` fallback never fires the host's `on: push`/`on: pull_request` CI, so if nothing else in the run failed, zero registered checks would otherwise look indistinguishable from "everything passed" and the PR would auto-merge undocumented, unvalidated changes.

Two more distinctions worth carrying into any future App-token debugging:

- **A 404 on the installation lookup is not the same failure as a 401.** A 404 on `/repos/{owner}/{repo}/installation` means the JWT itself authenticated fine but no installation currently covers the repo — the App was uninstalled, the org transferred (the actual 2026-07-23 cause), or repo-selection narrowed. The fix is **re-install**; the App ID and private key need no change. A 401 means the App or its key is actually bad, and the fix is to rotate the key.
- **CI does not lint `templates/` by default.** `.github/workflows/actionlint.yml` runs bare `actionlint -color`, which only searches `.github/workflows/`, so a template-only change needs an explicit `actionlint templates/workflow-run.yml` pass. This gap is plausibly how the plugin's own template first drifted from its dogfood workflow.

CCE-127 also closed that drift directly: the dogfood `.github/workflows/docs-agent-nightly.yml` now carries the same `if:` guard on the App-token step, both `||` fallbacks, and the `SLACK_WEBHOOK_URL` job-env the template has — removing three `_TEMPLATE_ONLY_DIVERGENCES` entries in `tests/templates/test_workflow_run_parity.py` that had justified the dogfood's narrower behavior as "the dogfood requires the App" / "the dogfood uses only the App token." Both justifications were true and both were irrelevant: the step fails on runtime *state* (an App losing its installation), not on the operator's *intent* to always use the App. Recording a divergence as accepted risk is not the same as the risk staying acceptable, and nothing re-examines that list automatically — audit it whenever a safety property lands on only one side of the template/dogfood boundary.

A death alarm for failures that happen *before* `actions/checkout` runs — where the tree isn't checked out yet and `if: failure()` steps can't assume it is — is tracked separately as CCE-128 and is explicitly out of scope here.
