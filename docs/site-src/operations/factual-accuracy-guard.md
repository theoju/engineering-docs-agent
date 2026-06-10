---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/131
synthesized_into: []
---

# Factual-Accuracy Guard

The nightly pipeline historically validated structure — frontmatter contract, Tier-1 lint, strict site build — but never checked whether a page's prose was true. CCE-110 documented the failure mode: the page-author wrote conventional-but-wrong descriptions of deliberately counterintuitive code and cited tests that do not exist. The factual-accuracy guard closes that gap with three independent layers.

## Layer 1 — grounding the author (advisory)

`page-author` receives a `source_paths` input: the code files touched by the PRs it is documenting. Its contract requires reading the relevant sources before composing — claims about behavior, invariants, defaults, or tests must come from what it read, not from convention. The agent returns an advisory `evidence.files_read` list, recorded for run forensics but never gated: a confabulating author would confabulate its evidence too, so verification belongs to the external layers below.

## Layer 2 — citation existence (deterministic, blocks)

`citation_exists` is a Tier-1 lint rule in `scripts/lint/citation_exists.py`. It scans the inline code spans in a page's prose — fenced code blocks are excluded, since fenced examples are legitimately hypothetical — and verifies two citation classes against the host repo:

- **Repo paths** (slash-and-extension tokens such as `scripts/orchestrator_runner.py`, optional `:line` suffix) must exist in `git ls-files` or on disk.
- **Test identifiers** (matching `test_[a-z0-9_]+`) must be defined or called somewhere in tracked files, checked via `git grep`.

Tokens carrying placeholder markers (`<...>`, `*`, `{}`, `YYYY`, `...`), URLs, and environment references (`~/`, `$VAR`) are skipped. A failure blocks the page through the standard Tier-1 path — the page is reverted, and the reason lands in `partial_reasons` as `lint_block: <page> citation_exists: cites nonexistent test '<name>'`.

The rule ships in `TIER1_DEFAULT`, so any host with `lint.tier1: default` gets it without opt-in. On a host where the config does not live inside a git repo, the rule passes trivially — it cannot verify, so it never blocks.

Regression tests in `tests/lint/test_citation_exists.py` pin the rule against condensed replicas of the two pages from the original incident; both fail on their fabricated test names.

## Layer 3 — the fact-checker subagent (semantic, warns)

After content validation, the orchestrator dispatches the `fact-checker` subagent once per surviving page that cites at least one existing repo source file. The agent reads the page and its cited sources and flags prose claims the source contradicts. Its prompt encodes the lesson from the incident: counterintuitive code wins over convention — if the source does something surprising, the page must say the surprising thing.

The fact-checker is deliberately warn-only:

- `contradiction` findings render as a **Factual-accuracy warnings** section in the docs PR body and in the notifier digest.
- A page is never dropped and the run is never marked partial by this layer.
- A failed or unparseable dispatch records `fact_checker_unavailable: <page>` as an info-only reason.
- Pages that cite nothing skip the dispatch entirely, which also bounds cost.

The asymmetry between layers 2 and 3 is the design: only the judge that cannot be wrong gets kill-power. A nonexistent test name is never a false positive, so it blocks; a language model's reading of code can be wrong, so it warns.

## Operator workflow

When a nightly PR carries a Factual-accuracy warnings section, read the listed claims against the named source files before merging. A warning is a review prompt, not a verdict. When a page is dropped by `citation_exists`, the partial reason names the offending token — fix the page content (or the citation) and the next run re-authors it.

## Testing

```bash
python3 -m pytest tests/lint/test_citation_exists.py tests/orchestrator/test_fact_checker.py -v
```

The orchestrator-side tests cover dispatch gating (cited pages only), warn-only semantics, PR-body and digest threading, and degradation (missing fixture, undecodable page, no citations).
