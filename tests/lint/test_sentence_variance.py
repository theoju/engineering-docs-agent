from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).parent.parent.parent / "scripts" / "lint" / "sentence_variance.py"
)
FIX = Path(__file__).parent.parent / "fixtures" / "sentence_variance"


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


def test_short_passes(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "short.md"], cfg)
    assert rc == 0
    assert out["rule"] == "sentence_variance"
    assert out["severity"] == "warn"
    assert out["results"][0]["ok"] is True


def test_uniform_warns(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "uniform.md"], cfg)
    assert rc == 2
    assert out["rule"] == "sentence_variance"
    assert out["severity"] == "warn"
    assert out["results"][0]["ok"] is False
    assert "variance" in out["results"][0]["message"].lower()


def test_varied_passes(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "good.md"], cfg)
    assert rc == 0
    assert out["results"][0]["ok"] is True
