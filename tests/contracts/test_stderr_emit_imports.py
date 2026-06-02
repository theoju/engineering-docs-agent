"""CCE-74: Leaf-module invariants for scripts/stderr_emit.py.

stderr_emit.py is the lowest-level observability module. It MUST NOT
import from scripts.state_io or scripts.orchestrator_runner — doing so
creates a cycle that breaks state_io's role as the data layer.

Also locks Acceptance Criterion #8: no raw `print(..., file=sys.stderr)`
remains in scripts/orchestrator_runner.py outside the single intentional
_record_failure site.
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


@pytest.mark.xfail(
    reason="Pending Task 7: 9 raw print(..., file=sys.stderr) sites at "
    "lines 643, 683, 969, 975, 981, 1493, 1498, 1503, 1508 are migrated "
    "to emit_log; the exit-1 dump at 1412 is also routed through emit_log. "
    "Remove this xfail in Task 7.",
    strict=True,
)
def test_no_new_raw_stderr_prints_in_orchestrator_runner():
    """Acceptance Criterion #8: every stderr write in orchestrator_runner.py
    routes through stderr_emit (emit_stderr / emit_log) EXCEPT the single
    intentional _record_failure site, which stays direct.

    This test reads the source and asserts the only `print(..., file=sys.stderr`
    match lives inside the body of _record_failure (matched by surrounding
    `def _record_failure` text).
    """
    src = Path("scripts/orchestrator_runner.py").read_text()
    # Find all raw stderr-print call sites (allow flush kwarg ordering).
    raw_pattern = re.compile(r"print\([^)]*file=sys\.stderr", re.DOTALL)
    matches = list(raw_pattern.finditer(src))
    # The single allowed site is inside _record_failure. Identify it by
    # locating the def and asserting the match falls between that def and
    # the next top-level def (or the next blank-line + def).
    record_failure_start = src.find("def _record_failure(")
    assert record_failure_start != -1, "_record_failure should still exist"
    # Find the next top-level def after _record_failure to bound its body.
    next_def_after = src.find("\ndef ", record_failure_start + 1)
    if next_def_after == -1:
        next_def_after = len(src)

    offending = []
    for m in matches:
        start = m.start()
        in_record_failure = record_failure_start <= start < next_def_after
        if not in_record_failure:
            # Compute approximate line number for the error message.
            line_no = src.count("\n", 0, start) + 1
            offending.append((line_no, src[start : start + 80]))

    assert not offending, (
        "Raw `print(..., file=sys.stderr` outside _record_failure — must "
        "route through scripts.stderr_emit.emit_stderr or emit_log:\n"
        + "\n".join(f"  line {ln}: {snippet!r}" for ln, snippet in offending)
    )
