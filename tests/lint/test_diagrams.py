from __future__ import annotations
import json
import subprocess
import sys
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


def test_bad_fails(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, _ = _run([FIXTURES / "bad.md"], cfg)
    assert rc == 1
