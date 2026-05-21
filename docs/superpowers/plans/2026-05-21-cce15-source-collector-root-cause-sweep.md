# CCE-15: Source-Collector Root-Cause Sweep — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two residual source-collector failure modes from the CCE-14 baseline (checklist bypass via phantom-field acceptance + "★ Insight" prose contamination from style-hook propagation) by addressing their root causes in the dispatch subprocess env, the schema validator, and a defense-in-depth rescue path — then re-measure against the same SHA window to verify acceptance.

**Architecture:** Three composable fixes layered across the existing pipeline. (1) Add `claude --bare` to `dispatch_subagent` argv — kills the SessionStart-hook contamination class. (2) Add `additionalProperties: false` to `source_collector.schema.json` (top-level + per-PR item) — phantom fields like `commits` flow through the existing schema-validation path as `schema_invalid: ...` in `partial_reasons` instead of silently passing as "empty success". (3) Add a prose-tolerant JSON rescue helper invoked from `dispatch_subagent` when strict `json.loads` fails — surfaces via an optional `out_reasons` parameter (additive, backward-compatible signature) and bubbles up through `dispatch_validated`'s existing tuple return.

**Tech Stack:** Python stdlib (`json`, `subprocess`, `os`, `pathlib`), pytest + monkeypatch, jsonschema (draft-07), Claude Code CLI `--bare` flag.

**Spec:** [`docs/superpowers/specs/2026-05-21-cce15-source-collector-root-cause-sweep-design.md`](../specs/2026-05-21-cce15-source-collector-root-cause-sweep-design.md)

---

## Implementation-mechanism deviation from spec

The spec proposes changing `dispatch_subagent`'s return type from `dict | None` to `tuple[dict | None, list[str]]`, with 19 caller-site updates in lockstep. This plan uses an additive backward-compatible alternative: a new optional `out_reasons: list[str] | None = None` parameter that `dispatch_subagent` appends rescue reasons to when provided. `dispatch_validated` passes a fresh list and merges; the other 18 caller sites need no changes.

Same behavioral goals (rescue reasons surface via `partial_reasons`), smaller blast radius, identical observable behavior at the `dispatch_validated` boundary. If you prefer the spec's literal tuple-return change, swap Task 3's "Step 7" implementation block — both forms are isomorphic.

---

## File Structure

