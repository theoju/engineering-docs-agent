from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "lint" / "internal_links.py"
FIX = Path(__file__).parent.parent / "fixtures" / "internal_links"


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
    assert out["rule"] == "internal_links"
    assert out["severity"] == "block"
    assert all(r["ok"] for r in out["results"])


def test_broken(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "bad_broken.md"], cfg)
    assert rc == 1
    msg = out["results"][0]["message"]
    assert "does-not-exist.md" in msg


def test_external_links_skipped(tmp_path):
    p = tmp_path / "ext.md"
    p.write_text("[ext](https://example.com)\n[mail](mailto:x@y.z)\n")
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([p], cfg)
    assert rc == 0
