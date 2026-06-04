"""CCE-87: defensive test that fails when scripts/*.py docstrings carry
--FLAG VALUE shapes outside fenced/inline code blocks. Prevents the
CCE-80 class of mkdocs-autorefs WARNING-on-strict-build regression.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

PATTERN_BARE = re.compile(r"^\s+--[a-z][a-z_-]+\s+[A-Z][A-Z_]+", re.MULTILINE)
PATTERN_BRACKETED = re.compile(r"\[--[a-z][a-z_-]+\s+[A-Z][A-Z_]+\]")


def _strip_code_regions(docstring: str) -> str:
    """Remove regions that are legitimately allowed to contain --FLAG VALUE
    shapes: triple-backtick fences, single-backtick inline code, and
    reST-style `Name::` literal blocks (indented blocks following a `::`
    line — the post-CCE-80 wrapping idiom)."""
    s = re.sub(r"```.*?```", "", docstring, flags=re.DOTALL)
    s = re.sub(r"`[^`\n]+`", "", s)
    s = re.sub(
        r"^\S.*::\s*\n(?:[ \t]+.*\n?)+",
        "",
        s,
        flags=re.MULTILINE,
    )
    return s


def _extract_docstrings(py_path: Path) -> list[str]:
    """Return all docstrings (module + each function/class) from py_path."""
    tree = ast.parse(py_path.read_text())
    out: list[str] = []
    mod_doc = ast.get_docstring(tree)
    if mod_doc:
        out.append(mod_doc)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            d = ast.get_docstring(node)
            if d:
                out.append(d)
    return out


def _lint_one(py_path: Path) -> list[str]:
    """Return list of offending lines (--FLAG VALUE outside code) for py_path."""
    findings: list[str] = []
    for doc in _extract_docstrings(py_path):
        stripped = _strip_code_regions(doc)
        for m in PATTERN_BARE.finditer(stripped):
            findings.append(f"bare:{m.group(0).strip()}")
        for m in PATTERN_BRACKETED.finditer(stripped):
            findings.append(f"bracketed:{m.group(0)}")
    return findings


@pytest.mark.parametrize("py_file", sorted(SCRIPTS_DIR.glob("*.py")))
def test_no_unwrapped_flag_value_in_docstrings(py_file: Path) -> None:
    """CCE-87: scripts/*.py docstrings must not carry --FLAG VALUE shapes
    outside fenced/inline code blocks. mkdocs-autorefs treats them as
    broken cross-refs and fails --strict builds."""
    findings = _lint_one(py_file)
    assert findings == [], (
        f"{py_file.name} has unwrapped --FLAG VALUE shapes in a docstring: "
        f"{findings}. Wrap in `inline backticks`, ```triple-backtick fence```, "
        f"or a reST `Usage::` literal block (see CCE-80 fix)."
    )


def test_fixture_triggers_lint() -> None:
    """CCE-87 self-check: the synthetic regression fixture MUST trigger the
    lint. If this fails, the lint stopped detecting the class of bug it was
    written to catch — fix the lint or the fixture, not the assertion."""
    fixture = FIXTURES_DIR / "regression_docstring.py"
    findings = _lint_one(fixture)
    assert any(f.startswith("bare:") for f in findings), (
        f"fixture {fixture.name} should trigger the bare-form pattern; "
        f"findings: {findings}"
    )
    assert any(f.startswith("bracketed:") for f in findings), (
        f"fixture {fixture.name} should trigger the bracketed-form pattern; "
        f"findings: {findings}"
    )