| File                                                                                                                               | Action          | Responsibility                                                                                                                                                                                 |
| ---------------------------------------------------------------------------------------------------------------------------------- | --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/orchestrator_runner.py`                                                                                                   | Modify          | Add `--bare` flag to dispatch argv (Task 1). Add `_rescue_json_object` helper + wire into `dispatch_subagent` via `out_reasons` parameter (Task 3). Update `dispatch_validated` body (Task 4). |
| `agents/schemas/source_collector.schema.json`                                                                                      | Modify          | Add `additionalProperties: false` at top level and per-PR item (Task 2).                                                                                                                       |
| `tests/orchestrator/test_dispatch_subagent.py`                                                                                     | Modify          | Add `test_dispatch_passes_bare_flag` (Task 1).                                                                                                                                                 |
| `tests/schemas/test_source_collector_schema.py`                                                                                    | Create          | Four tests covering schema strictness + regression guards (Task 2).                                                                                                                            |
| `tests/orchestrator/test_dispatch_rescue.py`                                                                                       | Create          | Five tests for `_rescue_json_object` + one for `dispatch_subagent` with `out_reasons` (Task 3).                                                                                                |
| `tests/orchestrator/test_dispatch_validated.py`                                                                                    | Modify          | Add `test_dispatch_validated_propagates_rescue_reason_to_partial_reasons` (Task 4).                                                                                                            |
| `docs/superpowers/measurements/2026-05-21-cce15-run<N>-source-collector.{stream.jsonl,meta.json,stdout.txt,stderr.txt,prompt.txt}` | Create (5 runs) | Raw per-run capture artifacts from Task 5's ceremony.                                                                                                                                          |
| `docs/superpowers/measurements/2026-05-21-cce15-root-cause-baseline.md`                                                            | Create          | Measurement doc with CCE-12 → CCE-14 → CCE-15 three-column side-by-side and acceptance verdict (Task 6).                                                                                       |

---

## Task 1: Add `--bare` flag to dispatch subprocess

**Goal:** Single argv addition + test that pins it. Kills the SessionStart-hook contamination pathway (Mode 2 root cause) for all dispatched subagents.

**Files:**

- Modify: `scripts/orchestrator_runner.py:222-232` (base_argv construction)
- Test: `tests/orchestrator/test_dispatch_subagent.py` (append new test at end)

- [ ] **Step 1: Write the failing test**

Append to `tests/orchestrator/test_dispatch_subagent.py`:

```python
def test_dispatch_passes_bare_flag(monkeypatch):
    """CCE-15: dispatch must pass `--bare` so SessionStart hooks (e.g. the
    explanatory-output-style plugin's hook that injects '★ Insight ─'
    formatting) don't contaminate the subagent's stdout with prose
    preambles. `--bare` is the documented way to skip hooks, plugin sync,
    auto-memory, attribution, and CLAUDE.md auto-discovery while still
    loading explicit --plugin-dir + --agent context.
    """
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_capture(captured, stdout="{}"))

    orchestrator_runner.dispatch_subagent(
        "source-collector", {"foo": "bar"}, dry_run_dir=None
    )

    cmd = captured["cmd"]
    assert "--bare" in cmd, f"--bare not in argv: {cmd}"
    # --bare must appear before -p/--agent so it governs the whole invocation.
    assert cmd.index("--bare") < cmd.index("-p"), (
        f"--bare must precede -p: {cmd}"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_subagent.py::test_dispatch_passes_bare_flag -v
```

Expected: FAIL with `AssertionError: --bare not in argv: ['claude', '-p', ...]`.

- [ ] **Step 3: Add `--bare` to the base_argv list**

Edit `scripts/orchestrator_runner.py` lines 222–232. Replace:

```python
    base_argv = [
        "claude",
        "-p",
        prompt,
        "--agent",
        name,
        "--plugin-dir",
        str(_PLUGIN_ROOT),
        "--allowedTools",
        " ".join(_AGENT_ALLOWED_TOOLS),
    ]
```

With:

```python
    base_argv = [
        "claude",
        # CCE-15: --bare skips SessionStart hooks (including the
        # explanatory-output-style plugin's hook that injects "★ Insight ─"
        # formatting), plugin sync, auto-memory, attribution, and CLAUDE.md
        # auto-discovery. Subagent role instructions still come from
        # --plugin-dir + --agent below, so the agent context is unchanged.
        "--bare",
        "-p",
        prompt,
        "--agent",
        name,
        "--plugin-dir",
        str(_PLUGIN_ROOT),
        "--allowedTools",
        " ".join(_AGENT_ALLOWED_TOOLS),
    ]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_subagent.py::test_dispatch_passes_bare_flag -v
```

Expected: PASS.

- [ ] **Step 5: Run the full test suite to verify no regression**

```bash
.venv/bin/pytest
```

Expected: 177 passed (176 existing + 1 new). The existing dispatch tests inspect `cmd[0]`, `cmd.index("-p")`, etc. — none assert a specific length or position that `--bare` would break. If any test fails because it pinned the argv shape, the failure is a real signal — fix the pinned position by adjusting the index, do not remove `--bare`.

- [ ] **Step 6: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_dispatch_subagent.py
git commit -m "$(cat <<'EOF'
feat(CCE-15): pass --bare to dispatched subagents

Eliminates the SessionStart-hook contamination pathway. The
explanatory-output-style plugin (and any future hook plugin) registers
a SessionStart hook that injects additionalContext into every new
Claude process — including subagents spawned via `claude -p`. That
injection caused Run 4 of the CCE-14 baseline to prepend a "★ Insight"
prose block before the JSON, breaking _extract_final_assistant_text
parsing despite the agent invoking tools and fetching correct data.

`--bare` is the documented kill-switch for hooks, plugin sync,
auto-memory, attribution, and CLAUDE.md auto-discovery. Subagent role
instructions still come from --plugin-dir + --agent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Tighten source-collector schema with additionalProperties: false

**Goal:** Make phantom-field acceptances (Runs 2, 3 of the CCE-14 baseline emitted `{"prs":[],"jira_issues":[],"commits":[]}` with a phantom `commits` field) impossible at the schema layer. After this task, the phantom output flows through `dispatch_validated` as `schema_invalid: source_collector: additional properties not allowed (commits)` in `partial_reasons` instead of silently passing as "empty success".

**Files:**

- Modify: `agents/schemas/source_collector.schema.json`
- Create: `tests/schemas/test_source_collector_schema.py`

- [ ] **Step 1: Create the test file with four tests**

Create `tests/schemas/test_source_collector_schema.py`:

```python
from __future__ import annotations
import json
from pathlib import Path
from jsonschema import validate, ValidationError
import pytest

SCHEMA = json.loads(
    (
        Path(__file__).parent.parent.parent
        / "agents"
        / "schemas"
        / "source_collector.schema.json"
    ).read_text()
)


def test_canonical_empty_shape_still_passes():
    """Regression guard: the empty {prs:[], jira_issues:[]} shape that the
    agent emits when last_sha..HEAD has zero merged PRs must still pass
    after additionalProperties:false is added.
    """
    validate({"prs": [], "jira_issues": []}, SCHEMA)


def test_full_pr_with_all_known_fields_still_passes():
    """Regression guard: the most complex canonical output observed in
    production (CCE-14 Run 1's stdout) must still pass. Tightening the
    schema must not reject any field listed in `properties`.
    """
    full = {
        "prs": [
            {
                "number": 9,
                "url": "https://github.com/theoju/engineering-docs-agent/pull/9",
                "title": "feat(CCE-12): source-collector tool-use diagnostics",
                "body": "## Summary\n\n- Adds a debug-dir-gated stream-json path...",
                "merge_sha": "f0e774c34ba7afdc308434d5321285a7256578ab",
                "merged_at": "2026-05-21T06:01:49Z",
                "author": "theoju",
                "files": [
                    {"path": "scripts/orchestrator_runner.py", "additions": 145, "deletions": 13, "changeType": "MODIFIED"}
                ],
                "labels": [],
                "jira_keys": ["CCE-12", "CCE-13", "CCE-10"],
            }
        ],
        "jira_issues": [],
    }
    validate(full, SCHEMA)


def test_phantom_top_level_field_rejected():
    """CCE-15 Mode 1: the agent has been observed emitting
    {"prs":[], "jira_issues":[], "commits":[]} — a phantom `commits`
    field that doesn't exist in the schema. This MUST be rejected so
    the orchestrator sees schema_invalid instead of silently accepting
    it as an empty-success run.
    """
    bad = {"prs": [], "jira_issues": [], "commits": []}
    with pytest.raises(ValidationError) as exc_info:
        validate(bad, SCHEMA)
    assert "commits" in str(exc_info.value)


def test_phantom_per_pr_item_field_rejected():
    """CCE-15: tighten per-PR items too. If an agent invents fields
    inside a PR object (e.g. `extra`, `status`, `summary`), they must
    be rejected. Otherwise the orchestrator could receive misleading
    auxiliary data the downstream agents don't know how to consume.
    """
    bad = {
        "prs": [{"number": 1, "url": "https://example.com/pr/1", "extra": "x"}],
        "jira_issues": [],
    }
    with pytest.raises(ValidationError) as exc_info:
        validate(bad, SCHEMA)
    assert "extra" in str(exc_info.value)
```

- [ ] **Step 2: Run the new tests to verify the phantom-rejection ones fail**

```bash
.venv/bin/pytest tests/schemas/test_source_collector_schema.py -v
```

Expected:

- `test_canonical_empty_shape_still_passes` — PASS (schema already accepts empty arrays)
- `test_full_pr_with_all_known_fields_still_passes` — PASS (schema already accepts all listed properties)
- `test_phantom_top_level_field_rejected` — FAIL with `DID NOT RAISE <class 'jsonschema.exceptions.ValidationError'>` (additionalProperties defaults to true; phantom `commits` passes silently)
- `test_phantom_per_pr_item_field_rejected` — FAIL with the same message for per-PR `extra`

- [ ] **Step 3: Add `additionalProperties: false` to the schema (top level + per-PR item)**

Replace the entire contents of `agents/schemas/source_collector.schema.json` with:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "source-collector output",
  "type": "object",
  "required": ["prs", "jira_issues"],
  "additionalProperties": false,
  "properties": {
    "prs": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["number", "url"],
        "additionalProperties": false,
        "properties": {
          "number": { "type": "integer" },
          "url": { "type": "string" },
          "title": { "type": "string" },
          "body": { "type": ["string", "null"] },
          "merge_sha": { "type": "string" },
          "merged_at": { "type": "string" },
          "author": { "type": "string" },
          "files": { "type": "array" },
          "labels": { "type": "array" },
          "jira_keys": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "jira_issues": { "type": "array" },
    "error": { "type": ["string", "null"] },
    "partial": { "type": "boolean" }
  }
}
```

Only two changes from before: `"additionalProperties": false` added at top level (after `required`) and inside the `prs.items` object (after that object's `required`). All `properties` definitions and other constraints are unchanged.

- [ ] **Step 4: Run the new tests to verify all four pass**

```bash
.venv/bin/pytest tests/schemas/test_source_collector_schema.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run the full test suite to verify no regression**

```bash
.venv/bin/pytest
```

Expected: 181 passed (177 from Task 1 + 4 new). If any existing test in `tests/orchestrator/` or `tests/schemas/` fails because it submitted a fixture with an extra field, the failure is a real signal — fix the fixture, do not relax the schema. Likely zero such failures because the existing fixtures in `tests/orchestrator/fixtures/` are minimal canonical shapes.

- [ ] **Step 6: Commit**

```bash
git add agents/schemas/source_collector.schema.json tests/schemas/test_source_collector_schema.py
git commit -m "$(cat <<'EOF'
feat(CCE-15): tighten source-collector schema (additionalProperties:false)

Mode 1 root cause: the agent in Runs 2 and 3 of the CCE-14 baseline
emitted {"prs":[], "jira_issues":[], "commits":[]} — a phantom
`commits` field that doesn't exist in the schema. additionalProperties
defaults to `true` in JSON Schema draft-07, so the orchestrator
silently accepted it as an empty-success run.

Adding additionalProperties:false at the top level and inside the
prs[] item makes phantom fields flow through dispatch_validated as
`schema_invalid: source_collector: ...` in partial_reasons, where the
pipeline summary surfaces them to the operator. The checklist-bypass
failure becomes loud and auditable instead of invisible.

Regression-tested against an empty canonical shape and the full PR
object from CCE-14 Run 1 (most complex production output observed).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Add prose-tolerant JSON rescue helper + wire via `out_reasons` parameter

**Goal:** Add a `_rescue_json_object(text) -> dict | None` helper that extracts the first balanced JSON object from prose-contaminated text. Wire it into `dispatch_subagent` as a fallback when strict `json.loads` fails, surfacing the rescue event via an optional `out_reasons: list[str] | None = None` parameter. Defense in depth — if `--bare` (Task 1) catches every contamination pattern, the rescue path stays cold. If a future pattern slips through, rescue + visible `partial_reasons` keep the run useful + auditable.

**Files:**

- Create: `tests/orchestrator/test_dispatch_rescue.py`
- Modify: `scripts/orchestrator_runner.py:75-105` (insert `_rescue_json_object` before `_extract_final_assistant_text`)
- Modify: `scripts/orchestrator_runner.py:215-302` (`dispatch_subagent` signature + parse-fallback wiring)

- [ ] **Step 1: Create the rescue test file with five unit tests for the helper**

Create `tests/orchestrator/test_dispatch_rescue.py`:

```python
"""CCE-15: _rescue_json_object — extract the first balanced JSON object
from prose-contaminated subagent stdout. Defense in depth for the
Mode 2 contamination class even after --bare (Task 1) closes the
SessionStart-hook pathway.
"""

from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import orchestrator_runner as runner  # noqa: E402


def test_rescue_extracts_first_balanced_object_from_prose_prefix():
    """Mirrors CCE-14 Run 4: an '★ Insight' prose block followed by the
    canonical JSON. The rescue must locate the first '{', balance to
    the matching '}', and return the parsed dict.
    """
    contaminated = (
        '`★ Insight ─────────────────────────────────────`\n'
        'The CCE-14 prompt worked: I invoked gh pr list and identified PR #9.\n'
        '`─────────────────────────────────────────────────`\n\n'
        '{"prs":[{"number":9,"url":"https://example.com/9"}],"jira_issues":[]}'
    )
    assert runner._rescue_json_object(contaminated) == {
        "prs": [{"number": 9, "url": "https://example.com/9"}],
        "jira_issues": [],
    }


def test_rescue_extracts_json_with_braces_in_string_literals():
    """The brace-balanced scan must honor JSON string state. Braces
    inside string literals (e.g. {"body": "see {detail}"}) must not
    affect depth tracking. Escaped quotes inside strings must not
    close the string early.
    """
    text = 'preamble\n{"body": "see {detail} and \\"quoted\\" text", "n": 1}\ntrailing'
    assert runner._rescue_json_object(text) == {
        "body": 'see {detail} and "quoted" text',
        "n": 1,
    }


def test_rescue_returns_none_when_no_opening_brace():
    """All-prose output (no '{' anywhere) — rescue returns None so the
    caller falls through to the original failure path.
    """
    assert runner._rescue_json_object("nothing parseable here") is None
    assert runner._rescue_json_object("") is None


def test_rescue_returns_none_when_brace_extracted_object_does_not_parse():
    """A balanced brace pair whose contents aren't valid JSON (e.g.
    Python repr, malformed) — rescue returns None. Avoids accepting
    syntactically-balanced-but-semantically-broken pseudo-JSON.
    """
    text = "header\n{'not': 'json', invalid: True}\nfooter"
    assert runner._rescue_json_object(text) is None


def test_rescue_takes_first_object_when_multiple_present():
    """The agent's contract is 'the canonical JSON is the response'.
    If multiple JSON objects appear in contaminated output, treat the
    first as canonical and any later ones as decorative — matches
    existing parse semantics.
    """
    text = 'first {"a": 1}\nsecond {"b": 2}\nthird {"c": 3}'
    assert runner._rescue_json_object(text) == {"a": 1}
```

- [ ] **Step 2: Run the rescue tests to verify they fail (helper does not exist)**

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_rescue.py -v
```

Expected: 5 FAILED with `AttributeError: module 'orchestrator_runner' has no attribute '_rescue_json_object'`.

- [ ] **Step 3: Implement `_rescue_json_object` helper**

Insert this function in `scripts/orchestrator_runner.py` immediately before the existing `_extract_final_assistant_text` definition at line 75:

```python
def _rescue_json_object(text: str) -> dict | None:
    """Extract the first balanced JSON object from prose-contaminated
    text. Returns the parsed dict on success, None otherwise.

    Defense in depth for CCE-15. With --bare (Task 1) the SessionStart-
    hook contamination pathway is closed, but other contamination
    patterns may exist (CCE-14 Run 4 was an "★ Insight" preamble
    injected by the explanatory-output-style plugin). When strict
    json.loads on the dispatch output fails, callers can fall through
    to this rescue.

    Algorithm: find the first '{', scan forward tracking brace depth
    while honoring JSON string state (open quote, escaped quote skip).
    When depth returns to 0, attempt json.loads on the slice.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None
```

- [ ] **Step 4: Run the rescue tests to verify they pass**

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_rescue.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Add the `dispatch_subagent`-level test for the out_reasons parameter**

Append to `tests/orchestrator/test_dispatch_rescue.py`:

```python
import subprocess
from types import SimpleNamespace


def _fake_run_capture(captured: dict, *, stdout: str = "{}", returncode: int = 0):
    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    return fake_run


def test_dispatch_subagent_appends_rescue_reason_to_out_reasons(monkeypatch):
    """When strict parse fails but rescue succeeds, dispatch_subagent
    returns the rescued dict AND appends a labeled partial reason to
    the caller's out_reasons list.
    """
    contaminated_stdout = (
        '`★ Insight ─`\nsome prose\n`─`\n\n'
        '{"prs": [], "jira_issues": []}'
    )
    captured: dict = {}
    monkeypatch.setattr(
        subprocess, "run", _fake_run_capture(captured, stdout=contaminated_stdout)
    )

    reasons: list[str] = []
    result = runner.dispatch_subagent(
        "source-collector", {}, dry_run_dir=None, out_reasons=reasons
    )

    assert result == {"prs": [], "jira_issues": []}
    assert reasons == ["prose_contamination_rescued: source-collector"]


def test_dispatch_subagent_out_reasons_stays_empty_on_clean_parse(monkeypatch):
    """The rescue path must be cold when strict parse succeeds. No
    rescue reason appended; out_reasons stays empty.
    """
    captured: dict = {}
    monkeypatch.setattr(
        subprocess, "run", _fake_run_capture(captured, stdout='{"prs": [], "jira_issues": []}')
    )

    reasons: list[str] = []
    result = runner.dispatch_subagent(
        "source-collector", {}, dry_run_dir=None, out_reasons=reasons
    )

    assert result == {"prs": [], "jira_issues": []}
    assert reasons == []


def test_dispatch_subagent_out_reasons_optional_backward_compatible(monkeypatch):
    """Existing callers (18 sites in this repo) call dispatch_subagent
    without out_reasons. The parameter must default to None and the
    return type must remain dict | None for those callers.
    """
    captured: dict = {}
    monkeypatch.setattr(
        subprocess, "run", _fake_run_capture(captured, stdout='{"prs": []}')
    )

    # No out_reasons argument: existing signature contract.
    result = runner.dispatch_subagent("source-collector", {}, dry_run_dir=None)
    assert result == {"prs": []}
```

- [ ] **Step 6: Run the three new dispatch tests to verify they fail**

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_rescue.py -v
```

Expected: the first 5 rescue-helper tests still PASS. The three new ones FAIL:

- `test_dispatch_subagent_appends_rescue_reason_to_out_reasons` — FAIL with `TypeError: dispatch_subagent() got an unexpected keyword argument 'out_reasons'`
- `test_dispatch_subagent_out_reasons_stays_empty_on_clean_parse` — same error
- `test_dispatch_subagent_out_reasons_optional_backward_compatible` — currently PASSES (existing signature is backward-compatible by definition). This test fails only after the wiring change rejects no-out_reasons callers; if that's the case the wiring is wrong. The test guards against a future regression.

- [ ] **Step 7: Wire out_reasons parameter + rescue into dispatch_subagent**

Edit `scripts/orchestrator_runner.py`. Two changes:

**Change A** — extend `dispatch_subagent`'s signature. Find the function definition (currently around line 215):

```python
def dispatch_subagent(
    name: str,
    inputs: dict,
    *,
    dry_run_dir: Path | None,
    cwd: Path | None = None,
) -> dict | None:
```

Replace with:

```python
def dispatch_subagent(
    name: str,
    inputs: dict,
    *,
    dry_run_dir: Path | None,
    cwd: Path | None = None,
    out_reasons: list[str] | None = None,
) -> dict | None:
```

**Change B** — replace the parse-fallback at lines 299–302:

```python
    try:
        return json.loads(canonical_text)
    except json.JSONDecodeError:
        return None
```

With:

```python
    try:
        return json.loads(canonical_text)
    except json.JSONDecodeError:
        # CCE-15: strict parse failed. Try prose-tolerant rescue. If we
        # extract a valid object, surface the rescue event via
        # out_reasons so dispatch_validated can roll it into the
        # pipeline's partial_reasons summary.
        rescued = _rescue_json_object(canonical_text)
        if rescued is not None:
            if out_reasons is not None:
                out_reasons.append(f"prose_contamination_rescued: {name}")
            return rescued
        return None
```

- [ ] **Step 8: Run the dispatch tests + full suite to verify all pass**

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_rescue.py -v
.venv/bin/pytest
```

Expected: 8 passed in the rescue file (5 helper + 3 wiring); 189 passed in the full suite (181 from Task 2 + 8 new).

- [ ] **Step 9: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_dispatch_rescue.py
git commit -m "$(cat <<'EOF'
feat(CCE-15): prose-tolerant JSON rescue in dispatch_subagent

Defense in depth for Mode 2 contamination. With --bare (previous
commit) the SessionStart-hook pathway is closed, but if a future
contamination pattern slips through (different hook, different plugin)
we want to recover the agent's data, not lose the run.

New helper _rescue_json_object(text) does a brace-balanced scan
honoring JSON string state, attempts json.loads on the first balanced
object, returns dict | None. When dispatch_subagent's strict parse
fails, falls through to rescue. On success appends
"prose_contamination_rescued: <agent>" to an optional out_reasons
list — backward-compatible additive signature (out_reasons defaults
to None for the 18 existing call sites).

dispatch_validated wiring + partial_reasons propagation in the next
commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Wire `dispatch_validated` to consume rescue reasons via `out_reasons`

**Goal:** When a rescue fires inside `dispatch_subagent`, the rescue reason must propagate through `dispatch_validated` into `state['current_run']['partial_reasons']` so the pipeline summary surfaces it. This task does the wiring + the one integration test that pins the end-to-end flow.

**Files:**

- Modify: `scripts/orchestrator_runner.py:305-329` (`dispatch_validated` body)
- Modify: `tests/orchestrator/test_dispatch_validated.py` (append new test)

- [ ] **Step 1: Write the failing integration test**

Append to `tests/orchestrator/test_dispatch_validated.py`:

```python
def test_dispatch_validated_propagates_rescue_reason_to_partial_reasons(
    monkeypatch,
):
    """CCE-15: when dispatch_subagent's strict parse fails and rescue
    extracts a valid object, the rescue reason must flow through
    dispatch_validated's returned reasons list. The orchestrator's
    state['current_run']['partial_reasons'] accumulator reads from
    this list, so a sustained rescue rate is visible at the pipeline
    summary layer.
    """
    import subprocess
    from types import SimpleNamespace
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    contaminated_stdout = (
        '`★ Insight ─`\nsome prose preamble\n`─`\n\n'
        '{"prs": [], "jira_issues": []}'
    )

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout=contaminated_stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    raw, reasons = runner.dispatch_validated(
        "source-collector", {}, dry_run_dir=None
    )

    assert raw == {"prs": [], "jira_issues": []}
    assert reasons == ["prose_contamination_rescued: source-collector"]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_validated.py::test_dispatch_validated_propagates_rescue_reason_to_partial_reasons -v
```

Expected: FAIL with `assert reasons == ['prose_contamination_rescued: source-collector']` mismatch (actual is `[]` — `dispatch_validated` doesn't pass `out_reasons` to dispatch yet).

- [ ] **Step 3: Update `dispatch_validated` to pass + merge out_reasons**

Edit `scripts/orchestrator_runner.py`. Find the `dispatch_validated` body (currently around lines 320–329):

```python
    raw = dispatch_subagent(name, inputs, dry_run_dir=dry_run_dir, cwd=cwd)
    if raw is None:
        return None, []
    from contracts import validate_and_parse

    validated, reasons = validate_and_parse(name, raw)
    if validated is None:
        return None, reasons
    # Return raw (not the dataclass) so call sites can keep using dict.get() patterns.
    return raw, []
```

Replace with:

```python
    # CCE-15: pass an out_reasons collector so dispatch_subagent can
    # surface prose-contamination rescue events; merge them into the
    # tuple returned to callers (orchestrator state accumulates them
    # into state['current_run']['partial_reasons']).
    dispatch_reasons: list[str] = []
    raw = dispatch_subagent(
        name, inputs, dry_run_dir=dry_run_dir, cwd=cwd, out_reasons=dispatch_reasons
    )
    if raw is None:
        return None, dispatch_reasons
    from contracts import validate_and_parse

    validated, reasons = validate_and_parse(name, raw)
    if validated is None:
        return None, dispatch_reasons + reasons
    # Return raw (not the dataclass) so call sites can keep using dict.get() patterns.
    return raw, dispatch_reasons
```

Also update the docstring just above. Find:

```python
    """Compose dispatch_subagent with validate_and_parse.

    Returns:
      Schema-valid:   (raw_dict, [])
      Schema-invalid: (None, ["schema_invalid: <name>: <field-detail>"])
      Dispatch-None:  (None, [])  — caller adds its own generic reason
      Schema-missing: (None, ["schema_missing: <name>"]) — corrupted install
    """
```

Replace with:

```python
    """Compose dispatch_subagent with validate_and_parse.

    Returns:
      Schema-valid clean:           (raw_dict, [])
      Schema-valid + rescued (CCE-15):
                                    (raw_dict, ["prose_contamination_rescued: <name>"])
      Schema-invalid:               (None, [...reasons including any rescue tag])
      Dispatch-None:                (None, []) — caller adds its own generic reason
      Schema-missing:               (None, ["schema_missing: <name>"])
    """
```

- [ ] **Step 4: Run the integration test + full suite**

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_validated.py -v
.venv/bin/pytest
```

Expected: the new test PASSES; full suite shows 190 passed (189 from Task 3 + 1 new).

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_dispatch_validated.py
git commit -m "$(cat <<'EOF'
feat(CCE-15): propagate rescue reasons through dispatch_validated

Wires the out_reasons collector from the previous commit into
dispatch_validated. When dispatch_subagent's prose-tolerant rescue
fires, the "prose_contamination_rescued: <agent>" reason now flows
through dispatch_validated into the orchestrator's partial_reasons
accumulator and shows up in the pipeline summary.

Same mechanism that surfaces schema_invalid reasons today (CCE-10);
both prefixes are now distinct, labeled, and queryable.

End-to-end test asserts the propagation under a monkeypatched
subprocess.run that emits a "★ Insight" prose preamble followed by
canonical JSON.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Five-run Mode B re-measurement ceremony

**Goal:** Generate the raw per-run capture artifacts that Task 6's baseline doc summarizes. Runs are serial (NOT parallel — fresh subagent context per run); each writes 5 files into a per-run debug dir under `/tmp/cce15-run<N>`, which are then copied into `docs/superpowers/measurements/` with the canonical naming convention.

**Files (all generated, 5 runs × 5 artifacts = 25 files):**

- Create: `docs/superpowers/measurements/2026-05-21-cce15-run<N>-source-collector.stream.jsonl` for N ∈ {1..5}
- Create: `docs/superpowers/measurements/2026-05-21-cce15-run<N>-source-collector.meta.json` for N ∈ {1..5}
- Create: `docs/superpowers/measurements/2026-05-21-cce15-run<N>-source-collector.stdout.txt` for N ∈ {1..5}
- Create: `docs/superpowers/measurements/2026-05-21-cce15-run<N>-source-collector.stderr.txt` for N ∈ {1..5}
- Create: `docs/superpowers/measurements/2026-05-21-cce15-run<N>-source-collector.prompt.txt` for N ∈ {1..5}

- [ ] **Step 1: Pre-flight — verify branch + tests + clean tree**

```bash
git branch --show-current  # must be: feat/CCE-15-source-collector-root-cause-sweep
git status --porcelain     # must be empty
.venv/bin/pytest           # must be: 190 passed
```

If any of these fail, halt and resolve before measuring. Measuring against a dirty tree or a different branch invalidates the comparison.

- [ ] **Step 2: Build the dispatch input payload**

The window must be IDENTICAL to CCE-12 and CCE-14 (`a2a9dba..b2cd07a`) for direct comparability. Write the input file once:

```bash
cat > /tmp/cce15-dispatch-input.json <<'EOF'
{"last_sha": "a2a9dba273bf5ef82ef6d450d3eb44ee27e04681", "head_sha": "b2cd07af5cdcf0482515fc757a6ee6def3af278d", "repo": {"owner": "theoju", "name": "engineering-docs-agent"}, "pr_branch_filter": ["docs-agent/*"]}
EOF
cat /tmp/cce15-dispatch-input.json
```

Expected: a single-line JSON with both SHAs and the repo set to the self-host target.

- [ ] **Step 3: Run iteration 1 with diagnostics on**

```bash
mkdir -p /tmp/cce15-run1
DOCS_AGENT_DEBUG_DIR=/tmp/cce15-run1 \
CLAUDE_STOP_VERIFY=0 \
python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from orchestrator_runner import dispatch_subagent

inputs = json.loads(Path('/tmp/cce15-dispatch-input.json').read_text())
reasons = []
result = dispatch_subagent('source-collector', inputs, dry_run_dir=None, out_reasons=reasons)
print('REASONS:', reasons)
print('RESULT:', json.dumps(result, indent=2) if result else 'DISPATCH RETURNED None')
"
ls -la /tmp/cce15-run1
```

Expected: a `<ts>-source-collector.{stream.jsonl,stdout.txt,stderr.txt,prompt.txt,meta.json}` in `/tmp/cce15-run1`. The script prints either the parsed dict or `DISPATCH RETURNED None`, plus the rescue-reasons list (should be `[]` if `--bare` worked; non-empty if rescue fired).

- [ ] **Step 4: Copy run 1 artifacts into the measurements directory**

```bash
mkdir -p docs/superpowers/measurements
cp /tmp/cce15-run1/*-source-collector.stream.jsonl docs/superpowers/measurements/2026-05-21-cce15-run1-source-collector.stream.jsonl
cp /tmp/cce15-run1/*-source-collector.stdout.txt   docs/superpowers/measurements/2026-05-21-cce15-run1-source-collector.stdout.txt
cp /tmp/cce15-run1/*-source-collector.stderr.txt   docs/superpowers/measurements/2026-05-21-cce15-run1-source-collector.stderr.txt
cp /tmp/cce15-run1/*-source-collector.prompt.txt   docs/superpowers/measurements/2026-05-21-cce15-run1-source-collector.prompt.txt
cp /tmp/cce15-run1/*-source-collector.meta.json    docs/superpowers/measurements/2026-05-21-cce15-run1-source-collector.meta.json
```

- [ ] **Step 5: Repeat Step 3 + Step 4 for runs 2, 3, 4, 5 (serially)**

For each iteration N ∈ {2, 3, 4, 5} (do them one at a time, NOT in parallel — we want fresh subagent contexts):

```bash
mkdir -p /tmp/cce15-runN
DOCS_AGENT_DEBUG_DIR=/tmp/cce15-runN \
CLAUDE_STOP_VERIFY=0 \
python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from orchestrator_runner import dispatch_subagent

inputs = json.loads(Path('/tmp/cce15-dispatch-input.json').read_text())
reasons = []
result = dispatch_subagent('source-collector', inputs, dry_run_dir=None, out_reasons=reasons)
print('REASONS:', reasons)
print('RESULT:', json.dumps(result, indent=2) if result else 'DISPATCH RETURNED None')
"
ls -la /tmp/cce15-runN

cp /tmp/cce15-runN/*-source-collector.stream.jsonl docs/superpowers/measurements/2026-05-21-cce15-runN-source-collector.stream.jsonl
cp /tmp/cce15-runN/*-source-collector.stdout.txt   docs/superpowers/measurements/2026-05-21-cce15-runN-source-collector.stdout.txt
cp /tmp/cce15-runN/*-source-collector.stderr.txt   docs/superpowers/measurements/2026-05-21-cce15-runN-source-collector.stderr.txt
cp /tmp/cce15-runN/*-source-collector.prompt.txt   docs/superpowers/measurements/2026-05-21-cce15-runN-source-collector.prompt.txt
cp /tmp/cce15-runN/*-source-collector.meta.json    docs/superpowers/measurements/2026-05-21-cce15-runN-source-collector.meta.json
```

Substitute `N` with the actual run number (2, 3, 4, 5) in both the `/tmp/cce15-runN` path and the output filenames.

- [ ] **Step 6: Verify all 25 artifacts exist + are non-empty (except stderr which is allowed empty)**

```bash
ls -la docs/superpowers/measurements/2026-05-21-cce15-run*-source-collector.* | wc -l
# Expected: 25
for N in 1 2 3 4 5; do
  for ext in stream.jsonl stdout.txt prompt.txt meta.json; do
    f="docs/superpowers/measurements/2026-05-21-cce15-run${N}-source-collector.${ext}"
    [ -s "$f" ] || echo "MISSING OR EMPTY: $f"
  done
done
# Expected: no MISSING OR EMPTY lines
```

- [ ] **Step 7: Stage artifacts but DO NOT commit yet (commit happens in Task 6 with the baseline doc)**

```bash
git add docs/superpowers/measurements/2026-05-21-cce15-run*-source-collector.*
git status --short | head -10
```

Expected: 25 new files staged. Hold the commit — Task 6 writes the baseline doc and they all commit together.

---

## Task 6: Baseline doc with three-column comparison + commit

**Goal:** Write the measurement doc that summarizes Task 5's runs against the CCE-12 and CCE-14 baselines. Per-run categorization (A/B/C/data-returned), the five acceptance-criteria checks, and a verdict that's either clean PASS or documented partial PASS (per the CCE-14 precedent — ship the improvement, document residuals, file CCE-16 if needed).

**Files:**

- Create: `docs/superpowers/measurements/2026-05-21-cce15-root-cause-baseline.md`

- [ ] **Step 1: Per-run categorization from Task 5 artifacts**

For each run N ∈ {1..5}, read the meta.json + stdout.txt and categorize. The categories:

- **A: zero tool calls** — `meta.json.tool_use.total_calls == 0`
- **B: called and discarded** — `total_calls > 0` AND stdout returned no PR data (empty `prs: []`) AND `gh pr list` (or `gh api ... pulls`) WAS invoked
- **C: legitimately empty** — runs where the window genuinely had zero PRs (unlikely with our window)
- **data-returned** — runs where stdout contains at least one PR object

For each run, also record:

- whether `gh pr list` was invoked (look for `"name": "Bash"` events whose `input.command` starts with `gh pr list`)
- whether the rescue path fired (look at the script's printed `REASONS:` from Task 5 Step 3/5, OR re-parse the canonical_text to compare strict vs rescue)
- whether the output was schema-valid (parse stdout as JSON; if it has only `prs` and `jira_issues` and nothing else, schema-valid; otherwise schema_invalid)

Use this awk helper to extract `gh pr list` counts from a stream.jsonl:

```bash
for N in 1 2 3 4 5; do
  f="docs/superpowers/measurements/2026-05-21-cce15-run${N}-source-collector.stream.jsonl"
  gh_pr_list_count=$(jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="tool_use" and .name=="Bash") | .input.command' "$f" | grep -c "^gh pr list" || true)
  total_calls=$(jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="tool_use") | .name' "$f" | wc -l | tr -d ' ')
  echo "Run $N: total_calls=$total_calls, gh_pr_list_invocations=$gh_pr_list_count"
done
```

Record the output for use in Step 2's table.

- [ ] **Step 2: Write the baseline doc**

Create `docs/superpowers/measurements/2026-05-21-cce15-root-cause-baseline.md`:

```markdown
# CCE-15: Source-Collector Root-Cause Sweep Baseline — 5-Run Mode B Ceremony

**Jira:** [CCE-15](https://designitright.atlassian.net/browse/CCE-15)
**Branch:** `feat/CCE-15-source-collector-root-cause-sweep`
**Date:** 2026-05-21
**Dispatch window:** `a2a9dba273bf5ef82ef6d450d3eb44ee27e04681..b2cd07af5cdcf0482515fc757a6ee6def3af278d` on theoju/engineering-docs-agent (IDENTICAL to CCE-12 and CCE-14)
**PR filter:** `docs-agent/*`
**Interventions (vs. CCE-14):**

- `dispatch_subagent` now passes `claude --bare` (skips SessionStart hooks, plugin sync, auto-memory, attribution, CLAUDE.md auto-discovery)
- `source_collector.schema.json` tightened with `additionalProperties: false` at top level + per-PR item
- `_rescue_json_object` helper added in `dispatch_subagent` as defense in depth; rescue events surface via `prose_contamination_rescued: <agent>` in `partial_reasons`

## Three-column comparison (CCE-12 → CCE-14 → CCE-15)

| Run | CCE-12 cat | CCE-14 cat        | CCE-15 total_calls | CCE-15 by_name | CCE-15 cat | gh pr list? | rescue? | schema-valid? |
| --: | ---------- | ----------------- | -----------------: | -------------- | ---------- | :---------: | :-----: | :-----------: |
|   1 | A          | data-returned     |                <N> | <by_name>      | <cat>      |    <Y/N>    |  <Y/N>  |     <Y/N>     |
|   2 | B          | A                 |                <N> | <by_name>      | <cat>      |    <Y/N>    |  <Y/N>  |     <Y/N>     |
|   3 | A          | A                 |                <N> | <by_name>      | <cat>      |    <Y/N>    |  <Y/N>  |     <Y/N>     |
|   4 | A          | B (rescue-failed) |                <N> | <by_name>      | <cat>      |    <Y/N>    |  <Y/N>  |     <Y/N>     |
|   5 | A          | B                 |                <N> | <by_name>      | <cat>      |    <Y/N>    |  <Y/N>  |     <Y/N>     |

Raw artifacts: `2026-05-21-cce15-run<N>-source-collector.{stream.jsonl,stdout.txt,stderr.txt,prompt.txt,meta.json}` in this directory.

## Headline

CCE-12 baseline: Category A in 4 of 5 runs; `gh pr list` invoked in 0 of 5.
CCE-14 post-fix: Category A in 2 of 5 runs; `gh pr list` invoked in 3 of 5.
CCE-15 post-fix: Category A in <N> of 5 runs; `gh pr list` invoked in <N> of 5.

## Acceptance check

| Metric                             | CCE-12  | CCE-14 | CCE-15 actual | Target                                        | Verdict |
| ---------------------------------- | ------- | ------ | ------------- | --------------------------------------------- | ------- |
| Category A (empty + zero tools)    | 4 / 5   | 2 / 5  | <N> / 5       | ≤ 1 / 5                                       | <P/F>   |
| `gh pr list` invocations           | 0 / 5   | 3 / 5  | <N> / 5       | ≥ 4 / 5                                       | <P/F>   |
| Runs returning real PR data        | 0 / 5   | 1 / 5  | <N> / 5       | ≥ 3 / 5                                       | <P/F>   |
| Prose contamination failures       | n/a     | 1 / 5  | <N> / 5       | 0 / 5                                         | <P/F>   |
| Phantom-field acceptances (silent) | unknown | 2 / 5  | <N> / 5       | 0 / 5 (prevented OR logged as schema_invalid) | <P/F>   |

Overall: **<PASS / PARTIAL PASS / FAIL>**

## Delta from CCE-14

<2–4 paragraph analysis: what changed, what worked, what didn't, what surprised you. Cite specific runs by number. Reference the rescue path firings (if any). If acceptance missed on a specific metric, name the residual mechanism in concrete terms — "Run 3 still emitted X" — not abstract terms.>

## Follow-up

<If clean PASS: "No follow-up. Close CCE-15 on merge.">
<If PARTIAL PASS: "File CCE-16 with scope: [the specific residual modes observed], [the specific concrete intervention path]." Match the level of specificity in CCE-14's follow-up section pointing to CCE-15.>
<If FAIL: "Revert and reconsider — root-cause hypothesis was wrong. Investigation needed before next intervention.">

## Methodology notes

The CCE-15 commits (Tasks 1–4: --bare flag, schema tightening, rescue helper + wiring) are NOT in the dispatch window `a2a9dba..b2cd07a` — that window predates this branch. The agent loads the CCE-15 version of `agents/source-collector.md` at runtime via `--plugin-dir`, and `dispatch_subagent` runs from the working tree, so all three interventions are active during measurement.

Each run was executed serially (NOT in parallel) with a fresh `DOCS_AGENT_DEBUG_DIR` to ensure subagent context isolation. `CLAUDE_STOP_VERIFY=0` was set per the existing convention (CCE-10) to prevent the global stop-verify hook from contaminating stdout — note this is independent of `--bare`, which addresses a different contamination pathway.

The dispatch invocation now also passes `out_reasons=[]` so the script can print whether the rescue path fired without re-parsing the stdout. Runs where `REASONS:` was printed non-empty had a rescue event.
```

Fill in the placeholder values (`<N>`, `<by_name>`, `<cat>`, `<Y/N>`, `<P/F>`, `<PASS/PARTIAL PASS/FAIL>`, the Delta paragraphs, and the Follow-up branch) with the actual per-run data from Step 1's output.

- [ ] **Step 3: Stage the baseline doc + verify everything together**

```bash
git add docs/superpowers/measurements/2026-05-21-cce15-root-cause-baseline.md
git status --short
```

Expected: 26 new files staged (25 from Task 5 + 1 baseline doc).

- [ ] **Step 4: Commit Tasks 5 + 6 together**

```bash
git commit -m "$(cat <<'EOF'
docs(CCE-15): root-cause-sweep baseline — 5-run Mode B ceremony

Re-measurement of the source-collector dispatch against the IDENTICAL
SHA window used by CCE-12 (a2a9dba..b2cd07a) with the CCE-15
interventions active: --bare flag in dispatch_subagent argv, schema
tightening (additionalProperties:false), and prose-tolerant JSON
rescue with partial_reasons surfacing.

Headline: <fill from actual results>.

Per-run capture artifacts (stream.jsonl, meta.json, stdout.txt,
stderr.txt, prompt.txt) committed for auditability and to enable
CCE-16 investigation if any residual mode appears.

See docs/superpowers/measurements/2026-05-21-cce15-root-cause-baseline.md
for the three-column comparison (CCE-12 → CCE-14 → CCE-15) and the
acceptance check.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Replace `<fill from actual results>` in the commit body with the actual one-line summary from the baseline doc's Headline section.

- [ ] **Step 5: Final full-suite verification**

```bash
.venv/bin/pytest
git log --oneline main..HEAD
```

Expected: 190 passed; 6 commits on top of main (1 design spec already on branch + 5 implementation/measurement commits from Tasks 1–6).

---

## Self-Review Notes

Walked the spec against this plan:

**Spec coverage:**

- Spec Goal 1 (kill SessionStart-hook contamination) → Task 1 ✓
- Spec Goal 2 (make phantom-field acceptances impossible at schema layer) → Task 2 ✓
- Spec Goal 3 (defense-in-depth rescue path) → Task 3 ✓
- Spec Goal 4 (5-run re-measurement + sharpened acceptance bar) → Tasks 5 + 6 ✓
- Spec error-handling table (each row maps to a test in Tasks 1–4) ✓
- Spec Risks section ("--bare breaks an agent dependency", "schema over-tightening", "rescue masks regressions") — each test in Tasks 1, 2, 3 doubles as the regression guard

**Implementation-mechanism deviation:** Plan uses `out_reasons` parameter instead of the spec's tuple-return. Documented in the deviation block at the top.

**Type consistency:**

- `_rescue_json_object(text: str) -> dict | None` — name used consistently in Task 3 helper definition, Task 3 wiring block, and Task 4 docstring update
- `out_reasons: list[str] | None = None` — same name + type in Task 3 signature, Task 3 wiring, Task 4 `dispatch_validated` body
- `prose_contamination_rescued: <name>` label — same wording in Task 3 wiring, Task 4 test, Task 4 docstring, baseline doc methodology

**No placeholders:** every step has either complete code, an exact command with expected output, or a fill-in template (Task 6) where the values come directly from the Step 1 awk output.

**Frequent commits:** 5 commits across 6 tasks (Tasks 5 and 6 commit together; everything else commits per task).
