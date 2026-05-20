---
title: CCE-4 — Schema enforcement + agent prompt sharpening
status: approved
created: 2026-05-20
owner: theo
jira: CCE-4
related:
  - CCE-1 (v0.1.0 + v0.1.1 baseline)
  - CCE-2 (dispatch CLI surface)
  - CCE-3 (dispatch production wiring: framing, cwd, plugin-dir, allowedTools)
  - CCE-5 (partial_reasons carry-forward hygiene)
  - CCE-6 (--live pytest gate)
---

# CCE-4 — Schema enforcement + agent prompt sharpening

## 1. Goal

After CCE-2 fixed the CLI surface and CCE-3 completed the production wiring, the first live Mode B smoke run against ADIS exposed a silent-no-op failure mode: the source-collector agent returned syntactically valid JSON in a fabricated shape (`{status, modifications, summary, head_sha, branches_scanned, events_processed, verification}` instead of the contract's `{prs, jira_issues}`). The orchestrator's `sources.get("prs", [])` fallback absorbed it as if there were no PRs to process. Exit 0, no diagnostic signal, no work done.

Goal: make this failure visible by wiring `validate_and_parse` at the dispatch boundary, and reduce its frequency by sharpening the seven agent system prompts to embed canonical JSON Schemas inline.

## 2. Non-goals

- Hard fail on schema invalid. Keep the soft-fail contract from v0.1.1 ("Mixed validation: hard-fail config/state, soft-fail subagent output").
- Retry on schema invalid (deferred — would double API cost; revisit if frequency proves too high).
- Switching call sites from `dict.get(...)` to typed `SourceCollectorResult.prs` access (deferred to a future refactor; out of scope here).
- Per-agent custom retry budgets / circuit breakers.
- A `--live` pytest gate (that's CCE-6; this spec pre-conditions for it).
- Modifying `agents/schemas/*.schema.json` to be more or less strict (the existing schemas are the source of truth).

## 3. Audience and access

This is internal infrastructure for the orchestrator. No new user-facing flags, configuration, or runtime surfaces. Operators see the diagnostic dividend in the existing `notifier` digest and `state.json` `partial_reasons`.

## 4. Architecture

```
                                  orchestrator_runner.run()
                                          │
                                          ▼
                                 dispatch_subagent(...)
                                          │
                              ┌──── parses JSON ────┐
                              ▼                     ▼
                          (raw dict)           (None on parse failure)
                              │                     │
                              ▼                     │
                     validate_and_parse(...)        │
                       (at dispatch boundary)       │
                              │                     │
              ┌───────────────┼──────────────┐      │
              ▼               ▼              ▼      ▼
          (dataclass)   (schema_invalid)  (schema_missing)
              │               │              │      │
              └───────────────┴──────────────┴──────┘
                              │
                              ▼
                   caller sees (dict | None) + (reasons list)
```

Two surfaces, one PR:

1. **`scripts/orchestrator_runner.py`** gains a thin wrapper `dispatch_validated(name, inputs, *, dry_run_dir, cwd) -> tuple[dict | None, list[str]]` that composes `dispatch_subagent` with `validate_and_parse`. All six call sites in the file plus three in `scripts/verify_runner.py` are updated to consume the tuple and thread reasons into `partial_reasons`.

2. **`agents/*.md` (seven files)** each gain an `## Output schema (canonical)` section containing the contents of the corresponding `agents/schemas/<name>.schema.json` (verbatim is simplest; the lint allows any JSON-equivalent reformatting) plus a one-line "Return ONLY a JSON object that validates against this schema" instruction. The pre-existing prose `## Output contract` section stays but gains a pointer to the canonical schema below.

A new lint test asserts the `.md` schema block is JSON-equivalent to the `.json` file (compared after `json.loads()` on both sides).

## 5. Components

### 5.1 `dispatch_validated` wrapper

Add to `scripts/orchestrator_runner.py` just below `dispatch_subagent`:

```python
def dispatch_validated(
    name: str,
    inputs: dict,
    *,
    dry_run_dir: Path | None,
    cwd: Path | None = None,
) -> tuple[dict | None, list[str]]:
    """Compose dispatch_subagent with validate_and_parse.

    Returns:
      Schema-valid:   (raw_dict, [])
      Schema-invalid: (None, ["schema_invalid: <name>: <field-detail>"])
      Dispatch-None:  (None, [])  — caller adds its own `<name>_invalid: returned None`
      Schema-missing: (None, ["schema_missing: <name>"])  — corrupted install
    """
    raw = dispatch_subagent(name, inputs, dry_run_dir=dry_run_dir, cwd=cwd)
    if raw is None:
        return None, []
    from contracts import validate_and_parse
    validated, reasons = validate_and_parse(name, raw)
    if validated is None:
        return None, reasons
    return raw, []
```

Returning the raw dict (not the dataclass) keeps the call sites' existing `dict.get(...)` access patterns unchanged.

### 5.2 Call-site update pattern

Each of the nine existing `dispatch_subagent` call sites becomes:

```python
sources, reasons = dispatch_validated("source-collector", sc_inputs,
                                      dry_run_dir=dry_run_dir, cwd=repo_root)
for r in reasons:
    add_partial(state, r)
if sources is None:
    if not reasons:
        add_partial(state, "source_collector_invalid: returned None")
    sources = {"prs": [], "jira_issues": []}
```

The `if not reasons` guard ensures `partial_reasons` gets exactly one line per failed dispatch — the most specific available — never a stack of overlapping reasons.

### 5.3 Agent `.md` rewrite

For each of the seven agent files, insert a new section between `## Inputs` and `## Procedure`:

````markdown
## Output schema (canonical)

```json
<verbatim contents of agents/schemas/<name>.schema.json>
```
````

Return ONLY a JSON object that validates against this schema. No prose, no markdown fences, no commentary.

````

The pre-existing `## Output contract` section (prose + example) stays, with a single new line at the top: *"The canonical schema is in §Output schema below. The shape described here is the same; the schema is authoritative if they disagree."*

### 5.4 Drift-prevention lint

New file `tests/agents/test_schema_md_sync.py`:

```python
import json
import re
from pathlib import Path
import pytest

AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"
SCHEMA_BLOCK = re.compile(
    r"## Output schema \(canonical\)\s*\n+```json\s*\n(.+?)\n```", re.DOTALL
)

@pytest.mark.parametrize("agent_name", [
    "source-collector", "pr-summarizer", "page-author",
    "content-validator", "gap-detector", "publish-verifier", "notifier",
])
def test_md_schema_block_matches_canonical_schema_file(agent_name: str):
    md_text = (AGENTS_DIR / f"{agent_name}.md").read_text()
    schema_path = AGENTS_DIR / "schemas" / f"{agent_name.replace('-', '_')}.schema.json"
    schema_text = schema_path.read_text()

    match = SCHEMA_BLOCK.search(md_text)
    assert match, f"{agent_name}.md missing '## Output schema (canonical)' block"

    md_schema = json.loads(match.group(1))
    canonical = json.loads(schema_text)
    assert md_schema == canonical, (
        f"{agent_name}.md schema block drifted from "
        f"agents/schemas/{agent_name.replace('-', '_')}.schema.json"
    )
````

### 5.5 New schema-invalid integration test

New file `tests/orchestrator/test_schema_invalid_soft_fail.py`. Creates a fakes directory containing the Mode-B observed wrong shape for `source-collector` plus canonical shapes for the other six. Asserts:

- `run()` returns 0
- `state["current_run"]["partial"] is True`
- `state["current_run"]["partial_reasons"]` contains exactly one entry matching `^schema_invalid: source-collector: `
- That same list does NOT contain `source_collector_invalid: returned None`
- `state["current_run"]["pr_number"] is None` (no PR opened from empty work)

## 6. Data flow

Three scenarios end-to-end:

### 6.1 Schema-valid success

| Stage                   | Value                                                         |
| ----------------------- | ------------------------------------------------------------- |
| LLM stdout              | `{"prs":[{"number":42,...,"url":"..."}],"jira_issues":[...]}` |
| `dispatch_subagent`     | returns raw dict                                              |
| `validate_and_parse`    | returns `(SourceCollectorResult(...), [])`                    |
| `dispatch_validated`    | returns `(raw_dict, [])`                                      |
| `partial_reasons` added | none                                                          |
| `sources` value         | the raw dict                                                  |
| Pipeline                | proceeds with real PRs                                        |

### 6.2 Schema-invalid soft-fail (the new visibility)

| Stage                   | Value                                                                                                                     |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| LLM stdout              | `{"status":"success","modifications":[],"summary":"...","head_sha":"...","branches_scanned":[],"events_processed":0,...}` |
| `dispatch_subagent`     | returns raw dict                                                                                                          |
| `validate_and_parse`    | returns `(None, ["schema_invalid: source-collector: 'prs' is a required property"])`                                      |
| `dispatch_validated`    | returns `(None, [...])`                                                                                                   |
| `partial_reasons` added | `schema_invalid: source-collector: 'prs' is a required property`                                                          |
| `sources` value         | empty fallback `{"prs": [], "jira_issues": []}`                                                                           |
| Pipeline                | proceeds with empty PRs; no whats-new entry; no PR opened                                                                 |
| Operator signal         | `partial: true` + specific reason in notifier digest                                                                      |

### 6.3 Dispatch returned None (no behavior change vs today)

| Stage                   | Value                                                           |
| ----------------------- | --------------------------------------------------------------- |
| LLM stdout              | `""` (or claude binary missing, nonzero rc, unparseable JSON)   |
| `dispatch_subagent`     | returns `None`                                                  |
| `validate_and_parse`    | not called                                                      |
| `dispatch_validated`    | returns `(None, [])`                                            |
| `partial_reasons` added | `source_collector_invalid: returned None` (call site's generic) |
| `sources` value         | empty fallback                                                  |
| Pipeline                | proceeds with empty PRs                                         |

## 7. Error handling

### 7.1 Composition rules

1. **Validation never stops the pipeline.** Soft fail with empty fallback. Same exit-code surface as today.
2. **One reason per call site, picked by specificity.** The call-site dedup logic ensures at most one line per failed dispatch — specific schema reason if available, generic `<name>_invalid: returned None` otherwise.
3. **Validation infrastructure errors are surfaced, not swallowed.** `schema_missing: <name>` and `dataclass_missing: <name>` come through as partial_reasons; they indicate a corrupted install, not an agent misbehavior.

### 7.2 Downstream consumers

| Consumer                                                | Effect of a schema_invalid reason                                                          |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Empty-fallback pipeline (pr-summarizer, page-author, …) | Already handles empty inputs; no change.                                                   |
| What's New file synthesis                               | Already gated on `if prs:`; correctly emits nothing.                                       |
| `gh pr create`                                          | Already gated on `if authored:`; correctly emits nothing.                                  |
| `notifier` digest                                       | Receives the full `partial_reasons` array. Operator sees the schema reason in Slack/email. |
| `verify_runner`                                         | Same wrapper pattern; existing try/finally state-write contract holds.                     |

### 7.3 Empty-but-valid is not an error

Confirmed during design validation: `{"prs": [], "jira_issues": []}` validates cleanly. A legitimate "no merged PRs since last_sha" run produces this shape, zero partial_reasons, `partial: false`. No false positives.

### 7.4 Interaction with CCE-5

CCE-4 introduces reasons named with `schema_` and `dataclass_` prefixes (all transient — next run might succeed because the model is stochastic). CCE-5 (carry-forward hygiene) treats these as transient on new-run init. No coupling required between the two PRs; CCE-4 ships independently and CCE-5 retroactively benefits from the naming convention.

## 8. Testing

### 8.1 New tests (12 cases total)

| File                                                  | Cases             | Purpose                                                                                   |
| ----------------------------------------------------- | ----------------- | ----------------------------------------------------------------------------------------- |
| `tests/orchestrator/test_dispatch_validated.py`       | 4                 | Boundary tests for the new wrapper — valid, schema-invalid, dispatch-None, schema-missing |
| `tests/orchestrator/test_schema_invalid_soft_fail.py` | 1                 | End-to-end soft-fail behavior with a Mode-B-style wrong shape                             |
| `tests/agents/test_schema_md_sync.py`                 | 7 (parameterized) | Drift-prevention lint — each `.md` schema block JSON-equivalent to canonical              |

### 8.2 Existing-test impact audit (during implementation)

- `tests/orchestrator/test_dispatch_subagent.py` (10 tests): unchanged. `dispatch_subagent` keeps its signature; the new wrapper sits above it.
- `tests/orchestrator/test_pipeline_integration.py` (5 spy-based tests): each spy returns canned dicts that flow through `dispatch_validated`. Spies' returns must match canonical schemas, or every test fails with `schema_invalid`. The existing `fakes_block` fixtures already validate cleanly (verified during design), so most spies are safe; inline spy dicts need a one-time audit.
- `tests/orchestrator/test_verify_runner.py`: same audit applies for verify-side spies.

### 8.3 Coverage matrix at end of CCE-4

| Concern                                                       | Test                               |
| ------------------------------------------------------------- | ---------------------------------- |
| `dispatch_validated` returns correct tuple for all four paths | `test_dispatch_validated.py`       |
| Specific schema reason surfaces; no generic redundancy        | `test_schema_invalid_soft_fail.py` |
| Pipeline exit 0 + completion on schema-invalid                | `test_schema_invalid_soft_fail.py` |
| `.md` schema block JSON-equivalent to `.schema.json`          | `test_schema_md_sync.py` × 7       |
| No regression in `dispatch_subagent`'s 10 existing tests      | unchanged                          |
| No regression in pipeline integration                         | audit + fixture fixes              |

### 8.4 Pre-conditioning for CCE-6 (`--live` gate)

`dispatch_validated`'s tuple return makes a live test trivial:

```python
@pytest.mark.live  # added when CCE-6 lands
def test_source_collector_returns_contract_shape_live():
    result, reasons = dispatch_validated("source-collector", {...},
                                          dry_run_dir=None, cwd=tmp_repo)
    assert not reasons, f"Live agent produced schema-invalid response: {reasons}"
```

Not added in CCE-4. Test surface is ready.

### 8.5 Test count after CCE-4

| Category             | Existing | New    | Total    |
| -------------------- | -------- | ------ | -------- |
| dispatch (unit)      | 10       | 4      | 14       |
| pipeline integration | ~50      | 1      | ~51      |
| schema sync (lint)   | 0        | 7      | 7        |
| All other            | ~80      | 0      | ~80      |
| **Total**            | **146**  | **12** | **~158** |

## 9. Validation results (pre-design evidence)

Sanity-checked with the actual `validate_and_parse` against canonical fixtures and known-bad shapes before finalizing the design:

| Claim                                                                                   | Verdict                                                    |
| --------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| 7 agents map 1:1 to 7 schema files                                                      | ✅                                                         |
| `validate_and_parse(name, raw) -> tuple` with the documented signature                  | ✅                                                         |
| `jsonschema` runtime dep available (4.25.1)                                             | ✅                                                         |
| All 7 canonical fixtures validate cleanly                                               | ✅                                                         |
| Mode B observed wrong shape rejected with `'prs' is a required property`                | ✅                                                         |
| Subtle partial shapes (missing nested field) rejected                                   | ✅                                                         |
| Empty-but-valid `{prs: [], jira_issues: []}` accepted                                   | ✅                                                         |
| Actual reason format is `schema_invalid: <name>: <field>` (not `<name>_schema_invalid`) | ✅ corrected in spec                                       |
| `publish-verifier` fixture lives in `fakes_verify_ok/`, not `fakes_block/`              | ✅ noted (drift-lint compares to schema file, not fixture) |

## 10. Success criteria

1. `dispatch_validated` exists and is the production entry point for all nine subagent call sites.
2. All seven agent `.md` files contain a `## Output schema (canonical)` section with a JSON Schema that is JSON-equivalent to `agents/schemas/<name>.schema.json` (verified by the drift lint).
3. The schema-md-sync test passes for all seven agents.
4. The schema-invalid integration test passes — pipeline reaches exit 0 with the specific reason recorded.
5. All 146 existing tests still pass (after the spy/fixture audit).
6. New total: ~158 tests passing.
7. Running Mode B against ADIS produces either: (a) a `schema_invalid` reason in `partial_reasons` instead of silent no-op, or (b) a schema-valid response (the prompt sharpening worked) with `partial: false`.
8. No new runtime dependencies. No new configuration surfaces.

## 11. Files touched

| File                                                  | Change                                                       | Lines |
| ----------------------------------------------------- | ------------------------------------------------------------ | ----- |
| `scripts/orchestrator_runner.py`                      | Add `dispatch_validated` wrapper; update 6 call sites        | +30   |
| `scripts/verify_runner.py`                            | Update 3 call sites                                          | +12   |
| `agents/source-collector.md`                          | Add canonical schema block; tweak `## Output contract` intro | +25   |
| `agents/pr-summarizer.md`                             | Same                                                         | +25   |
| `agents/page-author.md`                               | Same                                                         | +25   |
| `agents/content-validator.md`                         | Same                                                         | +25   |
| `agents/gap-detector.md`                              | Same                                                         | +25   |
| `agents/publish-verifier.md`                          | Same                                                         | +25   |
| `agents/notifier.md`                                  | Same                                                         | +25   |
| `tests/agents/test_schema_md_sync.py`                 | New — drift-prevention lint                                  | +30   |
| `tests/orchestrator/test_dispatch_validated.py`       | New — wrapper boundary tests                                 | +50   |
| `tests/orchestrator/test_schema_invalid_soft_fail.py` | New — end-to-end soft-fail                                   | +60   |
| `tests/orchestrator/fakes_schema_invalid/*.json`      | New — 7 fixture files (1 bad source-collector + 6 canonical) | +60   |
| `CHANGELOG.md`                                        | v0.1.2 entry under "Added"/"Changed"                         | +10   |

Total: ~395 lines added, no deletions of existing functionality.
