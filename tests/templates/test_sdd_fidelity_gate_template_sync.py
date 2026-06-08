"""Drift guard: the markdown walkthrough must stay in sync with the tested module.

`sdd-fidelity-gate.mjs` is the executable source of truth; `sdd-fidelity-gate.md`
is the human-facing mirror. The two can silently diverge — a gate outcome added or
renamed in code but not in the doc (or vice versa) reintroduces exactly the
"documented one way, behaves another" risk the ladder exists to kill.

This test asserts the behavioral surface matches:
  * every `halt({kind: "..."})` outcome in the module appears in the markdown, and
    every `kind: "sdd_fidelity_*"` literal in the markdown is a real implemented outcome;
  * the shared helper names appear in both;
  * the markdown points readers at the module and its test suite.

This is a TEXTUAL tripwire, not a structural proof: it checks token presence on
both sides, so it reliably catches an added/renamed/inconsistently-deleted halt
kind, but it does not verify the mirrored snippet's surrounding logic matches the
module. The `.mjs` is the source of truth; `node --test` is the behavioral check.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TPL_DIR = ROOT / "docs" / "superpowers" / "templates"
MODULE = TPL_DIR / "sdd-fidelity-gate.mjs"
MARKDOWN = TPL_DIR / "sdd-fidelity-gate.md"

# Match ONLY genuine halt-kind literals (`kind: "sdd_fidelity_..."`), present in the
# same shape in both the module and the markdown's mirrored snippets. A bare
# `sdd_fidelity_[a-z0-9_]+` over-captures the two test FILENAMES cited in both files'
# headers (sdd_fidelity_gate_node, sdd_fidelity_gate_template_sync), which would
# inflate the count and weaken the floor below.
_KIND_RE = re.compile(r"""kind:\s*["'](sdd_fidelity_[a-z0-9_]+)["']""")
# Hand-maintained: the pure helpers shared verbatim between module and doc. A new
# shared helper added to the module is NOT auto-required here — extend this list
# when you add one (the runTier*/runReviewer/runImplementer runners are module-only
# by design and intentionally absent).
SHARED_HELPERS = [
    "gitReady",
    "dirtyPaths",
    "committedSince",
    "observedForTask",
    "expectedHit",
]


def _kinds(text: str) -> set[str]:
    return set(_KIND_RE.findall(text))


def test_files_exist():
    assert MODULE.exists()
    assert MARKDOWN.exists()


def test_halt_kinds_match_between_module_and_doc():
    mod_kinds = _kinds(MODULE.read_text())
    doc_kinds = _kinds(MARKDOWN.read_text())
    # The module must declare at least the eight known gate outcomes. With the
    # anchored regex this floor counts REAL halt kinds only (no filename tokens).
    assert len(mod_kinds) >= 8, f"module lost halt kinds: {sorted(mod_kinds)}"
    missing_in_doc = mod_kinds - doc_kinds
    assert not missing_in_doc, (
        "gate outcomes implemented but not documented in the markdown: "
        f"{sorted(missing_in_doc)}"
    )
    undocumented_impl = doc_kinds - mod_kinds
    assert not undocumented_impl, (
        "gate outcomes documented in markdown but not implemented in the module: "
        f"{sorted(undocumented_impl)}"
    )


def test_shared_helpers_present_in_both():
    mod = MODULE.read_text()
    doc = MARKDOWN.read_text()
    for name in SHARED_HELPERS:
        assert name in mod, f"helper {name} missing from module"
        assert name in doc, f"helper {name} missing from markdown walkthrough"


def test_markdown_points_at_tested_module_and_suite():
    doc = MARKDOWN.read_text()
    assert "sdd-fidelity-gate.mjs" in doc, (
        "markdown must reference the canonical module"
    )
    assert "sdd-fidelity-gate.test.mjs" in doc, "markdown must reference the test suite"
