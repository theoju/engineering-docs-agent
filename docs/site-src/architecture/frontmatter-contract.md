---
description: 'Documents architecture frontmatter contract: Fixed the nightly incremental docs-authoring path so it builds generator-aware frontmatter for agent-authored sections instead of always using the default template'
source_files:
  - CHANGELOG.md
  - docs/superpowers/plans/2026-06-27-cce117-agent-authored-create-frontmatter.md
  - docs/superpowers/specs/2026-06-27-cce117-agent-authored-create-frontmatter-design.md
  - scripts/frontmatter_contract.py
  - scripts/orchestrator_runner.py
  - tests/orchestrator/test_agent_authored_create_frontmatter.py
  - tests/orchestrator/test_synthesize_description.py
last_reviewed: '2026-07-04'
status: draft
---

# Frontmatter contract

Every page the docs-agent authors needs frontmatter, but not the same frontmatter. Which fields are required depends on the **generator** of the site section the page lives in. `scripts/frontmatter_contract.py` is the single source of truth for that mapping, and it is deliberately small: two tuples and a handful of pure functions, no YAML library dependency, never raises on bad input.

## Two field sets

```python
DEFAULT_REQUIRED = ("status", "sources", "synthesized_into")
AGENT_AUTHORED_REQUIRED = ("description", "source_files", "last_reviewed", "status")
```

`DEFAULT_REQUIRED` covers changelog, archive, API, and any page with no configured `site:` section or no generator — the historical set. `AGENT_AUTHORED_REQUIRED` is for `agent-authored` sections (Capability C2 core pages, like this one) and adds citation-bearing fields: `description`, `source_files`, `last_reviewed`.

`section_generator_for(page, config)` decides which set applies. It matches the section whose `docs_dir/path` is a path-segment prefix of the page, with longest-match-wins so a nested section beats its parent. It resolves absolute/repo-relative paths against the embedded `docs_dir` segment first (Frame 1); only when `docs_dir` is truly absent from the page does it fall back to matching the bare section path (Frame 2) — a deliberate precision-for-robustness tradeoff that's sound for the orchestrator's always-absolute-path frame, but worth knowing before you feed it an arbitrary relative path from outside the docs tree. No `site:` block, no `docs_dir`, or no match all return `None`, which yields the default field set.

## The CCE-117 gap: the create path ignored generator

The generator-aware machinery above existed for a while, but it was wired only into the **bootstrap** path. The incremental nightly create path hardcoded `fmc.default_frontmatter_dict(...)` unconditionally — it never called `section_generator_for` to check whether the section it was writing into actually needed the agent-authored set.

The result: the `architecture/` section is configured `generator: agent-authored`, so every new page the nightly run created there was missing `description`, `source_files`, and `last_reviewed`. Tier-1 lint (`frontmatter_schema` + `description_quality`) blocked them every night — the 2026-06-26 run alone blocked 20 pages this way — and the run was marked `(partial)` on repeat, even though nothing was actually broken about the run itself (CCE-114's time-budget fix was healthy; this was a separate content-path defect). The blocked pages never landed on `main`, so the agent re-authored the same doomed pages the next night, forever.

## The fix: synthesize the description deterministically

The chosen fix (CCE-117) makes the create path branch on `section_generator_for(rel, config)`, mirroring what the bootstrap path already did:

```python
if action == "create" and fmc.section_generator_for(rel, config) == "agent-authored":
    agent_fields = fmc.agent_authored_frontmatter_dict(
        description=_synthesize_agent_description(batch_summaries, hint=hint),
        source_files=sorted(grounding),
        last_reviewed=run_date,
        status="draft",
    )
```

`grounding` here is `_pr_changed_files(batch_prs)` — the same CCE-110 factual-accuracy grounding already computed for the page-author's `source_paths` input, reused rather than recomputed. This ordering matters: grounding is now computed before the frontmatter template is built, specifically so an agent-authored create can cite the same files in `source_files` that the author was grounded against.

The interesting design decision is `description`. `description_quality` lint is purely mechanical — it checks `min_words: 6`, that the description doesn't equal the page's H1, and that it doesn't end in a trailing colon. Nothing about prose quality. Given that, the team picked a **deterministic, orchestrator-synthesized** description over letting the page-author LLM write one: a mechanical lint check should not depend on an LLM getting wording right. `_synthesize_agent_description(summaries, *, hint)` builds a one-line description from the batch's PR summaries — preferring the first non-empty `what_changed` over `why`, composing `"Covers <topic>: <what_changed>."`-style prose — and pads deterministically from the hint when the summary text is too short to clear the 6-word floor. Same inputs always yield the same output; malformed summary entries (non-dicts, `None` values) are skipped rather than raising. Default-section pages are entirely unaffected — the branch only fires when the generator match is exactly `agent-authored`.

A latent YAML bug was fixed in the same change: `agent_authored_frontmatter_text` now single-quotes the `description` field (with the standard YAML single-quote escape of doubling embedded `'`), so a synthesized sentence containing a colon — which is common, since the synthesis format itself uses `Covers <topic>: <detail>` — doesn't break the frontmatter block.

## Frontmatter values for an agent-authored create

| field           | value                                                        | source                                                        |
| --------------- | ------------------------------------------------------------- | -------------------------------------------------------------- |
| `description`   | summary-derived sentence (≥6 words, ≠ H1, no trailing `:`)    | `_synthesize_agent_description`                                 |
| `source_files`  | `sorted(grounding)`                                            | `_pr_changed_files(batch_prs)`, computed before the template     |
| `last_reviewed` | run date                                                       | the already-bound `now[:10]`                                    |
| `status`        | `draft`                                                        | constant, matches the bootstrap path                             |
| `doc_kind`      | preserved when present                                         | `doc_kind_by_target`                                             |

## Edits keep the existing frontmatter

The branch is create-only. An `edit` action on an existing page never touches its frontmatter here — whatever fields the page already carries stay as they are. This mirrors the general rule elsewhere in the pipeline: incremental edits integrate new content into existing structure rather than re-deriving metadata from scratch.

## Still open

As of this fix, AC4 from the design spec is a post-merge observation, not yet confirmed: the next nightly run needs to verify that the previously-blocked architecture pages — `orchestrator.md`, `meta-orchestrator.md`, and roughly 18 others — now author without `lint_block`. Two follow-ups are deferred from review: tightening the page-author contract so these deterministic frontmatter fields survive verbatim through authoring, and making the synthesis helper's minimum-word floor read from a host `min_words` override instead of a hardcoded constant.
