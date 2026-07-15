---
description: 'Documents architecture orchestrator: the CCE-119 reconciliation step now overwrites an agent-authored create''s written frontmatter with the orchestrator''s own deterministic agent_fields, and the description synthesizer resolves its min-words floor from host config instead of a hardcoded constant.'
source_files:
  - CHANGELOG.md
  - agents/page-author.md
  - scripts/lint/description_quality.py
  - scripts/orchestrator_runner.py
  - tests/orchestrator/test_agent_authored_create_frontmatter.py
  - tests/orchestrator/test_enforce_agent_frontmatter.py
last_reviewed: '2026-07-15'
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

## Agent-authored create-path frontmatter fidelity

For an `agent-authored` section (`fmc.section_generator_for(rel, config) == "agent-authored"`), a fresh page needs four lint-guarded frontmatter fields — `description`, `source_files`, `last_reviewed`, `status` — or Tier-1 lint drops it. The page-authoring fan-out (`scripts/orchestrator_runner.py:1535`) computes those fields itself, before dispatch, as `agent_fields`:

```python
agent_fields = fmc.agent_authored_frontmatter_dict(
    description=_synthesize_agent_description(
        batch_summaries, hint=hint, min_words=_desc_min_words
    ),
    source_files=sorted(grounding),
    last_reviewed=now[:10],
)
```

`_synthesize_agent_description` (`scripts/orchestrator_runner.py:977`) is deterministic — it never calls out to a model. It pulls the first summary's `what_changed`/`why` text into a one-line description, falling back to a generic "Reference documentation for `<topic>`" sentence when no usable text is present, and pads with neutral filler words until the description clears `min_words`.

**`min_words` is resolved from config, not hardcoded (CCE-119 Item B).** Before CCE-119, the synthesizer padded to a hardcoded `_DESC_MIN_WORDS = 6`, silently mirroring `description_quality._DEFAULTS["min_words"]`. A host that raised `lint.tier1.description_quality.min_words` above 6 got its agent-authored creates dropped anyway, because the synthesizer never saw the override. `description_quality.resolve_min_words(config)` is now the single source of truth for that floor — a thin wrapper over the same `_resolve_config(config)` the lint rule itself uses — and the fan-out calls it once per run (`_desc_min_words = _description_quality.resolve_min_words(config)`, `scripts/orchestrator_runner.py:1534`) before looping over batches.

**The written page's frontmatter is reconciled after dispatch, not trusted from the LLM (CCE-119 Item A).** `agent_fields` is only ever handed to `page-author` as a `frontmatter_template` — on the real production dispatch path, the page-author subagent (an LLM) is the one that actually writes the file to disk, and nothing stopped it from rewording `description` below the floor, matching it to the H1, or dropping `source_files`/`last_reviewed` outright. That gap existed only on the production path: the dry-run stand-in (`scripts/orchestrator_runner.py:1636`, guarded `if dry_run_dir and not target_path.exists()`) always wrote the orchestrator's own `agent_fields` directly, so the two paths diverged on *who* writes the frontmatter.

CCE-119 closes the gap with post-dispatch reconciliation. After `out.get("ok")` is true and `agent_fields is not None`, the orchestrator calls:

```python
if agent_fields is not None and target_path.exists():
    _enforce_agent_frontmatter(target_path, agent_fields)
```

`_enforce_agent_frontmatter` (`scripts/orchestrator_runner.py:1015`) reads whatever the subagent (or the dry-run synth) wrote, strips the leading `---`-fenced block using the same `split("---", 2)` convention as `archive_indexes.parse_frontmatter`, and re-prepends `fmc.agent_authored_frontmatter_text(**agent_fields)` in front of the preserved body. It's idempotent — running it twice on an already-conforming page is a no-op — and it never raises on a well-formed file. Both paths now converge on the same deterministic writer: production corrects whatever the LLM wrote; dry-run reconciles a write that already matched.

This is create-only and scoped narrowly by design. An `edit` skips reconciliation entirely — an existing page's curated frontmatter (accumulated `source_files`, a promoted `status`) is never clobbered by a later edit batch. A default-section (non-agent-authored) create leaves `agent_fields` as `None`, so the guard skips it too.

**The page-author contract is belt-and-suspenders, not the enforcement mechanism.** `agents/page-author.md` now instructs the subagent to emit `description`, `source_files`, and `last_reviewed` *verbatim* from `frontmatter_template` for an agent-authored create — no rewording, shortening, or dropping. That instruction alone was CCE-117's original (insufficient) guarantee; CCE-119 stopped relying on subagent cooperation for it and made the orchestrator's own reconciliation the authoritative source, consistent with CLAUDE.md's declare-then-discharge principle: trust nothing the subagent authors about its own work unless it's checked against external state afterward.

One implementation note worth flagging for anyone touching `agent_fields`: it carries exactly the four agent-authored keys and nothing else. `doc_kind` — needed for routing but never read back from a page — is attached to a *copy* of `agent_fields` (`fm_template = dict(agent_fields)`) before dispatch, so `_enforce_agent_frontmatter`'s `agent_authored_frontmatter_text(**agent_fields)` call never receives an unexpected `doc_kind` kwarg.
