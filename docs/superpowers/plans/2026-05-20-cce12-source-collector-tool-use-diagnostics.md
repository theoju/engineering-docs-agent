# CCE-12: Source-Collector Tool-Use Diagnostics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instrument `dispatch_subagent` to capture the source-collector subagent's complete tool-call sequence on Mode B dispatches (when `DOCS_AGENT_DEBUG_DIR` is set), then re-run the CCE-10 5-run ceremony with diagnostics on and categorize the outcomes.

**Architecture:** When `DOCS_AGENT_DEBUG_DIR` is set, `dispatch_subagent` invokes `claude -p ... --output-format stream-json --verbose`, parses the NDJSON event stream, extracts the final assistant message's text content as the canonical JSON, and writes both the raw stream (`<agent>.stream.jsonl`) and a tool-use summary (`meta.json["tool_use"]`) alongside CCE-9's existing capture artifacts. When the gate is off, behavior is byte-for-byte identical to today.

**Tech Stack:** Python stdlib (`json`, `subprocess`, `os`, `pathlib`), pytest with monkeypatch, Claude Code CLI `--output-format stream-json`.

**Spec:** [`docs/superpowers/specs/2026-05-20-cce12-source-collector-tool-use-diagnostics-design.md`](../specs/2026-05-20-cce12-source-collector-tool-use-diagnostics-design.md)

---

## File Structure

| File                                                                                                                               | Action                | Responsibility                                                                                                                                                                                                                                                             |
| ---------------------------------------------------------------------------------------------------------------------------------- | --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/orchestrator/fixtures/cce12_stream_json/source_collector_with_tools.jsonl`                                                  | Create                | NDJSON fixture: 2 `Bash` tool_use turns + tool_results + final text turn with canonical JSON. Used by helper tests and integration test.                                                                                                                                   |
| `tests/orchestrator/fixtures/cce12_stream_json/source_collector_no_tools.jsonl`                                                    | Create                | NDJSON fixture: zero tool_use blocks, single assistant turn with empty `{"prs":[],"jira_issues":[]}`.                                                                                                                                                                      |
| `scripts/orchestrator_runner.py`                                                                                                   | Modify (lines 75–153) | Branch `dispatch_subagent` on `DOCS_AGENT_DEBUG_DIR`. Add `_extract_final_assistant_text` and `_summarize_tool_use` module-level helpers. Extend the existing CCE-9 capture so the gate-on path additionally writes `.stream.jsonl` and folds `tool_use` into `meta.json`. |
| `tests/orchestrator/test_dispatch_subagent_stream_json.py`                                                                         | Create                | Unit tests for the two helpers plus an integration test that exercises the gate-on dispatch path end-to-end via monkeypatched `subprocess.run` returning fixture NDJSON. Also asserts the gate-off path is unchanged.                                                      |
| `docs/superpowers/measurements/2026-05-20-cce12-tool-use-baseline.md`                                                              | Create                | Measurement doc: 5-run Mode B ceremony results, per-run table with `total_calls` / `by_name` / `stop_reason` / output PR + Jira counts / root-cause category (A/B/C/D), and a closing analysis of which category dominates.                                                |
| `docs/superpowers/measurements/2026-05-20-cce12-run<N>-source-collector.{stream.jsonl,meta.json,stdout.txt,stderr.txt,prompt.txt}` | Create (generated)    | Raw per-run capture artifacts from Task 5's ceremony, checked in for auditability.                                                                                                                                                                                         |

---

## Task 1: Stream-json Test Fixtures

Fixtures are data, not behavior — no TDD cycle, but we must verify they parse as valid NDJSON before any test depends on them.

**Files:**

- Create: `tests/orchestrator/fixtures/cce12_stream_json/source_collector_with_tools.jsonl`
- Create: `tests/orchestrator/fixtures/cce12_stream_json/source_collector_no_tools.jsonl`

- [ ] **Step 1: Create the fixture directory**

```bash
mkdir -p tests/orchestrator/fixtures/cce12_stream_json
```

- [ ] **Step 2: Write `source_collector_with_tools.jsonl`**

Each line is a single JSON object. No trailing newline issues — write exactly 7 lines. Use the editor's "no autoformat" / "raw" mode if it tries to pretty-print.

File content (one event per line):

```jsonl
{"type":"system","subtype":"init","session_id":"sess-001","model":"claude-sonnet-4-6","cwd":"/repo","tools":["Bash","Read","Write","Edit","WebFetch"],"mcp_servers":[]}
{"type":"assistant","message":{"id":"msg_01","role":"assistant","content":[{"type":"tool_use","id":"tu_001","name":"Bash","input":{"command":"gh pr list --state merged --search merged:>=2026-05-19","description":"List merged PRs"}}]}}
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_001","content":"42  Add foo  user1  abc123\n43  Fix bar  user2  def456","is_error":false}]}}
{"type":"assistant","message":{"id":"msg_02","role":"assistant","content":[{"type":"tool_use","id":"tu_002","name":"Bash","input":{"command":"gh api repos/o/n/pulls/42","description":"Fetch PR 42 details"}}]}}
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_002","content":"{\"title\":\"Add foo\",\"body\":\"sample body\"}","is_error":false}]}}
{"type":"assistant","message":{"id":"msg_03","role":"assistant","content":[{"type":"text","text":"{\"prs\":[{\"number\":42,\"url\":\"https://example.com/pr/42\",\"title\":\"Add foo\"}],\"jira_issues\":[]}"}]}}
{"type":"result","subtype":"success","stop_reason":"end_turn","num_turns":3,"duration_ms":18742,"total_cost_usd":0.045}
```

- [ ] **Step 3: Write `source_collector_no_tools.jsonl`**

```jsonl
{"type":"system","subtype":"init","session_id":"sess-002","model":"claude-sonnet-4-6","cwd":"/repo","tools":["Bash","Read","Write","Edit","WebFetch"],"mcp_servers":[]}
{"type":"assistant","message":{"id":"msg_01","role":"assistant","content":[{"type":"text","text":"{\"prs\":[],\"jira_issues\":[]}"}]}}
{"type":"result","subtype":"success","stop_reason":"end_turn","num_turns":1,"duration_ms":2103,"total_cost_usd":0.008}
```

- [ ] **Step 4: Verify both fixtures parse as NDJSON**

Run:

```bash
python3 -c "
import json
from pathlib import Path
for name in ('source_collector_with_tools', 'source_collector_no_tools'):
    p = Path('tests/orchestrator/fixtures/cce12_stream_json') / f'{name}.jsonl'
    lines = [ln for ln in p.read_text().splitlines() if ln.strip()]
    parsed = [json.loads(ln) for ln in lines]
    print(f'{name}: {len(parsed)} events OK')
