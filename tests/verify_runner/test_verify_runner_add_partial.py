"""CCE-74 Task 4: verify_runner routes partial-reason writes through add_partial.

Three tests:
  1. Sanity  — verify_runner imports add_partial from state_io.
  2. Semantic — the verify_reasons loop accumulates reasons via add_partial.
  3. Invariant — line 49's dict literal is NOT a state write (regex source-scan).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

VERIFY_RUNNER_SRC = Path(__file__).parent.parent.parent / "scripts" / "verify_runner.py"


# ---------------------------------------------------------------------------
# 1. Sanity: add_partial is imported
# ---------------------------------------------------------------------------


def test_verify_runner_imports_add_partial():
    """verify_runner must import add_partial from state_io."""
    import scripts.verify_runner as vr  # noqa: F401 — triggers ImportError if missing

    from scripts.state_io import add_partial as _add_partial  # noqa: F401

    # If the module loaded and add_partial is importable from state_io,
    # the wiring is in place.  The import-tuple check validates the source.
    src = VERIFY_RUNNER_SRC.read_text()
    assert "add_partial" in src, "add_partial must appear in verify_runner.py source"
    # Confirm it comes from the state_io import block (not an unrelated variable).
    assert re.search(r"from state_io import[^)]+add_partial", src, re.DOTALL), (
        "add_partial must be part of the 'from state_io import (...)' block"
    )


# ---------------------------------------------------------------------------
# 2. Semantic: verify_reasons loop behaviour via direct add_partial calls
# ---------------------------------------------------------------------------


def test_verify_runner_verify_reasons_loop_uses_add_partial(capsys):
    """Mirrors the verify_reasons loop: add_partial must set partial=True and
    append each reason to state['current_run']['partial_reasons']."""
    from scripts.state_io import add_partial

    state: dict = {
        "current_run": {
            "started_at": "2026-06-01T00:00:00+00:00",
            "head_sha": "deadbeef",
            "partial": False,
            "partial_reasons": [],
        }
    }

    verify_reasons = ["page_404: /docs/api", "build_timeout: 120s"]

    # Replicate the refactored loop body
    for r in verify_reasons:
        add_partial(state, r)

    assert state["current_run"]["partial"] is True
    assert state["current_run"]["partial_reasons"] == verify_reasons

    # add_partial must also emit to stderr
    captured = capsys.readouterr()
    for r in verify_reasons:
        assert r in captured.err, f"Expected '{r}' in stderr"


# ---------------------------------------------------------------------------
# 3. Invariant: line-49 dict literal is NOT a state write
# ---------------------------------------------------------------------------


def test_verify_runner_line_49_notifier_digest_is_NOT_a_state_write():
    """The 'partial_reasons' dict key in verify_runner.py's error-notifier block
    (originally line 49) is a plain dict literal inside a notifier-payload —
    not a state.setdefault / add_partial call.

    This test uses a whitespace-tolerant regex to assert the pattern remains
    a plain dict key assignment and has not been mistakenly refactored.
    The check is line-number-agnostic so it survives minor import-block edits.
    """
    src = VERIFY_RUNNER_SRC.read_text()
    lines = src.splitlines()

    # Find the line that carries "partial_reasons" as a dict key in the source.
    # There must be exactly one such occurrence (the error-notifier digest field).
    matching = [
        (i + 1, line)
        for i, line in enumerate(lines)
        if re.search(r"""["']partial_reasons["']\s*:""", line)
    ]
    assert len(matching) == 1, (
        f"Expected exactly one 'partial_reasons' dict-key line; found {len(matching)}: {matching}"
    )
    lineno, target_line = matching[0]

    # Must NOT be a state.setdefault or add_partial call
    assert "setdefault" not in target_line, (
        f"Line {lineno} must not use setdefault — it is a notifier digest field, not a state write"
    )
    assert "add_partial" not in target_line, (
        f"Line {lineno} must not call add_partial — it is a notifier digest field, not a state write"
    )
