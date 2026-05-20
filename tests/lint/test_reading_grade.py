from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "lint" / "reading_grade.py"
FIX = Path(__file__).parent.parent / "fixtures" / "reading_grade"


def _run(paths, cfg):
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


def test_too_short_passes(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "short.md"], cfg)
    assert rc == 0
    assert out["rule"] == "reading_grade"
    assert out["severity"] == "warn"
    assert out["results"][0]["ok"] is True


def test_simple_warns(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("lint:\n  tier3:\n    reading_grade_range:\n      - 8\n      - 12\n")
    rc, out = _run([FIX / "simple.md"], cfg)
    assert rc == 1
    assert out["rule"] == "reading_grade"
    assert out["severity"] == "warn"
    assert out["results"][0]["ok"] is False
    assert "reading grade" in out["results"][0]["message"].lower()


def test_good_passes(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "good.md"], cfg)
    assert rc == 0
    assert out["results"][0]["ok"] is True
