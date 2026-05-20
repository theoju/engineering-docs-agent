from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "lint" / "banned_phrases.py"
FIX = Path(__file__).parent.parent / "fixtures" / "banned_phrases"


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


def test_good_with_banned_configured(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("lint:\n  tier2:\n    banned_phrases:\n      - simply\n")
    rc, out = _run([FIX / "good.md"], cfg)
    assert rc == 0
    assert out["rule"] == "banned_phrases"
    assert out["severity"] == "block"
    assert out["results"][0]["ok"] is True


def test_bad_hits_banned(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("lint:\n  tier2:\n    banned_phrases:\n      - simply\n")
    rc, out = _run([FIX / "bad.md"], cfg)
    assert rc == 1
    msg = out["results"][0]["message"].lower()
    assert "simply" in msg


def test_empty_banned_passes(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "bad.md"], cfg)
    assert rc == 0
    assert out["results"][0]["ok"] is True
