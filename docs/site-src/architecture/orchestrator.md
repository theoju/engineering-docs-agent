---
description: 'Documents architecture orchestrator: the CCE-109/CCE-114 soft time-budget check bounds every expensive loop in the nightly run, and CCE-119 makes the orchestrator (not the page-author LLM) the authority over frontmatter on agent-authored create pages.'
source_files:
  - CHANGELOG.md
  - scripts/orchestrator_runner.py
  - agents/page-author.md
  - scripts/lint/description_quality.py
  - tests/orchestrator/test_enforce_agent_frontmatter.py
  - tests/orchestrator/test_agent_authored_create_frontmatter.py
last_reviewed: '2026-07-16'
status: draft
doc_kind: architecture
---

# Orchestrator

`run()` in `scripts/orchestrator_runner.py:1240` is the nightly pipeline entry point. It runs as a straight-line sequence of stages against one window of merged PRs (`last_successful_run.head_sha` to the current `HEAD`):

1. **source-collector** dispatch — pulls PRs (and Jira context, if configured) for the window.
2. **PR admission loop** — dispatches `pr-summarizer` once per PR, oldest-first (`scripts/orchestrator_runner.py:1393`).
3. **Page-authoring fan-out** — batches `doc_targets` by `(lens, page_hint)` and dispatches `page-author` once per batch (`scripts/orchestrator_runner.py:1467`).
4. **content-validator** — Tier-1 lint over every authored page; `block`-severity failures are reverted or unlinked.
5. **fact-checker warn layer** — one dispatch per authored page that cites a resolvable repo source (`scripts/orchestrator_runner.py:1664`).
6. Deterministic site generators, source-drift (M) and citation-drift (C1) checks, canonical-core drift (C2).
7. **gap-detector loop** — one dispatch per admitted PR (`scripts/orchestrator_runner.py:1783`).
8. What's New composition and `last_successful_run.head_sha` promotion.

Each stage that dispatches a subagent accumulates `partial_reasons` on failure via `add_partial`; a run with any non-`info_only` reason is marked `partial: true` and — per CCE-101 — never auto-merges.

## Soft time budget

The run computes one deadline up front and carries it through every loop:

```python
budget = resolve_time_budget(config, time_budget_seconds)
deadline = clock() + budget if budget > 0 else None
```

`resolve_time_budget` (`scripts/orchestrator_runner.py:339`) resolves precedence CLI override (including an explicit `0` for "unlimited") over `run.time_budget_seconds` in config over `DEFAULT_TIME_BUDGET_SECONDS` — 2700 seconds (45 minutes), deliberately below the nightly workflow's 60-minute hard kill (`scripts/orchestrator_runner.py:310`). A budget `<= 0` means no deadline at all: every per-loop check below is a no-op and the run authors, fact-checks, and gap-checks everything it admitted.

## Where the deadline is checked

CCE-109 introduced the deadline but only wired it into PR admission. CCE-114 closed the rest of the run — the page-author fan-out and the two advisory loops downstream of it — against the same clock. There are now four checkpoints, and they don't all behave the same way:

**PR admission** (`scripts/orchestrator_runner.py:1394`) — checked before summarizing PR `i`, guarded by `i > 0` so the run always admits at least one PR regardless of how slow it was to get there:

```python
if deadline is not None and i > 0 and clock() > deadline:
    ...
    prs = prs[:i]
    time_truncated = True
    break
```

A truncation here also decides whether the baseline is safe to advance — a deferred PR with no `merge_sha` can't be re-anchored by the next window, so `deferred_unanchored` blocks the advance in that case.

**Page-authoring fan-out** (`scripts/orchestrator_runner.py:1474`) — the same `i > 0` at-least-one-progress guarantee, but scoped to `per_target` batches rather than PRs:

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

**fact-checker warn layer** (`scripts/orchestrator_runner.py:1671`) and **gap-detector loop** (`scripts/orchestrator_runner.py:1786`) drop the `i > 0` guard entirely — they skip outright the moment the deadline has passed, with no minimum-progress guarantee:

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