"
```

Expected output:

```
source_collector_with_tools: 7 events OK
source_collector_no_tools: 3 events OK
```

- [ ] **Step 5: Commit**

```bash
git add tests/orchestrator/fixtures/cce12_stream_json/
git commit -m "$(cat <<'EOF'
test(CCE-12): stream-json NDJSON fixtures for source-collector

Two fixtures covering the tool-use and no-tool-use cases. Both end with a
result event whose stop_reason is end_turn, mirroring the Claude Code CLI's
documented stream-json schema.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `_extract_final_assistant_text` Helper (TDD)

Pure function that walks a list of stream-json events and returns the concatenated text content of the LAST `assistant` message. Test before code.

**Files:**

- Create: `tests/orchestrator/test_dispatch_subagent_stream_json.py` (test module)
- Modify: `scripts/orchestrator_runner.py` (add helper at module level, before `dispatch_subagent`)

- [ ] **Step 1: Write the failing test for the happy path**

Create the new test file with this initial content:

```python
"""CCE-12: stream-json dispatch path — parse NDJSON, extract final text,
summarize tool use, persist forensics artifacts."""

from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cce12_stream_json"


def _load_events(fixture_name: str) -> list[dict]:
    path = _FIXTURE_DIR / fixture_name
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def test_extract_final_assistant_text_with_tools_fixture():
    import orchestrator_runner as runner

    events = _load_events("source_collector_with_tools.jsonl")
    text = runner._extract_final_assistant_text(events)

    parsed = json.loads(text)
    assert parsed == {
        "prs": [{"number": 42, "url": "https://example.com/pr/42", "title": "Add foo"}],
        "jira_issues": [],
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_subagent_stream_json.py::test_extract_final_assistant_text_with_tools_fixture -v
```

Expected: `AttributeError: module 'orchestrator_runner' has no attribute '_extract_final_assistant_text'`

- [ ] **Step 3: Implement `_extract_final_assistant_text` in `orchestrator_runner.py`**

Insert immediately above the existing `def dispatch_subagent(...)` (around line 75). Exact code:

```python
def _extract_final_assistant_text(events: list[dict]) -> str:
    """Concatenate all text blocks from the LAST assistant message in a
    stream-json event list. Returns empty string if no assistant message
    is present or the final assistant has no text blocks.

    The orchestrator's downstream contract is that dispatch returns the
    canonical JSON dict; in stream-json mode the canonical JSON is the text
    content of the final assistant turn — possibly split across multiple
    text blocks if the model interleaved tool_use blocks.
    """
    last_assistant: dict | None = None
    for ev in events:
        if ev.get("type") == "assistant":
            last_assistant = ev
    if last_assistant is None:
        return ""
    content = last_assistant.get("message", {}).get("content", [])
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_subagent_stream_json.py::test_extract_final_assistant_text_with_tools_fixture -v
```

Expected: `PASSED`

- [ ] **Step 5: Add edge-case tests for the helper**

Append to `tests/orchestrator/test_dispatch_subagent_stream_json.py`:

```python
def test_extract_final_assistant_text_no_assistant_returns_empty():
    import orchestrator_runner as runner

    events = [
        {"type": "system", "subtype": "init"},
        {"type": "result", "subtype": "success"},
    ]
    assert runner._extract_final_assistant_text(events) == ""


def test_extract_final_assistant_text_concatenates_multi_text_blocks():
    import orchestrator_runner as runner

    events = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "{\"prs\":"},
                    {"type": "tool_use", "id": "tu_x", "name": "Bash", "input": {}},
                    {"type": "text", "text": "[],\"jira_issues\":[]}"},
                ],
            },
        }
    ]
    assert runner._extract_final_assistant_text(events) == (
        '{"prs":[],"jira_issues":[]}'
    )


def test_extract_final_assistant_text_uses_last_assistant_only():
    import orchestrator_runner as runner

    events = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "first"}],
            },
        },
        {"type": "user", "message": {"role": "user", "content": []}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "last"}],
            },
        },
    ]
    assert runner._extract_final_assistant_text(events) == "last"
```

- [ ] **Step 6: Run all three new tests**

