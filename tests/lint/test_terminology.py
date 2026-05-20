from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "lint" / "terminology.py"
FIX = Path(__file__).parent.parent / "fixtures" / "terminology"


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
    cfg.write_text(
        f"lint:\n  tier2:\n    terminology_glossary: {FIX / 'glossary.yml'}\n"
    )
    rc, out = _run([FIX / "good.md"], cfg)
    assert rc == 0
    assert out["rule"] == "terminology"
    assert out["severity"] == "block"
    assert out["results"][0]["ok"] is True


def test_bad(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        f"lint:\n  tier2:\n    terminology_glossary: {FIX / 'glossary.yml'}\n"
    )
    rc, out = _run([FIX / "bad.md"], cfg)
    assert rc == 1
    msg = out["results"][0]["message"].lower()
    assert "datasource" in msg


def test_no_glossary_passes(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "bad.md"], cfg)
    assert rc == 0
    assert out["results"][0]["ok"] is True
