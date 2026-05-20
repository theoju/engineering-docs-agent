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
    assert out["rule"] == "footnotes"
    assert out["severity"] == "block"
    assert all(r["ok"] for r in out["results"])


def test_bad_fails():
    rc, out = _run([FIXTURES / "bad.md"])
    assert rc == 1
    failed = [r for r in out["results"] if not r["ok"]]
    assert failed, "expected at least one failure"
    # The bad fixture has both an orphan ref ([^1] with no def) AND an orphan def ([^2]).
    msg = failed[0]["message"]
    assert "[^1]" in msg or "[^2]" in msg


def test_empty_paths_no_crash():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    body = json.loads(result.stdout)
    assert body["rule"] == "footnotes"
    assert body["results"] == []


def test_orphan_def_only_detected(tmp_path):
    # File with a def but no ref — should now fail (was passing before C1 fix).
    p = tmp_path / "orphan_def.md"
    p.write_text("# x\n\n[^lonely]: definition with no reference.\n")
    rc, out = _run([p])
    assert rc == 1
    failed = [r for r in out["results"] if not r["ok"]]
    assert failed
    assert "[^lonely]" in failed[0]["message"]