Run:

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_subagent_stream_json.py -v
```

Expected: 4 passed (1 from Step 1 + 3 from Step 5).

- [ ] **Step 7: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_dispatch_subagent_stream_json.py
git commit -m "$(cat <<'EOF'
feat(CCE-12): _extract_final_assistant_text helper for stream-json

Walks a stream-json event list and returns the concatenated text content
of the LAST assistant message. Handles the multi-block case where the
model interleaved tool_use blocks between text blocks.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `_summarize_tool_use` Helper (TDD)

Pure function that walks the event list and returns a structured summary: total calls, calls grouped by tool name, per-call detail (capped at 50), run-level metadata from the result event.

**Files:**

- Modify: `tests/orchestrator/test_dispatch_subagent_stream_json.py` (append tests)
- Modify: `scripts/orchestrator_runner.py` (add second helper)

- [ ] **Step 1: Write the failing test for the happy path**

Append to `tests/orchestrator/test_dispatch_subagent_stream_json.py`:

```python
def test_summarize_tool_use_with_tools_fixture():
    import orchestrator_runner as runner

    events = _load_events("source_collector_with_tools.jsonl")
    summary = runner._summarize_tool_use(events)

    assert summary["total_calls"] == 2
    assert summary["by_name"] == {"Bash": 2}
    assert summary["calls_truncated"] is False
    assert summary["turns"] == 3
    assert summary["stop_reason"] == "end_turn"
    assert summary["duration_ms"] == 18742

    assert len(summary["calls"]) == 2
    first = summary["calls"][0]
    assert first["name"] == "Bash"
    assert "gh pr list" in first["input_preview"]
    assert first["is_error"] is False
    assert first["result_chars"] > 0


def test_summarize_tool_use_no_tools_fixture():
    import orchestrator_runner as runner

    events = _load_events("source_collector_no_tools.jsonl")
    summary = runner._summarize_tool_use(events)

    assert summary["total_calls"] == 0
    assert summary["by_name"] == {}
    assert summary["calls"] == []
    assert summary["calls_truncated"] is False
    assert summary["turns"] == 1
    assert summary["stop_reason"] == "end_turn"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_subagent_stream_json.py::test_summarize_tool_use_with_tools_fixture tests/orchestrator/test_dispatch_subagent_stream_json.py::test_summarize_tool_use_no_tools_fixture -v
```

Expected: `AttributeError: module 'orchestrator_runner' has no attribute '_summarize_tool_use'`

- [ ] **Step 3: Implement `_summarize_tool_use` in `orchestrator_runner.py`**

Insert immediately below `_extract_final_assistant_text` (before `def dispatch_subagent`). Exact code:

```python
def _summarize_tool_use(events: list[dict]) -> dict:
    """Walk a stream-json event list and produce a tool-use summary.

    Two-pass algorithm:
      1. Collect `tool_result` outcomes keyed by `tool_use_id` from user events.
      2. Collect `tool_use` blocks from assistant events; join with outcomes
         from pass 1 so each call gets its `is_error` and `result_chars`.

    The `calls` list is capped at 50 to keep meta.json compact on chatty runs;
    `calls_truncated` flips True when the cap engages. Run-level fields
    (turns, stop_reason, duration_ms) come from the terminal `result` event.
    """
    errors_by_id: dict[str, bool] = {}
    result_chars_by_id: dict[str, int] = {}

    for ev in events:
        if ev.get("type") != "user":
            continue
        for block in ev.get("message", {}).get("content", []):
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tuid = block.get("tool_use_id", "")
            errors_by_id[tuid] = bool(block.get("is_error", False))
            content = block.get("content", "")
            if isinstance(content, list):
                content = "".join(
                    c.get("text", "") for c in content if isinstance(c, dict)
                )
            result_chars_by_id[tuid] = len(str(content))

    calls: list[dict] = []
    for ev in events:
        if ev.get("type") != "assistant":
            continue
        for block in ev.get("message", {}).get("content", []):
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tuid = block.get("id", "")
            input_preview = json.dumps(block.get("input", {}), default=str)[:200]
            calls.append(
                {
                    "name": block.get("name", ""),
                    "input_preview": input_preview,
                    "is_error": errors_by_id.get(tuid, False),
                    "result_chars": result_chars_by_id.get(tuid, 0),
                }
            )

    by_name: dict[str, int] = {}
    for c in calls:
        by_name[c["name"]] = by_name.get(c["name"], 0) + 1

    result_ev: dict = next(
        (e for e in events if e.get("type") == "result"), {}
    )

    return {
        "total_calls": len(calls),
        "by_name": by_name,
        "calls": calls[:50],
        "calls_truncated": len(calls) > 50,
        "turns": result_ev.get("num_turns"),
        "stop_reason": result_ev.get("stop_reason"),
        "duration_ms": result_ev.get("duration_ms"),
    }
```

- [ ] **Step 4: Run the two new tests**

Run:

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_subagent_stream_json.py::test_summarize_tool_use_with_tools_fixture tests/orchestrator/test_dispatch_subagent_stream_json.py::test_summarize_tool_use_no_tools_fixture -v
```

Expected: 2 passed.

- [ ] **Step 5: Add edge-case tests (errored call + cap engagement)**

Append to `tests/orchestrator/test_dispatch_subagent_stream_json.py`:

```python
def test_summarize_tool_use_flags_errored_tool_result():
    import orchestrator_runner as runner

    events = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tu_err", "name": "Bash",
                     "input": {"command": "gh pr list --bad"}},
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu_err",
                     "content": "error: unknown flag --bad", "is_error": True},
                ],
            },
        },
        {"type": "result", "subtype": "error", "stop_reason": "tool_error",
         "num_turns": 1, "duration_ms": 412},
    ]
    summary = runner._summarize_tool_use(events)
    assert summary["total_calls"] == 1
    assert summary["calls"][0]["is_error"] is True
    assert summary["stop_reason"] == "tool_error"


def test_summarize_tool_use_caps_calls_at_50_and_sets_truncated():
    import orchestrator_runner as runner

    # 51 tool_use blocks in a single assistant message — should cap at 50.
    events = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": f"tu_{i:03d}", "name": "Bash",
                     "input": {"command": f"echo {i}"}}
                    for i in range(51)
                ],
            },
        },
        {"type": "result", "subtype": "success", "stop_reason": "end_turn",
         "num_turns": 1, "duration_ms": 999},
    ]
    summary = runner._summarize_tool_use(events)
    assert summary["total_calls"] == 51
    assert len(summary["calls"]) == 50
    assert summary["calls_truncated"] is True
    assert summary["by_name"] == {"Bash": 51}
```

