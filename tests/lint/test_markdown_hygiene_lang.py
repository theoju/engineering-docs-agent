from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPT = (
    Path(__file__).parent.parent.parent
    / "scripts"
    / "lint"
    / "markdown_hygiene_lang.py"
)
FIX = Path(__file__).parent.parent / "fixtures" / "markdown_hygiene"


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


def test_warns_on_missing_lang_tag(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "bad_no_lang.md"], cfg)
    assert rc == 1
    assert out["rule"] == "markdown_hygiene_lang"
    assert out["severity"] == "warn"
    assert "language" in out["results"][0]["message"].lower()


def test_good_passes(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "good.md"], cfg)
    assert rc == 0
    assert out["rule"] == "markdown_hygiene_lang"
    assert out["severity"] == "warn"


def test_does_not_flag_structural_defect(tmp_path):
    # Unpaired fences, but both have language tags. Lang rule should pass.
    p = tmp_path / "unpaired.md"
    p.write_text("# x\n\n```python\ncode\n```\n\n```ruby\nmore\n")
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([p], cfg)
    assert rc == 0
