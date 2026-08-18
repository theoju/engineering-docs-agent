"""Run the SDD fidelity-gate JS unit suite under the integrated pytest run.

The verification-ladder logic in `docs/superpowers/templates/sdd-fidelity-gate.mjs`
is JavaScript (it runs inside inline Workflow scripts), so its tests run under
Node's built-in `node:test` runner. This wrapper shells out to `node --test` so a
single `pytest` invocation stays the integrated gate.

Degrades gracefully per the plugin mandate: if Node is not installed, the JS suite
is SKIPPED, never failed — a host without Node can still run the Python suite green.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

# The suite is pinned to the TAP reporter (see `_NODE_TEST_ARGV`), whose summary
# lines are `# pass 36`. Anchor to the summary line so test NAMES containing
# "pass"/"fail" never match.
_PASS_RE = re.compile(r"^\s*#\s*pass (\d+)\b", re.MULTILINE)
_FAIL_RE = re.compile(r"^\s*#\s*fail (\d+)\b", re.MULTILINE)
# Floor well below the real suite size: catches a gutted or all-skipped run
# (which exits 0 and prints `pass 0`) without being brittle to small edits.
_MIN_EXPECTED_TESTS = 20

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "docs" / "superpowers" / "templates" / "sdd-fidelity-gate.mjs"
TEST_MJS = ROOT / "docs" / "superpowers" / "templates" / "sdd-fidelity-gate.test.mjs"

# CCE-160: `--test-reporter=tap` is load-bearing, not a preference.
#
# node's DEFAULT reporter writes for humans, so it colourises whenever
# `FORCE_COLOR` is set — which every agent session sets, whether or not anyone
# will read the output. The SGR escape then lands between `^` and the summary
# text, the patterns above cannot match, and a suite that passed 53 tests is
# reported as one whose summary could not be read. Verified on node v26.5.0:
# `FORCE_COLOR=3 node --test --test-reporter=tap` emits zero escape bytes, and
# TAP's wording is a machine contract rather than human-facing prose.
#
# Deleting this flag does NOT degrade gracefully, and that is deliberate: the
# patterns match `#` only, so the default reporter's `ℹ pass 53` fails to parse
# everywhere, CI included. The alternative — tolerating both formats — would let
# the flag's removal pass CI green and fail only inside agent sessions, which is
# precisely the bug this closes, returning silently.
_NODE_TEST_ARGV = ["node", "--test", "--test-reporter=tap", str(TEST_MJS)]

_SKIP_WITHOUT_NODE = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node not installed — JS gate suite skipped (Python suite still authoritative)",
)


def _run_gate_suite(env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        _NODE_TEST_ARGV,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_gate_is_green(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, (
        "node --test failed for the SDD fidelity gate suite:\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    # Sanity: parse the summary counts and prove real tests ran. A substring check
    # for "pass " is NOT enough — `"pass "` is a prefix of `"pass 0"`, so an
    # all-skipped/zero-pass run (which still exits 0) would false-pass the wrapper,
    # reproducing the exact phantom-pass failure this gate exists to kill.
    pass_m = _PASS_RE.search(result.stdout)
    fail_m = _FAIL_RE.search(result.stdout)
    # repr(), not raw: an unparseable summary most often carries control
    # characters, and a terminal renders those invisibly — printing it raw shows
    # a summary that looks perfectly readable and sends the reader to their own
    # diff instead of to the bytes.
    assert pass_m and fail_m, (
        "could not parse the node:test summary (shown as repr() so any control "
        f"characters are visible):\n{result.stdout!r}"
    )
    passed, failed = int(pass_m.group(1)), int(fail_m.group(1))
    assert failed == 0, f"node:test reported {failed} failure(s):\n{result.stdout}"
    assert passed >= _MIN_EXPECTED_TESTS, (
        f"node:test ran only {passed} test(s) (expected >= {_MIN_EXPECTED_TESTS}); "
        f"discovery may be broken or the suite gutted:\n{result.stdout}"
    )


def test_module_and_suite_exist():
    assert MODULE.exists(), "canonical gate module sdd-fidelity-gate.mjs must exist"
    assert TEST_MJS.exists(), "gate unit suite sdd-fidelity-gate.test.mjs must exist"


@_SKIP_WITHOUT_NODE
def test_sdd_fidelity_gate_js_suite_passes():
    _assert_gate_is_green(_run_gate_suite())


@_SKIP_WITHOUT_NODE
def test_the_gate_survives_an_environment_that_forces_colour():
    """CCE-160 regression: the same run, with `FORCE_COLOR` set explicitly.

    Forcing it here rather than relying on inheritance is the whole point. Agent
    sessions export `FORCE_COLOR`, so the test above already covers this case
    when an agent runs it — and covers nothing when CI or a human terminal does,
    because neither sets it. That is how the original bug reached `main` green:
    invisible to every environment that could have caught it, and deterministic
    in the one environment least able to tell it was environmental at all.

    Setting it explicitly makes the guard hold for everyone, everywhere, rather
    than only for the readers worst placed to diagnose what it means.
    """
    _assert_gate_is_green(_run_gate_suite(env={**os.environ, "FORCE_COLOR": "3"}))