- [ ] **Step 6: Run the full test module**

Run:

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_subagent_stream_json.py -v
```

Expected: 8 passed (4 from Task 2 + 4 from Task 3).

- [ ] **Step 7: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_dispatch_subagent_stream_json.py
git commit -m "$(cat <<'EOF'
feat(CCE-12): _summarize_tool_use helper for stream-json events

Two-pass walk over the NDJSON event list. Collects tool_result outcomes by
id, then joins with tool_use blocks so each call carries is_error and
result_chars. Caps calls list at 50 to keep meta.json compact; sets
calls_truncated when the cap engages.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Wire Helpers Into `dispatch_subagent` (TDD)

This is the integration step. When `DOCS_AGENT_DEBUG_DIR` is set, the dispatch path now uses `--output-format stream-json --verbose`, parses the NDJSON, extracts the final assistant text as the canonical JSON dict, and writes the additional `<agent>.stream.jsonl` artifact plus a `tool_use` block inside `<agent>.meta.json`. When the gate is off, behavior is unchanged.

**Files:**

- Modify: `tests/orchestrator/test_dispatch_subagent_stream_json.py` (append integration tests)
- Modify: `scripts/orchestrator_runner.py` (lines 75–153 — `dispatch_subagent` itself)

- [ ] **Step 1: Write the failing integration test for the gate-ON path**

Append to `tests/orchestrator/test_dispatch_subagent_stream_json.py`:

```python
class _FakeCompleted:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_dispatch_uses_stream_json_when_debug_dir_set(tmp_path, monkeypatch):
    import orchestrator_runner as runner

    fixture = _FIXTURE_DIR / "source_collector_with_tools.jsonl"
    ndjson_stdout = fixture.read_text()

    captured_argv: list[list[str]] = []

    def fake_run(*args, **kwargs):
        captured_argv.append(list(args[0]))
        return _FakeCompleted(stdout=ndjson_stdout)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setenv("DOCS_AGENT_DEBUG_DIR", str(tmp_path))

    result = runner.dispatch_subagent(
        "source-collector",
        {"last_sha": "x", "head_sha": "y", "repo": {"owner": "o", "name": "n"}},
        dry_run_dir=None,
    )

    # 1. Caller contract preserved: parsed dict comes from the final assistant text.
    assert result == {
        "prs": [{"number": 42, "url": "https://example.com/pr/42", "title": "Add foo"}],
        "jira_issues": [],
    }

    # 2. Subprocess argv carries the stream-json flags.
    assert len(captured_argv) == 1
    argv = captured_argv[0]
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv

    # 3. All five forensics artifacts written.
    artifacts = sorted(p.name for p in tmp_path.iterdir())
    suffixes = {name.split(".", 1)[1] for name in artifacts}
    assert suffixes == {
        "prompt.txt",
        "stdout.txt",
        "stderr.txt",
        "stream.jsonl",
        "meta.json",
    }, f"got {artifacts}"

    # 4. stdout.txt = extracted canonical JSON (caller view), NOT raw NDJSON.
    stdout_file = next(p for p in tmp_path.iterdir() if p.name.endswith(".stdout.txt"))
    assert json.loads(stdout_file.read_text()) == result

    # 5. stream.jsonl = raw NDJSON bytes (forensics).
    stream_file = next(p for p in tmp_path.iterdir() if p.name.endswith(".stream.jsonl"))
    assert stream_file.read_text() == ndjson_stdout

    # 6. meta.json includes the tool_use summary block.
    meta_file = next(p for p in tmp_path.iterdir() if p.name.endswith(".meta.json"))
    meta = json.loads(meta_file.read_text())
    assert meta["returncode"] == 0
    assert "source-collector" in meta["argv"]
    assert meta["tool_use"]["total_calls"] == 2
    assert meta["tool_use"]["by_name"] == {"Bash": 2}
    assert meta["tool_use"]["stop_reason"] == "end_turn"