Both loops are otherwise advisory — a fact-checker `contradiction` verdict adds a PR-body warning, not a block, and gap-detector findings are informational flags — so their other failure paths use `info_only=True` reasons that don't affect `partial`. The time-budget cut is the one exception: it is deliberately *not* `info_only`. Pages that were authored but never fact-checked, or PRs that were never gap-checked, must not slide into an auto-merge just because nothing else went wrong. Flipping `partial` here is what keeps the CCE-101 merge gate honest.

## Net effect

A time-budget cut anywhere in the run — admission, authoring, fact-checking, or gap-detection — sets `state["current_run"]["partial"] = True` with a `time_budget_exceeded: ...` reason describing exactly how much of that stage completed (`authored 1/3 page batches`, `fact-checked 0/3 pages`, `gap-checked 0/3 PRs`). Because authoring and the two advisory loops run in that fixed order, an authoring-loop cut also means the fact-checker and gap-detector loops never start — the pages that *were* authored still exist and are still committed, but the run stays partial and open for manual review rather than auto-merging. Setting `time_budget_seconds: 0` (or passing `--time-budget 0` at the CLI) disables all four checkpoints and lets a run author, fact-check, and gap-check every admitted PR regardless of wall-clock time — useful for a manual `--no-pr` bootstrap run where you're willing to wait, dangerous to leave on for the scheduled nightly.

## Agent-authored create-page frontmatter fidelity

Step 3 (page-authoring fan-out) hands `page-author` a `frontmatter_template` for every batch. For a `create` in an `agent-authored` section (the generator behind this very page — see `scripts/frontmatter_contract.py`), that template carries the four lint-guarded fields: `description`, `source_files`, `last_reviewed`, `status`. Until CCE-119, the orchestrator wrote that template to disk only as a dry-run synth fallback and otherwise trusted the LLM's own write — `agents/page-author.md` told it to "draft" frontmatter from the template, not emit it verbatim, so a reworded description or a dropped `source_files` entry could pass through untouched.

CCE-119 closes that gap on the real production dispatch path. After `page-author` returns `ok` for a `create` batch, the orchestrator calls `_enforce_agent_frontmatter(target_path, agent_fields)` (`scripts/orchestrator_runner.py:1015`, invoked at `scripts/orchestrator_runner.py:1653`): it reads the page back, strips whatever `---` block is on disk, and re-prepends `frontmatter_contract.agent_authored_frontmatter_text(**agent_fields)` — the same `agent_fields` dict the orchestrator computed before dispatch, never anything the LLM wrote. The authored body is preserved untouched; only the frontmatter block is replaced. This is declare-then-discharge applied to a single subagent write: the page-author's frontmatter output is now advisory, not authoritative.

The reconciliation is scoped narrowly and deliberately:

- **Create-only.** An `edit` batch keeps the existing page's curated frontmatter as-is — reconciling here would clobber accumulated `source_files` or a since-promoted `status: published` that the orchestrator never tracked itself.
- **Agent-authored sections only.** Pages generated under the default authoring template (`status`/`sources`/`synthesized_into`) are untouched; `agent_fields` is `None` for those batches and the enforcement call is skipped.
- **Idempotent.** A page-author write that already matches `agent_fields` byte-for-byte is a no-op after reconciliation.

A second, related CCE-119 fix removed a duplicated constant. `_synthesize_agent_description` (the deterministic description used when the orchestrator itself has to author placeholder content, e.g. in dry-run) used to pad to a hardcoded minimum word count; it now calls `description_quality.resolve_min_words(config)` (`scripts/lint/description_quality.py:51`, resolved once at `scripts/orchestrator_runner.py:1534` before the batch loop starts) so a host that raises `lint.tier1.description_quality.min_words` above the library default of 6 gets a synthesized description that still clears Tier-1 lint, instead of one silently pinned to the old constant.

Neither gap was a live failure before this fix — the content-validator's Tier-1 lint-drop path caught a bad frontmatter write and reverted it, same as any other `block`-severity failure — but both were CCE-117 residuals that left the production dispatch path relying on an LLM cooperating with an instruction rather than on a value the orchestrator itself controls. Tracker: CCE-119 (closes the two residual gaps identified after CCE-117 fixed the recurring "partial" nightly run caused by 20 blocked architecture pages).
