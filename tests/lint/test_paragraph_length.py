from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).parent.parent.parent / "scripts" / "lint" / "paragraph_length.py"
)
FIX = Path(__file__).parent.parent / "fixtures" / "paragraph_length"


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


def test_good(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "good.md"], cfg)
    assert rc == 0
    assert out["rule"] == "paragraph_length"
    assert out["severity"] == "block"
    assert out["results"][0]["ok"] is True


def test_bad(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "bad.md"], cfg)
    assert rc == 1
    msg = out["results"][0]["message"].lower()
    assert "paragraphs over" in msg or "150" in msg