```

- [ ] **Step 2: Write the failing integration test for the gate-OFF path**

Append to the same file:

```python
def test_dispatch_uses_simple_print_when_debug_dir_unset(tmp_path, monkeypatch):
    import orchestrator_runner as runner

    captured_argv: list[list[str]] = []

    def fake_run(*args, **kwargs):
        captured_argv.append(list(args[0]))
        return _FakeCompleted(stdout='{"prs":[],"jira_issues":[]}')

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.delenv("DOCS_AGENT_DEBUG_DIR", raising=False)

    result = runner.dispatch_subagent(
        "source-collector",
        {"last_sha": "x", "head_sha": "y", "repo": {"owner": "o", "name": "n"}},
        dry_run_dir=None,
    )

    assert result == {"prs": [], "jira_issues": []}

    # No stream-json flags in argv when gate is off.
    argv = captured_argv[0]
    assert "--output-format" not in argv
    assert "--verbose" not in argv

    # No debug artifacts written.
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 3: Run both new tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_subagent_stream_json.py::test_dispatch_uses_stream_json_when_debug_dir_set tests/orchestrator/test_dispatch_subagent_stream_json.py::test_dispatch_uses_simple_print_when_debug_dir_unset -v
```

Expected: both FAIL. The stream-json test fails because the current dispatcher tries `json.loads(r.stdout)` on multi-line NDJSON (which raises) and returns None; even if it didn't, no `--output-format` flag is in argv and no `.stream.jsonl` is written. The gate-off test would currently pass only the parse assertion but the argv check is incidental — it would actually pass today since gate-off behavior matches. Run it to confirm baseline.

- [ ] **Step 4: Refactor `dispatch_subagent` to branch on `DOCS_AGENT_DEBUG_DIR`**

Replace lines 75–153 of `scripts/orchestrator_runner.py` with the new branching implementation. Exact code (the section being replaced spans from `def dispatch_subagent(` through the final `return json.loads(stdout)` / `except` block, before `dispatch_validated`):

```python
def dispatch_subagent(
    name: str,
    inputs: dict,
    *,
    dry_run_dir: Path | None,
    cwd: Path | None = None,
) -> dict | None:
    """Dispatch a subagent. Returns parsed JSON output, or None on failure.

    In dry-run mode, reads from `<dry_run_dir>/fake_<name_with_underscores>.json`
    instead of invoking Claude. Returns None if the fixture is missing.

    In production, the subprocess invocation:
    - wraps `inputs` in execution framing so Claude executes the agent's
      Job rather than analyzing the JSON as content (CCE-3 A)
    - sets `cwd` so the agent loads the target repo's CLAUDE.md and its
      git/gh state, not the plugin's (CCE-3 B)
    - passes `--plugin-dir` and `--allowedTools` so agents resolve and can
      run their declared tools non-interactively (CCE-3 C)

    When DOCS_AGENT_DEBUG_DIR is set (CCE-9 + CCE-12):
    - dispatch uses `--output-format stream-json --verbose` so we observe
      ground-truth tool-call sequence
    - raw NDJSON event stream is persisted to <agent>.stream.jsonl
    - extended <agent>.meta.json carries a tool_use summary block
    - the dict returned to callers is parsed from the FINAL assistant
      message's concatenated text content (caller contract preserved)

    Returns None if:
    - the `claude` binary is not installed (FileNotFoundError)
    - the subagent process exits with a non-zero return code
    - the subagent emits empty stdout (or in stream-json mode, no assistant text)
    - the subagent emits unparseable JSON
    """
    if dry_run_dir is not None:
        fixture = dry_run_dir / f"fake_{name.replace('-', '_')}.json"
        if not fixture.exists():
            return None
        return load_json(fixture)

    prompt = _EXECUTION_FRAMING.format(payload=json.dumps(inputs))
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
    debug_dir = os.environ.get("DOCS_AGENT_DEBUG_DIR")
    argv = (
        base_argv + ["--output-format", "stream-json", "--verbose"]
        if debug_dir
        else base_argv
    )

    run_kwargs: dict = {"capture_output": True, "text": True, "check": False}
    if cwd is not None:
        run_kwargs["cwd"] = str(cwd)
    # CCE-10: pass CLAUDE_STOP_VERIFY=0 so the global stop-verify hook does
    # not contaminate subagent stdout with a "Verification statement:" prose
    # preamble that breaks json.loads(). See agents/source-collector.md and
    # ~/.claude/hooks/stop-verify.sh:22.
    run_kwargs["env"] = {**os.environ, "CLAUDE_STOP_VERIFY": "0"}
    try:
        r = subprocess.run(argv, **run_kwargs)
    except FileNotFoundError:
        return None

    # Parse subagent output. In stream-json mode the canonical JSON is the
    # final assistant message's text content; in simple-print mode it IS
    # the raw stdout.
    raw_stdout = r.stdout or ""
    tool_use_summary: dict | None = None
    if debug_dir:
        events: list[dict] = []
        for line in raw_stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip malformed lines; raw stream.jsonl preserves them for forensics.
                continue
        canonical_text = _extract_final_assistant_text(events)
        tool_use_summary = _summarize_tool_use(events)
    else:
        canonical_text = raw_stdout

    # CCE-9 + CCE-12: when DOCS_AGENT_DEBUG_DIR is set, write forensics
    # artifacts. The extra stream.jsonl is stream-json-only; the tool_use
    # block in meta.json is also stream-json-only.
    if debug_dir:
        debug_path = Path(debug_dir)
        debug_path.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        base = debug_path / f"{ts}-{name}"
        base.with_suffix(".prompt.txt").write_text(prompt)
        # stdout.txt holds the caller view (extracted canonical JSON), so
        # readers can diff against the simple-print mode's stdout.txt
        # without knowing which dispatch path produced it.
        base.with_suffix(".stdout.txt").write_text(canonical_text)
        base.with_suffix(".stderr.txt").write_text(r.stderr or "")
        base.with_suffix(".stream.jsonl").write_text(raw_stdout)
        meta_payload: dict = {"returncode": r.returncode, "argv": argv}
        if tool_use_summary is not None:
            meta_payload["tool_use"] = tool_use_summary
        base.with_suffix(".meta.json").write_text(
            json.dumps(meta_payload, indent=2)
        )

    if r.returncode != 0:
        return None
    canonical_text = canonical_text.strip()
    if not canonical_text:
        return None
    try:
        return json.loads(canonical_text)
    except json.JSONDecodeError:
        return None
```

- [ ] **Step 5: Run the two integration tests to verify they pass**

Run:

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_subagent_stream_json.py::test_dispatch_uses_stream_json_when_debug_dir_set tests/orchestrator/test_dispatch_subagent_stream_json.py::test_dispatch_uses_simple_print_when_debug_dir_unset -v
```

Expected: 2 passed.

- [ ] **Step 6: Run the full new test module**

Run:

```bash
.venv/bin/pytest tests/orchestrator/test_dispatch_subagent_stream_json.py -v
```

Expected: 10 passed (4 from Task 2 + 4 from Task 3 + 2 from Task 4).

- [ ] **Step 7: Run the full test suite to confirm no regressions**

Run:

```bash
.venv/bin/pytest tests/ -v
```

Expected: all existing tests pass. The CCE-9 capture test (`test_dispatch_debug_capture.py`) used to assert exactly 4 suffixes — verify that test still passes given the refactor. The CCE-9 test sets `DOCS_AGENT_DEBUG_DIR` and monkeypatches `subprocess.run` with simple JSON stdout (not NDJSON), so it now flows through the stream-json branch with malformed events (the single JSON object is not valid NDJSON — it's one valid line, so it parses as one `event` dict with no `type`). The new branch will then write a `.stream.jsonl` (with the simple JSON in it) and a `meta.json` with `tool_use` keys whose values are mostly None. The existing test's assertion `suffixes == {"prompt.txt", "stdout.txt", "stderr.txt", "meta.json"}` will FAIL because we now also write `.stream.jsonl`.

- [ ] **Step 8: Update `test_dispatch_debug_capture.py` to reflect the new artifact set**

This is expected fallout from the design — the CCE-9 test asserted on an artifact set that the spec now extends. Modify `tests/orchestrator/test_dispatch_debug_capture.py`:

In `test_debug_capture_writes_files_when_env_var_set`, replace:

```python
    captured = sorted(tmp_path.iterdir())
    suffixes = {p.name.split(".", 1)[1] for p in captured}
    assert suffixes == {"prompt.txt", "stdout.txt", "stderr.txt", "meta.json"}, (
        f"expected 4 capture artifacts; got {sorted(p.name for p in captured)}"
    )

    stdout_file = next(p for p in captured if p.name.endswith(".stdout.txt"))
    assert stdout_file.read_text() == fake_stdout
```

with:

```python
    captured = sorted(tmp_path.iterdir())
    suffixes = {p.name.split(".", 1)[1] for p in captured}
    assert suffixes == {
        "prompt.txt", "stdout.txt", "stderr.txt", "stream.jsonl", "meta.json",
    }, (
        f"expected 5 capture artifacts; got {sorted(p.name for p in captured)}"
    )

    # CCE-12: in stream-json mode, stdout.txt holds the extracted final
    # assistant text. Our fake CompletedProcess used a single JSON object
    # as stdout (not real NDJSON), so the parser sees zero assistant events
    # and the extracted text is empty.
    stdout_file = next(p for p in captured if p.name.endswith(".stdout.txt"))
    assert stdout_file.read_text() == ""

    # Raw fake stdout is preserved in stream.jsonl for forensics.
    stream_file = next(p for p in captured if p.name.endswith(".stream.jsonl"))
    assert stream_file.read_text() == fake_stdout
```

Also adjust the assertion on the dispatch result. Today the test expects `result == {"prs": [], "jira_issues": []}`. With the new branch, since the fake stdout isn't real NDJSON, the extracted text is empty and `dispatch_subagent` returns `None`. Change:

```python
    assert result == {"prs": [], "jira_issues": []}
```

to:

```python
    # CCE-12: with DOCS_AGENT_DEBUG_DIR set the dispatcher uses stream-json.
    # This test's fake stdout is a single JSON object (not real NDJSON), so
    # no assistant events are found and the canonical text is empty -> None.
    # The capture artifacts are still written for forensics regardless.
    assert result is None
```

- [ ] **Step 9: Run the full test suite again**

Run:

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_dispatch_subagent_stream_json.py tests/orchestrator/test_dispatch_debug_capture.py
git commit -m "$(cat <<'EOF'
feat(CCE-12): stream-json dispatch path with tool-use diagnostics

dispatch_subagent now branches on DOCS_AGENT_DEBUG_DIR:
- gate ON  -> claude -p ... --output-format stream-json --verbose;
              parse NDJSON; extract final assistant text as canonical JSON;
              write <agent>.stream.jsonl (raw) and tool_use block in meta.json
- gate OFF -> existing simple --print path, byte-for-byte unchanged

Caller contract preserved: dispatch_subagent still returns dict|None. The
new <agent>.stdout.txt holds the caller view (extracted canonical JSON)
regardless of dispatch mode, so forensics readers can diff across modes.

The CCE-9 debug-capture test was updated to reflect the new 5-artifact
set and the empty-text fallback for non-NDJSON fake stdouts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 5-Run Mode B Measurement Ceremony

Run the production source-collector dispatch 5 consecutive times with `DOCS_AGENT_DEBUG_DIR` set, capture all artifacts, and write the measurement doc with per-run categorization.

**Files:**

- Create: `docs/superpowers/measurements/2026-05-20-cce12-tool-use-baseline.md`
- Create (generated): `docs/superpowers/measurements/2026-05-20-cce12-run<N>-source-collector.{stream.jsonl,meta.json,stdout.txt,stderr.txt,prompt.txt}` for N = 1..5

- [ ] **Step 1: Determine the dispatch window**

Run:

```bash
git log --oneline -1
git log --oneline main..HEAD
```

The `head_sha` for the dispatch is the current `HEAD`. The `last_sha` is the most recent commit on `main` before this branch diverged — use the same window CCE-10 used for comparability:

```bash
LAST_SHA=$(git log --format=%H main -1)
HEAD_SHA=$(git rev-parse HEAD)
echo "last_sha=$LAST_SHA"
echo "head_sha=$HEAD_SHA"
```

Record these two values; you will reuse them across all 5 runs.

- [ ] **Step 2: Set the dispatch payload**

Compose the JSON input the orchestrator would normally hand to the source-collector. Save to a temp file so each run reads the same input:

```bash
cat > /tmp/cce12-dispatch-input.json <<EOF
{
  "last_sha": "$LAST_SHA",
  "head_sha": "$HEAD_SHA",
  "repo": {"owner": "theoju", "name": "engineering-docs-agent"},
  "pr_branch_filter": ["docs-agent/*"]
}
EOF
cat /tmp/cce12-dispatch-input.json
```

Expected: JSON with both SHAs populated and the repo set to the self-host target.

- [ ] **Step 3: Run iteration 1 with diagnostics on**

Run (replace `<PLUGIN_ROOT>` with the absolute path to this repo):

```bash
mkdir -p /tmp/cce12-run1
DOCS_AGENT_DEBUG_DIR=/tmp/cce12-run1 \
CLAUDE_STOP_VERIFY=0 \
python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from orchestrator_runner import dispatch_subagent

inputs = json.loads(Path('/tmp/cce12-dispatch-input.json').read_text())
result = dispatch_subagent('source-collector', inputs, dry_run_dir=None)
print(json.dumps(result, indent=2) if result else 'DISPATCH RETURNED None')
"
ls -la /tmp/cce12-run1
```

Expected: a `<ts>-source-collector.stream.jsonl`, `.stdout.txt`, `.stderr.txt`, `.prompt.txt`, `.meta.json` in `/tmp/cce12-run1`. The script prints either the parsed dict or `DISPATCH RETURNED None`.

- [ ] **Step 4: Copy run 1 artifacts into the measurements directory**

```bash
mkdir -p docs/superpowers/measurements
cp /tmp/cce12-run1/*-source-collector.stream.jsonl docs/superpowers/measurements/2026-05-20-cce12-run1-source-collector.stream.jsonl
cp /tmp/cce12-run1/*-source-collector.stdout.txt   docs/superpowers/measurements/2026-05-20-cce12-run1-source-collector.stdout.txt
cp /tmp/cce12-run1/*-source-collector.stderr.txt   docs/superpowers/measurements/2026-05-20-cce12-run1-source-collector.stderr.txt
cp /tmp/cce12-run1/*-source-collector.prompt.txt   docs/superpowers/measurements/2026-05-20-cce12-run1-source-collector.prompt.txt
cp /tmp/cce12-run1/*-source-collector.meta.json    docs/superpowers/measurements/2026-05-20-cce12-run1-source-collector.meta.json
```

- [ ] **Step 5: Repeat Step 3 + Step 4 for runs 2 through 5**

Each iteration uses its own `/tmp/cce12-run<N>` debug dir and copies into `2026-05-20-cce12-run<N>-source-collector.*`. Do them serially, not in parallel — we want fresh subagent contexts.

For run N (substitute N = 2, 3, 4, 5):

```bash
mkdir -p /tmp/cce12-runN
DOCS_AGENT_DEBUG_DIR=/tmp/cce12-runN \
CLAUDE_STOP_VERIFY=0 \
python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from orchestrator_runner import dispatch_subagent
inputs = json.loads(Path('/tmp/cce12-dispatch-input.json').read_text())
result = dispatch_subagent('source-collector', inputs, dry_run_dir=None)
print(json.dumps(result, indent=2) if result else 'DISPATCH RETURNED None')
"
cp /tmp/cce12-runN/*-source-collector.stream.jsonl docs/superpowers/measurements/2026-05-20-cce12-runN-source-collector.stream.jsonl
cp /tmp/cce12-runN/*-source-collector.stdout.txt   docs/superpowers/measurements/2026-05-20-cce12-runN-source-collector.stdout.txt
cp /tmp/cce12-runN/*-source-collector.stderr.txt   docs/superpowers/measurements/2026-05-20-cce12-runN-source-collector.stderr.txt
cp /tmp/cce12-runN/*-source-collector.prompt.txt   docs/superpowers/measurements/2026-05-20-cce12-runN-source-collector.prompt.txt
cp /tmp/cce12-runN/*-source-collector.meta.json    docs/superpowers/measurements/2026-05-20-cce12-runN-source-collector.meta.json
```

- [ ] **Step 6: Extract per-run categorization data**

For each run, read the `meta.json` and `stdout.txt` to compute the row. Use this helper script — run it from the repo root:

```bash
python3 -c "
import json
from pathlib import Path

rows = []
for n in range(1, 6):
    meta = json.loads(Path(f'docs/superpowers/measurements/2026-05-20-cce12-run{n}-source-collector.meta.json').read_text())
    stdout_text = Path(f'docs/superpowers/measurements/2026-05-20-cce12-run{n}-source-collector.stdout.txt').read_text().strip()
    try:
        result = json.loads(stdout_text) if stdout_text else {}
    except json.JSONDecodeError:
        result = {}
    tu = meta.get('tool_use', {}) or {}
    total = tu.get('total_calls', 0)
    by_name = tu.get('by_name', {})
    stop = tu.get('stop_reason')
    prs_n = len(result.get('prs', []))
    jira_n = len(result.get('jira_issues', []))
    has_error = any(c.get('is_error') for c in tu.get('calls', []))
    if total == 0:
        cat = 'A: zero tool calls'
    elif has_error:
        cat = 'D: tool errored'
    elif prs_n == 0 and any(c.get('result_chars', 0) > 50 for c in tu.get('calls', [])):
        cat = 'B: called and discarded'
    elif prs_n == 0:
        cat = 'C: legitimately empty'
    else:
        cat = 'data returned'
    rows.append((n, total, by_name, stop, prs_n, jira_n, cat))

print(f'{\"run\":<4} {\"total\":<6} {\"by_name\":<25} {\"stop\":<14} {\"prs\":<4} {\"jira\":<5} category')
print('-' * 90)
for r in rows:
    print(f'{r[0]:<4} {r[1]:<6} {str(r[2]):<25} {str(r[3]):<14} {r[4]:<4} {r[5]:<5} {r[6]}')
"
```

Record the table output — this is the raw data for the measurement doc.

- [ ] **Step 7: Write the measurement doc**

Create `docs/superpowers/measurements/2026-05-20-cce12-tool-use-baseline.md` with this structure (fill in real numbers from Step 6's output):

```markdown
# CCE-12: Source-Collector Tool-Use Baseline — 5-Run Mode B Ceremony

**Jira:** [CCE-12](https://designitright.atlassian.net/browse/CCE-12)
**Branch:** `feat/CCE-12-source-collector-tool-use-diagnostics`
**Date:** 2026-05-20
**Dispatch window:** `<LAST_SHA>..<HEAD_SHA>` on theoju/engineering-docs-agent
**PR filter:** `docs-agent/*`
**Diagnostic:** `DOCS_AGENT_DEBUG_DIR` set; stream-json dispatch path

## Per-run summary

| Run | total_calls | by_name | stop_reason | prs | jira_issues | category  |
| --: | ----------: | ------- | ----------- | --: | ----------: | --------- |
|   1 |         <N> | <{...}> | <reason>    | <N> |         <N> | <A/B/C/D> |
|   2 |         ... | ...     | ...         | ... |         ... | ...       |
|   3 |         ... | ...     | ...         | ... |         ... | ...       |
|   4 |         ... | ...     | ...         | ... |         ... | ...       |
|   5 |         ... | ...     | ...         | ... |         ... | ...       |

Raw artifacts: `2026-05-20-cce12-run<N>-source-collector.{stream.jsonl,stdout.txt,stderr.txt,prompt.txt,meta.json}` in this directory.

## Category definitions

- **A — Zero tool calls:** `total_calls == 0`. Agent emitted JSON without invoking any tool.
- **B — Called and discarded:** non-zero `total_calls`, non-trivial `result_chars` from at least one call, but `prs == []`. Agent saw real data and dropped it.
- **C — Legitimately empty:** non-zero `total_calls`, no errors, but the tool's own output was empty (e.g. `gh pr list` returned nothing for the window). `prs == []` is correct.
- **D — Tool errored:** any call has `is_error: true`. Agent's downstream behavior is moot until the tool itself works.

## Dominant pattern

<One-paragraph analysis: which category appears in the majority of runs and what that implies. Example skeletons depending on the dominant pattern:>

- If **A dominates:** the agent is skipping tools entirely. Root cause likely lives in `agents/source-collector.md`'s Procedure section or the `_EXECUTION_FRAMING` prompt. Follow-up ticket should focus on prompt clarity / explicit tool-call requirement.
- If **B dominates:** the agent calls tools, sees data, then fails to incorporate it. Root cause likely lives in parsing / reasoning between tool result and final answer. Follow-up should focus on response-construction guidance.
- If **C dominates:** there's no bug — the windows we tested were actually empty. Re-run against a window with known PRs to confirm.
- If **D dominates:** tool invocation itself is broken (auth, allowedTools mismatch, environment). Fix the tool surface before any agent-prompt work.

## Follow-up ticket

Based on the dominant pattern, file `CCE-<N>` with the specific fix. CCE-12 itself stays closed once this doc is committed — it shipped the instrument, not the cure.
```

- [ ] **Step 8: Commit the measurement artifacts and doc**

```bash
git add docs/superpowers/measurements/2026-05-20-cce12-tool-use-baseline.md docs/superpowers/measurements/2026-05-20-cce12-run*-source-collector.*
git commit -m "$(cat <<'EOF'
docs(CCE-12): tool-use baseline — 5-run Mode B ceremony with diagnostics

Re-ran the CCE-10 5-run ceremony with DOCS_AGENT_DEBUG_DIR set so the
stream-json branch captures full tool-call sequence per run. Per-run
table classifies each outcome (A: zero tool calls / B: called and
discarded / C: legitimately empty / D: errored) and the dominant
pattern guides the follow-up fix ticket.

Raw stream.jsonl / meta.json / stdout.txt / stderr.txt / prompt.txt
artifacts checked in for auditability.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review checklist (run before claiming done)

- [ ] All 5 Task-1 fixture lines parse as JSON; no trailing comma or stray formatter newlines.
- [ ] `_extract_final_assistant_text` and `_summarize_tool_use` are module-level (not nested inside `dispatch_subagent`) so the tests can import them directly.
- [ ] `dispatch_subagent` still returns `dict | None` (no signature change).
- [ ] When `DOCS_AGENT_DEBUG_DIR` is unset, `subprocess.run` is invoked with the SAME argv as before this change (no stream-json flags leak).
- [ ] `<agent>.stdout.txt` in stream-json mode = extracted canonical JSON text, NOT raw NDJSON (raw goes to `.stream.jsonl`).
- [ ] `<agent>.meta.json` includes a `tool_use` block ONLY in stream-json mode.
- [ ] CCE-9's `test_dispatch_debug_capture.py` updated to reflect the new 5-artifact set; full test suite green.
- [ ] Measurement doc names the dominant category and the implied follow-up.
