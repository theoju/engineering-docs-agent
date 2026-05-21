---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/14
synthesized_into: []
---

# CCE-17: pr-summarizer `page_hint` contract hardening

**Date:** 2026-05-21  
**Ticket:** CCE-17  
**PR:** [#14](https://github.com/theoju/engineering-docs-agent/pull/14)

## What happened

The 2026-05-21 full pipeline run produced ~30 `unsafe_page_path` rejections. The orchestrator's `agent_editable_paths` filter at `scripts/orchestrator_runner.py:521-547` blocked every one. No pages were written.

The root cause was not in the page-author subagent — it was in the pr-summarizer's output contract. The prompt gave no guidance on what `page_hint` values were valid, so the agent guessed. It emitted lens-prefix-doubled paths (e.g. `core/core/...`), source-tree paths, and out-of-sandbox creates. All were structurally invalid for the orchestrator's path filter. The post-first-run defects design reattributed the root cause here after Phase-1 evidence review.

## What changed

The fix is three-layered.

**Layer 1 — prompt rewrite.** The pr-summarizer agent prompt's §6 was rewritten with explicit per-action rules for `page_hint` formation. A new §Forbidden outputs section documents five categories of bad shape: lens-prefix-doubled paths, source-tree paths, out-of-sandbox creates, empty `doc_targets` on non-trivial changes, and prose-wrapped output.

**Layer 2 — schema enforcement.** `agents/schemas/pr_summarizer.schema.json` now enforces portable structural rules on every output: relative path, `.md` extension required, source-file extensions forbidden, `lens` constrained to `{core, superpowers}`, and `additionalProperties: false` throughout. The schema check runs inside the `dispatch_validated` → schema-check → `partial_reasons` chain, so a violation surfaces as a soft fail with a named reason rather than a silent rejection downstream.

**Layer 3 — regression fixtures and tests.** Ten fixtures captured from the failing run live under `tests/fixtures/cce17/`. Three new test modules cover: schema enforcement (does a bad `page_hint` fail schema?), replay behavior (do the ten regression fixtures pass the updated prompt?), and end-to-end soft-fail handling (does a schema violation produce the right `partial_reasons` entry?).

## Five forbidden `page_hint` shapes

| Category | Example bad value | Why it fails |
|---|---|---|
| Lens-prefix-doubled | `core/_agent-sandbox/core/foo.md` | `agent_editable_paths` glob doesn't match double-prefixed paths |
| Source-tree path | `scripts/orchestrator_runner.py` | Outside `docs/`; not a `.md` file |
| Out-of-sandbox create | `docs/core/new-feature.md` | Outside `docs/_agent-sandbox/`; `action: create` not allowed here |
| Empty `doc_targets` | `doc_targets: []` on a non-trivial PR | Suppresses page authoring when content clearly warrants it |
| Prose-wrapped output | JSON embedded in a markdown paragraph | Breaks the `dispatch_validated` schema check entirely |

## Test coverage added

- `tests/test_pr_summarizer_schema.py` — parametric tests over every forbidden shape; all must fail schema validation.
- `tests/test_pr_summarizer_replay.py` — replays the ten `cce17` fixtures against the updated prompt; asserts no `unsafe_page_path` in results.
- `tests/test_dispatch_soft_fail.py` — drives a schema-violating fixture through `dispatch_validated` and asserts the error surfaces in `partial_reasons` rather than raising.

## Out of scope

CCE-18 (Jira auth contract) and CCE-19 (source-collector window bound) are tracked on separate branches. Replay-test assertion granularity (per-violation vs. per-fixture) is deferred per a verify-agent caveat noted in the PR.
