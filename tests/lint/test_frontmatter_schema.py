from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPT = (
    Path(__file__).parent.parent.parent / "scripts" / "lint" / "frontmatter_schema.py"
)
FIX = Path(__file__).parent.parent / "fixtures" / "frontmatter_schema"


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
    assert out["rule"] == "frontmatter_schema"
    assert out["severity"] == "block"
    assert all(r["ok"] for r in out["results"])


def test_missing_field(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "bad_missing_field.md"], cfg)
    assert rc == 1
    msg = out["results"][0]["message"]
    assert "synthesized_into" in msg


def test_no_frontmatter(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "bad_no_frontmatter.md"], cfg)
    assert rc == 1
    assert "frontmatter" in out["results"][0]["message"].lower()
