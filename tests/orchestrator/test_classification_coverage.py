"""CCE-144: every blocking add_partial call site must be explicitly classified.

The runtime default for a blocking reason is BLIND (fail-safe). This test
forbids *relying* on that default: a call site that passes neither
`info_only` nor `degraded` has been classified by nobody, and would inherit
red-or-green by accident. Adding a bare add_partial call fails this test.

Deliberately not a registry of site->classification: keys built from the
enclosing function plus reason token collide in verify_runner, where three
separate reason loops share a key but not a classification, and a registry
decays as sites move. Requiring explicitness at the call site cannot decay.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARDED_MODULES = ("scripts/orchestrator_runner.py", "scripts/verify_runner.py")


def _add_partial_calls(path: Path):
    """Yield (lineno, enclosing_function, keyword_names) per add_partial call."""
    tree = ast.parse(path.read_text())
    enclosing: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    enclosing.setdefault(child.lineno, node.name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name != "add_partial":
            continue
        yield (
            node.lineno,
            enclosing.get(node.lineno, "<module>"),
            {kw.arg for kw in node.keywords if kw.arg},
        )


@pytest.mark.parametrize("rel", GUARDED_MODULES)
def test_every_add_partial_call_is_explicitly_classified(rel):
    path = REPO_ROOT / rel
    unclassified = [
        f"{rel}:{lineno} in {fn}()"
        for lineno, fn, kwargs in _add_partial_calls(path)
        if not ({"info_only", "degraded"} & kwargs)
    ]
    assert not unclassified, (
        "add_partial call sites with no explicit classification:\n  "
        + "\n  ".join(unclassified)
        + "\n\nPass degraded=True if the run HELD BACK the work it could not "
        "process (self-healing, stays green), degraded=False if the run "
        "CONSUMED input it could not process (blind, turns the nightly red), "
        "or info_only=True if the reason is advisory. See the Classification "
        "section of the CCE-144 spec."
    )


def test_the_guard_actually_detects_a_bare_call(tmp_path):
    """Meta-test: exercise _add_partial_calls on an isolated probe, so a green
    result above means "all sites classified" and never "the walk found
    nothing".

    Deliberately does NOT read the guarded modules: a probe appended to their
    source would count every still-unclassified call alongside it, so the test
    could only pass after the classification landed — failing at the TDD red
    gate with a message blaming the walk, which is the one part that works.
    Reading a fixture instead makes it order-independent and lets it exercise
    the `.attr` branch, which no real call site currently covers.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(
        "def f(state):\n"
        "    add_partial(state, 'bare')\n"
        "    add_partial(state, 'degraded', degraded=True)\n"
        "    add_partial(state, 'advisory', info_only=True)\n"
        "    mod.add_partial(state, 'attribute-style')\n"
    )
    calls = list(_add_partial_calls(probe))
    assert len(calls) == 4, f"walk found {len(calls)} calls, expected 4"
    unclassified = [
        fn for _lineno, fn, kwargs in calls if not ({"info_only", "degraded"} & kwargs)
    ]
    assert len(unclassified) == 2, (
        "the walk must flag the bare call AND the attribute-style call; "
        f"it flagged {len(unclassified)}"
    )


def test_orchestrator_has_the_expected_call_site_population():
    """Tripwire on the audit's scope. Not a hard contract — if this fails
    because sites were legitimately added or removed, re-audit the new ones
    against the spec's Classification section and update the number here in
    the same commit that adds them."""
    calls = list(_add_partial_calls(REPO_ROOT / "scripts/orchestrator_runner.py"))
    assert len(calls) == 38, (
        f"expected 38 add_partial calls, found {len(calls)}; re-audit and "
        "update this count deliberately"
    )
