from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).parent.parent.parent / "scripts" / "lint" / "duplicate_content.py"
)
FIX = Path(__file__).parent.parent / "fixtures" / "duplicate_content"


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


def test_always_passes_single_file(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "any.md"], cfg)
    assert rc == 0
    assert out["rule"] == "duplicate_content"
    assert out["severity"] == "warn"
    assert out["results"][0]["ok"] is True
