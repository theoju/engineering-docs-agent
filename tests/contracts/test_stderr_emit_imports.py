"""CCE-74: Leaf-module invariants for scripts/stderr_emit.py.

stderr_emit.py is the lowest-level observability module. It MUST NOT
import from scripts.state_io or scripts.orchestrator_runner — doing so
creates a cycle that breaks state_io's role as the data layer.

Also locks Acceptance Criterion #8: no raw `print(..., file=sys.stderr)`
remains in scripts/orchestrator_runner.py outside the two intentional
sites: _record_failure and _emit_shutdown_dump.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest


def test_stderr_emit_module_imports_only_stdlib():
    """stderr_emit must not transitively depend on state_io or
    orchestrator_runner. Prevents future contributors from creating
    a cycle by adding `from state_io import ...` to stderr_emit."""
    m = importlib.import_module("scripts.stderr_emit")
    # The module's own globals should not contain state_io or orchestrator_runner
    # names (they would appear if imported via `from X import ...` or `import X`).
    assert "state_io" not in dir(m), (
        f"stderr_emit must not import state_io; found symbol in module dir: "
        f"{[n for n in dir(m) if 'state_io' in n]}"
    )
    assert "orchestrator_runner" not in dir(m), (
        f"stderr_emit must not import orchestrator_runner; found: "
        f"{[n for n in dir(m) if 'orchestrator_runner' in n]}"
    )


def test_no_new_raw_stderr_prints_in_orchestrator_runner():
    """Acceptance Criterion #8: every stderr write in orchestrator_runner.py
    routes through stderr_emit (emit_stderr / emit_log) EXCEPT TWO
    intentional sites:
      1. _record_failure (line ~1893) — fires before any later crash; must
         emit at failure source, can't be best-effort.
      2. _emit_shutdown_dump — last-resort shutdown signal; must propagate
         OSError, so cannot use emit_stderr/emit_log (which swallow it).

    Reads the source and asserts every raw `print(..., file=sys.stderr`
    match falls inside the body of one of these two functions.
    """
    src = Path("scripts/orchestrator_runner.py").read_text()
    raw_pattern = re.compile(r"print\([^)]*file=sys\.stderr", re.DOTALL)
    matches = list(raw_pattern.finditer(src))

    allowed_funcs = ("_record_failure", "_emit_shutdown_dump")
    allowed_ranges = []
    for func_name in allowed_funcs:
        start = src.find(f"def {func_name}(")
        assert start != -1, f"{func_name} should exist in orchestrator_runner.py"
        next_def = src.find("\ndef ", start + 1)
        if next_def == -1:
            next_def = len(src)
        allowed_ranges.append((start, next_def, func_name))

    offending = []
    for m in matches:
        start = m.start()
        in_allowed = any(lo <= start < hi for lo, hi, _ in allowed_ranges)
        if not in_allowed:
            line_no = src.count("\n", 0, start) + 1
            offending.append((line_no, src[start : start + 80]))

    assert not offending, (
        "Raw `print(..., file=sys.stderr` outside _record_failure / "
        "_emit_shutdown_dump — must route through scripts.stderr_emit."
        "emit_stderr or emit_log:\n"
        + "\n".join(f"  line {ln}: {snippet!r}" for ln, snippet in offending)
    )
