# CCE-7: Per-agent `--allowedTools` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the union-of-all-tools `--allowedTools` grant in `dispatch_subagent` with per-agent declarations parsed from each agent's `.md` frontmatter.

**Architecture:** Add a module-level helper `_load_agent_allowed_tools()` that parses YAML frontmatter from `agents/<name>.md` files. `dispatch_subagent` consults this for the agent being dispatched and passes only the declared tools. Agents with no `tools:` frontmatter get no `--allowedTools` flag (default permissioning per CCE-7 acceptance #3).

**Tech Stack:** Python stdlib + `pyyaml` (already a project dep). pytest for unit tests.

**Spec reference:** `docs/superpowers/specs/2026-05-22-cce6-7-8-batch-design.md` — CCE-7 section.

---

## File Structure

- **Modify:** `scripts/orchestrator_runner.py` — add `_load_agent_allowed_tools()` helper near the `_AGENT_ALLOWED_TOOLS` constant (line ~63); update `dispatch_subagent` (line ~282) to use per-agent tools.
- **Test:** `tests/orchestrator/test_dispatch_subagent_allowed_tools.py` (create) — unit tests for the new behavior.

The seven agent `.md` files already declare `tools:` correctly (verified by inspection):

| Agent             | Declared tools       |
| ----------------- | -------------------- |
| content-validator | Bash, Read           |
| gap-detector      | Read                 |
| notifier          | Bash                 |
| page-author       | Read, Edit, Write    |
| pr-summarizer     | Read                 |
| publish-verifier  | Bash, WebFetch       |
| source-collector  | Bash, Read, WebFetch |

So this plan changes ONLY `scripts/orchestrator_runner.py` + adds one test file. No agent `.md` file is touched.

---

## Task 1: Failing tests for per-agent `--allowedTools`

**Files:**

- Test: `tests/orchestrator/test_dispatch_subagent_allowed_tools.py` (create)

- [ ] **Step 1: Write the failing tests**

Write `tests/orchestrator/test_dispatch_subagent_allowed_tools.py`:

```python
"""CCE-7: dispatch_subagent must pass only the agent's declared tools
to --allowedTools, not the union of all agents' tools.

Locks the per-agent argv shape for two representative agents:
- pr-summarizer declares only ["Read"] — expect --allowedTools "Read".
- page-author declares ["Read", "Edit", "Write"] — expect those three.

Also pins the "no tools frontmatter" case via a synthetic agent fixture:
when the parser finds no tools list, dispatch omits --allowedTools entirely.
"""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner  # noqa: E402


def _fake_run_capture(captured: dict, *, stdout: str = '{"ok": true}', returncode: int = 0):
    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")
    return fake_run


def _allowed_tools_arg(cmd: list[str]) -> str | None:
    """Return the string passed to --allowedTools in this argv, or None if absent."""
    for i, token in enumerate(cmd):
        if token == "--allowedTools" and i + 1 < len(cmd):
            return cmd[i + 1]
    return None


def test_pr_summarizer_gets_only_read(monkeypatch):
    """pr-summarizer's frontmatter declares only Read; argv must reflect that."""
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_capture(captured))

    orchestrator_runner.dispatch_subagent(
        "pr-summarizer", {"foo": "bar"}, dry_run_dir=None
    )

    arg = _allowed_tools_arg(captured["cmd"])
    assert arg is not None, f"--allowedTools missing from argv; got {captured['cmd']}"
    tools = set(arg.split())
    assert tools == {"Read"}, f"expected just Read; got {tools}"


def test_page_author_gets_declared_three(monkeypatch):
    """page-author declares Read, Edit, Write."""
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_capture(captured))

    orchestrator_runner.dispatch_subagent(
        "page-author", {"foo": "bar"}, dry_run_dir=None
    )

    arg = _allowed_tools_arg(captured["cmd"])
    assert arg is not None, f"--allowedTools missing from argv; got {captured['cmd']}"
    tools = set(arg.split())
    assert tools == {"Read", "Edit", "Write"}, f"expected Read/Edit/Write; got {tools}"


def test_agent_without_tools_frontmatter_omits_allowed_tools_flag(
    monkeypatch, tmp_path: Path
):
    """When an agent's .md has no tools: list, --allowedTools is omitted entirely.

    Constructs a synthetic agent .md in tmp_path with no tools frontmatter,
    points the loader at the synthetic directory, and asserts the resulting
    argv has no --allowedTools flag at all.
    """
    # Synthetic agent file with no tools: list
    fake_agents_dir = tmp_path / "agents"
    fake_agents_dir.mkdir()
    (fake_agents_dir / "no-tools-agent.md").write_text(
        "---\nname: no-tools-agent\ndescription: A test agent.\nmodel: sonnet\n---\n\n# no-tools-agent\n\nDoes nothing.\n"
    )

    # Point the agents-dir helper at the synthetic dir for this test
    monkeypatch.setattr(
        orchestrator_runner, "_AGENTS_DIR", fake_agents_dir
    )
    # Also clear any cached frontmatter so the synthetic file is read fresh
    if hasattr(orchestrator_runner, "_AGENT_TOOLS_CACHE"):
        orchestrator_runner._AGENT_TOOLS_CACHE.clear()

    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_capture(captured))

    orchestrator_runner.dispatch_subagent(
        "no-tools-agent", {"foo": "bar"}, dry_run_dir=None
    )

    assert "--allowedTools" not in captured["cmd"], (
        f"expected --allowedTools absent for no-tools agent; got {captured['cmd']}"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_dispatch_subagent_allowed_tools.py -v`

Expected: all 3 tests FAIL. Failures will be on the assertion — current code passes the union `"Bash Read Write Edit WebFetch"` for every agent, so `pr-summarizer` argv contains all 5 tools, not just `Read`. The third test will also fail because the symbol `_AGENTS_DIR` / `_AGENT_TOOLS_CACHE` doesn't exist yet (AttributeError) — that's expected; Task 2 introduces them.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/orchestrator/test_dispatch_subagent_allowed_tools.py
git commit -m "$(cat <<'EOF'
test(CCE-7): failing tests for per-agent --allowedTools

Pin the contract that dispatch_subagent passes only the agent's
declared tools (parsed from agents/<name>.md frontmatter) instead
of the union. Three cases: pr-summarizer (Read), page-author
(Read/Edit/Write), synthetic agent with no tools frontmatter
(omit --allowedTools entirely).

Refs: docs/superpowers/specs/2026-05-22-cce6-7-8-batch-design.md (CCE-7)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add `_load_agent_allowed_tools` helper

**Files:**

- Modify: `scripts/orchestrator_runner.py` — add helper + cache near existing `_AGENT_ALLOWED_TOOLS` constant.

- [ ] **Step 1: Read the current top-of-file constants**

Run: `sed -n '1,70p' scripts/orchestrator_runner.py`

You'll see existing constants and helpers. The new helper goes just below `_AGENT_ALLOWED_TOOLS: tuple[str, ...] = ("Bash", "Read", "Write", "Edit", "WebFetch")` at line ~63.

- [ ] **Step 2: Add the helper and module-level cache**

Insert this block immediately after the `_AGENT_ALLOWED_TOOLS` line:

```python
_AGENTS_DIR: Path = Path(__file__).parent.parent / "agents"
_AGENT_TOOLS_CACHE: dict[str, tuple[str, ...] | None] = {}


def _load_agent_allowed_tools(name: str) -> tuple[str, ...] | None:
    """Parse `tools:` YAML frontmatter from agents/<name>.md.

    Returns a tuple of tool names if the agent declares them, or None
    if the agent has no `tools:` frontmatter (caller should omit
    --allowedTools entirely for that case).

    Result is cached per agent name; clear _AGENT_TOOLS_CACHE in tests
    that swap _AGENTS_DIR.
    """
    if name in _AGENT_TOOLS_CACHE:
        return _AGENT_TOOLS_CACHE[name]

    agent_path = _AGENTS_DIR / f"{name}.md"
    if not agent_path.exists():
        _AGENT_TOOLS_CACHE[name] = None
        return None

    text = agent_path.read_text()
    # Frontmatter is delimited by lines that are exactly "---".
    parts = text.split("\n---\n", 2) if text.startswith("---\n") else []
    # text starts with "---\n", then frontmatter, then "\n---\n", then body
    if text.startswith("---\n"):
        # split on the first "\n---\n" after the opening "---\n"
        body_split = text[4:].split("\n---\n", 1)
        if len(body_split) == 2:
            fm_text = body_split[0]
        else:
            _AGENT_TOOLS_CACHE[name] = None
            return None
    else:
        _AGENT_TOOLS_CACHE[name] = None
        return None

    fm = yaml.safe_load(fm_text) or {}
    tools = fm.get("tools")
    if tools is None:
        _AGENT_TOOLS_CACHE[name] = None
        return None
    if not isinstance(tools, list):
        # Malformed: surface clearly rather than fall back to the union.
        raise ValueError(
            f"agent {name}: 'tools' frontmatter must be a YAML list; got {type(tools).__name__}"
        )

    result = tuple(str(t) for t in tools)
    _AGENT_TOOLS_CACHE[name] = result
    return result
```

- [ ] **Step 3: Verify `yaml` is already imported**

Run: `grep -n "^import yaml\|^from yaml" scripts/orchestrator_runner.py`

Expected: yaml is already imported (state_io.py uses it; orchestrator_runner.py imports state_io functions and may import yaml directly).

If yaml is NOT imported at module level in orchestrator_runner.py, add `import yaml` to the imports block at the top of the file.

- [ ] **Step 4: Run the new tests partially (Task 2 only completes 1 of 3 yet)**

Run: `python3 -m pytest tests/orchestrator/test_dispatch_subagent_allowed_tools.py -v`

Expected: still 3 failures. The helper exists but `dispatch_subagent` doesn't use it yet — Task 3 wires it up.

But: the third test (`test_agent_without_tools_frontmatter_omits_allowed_tools_flag`) should now fail at the ASSERTION about `--allowedTools` being absent, NOT at the AttributeError on `_AGENTS_DIR`. If you still see AttributeError, the helper isn't visible — re-read your edits.

- [ ] **Step 5: Commit the helper**

```bash
git add scripts/orchestrator_runner.py
git commit -m "$(cat <<'EOF'
feat(CCE-7): _load_agent_allowed_tools helper parses agent frontmatter

Adds module-level helper + cache for reading the `tools:` YAML list
from agents/<name>.md. Returns None when the agent has no tools
frontmatter (signal to caller: omit --allowedTools entirely).
Raises ValueError on malformed `tools:` (not a list).

dispatch_subagent will consume this in Task 3.

Refs: docs/superpowers/specs/2026-05-22-cce6-7-8-batch-design.md (CCE-7)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `dispatch_subagent` uses per-agent tools

**Files:**

- Modify: `scripts/orchestrator_runner.py` — `dispatch_subagent` function (around lines 348-350 where `--allowedTools` is currently set).

- [ ] **Step 1: Read the current `dispatch_subagent` argv-building block**

Run: `sed -n '340,360p' scripts/orchestrator_runner.py`

You should see:

```python
    base_argv = [
        "claude",
        "--setting-sources",
        "project,local",
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

- [ ] **Step 2: Replace the `--allowedTools` lines with the per-agent lookup**

Edit the `base_argv` construction. Replace the last two list entries (`"--allowedTools", " ".join(_AGENT_ALLOWED_TOOLS),`) with conditional inclusion. The new shape:

```python
    base_argv = [
        "claude",
        "--setting-sources",
        "project,local",
        "-p",
        prompt,
        "--agent",
        name,
        "--plugin-dir",
        str(_PLUGIN_ROOT),
    ]
    agent_tools = _load_agent_allowed_tools(name)
    if agent_tools:
        base_argv.extend(["--allowedTools", " ".join(agent_tools)])
```

- [ ] **Step 3: Run the new tests — all should now pass**

Run: `python3 -m pytest tests/orchestrator/test_dispatch_subagent_allowed_tools.py -v`

Expected: 3 passed.

- [ ] **Step 4: Run the full test suite to check for regressions**

Run: `pytest -q 2>&1 | tail -5`

Expected: 238 passed (was 235; +3 from this plan).

If pre-existing dispatch tests fail (e.g., `tests/orchestrator/test_dispatch_subagent.py` checking that argv contains `--allowedTools`), that's a contract-update — those tests were pinning the old union behavior. Update those test assertions to allow either the new per-agent shape OR no `--allowedTools` flag, depending on the agent under test. Surface specifically which tests changed and the minimal assertion update.

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py
git commit -m "$(cat <<'EOF'
feat(CCE-7): dispatch_subagent passes per-agent tools, not the union

Reads agent's declared tools from agents/<name>.md frontmatter via
_load_agent_allowed_tools. Agents without tools: frontmatter get
no --allowedTools flag (default permissioning).

pr-summarizer now gets only Read (was Bash/Read/Write/Edit/WebFetch);
page-author gets Read/Edit/Write; etc. The union grant introduced
in CCE-3 was a starting point — this lands the intended per-agent
defense-in-depth.

_AGENT_ALLOWED_TOOLS stays as a documented fallback / default-deny
floor per the ticket's "Out of scope" note.

Closes CCE-7.

Refs: docs/superpowers/specs/2026-05-22-cce6-7-8-batch-design.md (CCE-7)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Handle malformed `tools:` frontmatter (defensive test)

**Files:**

- Test: `tests/orchestrator/test_dispatch_subagent_allowed_tools.py` — add one more test.

- [ ] **Step 1: Add the test**

Append to `tests/orchestrator/test_dispatch_subagent_allowed_tools.py`:

```python
def test_malformed_tools_frontmatter_raises_clear_error(
    monkeypatch, tmp_path: Path
):
    """When `tools:` is present but not a YAML list (e.g., a string),
    the loader raises ValueError instead of silently falling back to
    the union. Operators see the bug immediately."""
    fake_agents_dir = tmp_path / "agents"
    fake_agents_dir.mkdir()
    (fake_agents_dir / "broken-agent.md").write_text(
        "---\nname: broken-agent\ndescription: bad frontmatter.\nmodel: sonnet\ntools: Read\n---\n\n# broken-agent\n"
    )

    monkeypatch.setattr(orchestrator_runner, "_AGENTS_DIR", fake_agents_dir)
    if hasattr(orchestrator_runner, "_AGENT_TOOLS_CACHE"):
        orchestrator_runner._AGENT_TOOLS_CACHE.clear()

    with pytest.raises(ValueError) as exc_info:
        orchestrator_runner._load_agent_allowed_tools("broken-agent")
    assert "broken-agent" in str(exc_info.value)
    assert "list" in str(exc_info.value).lower()
```

- [ ] **Step 2: Run the new test**

Run: `python3 -m pytest tests/orchestrator/test_dispatch_subagent_allowed_tools.py::test_malformed_tools_frontmatter_raises_clear_error -v`

Expected: PASS (Task 2's helper already raises ValueError on non-list — this test verifies the contract).

- [ ] **Step 3: Run the full suite**

Run: `pytest -q 2>&1 | tail -3`

Expected: 239 passed (+1 from this task).

- [ ] **Step 4: Commit**

```bash
git add tests/orchestrator/test_dispatch_subagent_allowed_tools.py
git commit -m "$(cat <<'EOF'
test(CCE-7): pin clear-error contract for malformed tools frontmatter

Operators editing an agent .md file and writing `tools: Read` instead
of `tools: [Read]` (or YAML list form) should see an immediate
ValueError naming the agent, not a silent fallback to the union.

Refs: docs/superpowers/specs/2026-05-22-cce6-7-8-batch-design.md (CCE-7)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Spec coverage check

Spec acceptance criteria for CCE-7:

- [x] Parse `tools:` YAML frontmatter from each `agents/<name>.md` — Task 2 (`_load_agent_allowed_tools`).
- [x] `dispatch_subagent` passes only that agent's declared tools — Task 3.
- [x] If an agent declares no tools, omit `--allowedTools` entirely — Task 2 (returns None) + Task 3 (conditional extend).
- [x] Unit test: `dispatch_subagent("pr-summarizer", ...)` argv contains only `Read` — Task 1 test.
- [x] Unit test: missing `tools:` resolves to no `--allowedTools` — Task 1 third test.
- [x] No regression in the 235-test baseline — Task 3 step 4.

Bonus: clear-error contract for malformed frontmatter — Task 4.

No gaps.

## Risk and YAGNI

- This plan does NOT add new tool declarations to any agent `.md`. The seven existing declarations are correct as-is.
- This plan does NOT introduce per-agent `--permission-mode` (explicit out-of-scope in the ticket).
- The `_AGENT_ALLOWED_TOOLS` constant stays — it documents the floor / default-deny posture and isn't removed.
- The cache is invalidatable in tests (`_AGENT_TOOLS_CACHE.clear()`) but never invalidated in production. The agent files don't change at runtime, so this is correct.
