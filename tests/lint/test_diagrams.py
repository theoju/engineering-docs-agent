from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "lint" / "diagrams.py"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "diagrams"


def _run(paths: list[Path], cfg: Path) -> tuple[int, dict]:
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(cfg),
            "--paths",
            *[str(p) for p in paths],
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    return r.returncode, json.loads(r.stdout)


def test_good_passes(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIXTURES / "good.md"], cfg)
    assert rc == 0
    assert out["rule"] == "diagrams"
    assert out["severity"] == "block"
    assert all(r["ok"] for r in out["results"])


def test_bad_fails(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIXTURES / "bad.md"], cfg)
    assert rc == 1
    failed = [r for r in out["results"] if not r["ok"]]
    assert failed
    assert "unterminated" in failed[0]["message"].lower()
