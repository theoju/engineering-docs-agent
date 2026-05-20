from __future__ import annotations
import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "lint" / "footnotes.sh"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "footnotes"


def _run(paths: list[Path]) -> tuple[int, dict]:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--json", *[str(p) for p in paths]],
        capture_output=True,
        text=True,
    )
    return result.returncode, json.loads(result.stdout) if result.stdout else {}


def test_good_passes():
    rc, out = _run([FIXTURES / "good.md"])
    assert rc == 0


def test_bad_fails():
    rc, _ = _run([FIXTURES / "bad.md"])
    assert rc == 1
