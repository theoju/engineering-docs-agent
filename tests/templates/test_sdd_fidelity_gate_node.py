"""Run the SDD fidelity-gate JS unit suite under the integrated pytest run.

The verification-ladder logic in `docs/superpowers/templates/sdd-fidelity-gate.mjs`
is JavaScript (it runs inside inline Workflow scripts), so its tests run under
Node's built-in `node:test` runner. This wrapper shells out to `node --test` so a
single `pytest` invocation stays the integrated gate.

Degrades gracefully per the plugin mandate: if Node is not installed, the JS suite
is SKIPPED, never failed — a host without Node can still run the Python suite green.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

# node:test summary lines are either spec-reporter (`ℹ pass 36`) or tap (`# pass 36`).
# Anchor to the summary line so test NAMES containing "pass"/"fail" never match.
_PASS_RE = re.compile(r"^\s*[ℹ#]\s*pass (\d+)\b", re.MULTILINE)
_FAIL_RE = re.compile(r"^\s*[ℹ#]\s*fail (\d+)\b", re.MULTILINE)
# Floor well below the real suite size: catches a gutted or all-skipped run
# (which exits 0 and prints `pass 0`) without being brittle to small edits.
_MIN_EXPECTED_TESTS = 20

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "docs" / "superpowers" / "templates" / "sdd-fidelity-gate.mjs"
TEST_MJS = ROOT / "docs" / "superpowers" / "templates" / "sdd-fidelity-gate.test.mjs"


def test_module_and_suite_exist():
    assert MODULE.exists(), "canonical gate module sdd-fidelity-gate.mjs must exist"
    assert TEST_MJS.exists(), "gate unit suite sdd-fidelity-gate.test.mjs must exist"


@pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node not installed — JS gate suite skipped (Python suite still authoritative)",
)
def test_sdd_fidelity_gate_js_suite_passes():
    result = subprocess.run(
        ["node", "--test", str(TEST_MJS)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
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
    assert pass_m and fail_m, f"could not parse node:test summary:\n{result.stdout}"
    passed, failed = int(pass_m.group(1)), int(fail_m.group(1))
    assert failed == 0, f"node:test reported {failed} failure(s):\n{result.stdout}"
    assert passed >= _MIN_EXPECTED_TESTS, (
        f"node:test ran only {passed} test(s) (expected >= {_MIN_EXPECTED_TESTS}); "
        f"discovery may be broken or the suite gutted:\n{result.stdout}"
    )
